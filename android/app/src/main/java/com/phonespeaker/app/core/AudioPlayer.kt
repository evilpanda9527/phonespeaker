package com.phonespeaker.app.core

import android.media.AudioAttributes
import android.media.AudioFormat as AndroidAudioFormat
import android.media.AudioTrack
import android.util.Log
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean

/**
 * AudioPlayer.kt — AudioTrack(MODE_STREAM, LOW_LATENCY) 播放（§13，與 transport 解耦）。
 *
 * 只認 core.AudioFormat + RingBuffer，完全不知道資料是從哪個 transport 來的。
 * 若目前裝置/API 無法用 PC 給的 format 建立播放，丟 AudioFormatUnsupportedException，
 * 由呼叫端（StreamerService）回 FORMAT_UNSUPPORTED（§5：Android 不轉檔、不硬湊）。
 */
private const val TAG = "AudioPlayer"

/** 依 §9：underrun 時補的靜音長度上限（避免一次補太長反而增加延遲）。 */
private const val MAX_SILENCE_FILL_MS = 20
private const val RING_BUFFER_POLL_TIMEOUT_MS = 50L

class AudioFormatUnsupportedException(reason: String) : Exception(reason)

class AudioPlayer {
    private var audioTrack: AudioTrack? = null
    private var feederThread: Thread? = null
    private val running = AtomicBoolean(false)

    /**
     * pcm_f32le 用 ENCODING_PCM_FLOAT 建立的 AudioTrack 不接受 write(byte[], ...)
     * （不會正確播放，甚至回 ERROR_INVALID_OPERATION），必須改用
     * write(ByteBuffer, sizeInBytes, WRITE_BLOCKING)。這裡記住目前是不是 float 軌道，
     * 讓 writeAll() 走對應的 write 多載。
     */
    private var writeAsFloat = false

    @Volatile
    var underrunCount: Long = 0
        private set

    @Throws(AudioFormatUnsupportedException::class)
    fun start(format: AudioFormat, ringBuffer: RingBuffer) {
        if (audioTrack != null) {
            throw IllegalStateException("AudioPlayer 已在執行中，請先 stop()")
        }

        val track = buildAudioTrack(format)
        audioTrack = track
        underrunCount = 0
        writeAsFloat = format.encoding == "pcm_f32le"

        try {
            track.play()
        } catch (e: IllegalStateException) {
            track.release()
            audioTrack = null
            throw AudioFormatUnsupportedException("AudioTrack.play() 失敗: ${e.message}")
        }

        running.set(true)
        val bytesPerFrame = format.bytesPerFrame()
        val silenceChunk = ByteArray(
            (format.sampleRate * bytesPerFrame / 1000) * MAX_SILENCE_FILL_MS
        )

        val thread = Thread({
            feederLoop(track, ringBuffer, silenceChunk)
        }, "audio-player-feeder")
        thread.priority = Thread.MAX_PRIORITY
        feederThread = thread
        thread.start()
    }

    private fun feederLoop(track: AudioTrack, ringBuffer: RingBuffer, silenceChunk: ByteArray) {
        while (running.get()) {
            val chunk = ringBuffer.poll(RING_BUFFER_POLL_TIMEOUT_MS)
            val data = if (chunk != null) {
                chunk
            } else {
                // §9：underrun 補最短靜音、不 crash、不無限等待。
                underrunCount++
                silenceChunk
            }
            try {
                writeAll(track, data)
            } catch (e: Exception) {
                // AudioTrack 寫入失敗（例如裝置被拔掉）不該讓 app 崩潰；記 log 後停止 feeder，
                // 由上層（StreamerService）偵測 stop() 後續處理重連。
                Log.w(TAG, "AudioTrack.write 失敗，停止播放迴圈: ${e.message}")
                running.set(false)
            }
        }
    }

    private fun writeAll(track: AudioTrack, data: ByteArray) {
        if (writeAsFloat) {
            writeAllFloat(track, data)
        } else {
            writeAllBytes(track, data)
        }
    }

    /** pcm_s16le / pcm_s32le：ENCODING_PCM_16BIT / ENCODING_PCM_32BIT 軌道，byte[] 多載可正確播放。 */
    private fun writeAllBytes(track: AudioTrack, data: ByteArray) {
        var offset = 0
        while (offset < data.size && running.get()) {
            val written = track.write(data, offset, data.size - offset)
            if (written < 0) {
                throw IllegalStateException("AudioTrack.write 回傳錯誤碼: $written")
            }
            offset += written
        }
    }

    /**
     * pcm_f32le：ENCODING_PCM_FLOAT 軌道必須用 ByteBuffer（或 float[]）多載，
     * byte[] 多載在 float 軌道上不會正確播放。PC 送來的是 little-endian 32-bit
     * float bytes，包成 ByteBuffer 並明確設 LITTLE_ENDIAN 後以 WRITE_BLOCKING 寫入。
     */
    private fun writeAllFloat(track: AudioTrack, data: ByteArray) {
        val buffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        while (buffer.hasRemaining() && running.get()) {
            val written = track.write(buffer, buffer.remaining(), AudioTrack.WRITE_BLOCKING)
            if (written < 0) {
                throw IllegalStateException("AudioTrack.write(ByteBuffer) 回傳錯誤碼: $written")
            }
            if (written == 0) {
                // WRITE_BLOCKING 理論上不會回 0，除非 track 已停止；避免 busy-loop。
                break
            }
        }
    }

    fun stop() {
        running.set(false)
        feederThread?.join(2000)
        feederThread = null

        audioTrack?.let { track ->
            try {
                track.stop()
            } catch (e: IllegalStateException) {
                Log.d(TAG, "AudioTrack.stop() 發生非致命錯誤: ${e.message}")
            }
            track.release()
        }
        audioTrack = null
    }

    private fun buildAudioTrack(format: AudioFormat): AudioTrack {
        val encoding = mapEncoding(format.encoding)
            ?: throw AudioFormatUnsupportedException("不支援的 encoding: ${format.encoding}")
        val channelMask = mapChannelMask(format.channels)
            ?: throw AudioFormatUnsupportedException("不支援的聲道數: ${format.channels}")

        val minBufferSize = AudioTrack.getMinBufferSize(format.sampleRate, channelMask, encoding)
        if (minBufferSize == AudioTrack.ERROR_BAD_VALUE || minBufferSize == AudioTrack.ERROR) {
            throw AudioFormatUnsupportedException(
                "AudioTrack.getMinBufferSize 回報不支援此格式 " +
                    "(rate=${format.sampleRate}, channels=${format.channels}, enc=${format.encoding})"
            )
        }
        // 至少留兩倍 minBufferSize，降低 underrun 機率，同時仍在低延遲範圍內（§9）。
        val bufferSizeBytes = minBufferSize * 2

        val audioFormat = AndroidAudioFormat.Builder()
            .setEncoding(encoding)
            .setSampleRate(format.sampleRate)
            .setChannelMask(channelMask)
            .build()

        val attributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
            .build()

        return try {
            val track = AudioTrack.Builder()
                .setAudioAttributes(attributes)
                .setAudioFormat(audioFormat)
                .setBufferSizeInBytes(bufferSizeBytes)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
                .build()
            if (track.state != AudioTrack.STATE_INITIALIZED) {
                track.release()
                throw AudioFormatUnsupportedException(
                    "AudioTrack 初始化失敗（state=${track.state}），裝置可能不支援此格式"
                )
            }
            track
        } catch (e: UnsupportedOperationException) {
            throw AudioFormatUnsupportedException("裝置不支援此音訊格式: ${e.message}")
        } catch (e: IllegalArgumentException) {
            throw AudioFormatUnsupportedException("AudioTrack 參數不合法: ${e.message}")
        }
    }

    private fun mapEncoding(encoding: String): Int? = when (encoding) {
        "pcm_s16le" -> AndroidAudioFormat.ENCODING_PCM_16BIT
        "pcm_s32le" -> AndroidAudioFormat.ENCODING_PCM_32BIT
        "pcm_f32le" -> AndroidAudioFormat.ENCODING_PCM_FLOAT
        // ENCODING_PCM_24BIT_PACKED 在部分裝置/API 支援度不一致，先不支援，
        // 遇到就回 FORMAT_UNSUPPORTED（符合 §5：不硬湊、不轉檔）。
        else -> null
    }

    private fun mapChannelMask(channels: Int): Int? = when (channels) {
        1 -> AndroidAudioFormat.CHANNEL_OUT_MONO
        2 -> AndroidAudioFormat.CHANNEL_OUT_STEREO
        else -> null
    }
}

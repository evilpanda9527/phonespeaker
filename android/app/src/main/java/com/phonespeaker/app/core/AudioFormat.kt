package com.phonespeaker.app.core

import org.json.JSONException
import org.json.JSONObject

/**
 * AudioFormat.kt — 解析 PC 送來的 FORMAT payload（§5）。
 *
 * PC 端不轉檔，這裡收到什麼就照著建立 AudioTrack；如果目前裝置/API 無法用
 * 這個 format 建立播放，回報 FORMAT_UNSUPPORTED（見 [toUnsupportedReasonOrNull]
 * 及 transport 層對應的訊息），Android 端一樣不轉檔、不硬湊。
 */
data class AudioFormat(
    val sampleRate: Int,
    val channels: Int,
    val encoding: String,
) {
    /** 每個 frame（所有 channel 各一個 sample）的位元組數。 */
    fun bytesPerFrame(): Int {
        val bits = when (encoding) {
            "pcm_s16le" -> 16
            "pcm_s24le" -> 24
            "pcm_s32le" -> 32
            "pcm_f32le" -> 32
            else -> throw IllegalArgumentException("未知的 encoding: $encoding")
        }
        return (bits / 8) * channels
    }

    companion object {
        @Throws(FormatParseException::class)
        fun fromJsonBytes(data: ByteArray): AudioFormat {
            try {
                val obj = JSONObject(String(data, Charsets.UTF_8))
                return AudioFormat(
                    sampleRate = obj.getInt("sample_rate"),
                    channels = obj.getInt("channels"),
                    encoding = obj.getString("encoding"),
                )
            } catch (e: JSONException) {
                throw FormatParseException("無法解析 FORMAT payload: ${e.message}", e)
            }
        }
    }
}

class FormatParseException(message: String, cause: Throwable? = null) : Exception(message, cause)

/** 支援的 encoding 清單，對應 core/audio_format.py 的 Encoding。 */
val SUPPORTED_ENCODINGS = setOf("pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le")

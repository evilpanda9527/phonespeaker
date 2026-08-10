package com.phonespeaker.app.core

import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.math.ceil
import kotlin.math.max

/**
 * RingBuffer.kt — PCM chunk 緩衝（§9：target 20–60ms，underrun 補最短靜音、
 * 不 crash、無無限 queue）。
 *
 * 用有界的 chunk queue 實作（不是逐 byte 的環形緩衝）：網路收到的每個 PCM
 * frame 就是一個 chunk，整包放進 queue；播放執行緒（AudioPlayer）從這裡
 * 取資料寫進 AudioTrack。
 *   - queue 滿了（PC 送得比手機播得快，或網路忽快忽慢）：丟最舊的 chunk，
 *     不無限累積、不 OOM。
 *   - queue 空了（underrun）：poll() 逾時回傳 null，由呼叫端（AudioPlayer）
 *     自己決定要寫多長的靜音，這裡不猜。
 */
class RingBuffer(
    /** 依目前 AudioFormat 算出的目標容量（chunk 數），至少保留 2 個。 */
    capacityChunks: Int,
) {
    private val capacity = max(2, capacityChunks)
    private val queue = ArrayBlockingQueue<ByteArray>(capacity)

    @Volatile
    var droppedChunkCount: Long = 0
        private set

    @Volatile
    var underrunCount: Long = 0
        private set

    /** 網路收到一個 PCM chunk 時呼叫。滿了就丟最舊的一筆，永遠不阻塞呼叫端。 */
    fun push(chunk: ByteArray) {
        while (!queue.offer(chunk)) {
            if (queue.poll() != null) {
                droppedChunkCount++
            }
        }
    }

    /**
     * 播放執行緒呼叫：等到有資料或逾時。逾時回傳 null（呼叫端自行補靜音），
     * 並計入 underrunCount 方便 GUI/log 顯示。
     */
    fun poll(timeoutMs: Long): ByteArray? {
        val chunk = queue.poll(timeoutMs, TimeUnit.MILLISECONDS)
        if (chunk == null) {
            underrunCount++
        }
        return chunk
    }

    fun clear() {
        queue.clear()
    }

    companion object {
        /**
         * 依格式與目標毫秒數（§9：20–60ms）換算成要保留幾個 chunk。
         * chunkBytes 是單一 PCM frame 的位元組數（跟 PC 端送過來的一致）。
         */
        fun capacityForTargetMs(
            format: AudioFormat,
            chunkBytes: Int,
            targetMs: Int,
        ): Int {
            if (chunkBytes <= 0) return 4
            val bytesPerMs = (format.sampleRate * format.bytesPerFrame()) / 1000.0
            val targetBytes = bytesPerMs * targetMs
            return max(2, ceil(targetBytes / chunkBytes).toInt())
        }
    }
}

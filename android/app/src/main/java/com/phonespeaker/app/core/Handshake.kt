package com.phonespeaker.app.core

import org.json.JSONObject

/**
 * Handshake.kt — HELLO/FORMAT/READY/FORMAT_UNSUPPORTED 訊息定義（§6）。
 *
 * 必須跟 PC 端 pc/core/handshake.py 的 wire 協定完全一致：
 *
 *     每個 frame = [4 bytes length, big-endian, u32][1 byte type][payload]
 *     length = 1(type) + payload.size
 *
 *     type 0x01 FORMAT              payload = JSON({sample_rate, channels, encoding})
 *     type 0x02 READY                payload = 空
 *     type 0x03 FORMAT_UNSUPPORTED   payload = UTF-8 錯誤原因字串（可為空）
 *     type 0x04 PCM                  payload = 原始 PCM bytes
 *
 * 這個檔案是穩定層，凍結後改動要走 §10.4 回歸流程（PC/Android 兩邊要一起改）。
 */
enum class MsgType(val value: Int) {
    FORMAT(0x01),
    READY(0x02),
    FORMAT_UNSUPPORTED(0x03),
    PCM(0x04);

    companion object {
        fun fromValue(value: Int): MsgType =
            entries.find { it.value == value }
                ?: throw IllegalArgumentException("未知的 frame type: $value")
    }
}

data class Frame(val type: MsgType, val payload: ByteArray) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is Frame) return false
        return type == other.type && payload.contentEquals(other.payload)
    }

    override fun hashCode(): Int {
        var result = type.hashCode()
        result = 31 * result + payload.contentHashCode()
        return result
    }
}

fun makeReadyFrame(): Frame = Frame(MsgType.READY, ByteArray(0))

fun makeFormatUnsupportedFrame(reason: String = ""): Frame =
    Frame(MsgType.FORMAT_UNSUPPORTED, reason.toByteArray(Charsets.UTF_8))

/** 收到 FORMAT frame 後解析成 AudioFormat；解析失敗代表協定不合，直接視為錯誤。 */
fun parseFormatFrame(frame: Frame): AudioFormat {
    require(frame.type == MsgType.FORMAT) { "預期 FORMAT frame，卻收到 ${frame.type}" }
    return AudioFormat.fromJsonBytes(frame.payload)
}

/** 除錯用：把 payload 轉成人看得懂的字串（僅供 log，不用於協定判斷）。 */
fun Frame.payloadAsDebugString(): String = try {
    when (type) {
        MsgType.FORMAT -> JSONObject(String(payload, Charsets.UTF_8)).toString()
        MsgType.FORMAT_UNSUPPORTED -> String(payload, Charsets.UTF_8)
        MsgType.READY -> "(empty)"
        MsgType.PCM -> "${payload.size} bytes"
    }
} catch (e: Exception) {
    "<unparsable: ${e.message}>"
}

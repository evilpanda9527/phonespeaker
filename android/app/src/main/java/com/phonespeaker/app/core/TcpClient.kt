package com.phonespeaker.app.core

import java.io.EOFException
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.Socket

/**
 * TcpClient.kt — 凍結共用 TCP framing 輔助（§13：wifi / u1 / u2 共用）。
 *
 * 對應 PC 端 pc/core/tcp_client.py，只負責「怎麼在一條已建立的 socket 上
 * 收送 Frame」，不知道 socket 是誰建立的、也不知道上層是哪個 transport 在用。
 *
 * 依 §10.3：這個檔案一旦 WiFi 驗收通過就視為凍結，之後 U1/U2 只能「使用」它。
 */
private const val HEADER_LEN = 4
private const val TYPE_LEN = 1
private const val MAX_FRAME_LEN = 64 * 1024 * 1024 // 64MB 上限，防止壞資料造成記憶體暴衝

class ConnectionClosedException(message: String) : IOException(message)

object TcpFraming {

    @Throws(IOException::class)
    fun sendFrame(out: OutputStream, frame: Frame) {
        val body = ByteArray(TYPE_LEN + frame.payload.size)
        body[0] = frame.type.value.toByte()
        System.arraycopy(frame.payload, 0, body, TYPE_LEN, frame.payload.size)

        val header = ByteArray(HEADER_LEN)
        writeBigEndianInt(header, 0, body.size)

        out.write(header)
        out.write(body)
        out.flush()
    }

    @Throws(IOException::class)
    fun recvFrame(input: InputStream): Frame {
        val header = readExact(input, HEADER_LEN)
        val length = readBigEndianInt(header, 0)
        if (length < TYPE_LEN || length > MAX_FRAME_LEN) {
            throw IOException("frame 長度不合法: $length")
        }
        val body = readExact(input, length)
        val typeByte = body[0].toInt() and 0xFF
        val type = MsgType.fromValue(typeByte)
        val payload = body.copyOfRange(TYPE_LEN, body.size)
        return Frame(type, payload)
    }

    @Throws(IOException::class)
    private fun readExact(input: InputStream, n: Int): ByteArray {
        val buf = ByteArray(n)
        var offset = 0
        while (offset < n) {
            val read = input.read(buf, offset, n - offset)
            if (read < 0) {
                throw ConnectionClosedException("對端關閉連線（read 回傳 -1）")
            }
            if (read == 0) {
                // 理論上 blocking socket read() 不該回傳 0；防禦性處理避免忙迴圈。
                throw EOFException("讀到 0 bytes（非預期）")
            }
            offset += read
        }
        return buf
    }

    private fun writeBigEndianInt(buf: ByteArray, offset: Int, value: Int) {
        buf[offset] = ((value ushr 24) and 0xFF).toByte()
        buf[offset + 1] = ((value ushr 16) and 0xFF).toByte()
        buf[offset + 2] = ((value ushr 8) and 0xFF).toByte()
        buf[offset + 3] = (value and 0xFF).toByte()
    }

    private fun readBigEndianInt(buf: ByteArray, offset: Int): Int {
        return ((buf[offset].toInt() and 0xFF) shl 24) or
            ((buf[offset + 1].toInt() and 0xFF) shl 16) or
            ((buf[offset + 2].toInt() and 0xFF) shl 8) or
            (buf[offset + 3].toInt() and 0xFF)
    }

    /** 低延遲導向：關掉 Nagle，避免小封包被延遲合併。 */
    @Throws(IOException::class)
    fun configureSocketForStreaming(socket: Socket) {
        socket.tcpNoDelay = true
    }
}

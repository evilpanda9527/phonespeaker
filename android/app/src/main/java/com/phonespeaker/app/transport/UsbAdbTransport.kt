package com.phonespeaker.app.transport

import android.content.Context
import android.util.Log
import com.phonespeaker.app.core.ConnectionClosedException
import com.phonespeaker.app.core.Frame
import com.phonespeaker.app.core.TcpFraming
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.atomic.AtomicBoolean

private const val TAG = "UsbAdbTransport"

// 對應 pc/config.py 的 ADB_HOST / TCP_LISTEN_PORT。U2 靠 PC 端執行的
// `adb reverse tcp:<PORT> tcp:<PORT>` 把「手機連 127.0.0.1:<PORT>」轉發到
// PC 上真正監聽的 socket——手機端完全不需要知道 PC 的實際 IP，也不需要
// mDNS 探索（跟 WiFi/U1 最大的差別，見 pc/transport/usb_adb.py 開頭的
// 方向說明：PC 是 TCP server、手機是 client，因此用 `adb reverse` 而非
// `adb forward`）。
private const val ADB_REVERSE_HOST = "127.0.0.1"
private const val ADB_REVERSE_PORT = 58482
private const val SOCKET_CONNECT_TIMEOUT_MS = 5_000

// PC 端要先偵測 adb / 建好 reverse 規則、TCP server 才會真的開始聽，跟手機
// 這邊按下「啟動」的時序不保證同步；用短暫重試取代單次 connect() 失敗就
// 整個放棄，體驗上跟 WifiTransport/UsbTcpTransport「阻塞等待對面出現」的
// 精神一致，也避免外層 StreamerService.runEngine() 的 while 迴圈在 PC 端
// 還沒就緒時忙迴圈狂重試（見該檔案 runEngine() 的 catch TransportException
// → continue）。
private const val CONNECT_RETRY_INTERVAL_MS = 500L
private const val CONNECT_RETRY_TOTAL_TIMEOUT_MS = 20_000L

/**
 * UsbAdbTransport.kt — U2: USB (adb) transport（§8.2 U2）。
 *
 * 跟 WifiTransport/UsbTcpTransport 的差別：完全不做網路探索（不需要，也
 * 不能——adb reverse 只轉發 127.0.0.1 上的連線，探索本機網卡沒有意義）。
 * PC 端負責在使用者按下「啟動」時先透過 adb 建好 reverse 轉發規則；手機端
 * 這裡只需要重試連 localhost，直到 PC 端真的把 socket 開起來聽（或使用者
 * 取消）。
 *
 * 依 §10.3 檔案隔離：這是 U2 專屬檔案，不繼承/呼叫 WifiTransport 或
 * UsbTcpTransport 的任何內部邏輯。
 */
class UsbAdbTransport(@Suppress("UNUSED_PARAMETER") context: Context) : Transport {

    override val displayName: String = "USB (adb)"

    @Volatile
    private var socket: Socket? = null
    private val cancelled = AtomicBoolean(false)

    override val isConnected: Boolean
        get() = socket?.isConnected == true && socket?.isClosed == false

    @Throws(TransportException::class)
    override fun connect() {
        if (socket != null) {
            throw TransportException("已經有連線中的 socket，請先 disconnect()")
        }
        cancelled.set(false)

        val deadline = System.currentTimeMillis() + CONNECT_RETRY_TOTAL_TIMEOUT_MS
        var lastError: IOException? = null
        while (!cancelled.get()) {
            try {
                val newSocket = Socket()
                newSocket.connect(
                    InetSocketAddress(ADB_REVERSE_HOST, ADB_REVERSE_PORT),
                    SOCKET_CONNECT_TIMEOUT_MS,
                )
                TcpFraming.configureSocketForStreaming(newSocket)
                socket = newSocket
                Log.i(TAG, "已透過 adb reverse 連線到 PC: $ADB_REVERSE_HOST:$ADB_REVERSE_PORT")
                return
            } catch (e: IOException) {
                lastError = e
            }
            if (cancelled.get() || System.currentTimeMillis() >= deadline) break
            try {
                Thread.sleep(CONNECT_RETRY_INTERVAL_MS)
            } catch (ie: InterruptedException) {
                Thread.currentThread().interrupt()
                break
            }
        }

        if (cancelled.get()) {
            throw TransportCancelledException("connect() 被取消")
        }
        throw TransportException(
            "連線到 $ADB_REVERSE_HOST:$ADB_REVERSE_PORT 失敗" +
                "（已重試 ${CONNECT_RETRY_TOTAL_TIMEOUT_MS}ms）：請確認 PC 端已選「USB (adb)」" +
                "並按下啟動、且 adb 已偵測到這台手機（USB 偵錯已授權）。" +
                "詳細錯誤: ${lastError?.message}",
        )
    }

    override fun requestCancel() {
        cancelled.set(true)
        socket?.let { s ->
            try {
                s.close()
            } catch (e: IOException) {
                Log.d(TAG, "取消時關閉 socket 發生非致命錯誤: ${e.message}")
            }
        }
    }

    override fun disconnect() {
        cancelled.set(true)
        socket?.let { s ->
            try {
                s.close()
            } catch (e: IOException) {
                Log.d(TAG, "關閉 socket 時發生非致命錯誤: ${e.message}")
            }
        }
        socket = null
    }

    @Throws(TransportException::class)
    override fun sendFrame(frame: Frame) {
        val s = socket ?: throw TransportException("尚未連線")
        try {
            TcpFraming.sendFrame(s.getOutputStream(), frame)
        } catch (e: IOException) {
            socket = null
            throw TransportException("送出資料失敗: ${e.message}", e)
        }
    }

    @Throws(TransportException::class)
    override fun recvFrame(): Frame {
        val s = socket ?: throw TransportException("尚未連線")
        return try {
            TcpFraming.recvFrame(s.getInputStream())
        } catch (e: ConnectionClosedException) {
            socket = null
            throw TransportException("接收資料失敗: ${e.message}", e)
        } catch (e: IOException) {
            socket = null
            throw TransportException("接收資料失敗: ${e.message}", e)
        }
    }
}

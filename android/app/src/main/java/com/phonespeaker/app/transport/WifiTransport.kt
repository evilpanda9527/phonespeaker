package com.phonespeaker.app.transport

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import com.phonespeaker.app.core.ConnectionClosedException
import com.phonespeaker.app.core.Frame
import com.phonespeaker.app.core.TcpFraming
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

private const val TAG = "WifiTransport"

// 注意：Android NsdManager 的 serviceType 慣例是「service+proto+trailing dot」，
// 不含 ".local."（跟 PC 端 zeroconf 用的完整 mDNS type 字串格式不同，Android
// 底層 NSD 服務會自己補上 local domain）。必須跟 pc/config.py 的
// ZEROCONF_SERVICE_TYPE（"_phonespeaker._tcp.local."）代表同一個服務。
const val WIFI_SERVICE_TYPE = "_phonespeaker._tcp."
const val WIFI_SERVICE_NAME_PREFIX = "PhoneSpeaker"

private const val DISCOVERY_TIMEOUT_MS = 20_000L
private const val SOCKET_CONNECT_TIMEOUT_MS = 5_000

/**
 * WifiTransport — WiFi transport（§8.1，M1-A 第一個做的 transport）。
 *
 * Android 端是 client：用 NsdManager 探索 PC 廣播的服務，解析出 host:port
 * 後建立 TCP 連線；不用手動輸入 IP。依 §10.3 檔案隔離：這是 WiFi 專屬檔案，
 * 之後做 U1/U2/U3/BT 不應該修改這個檔案。
 */
class WifiTransport(private val context: Context) : Transport {

    override val displayName: String = "WiFi"

    @Volatile
    private var socket: Socket? = null
    private val cancelled = AtomicBoolean(false)

    private var nsdManager: NsdManager? = null
    private var discoveryListener: NsdManager.DiscoveryListener? = null

    @Volatile
    private var discoveryLatch: CountDownLatch? = null

    override val isConnected: Boolean
        get() = socket?.isConnected == true && socket?.isClosed == false

    @Throws(TransportException::class)
    override fun connect() {
        if (socket != null) {
            throw TransportException("已經有連線中的 socket，請先 disconnect()")
        }
        cancelled.set(false)

        val resolved = discoverService()
        if (resolved == null) {
            if (cancelled.get()) {
                throw TransportCancelledException("connect() 被取消（探索階段）")
            }
            throw TransportException("在 ${DISCOVERY_TIMEOUT_MS}ms 內找不到 PC（zeroconf 探索逾時）")
        }

        try {
            val newSocket = Socket()
            newSocket.connect(
                InetSocketAddress(resolved.host, resolved.port),
                SOCKET_CONNECT_TIMEOUT_MS,
            )
            TcpFraming.configureSocketForStreaming(newSocket)
            socket = newSocket
            Log.i(TAG, "已連線到 PC: ${resolved.host}:${resolved.port}")
        } catch (e: IOException) {
            if (cancelled.get()) {
                throw TransportCancelledException("connect() 被取消（連線階段）")
            }
            throw TransportException("連線到 ${resolved.host}:${resolved.port} 失敗: ${e.message}", e)
        }
    }

    override fun requestCancel() {
        cancelled.set(true)
        discoveryLatch?.countDown()
        stopDiscovery()
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
        discoveryLatch?.countDown()
        stopDiscovery()
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

    private data class ResolvedService(val host: String, val port: Int)

    private fun discoverService(): ResolvedService? {
        val manager = context.getSystemService(Context.NSD_SERVICE) as NsdManager
        nsdManager = manager

        val latch = CountDownLatch(1)
        discoveryLatch = latch
        val resultHolder = arrayOfNulls<ResolvedService>(1)

        val resolveListener = object : NsdManager.ResolveListener {
            override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                Log.w(TAG, "resolve 失敗 errorCode=$errorCode")
                latch.countDown()
            }

            override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                val host = serviceInfo.host?.hostAddress
                if (host != null) {
                    resultHolder[0] = ResolvedService(host, serviceInfo.port)
                }
                latch.countDown()
            }
        }

        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {
                Log.i(TAG, "zeroconf 探索已啟動: $serviceType")
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                if (!serviceInfo.serviceName.startsWith(WIFI_SERVICE_NAME_PREFIX)) {
                    return
                }
                Log.i(TAG, "找到服務: ${serviceInfo.serviceName}")
                try {
                    @Suppress("DEPRECATION")
                    manager.resolveService(serviceInfo, resolveListener)
                } catch (e: IllegalArgumentException) {
                    // 同一個 listener 短時間內被重複呼叫 resolve 時可能發生，忽略即可，
                    // 之後仍會因為逾時或使用者取消而結束等待。
                    Log.w(TAG, "resolveService 呼叫失敗: ${e.message}")
                }
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                Log.i(TAG, "服務消失: ${serviceInfo.serviceName}")
            }

            override fun onDiscoveryStopped(serviceType: String) {
                Log.i(TAG, "zeroconf 探索已停止")
            }

            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.w(TAG, "探索啟動失敗 errorCode=$errorCode")
                latch.countDown()
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.w(TAG, "停止探索失敗 errorCode=$errorCode")
            }
        }
        discoveryListener = listener

        manager.discoverServices(WIFI_SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)

        latch.await(DISCOVERY_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        discoveryLatch = null
        stopDiscovery()
        return resultHolder[0]
    }

    private fun stopDiscovery() {
        val manager = nsdManager
        val listener = discoveryListener
        if (manager != null && listener != null) {
            try {
                manager.stopServiceDiscovery(listener)
            } catch (e: IllegalArgumentException) {
                // 探索早已停止（例如已經 timeout 過一次）時會丟這個，安全忽略。
            }
        }
        discoveryListener = null
    }
}

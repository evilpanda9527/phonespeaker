package com.phonespeaker.app.transport

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import com.phonespeaker.app.core.ConnectionClosedException
import com.phonespeaker.app.core.Frame
import com.phonespeaker.app.core.TcpFraming
import java.io.IOException
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket
import java.util.Collections
import java.util.concurrent.Callable
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

private const val TAG = "UsbTcpTransport"

// U1 用比 WiFi 短的逾時：PoC 已實測 mDNS 能跨 RNDIS（見 §16-3 前置調查），
// 正常情況應該很快解析到，不需要像 WifiTransport 那樣等到 20 秒；逾時後
// 盡快切到子網掃描 fallback，避免使用者等太久。
private const val MDNS_DISCOVERY_TIMEOUT_MS = 6_000L
private const val SOCKET_CONNECT_TIMEOUT_MS = 5_000
private const val SUBNET_SCAN_PER_HOST_TIMEOUT_MS = 200
private const val SUBNET_SCAN_CONCURRENCY = 32

// 對應 pc/config.py 的 TCP_LISTEN_PORT。走 mDNS 解析到的連線一律用 PC 廣播
// 出來的 port（跟 WifiTransport 一樣不用寫死）；只有走「子網掃描」這個
// fallback、完全沒有 mDNS 資訊可用時，才需要這個寫死的預設 port 去試連。
private const val FALLBACK_SCAN_PORT = 58482

/**
 * UsbTcpTransport.kt — U1: USB 網路共享（RNDIS）transport（§8.2 U1）。
 *
 * 架構跟 WifiTransport 幾乎一樣：都是 TCP client + mDNS 探索。跟
 * WifiTransport 的差別只在：mDNS 逾時後多一層子網掃描 fallback，不需要
 * 使用者手動輸入 IP（見 U1 PoC 報告：Android 端 NsdManager 是否能穩定跨
 * RNDIS 因裝置/版本而異，子網掃描是不依賴 mDNS 是否可靠的保底路徑）。
 *
 * 依 §10.3 檔案隔離：這是 U1 專屬檔案，刻意不繼承/呼叫 WifiTransport 的
 * 任何內部邏輯，只共用同一個 package 內的 mDNS service type/name 常數
 * （定義在 WifiTransport.kt——兩邊本來就是同一個 PC 端服務，只是走不同
 * 實體鏈路，共用探索目標是合理的，不算破壞檔案隔離）。
 */
class UsbTcpTransport(private val context: Context) : Transport {

    override val displayName: String = "USB (USB 網路共享)"

    @Volatile
    private var socket: Socket? = null
    private val cancelled = AtomicBoolean(false)

    private var nsdManager: NsdManager? = null
    private var discoveryListener: NsdManager.DiscoveryListener? = null

    @Volatile
    private var discoveryLatch: CountDownLatch? = null

    @Volatile
    private var scanExecutor: ExecutorService? = null

    override val isConnected: Boolean
        get() = socket?.isConnected == true && socket?.isClosed == false

    @Throws(TransportException::class)
    override fun connect() {
        if (socket != null) {
            throw TransportException("已經有連線中的 socket，請先 disconnect()")
        }
        cancelled.set(false)

        var resolved = discoverViaMdns()
        if (resolved == null && !cancelled.get()) {
            Log.i(TAG, "mDNS 在 ${MDNS_DISCOVERY_TIMEOUT_MS}ms 內沒解析到，改用子網掃描 fallback")
            resolved = scanSubnet()
        }

        if (resolved == null) {
            if (cancelled.get()) {
                throw TransportCancelledException("connect() 被取消（探索階段）")
            }
            throw TransportException(
                "mDNS 探索與子網掃描都找不到 PC——請確認手機已開啟「USB 網路共享」，" +
                    "且 PC 端 GUI 有顯示偵測到的 USB IP"
            )
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
        scanExecutor?.shutdownNow()
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
        scanExecutor?.shutdownNow()
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

    /** 主路徑：跟 WifiTransport 一樣用 NsdManager 探索，只是逾時較短。 */
    private fun discoverViaMdns(): ResolvedService? {
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

        // WIFI_SERVICE_TYPE / WIFI_SERVICE_NAME_PREFIX 定義在同一個 package
        // 的 WifiTransport.kt——PC 端廣播的是同一個服務，這裡刻意共用探索
        // 目標常數，不算修改 WifiTransport 的行為。
        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {
                Log.i(TAG, "mDNS 探索已啟動（USB/RNDIS）: $serviceType")
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
                Log.i(TAG, "mDNS 探索已停止（USB/RNDIS）")
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

        latch.await(MDNS_DISCOVERY_TIMEOUT_MS, TimeUnit.MILLISECONDS)
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

    /**
     * fallback 路徑：找出目前手機上「像是 RNDIS」的介面（依介面名稱/顯示
     * 名稱含 "rndis" 判斷；真的找不到就退而求其次，試所有非 loopback 的
     * IPv4 介面），對它所在的 /24 網段平行掃 TCP port，找第一個能連上的
     * 位址。USB 網路共享是點對點高速鏈路，掃一輪通常在一兩秒內完成。
     */
    private fun scanSubnet(): ResolvedService? {
        val candidates = collectScanCandidates()
        if (candidates.isEmpty()) {
            Log.w(TAG, "子網掃描 fallback：找不到可用的本機網路介面")
            return null
        }

        val executor = Executors.newFixedThreadPool(SUBNET_SCAN_CONCURRENCY)
        scanExecutor = executor
        try {
            for (candidate in candidates) {
                if (cancelled.get()) return null
                Log.i(
                    TAG,
                    "子網掃描 fallback：掃描 ${candidate.subnetBase}.0/24（本機位址 ${candidate.localIp}）",
                )
                val found = scanOneSubnet(executor, candidate)
                if (found != null) return found
            }
        } finally {
            executor.shutdownNow()
            scanExecutor = null
        }
        return null
    }

    private data class ScanCandidate(val localIp: String, val subnetBase: String)

    private fun collectScanCandidates(): List<ScanCandidate> {
        val rndisNamed = mutableListOf<ScanCandidate>()
        val others = mutableListOf<ScanCandidate>()
        try {
            val interfaces = Collections.list(NetworkInterface.getNetworkInterfaces())
            for (iface in interfaces) {
                if (!iface.isUp || iface.isLoopback) continue
                val isRndisNamed = iface.name.contains("rndis", ignoreCase = true) ||
                    iface.displayName?.contains("rndis", ignoreCase = true) == true
                for (addr in Collections.list(iface.inetAddresses)) {
                    if (addr !is Inet4Address) continue
                    val host = addr.hostAddress ?: continue
                    if (host.startsWith("127.") || host.startsWith("169.254.")) continue
                    val base = host.substringBeforeLast('.')
                    val candidate = ScanCandidate(localIp = host, subnetBase = base)
                    if (isRndisNamed) rndisNamed.add(candidate) else others.add(candidate)
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "列舉本機網路介面失敗: ${e.message}")
        }
        // 介面名稱像 RNDIS 的優先試；真的沒有才退而求其次試其他介面
        // （保險用——萬一手機端 RNDIS 介面的實際命名跟預期不同）。
        return rndisNamed.ifEmpty { others }
    }

    private fun scanOneSubnet(executor: ExecutorService, candidate: ScanCandidate): ResolvedService? {
        val tasks = (1..254).mapNotNull { lastOctet ->
            val targetIp = "${candidate.subnetBase}.$lastOctet"
            if (targetIp == candidate.localIp) {
                null
            } else {
                Callable<ResolvedService?> {
                    if (cancelled.get()) return@Callable null
                    try {
                        Socket().use { probe ->
                            probe.connect(
                                InetSocketAddress(targetIp, FALLBACK_SCAN_PORT),
                                SUBNET_SCAN_PER_HOST_TIMEOUT_MS,
                            )
                            ResolvedService(targetIp, FALLBACK_SCAN_PORT)
                        }
                    } catch (e: IOException) {
                        // 這個位址沒有人在聽，正常情況，忽略即可。
                        null
                    }
                }
            }
        }
        val totalTimeoutMs =
            (SUBNET_SCAN_PER_HOST_TIMEOUT_MS.toLong() * tasks.size / SUBNET_SCAN_CONCURRENCY) + 3_000L
        return try {
            val futures = executor.invokeAll(tasks, totalTimeoutMs, TimeUnit.MILLISECONDS)
            futures.firstNotNullOfOrNull { future ->
                if (future.isCancelled) null else runCatching { future.get() }.getOrNull()
            }
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            null
        }
    }
}

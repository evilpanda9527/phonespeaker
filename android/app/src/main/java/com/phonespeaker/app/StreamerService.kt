package com.phonespeaker.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import com.phonespeaker.app.core.AudioFormat
import com.phonespeaker.app.core.AudioFormatUnsupportedException
import com.phonespeaker.app.core.AudioPlayer
import com.phonespeaker.app.core.MsgType
import com.phonespeaker.app.core.RingBuffer
import com.phonespeaker.app.core.makeFormatUnsupportedFrame
import com.phonespeaker.app.core.makeReadyFrame
import com.phonespeaker.app.core.payloadAsDebugString
import com.phonespeaker.app.transport.Transport
import com.phonespeaker.app.transport.TransportCancelledException
import com.phonespeaker.app.transport.TransportException
import com.phonespeaker.app.transport.UsbTcpTransport
import com.phonespeaker.app.transport.WifiTransport

/**
 * StreamerService.kt — 前景服務、transport 管理、reconnect（§4 StreamerService）。
 *
 * 對應 PC 端 pc/core/stream_engine.py 的角色：把 Transport、AudioPlayer、
 * RingBuffer 串起來跑狀態機，並用 Foreground Service 確保鎖屏後仍能續播。
 *
 * transport 依 MainActivity 傳進來的 [TransportMode]（見 [EXTRA_TRANSPORT_MODE]）
 * 由 [createTransport] 建立對應實作；U2/U3/BT 驗收通過後，比照 U1 在
 * [TransportMode] 加一個成員、[createTransport] 加一個分支即可，不需要動
 * 狀態機本身的邏輯（見 runEngine()/handleConnection()，兩者從頭到尾都沒改）。
 */
enum class ServiceState { IDLE, DISCOVERING, HANDSHAKE, STREAMING, STOPPED }

/** 使用者在 MainActivity 選的連線方式，透過 [StreamerService.EXTRA_TRANSPORT_MODE] 傳入。 */
enum class TransportMode { WIFI, USB_RNDIS }

interface StatusListener {
    fun onStateChanged(state: ServiceState) {}
    fun onFormatChanged(format: AudioFormat?) {}
    fun onLog(message: String) {}
    fun onError(message: String) {}
}

class StreamerService : Service() {

    companion object {
        private const val TAG = "StreamerService"
        const val ACTION_START = "com.phonespeaker.app.action.START"
        const val ACTION_STOP = "com.phonespeaker.app.action.STOP"
        /** String extra，值是 [TransportMode] 的 name（例如 "WIFI"、"USB_RNDIS"）。 */
        const val EXTRA_TRANSPORT_MODE = "com.phonespeaker.app.extra.TRANSPORT_MODE"

        private const val NOTIFICATION_CHANNEL_ID = "phonespeaker_streaming"
        private const val NOTIFICATION_ID = 1

        // 依 §9：ring buffer target 20–60ms，取上限比較保守（少一點 underrun）。
        private const val RING_BUFFER_TARGET_MS = 60

        /** 讓 MainActivity 訂閱狀態；同一個 process 內的簡單 observer，M1-A 夠用。 */
        @Volatile
        var listener: StatusListener? = null

        @Volatile
        var currentState: ServiceState = ServiceState.IDLE
            private set

        @Volatile
        var currentFormat: AudioFormat? = null
            private set
    }

    private var engineThread: Thread? = null
    @Volatile private var stopRequested = false
    private var transport: Transport? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var selectedMode: TransportMode = TransportMode.WIFI

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopEngine()
                stopSelf()
            }
            else -> {
                val modeName = intent?.getStringExtra(EXTRA_TRANSPORT_MODE)
                // 找不到/不合法的 mode 名稱時退回 WIFI，維持 M1-A 既有行為，
                // 不因為傳輸模式參數缺失就整個啟動失敗。
                selectedMode = TransportMode.values().find { it.name == modeName } ?: TransportMode.WIFI
                startEngine()
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        stopEngine()
        super.onDestroy()
    }

    // ------------------------------------------------------------------ //
    // 生命週期
    // ------------------------------------------------------------------ //

    private fun startEngine() {
        if (engineThread != null) {
            Log.d(TAG, "engine 已在執行中")
            return
        }
        startForeground(NOTIFICATION_ID, buildNotification(getString(R.string.status_discovering)))
        acquireWakeLock()

        stopRequested = false
        val thread = Thread({ runEngine() }, "streamer-engine")
        engineThread = thread
        thread.start()
    }

    private fun stopEngine() {
        stopRequested = true
        transport?.requestCancel()
        transport?.disconnect()
        engineThread?.join(3000)
        engineThread = null
        releaseWakeLock()
        setState(ServiceState.STOPPED)
        // stopForeground(int) 的 STOP_FOREGROUND_REMOVE 是 API 33+ 才有的 overload；
        // minSdk 26 必須用舊版 boolean overload 才能在所有支援的裝置上正常運作。
        @Suppress("DEPRECATION")
        stopForeground(true)
    }

    private fun acquireWakeLock() {
        if (wakeLock != null) return
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        val lock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "PhoneSpeaker:streaming")
        lock.setReferenceCounted(false)
        lock.acquire(6 * 60 * 60 * 1000L /* 最長 6 小時保險上限，避免忘記釋放耗電 */)
        wakeLock = lock
    }

    private fun releaseWakeLock() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }

    // ------------------------------------------------------------------ //
    // 狀態機主迴圈（背景執行緒）
    // ------------------------------------------------------------------ //

    private fun runEngine() {
        while (!stopRequested) {
            setState(ServiceState.DISCOVERING)
            log("等待/搜尋 PC…")

            val activeTransport = createTransport(selectedMode)
            transport = activeTransport

            try {
                activeTransport.connect()
            } catch (e: TransportCancelledException) {
                break
            } catch (e: TransportException) {
                error("連線失敗: ${e.message}")
                if (stopRequested) break
                continue
            }

            setState(ServiceState.HANDSHAKE)
            try {
                handleConnection(activeTransport)
            } catch (e: TransportException) {
                log("連線中斷: ${e.message}")
            } finally {
                activeTransport.disconnect()
            }

            if (stopRequested) break
            log("已斷線，回到等待連線狀態（§3 reconnect）")
        }
        setState(ServiceState.STOPPED)
    }

    /** 唯一「依使用者選的模式建立對應 transport」的地方；狀態機其餘邏輯完全不知道用的是哪個 transport。 */
    private fun createTransport(mode: TransportMode): Transport = when (mode) {
        TransportMode.WIFI -> WifiTransport(applicationContext)
        TransportMode.USB_RNDIS -> UsbTcpTransport(applicationContext)
    }

    @Throws(TransportException::class)
    private fun handleConnection(transport: Transport) {
        // 第一個 frame 一定是 FORMAT（§6 握手）。
        var frame = transport.recvFrame()
        if (frame.type != MsgType.FORMAT) {
            log("預期收到 FORMAT，卻收到 ${frame.type}，忽略此連線")
            return
        }

        var player: AudioPlayer? = null
        var ringBuffer: RingBuffer? = null

        try {
            while (!stopRequested) {
                val fmt = try {
                    AudioFormat.fromJsonBytes(frame.payload)
                } catch (e: Exception) {
                    transport.sendFrame(makeFormatUnsupportedFrame("FORMAT payload 解析失敗: ${e.message}"))
                    error("收到的 FORMAT 無法解析: ${e.message}")
                    return
                }

                // 收到新的 FORMAT（第一次，或 PC 端 §7 裝置熱切換後重送）：
                // 先停掉舊的 player 再用新格式重建。
                player?.stop()
                ringBuffer?.clear()

                // 480 frames/chunk 對應 PC 端 config.py 的 CAPTURE_CHUNK_FRAMES 預設值，
                // 只是拿來估算「要保留幾個 chunk」；就算 PC 端實際 chunk 大小不同，
                // RingBuffer 本身是以「chunk 數」為單位運作，不影響正確性，只影響
                // 換算出來的 target ms 準不準（純粹是 UI/log 顯示層面的估計值）。
                val newPlayer = AudioPlayer()
                val newRingBuffer = RingBuffer(
                    RingBuffer.capacityForTargetMs(fmt, fmt.bytesPerFrame() * 480, RING_BUFFER_TARGET_MS)
                )
                try {
                    newPlayer.start(fmt, newRingBuffer)
                } catch (e: AudioFormatUnsupportedException) {
                    transport.sendFrame(makeFormatUnsupportedFrame(e.message ?: "unsupported"))
                    error("FORMAT_UNSUPPORTED: ${e.message}")
                    return
                }

                transport.sendFrame(makeReadyFrame())
                log("已回 READY，開始播放 (${fmt.sampleRate}Hz/${fmt.channels}ch/${fmt.encoding})")
                setFormat(fmt)
                setState(ServiceState.STREAMING)
                updateNotification(getString(R.string.status_streaming))

                player = newPlayer
                ringBuffer = newRingBuffer

                // 收 frame 主迴圈：PCM 進 ring buffer，FORMAT 代表要重建播放。
                var nextFrame: com.phonespeaker.app.core.Frame? = null
                while (!stopRequested) {
                    val f = transport.recvFrame()
                    when (f.type) {
                        MsgType.PCM -> ringBuffer.push(f.payload)
                        MsgType.FORMAT -> {
                            log("PC 端重送 FORMAT（裝置熱切換，§7），重建播放: ${f.payloadAsDebugString()}")
                            nextFrame = f
                        }
                        else -> log("串流中收到非預期 frame type=${f.type}，忽略")
                    }
                    if (nextFrame != null) break
                }
                if (nextFrame == null) {
                    // stopRequested 造成的正常跳出
                    break
                }
                frame = nextFrame
            }
        } finally {
            player?.stop()
            ringBuffer?.clear()
        }
    }

    // ------------------------------------------------------------------ //
    // 狀態/通知回報
    // ------------------------------------------------------------------ //

    private fun setState(state: ServiceState) {
        currentState = state
        listener?.onStateChanged(state)
    }

    private fun setFormat(format: AudioFormat?) {
        currentFormat = format
        listener?.onFormatChanged(format)
    }

    private fun log(message: String) {
        Log.i(TAG, message)
        listener?.onLog(message)
    }

    private fun error(message: String) {
        Log.e(TAG, message)
        listener?.onError(message)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            NOTIFICATION_CHANNEL_ID,
            getString(R.string.notification_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        )
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(text: String): Notification {
        val stopIntent = Intent(this, StreamerService::class.java).apply { action = ACTION_STOP }
        val stopPendingIntent = PendingIntent.getService(
            this, 0, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val openIntent = Intent(this, MainActivity::class.java)
        val openPendingIntent = PendingIntent.getActivity(
            this, 0, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, NOTIFICATION_CHANNEL_ID)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentIntent(openPendingIntent)
            .addAction(0, getString(R.string.btn_stop), stopPendingIntent)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(text: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification(text))
    }
}

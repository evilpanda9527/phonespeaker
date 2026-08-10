package com.phonespeaker.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.phonespeaker.app.core.AudioFormat
import com.phonespeaker.app.databinding.ActivityMainBinding

/**
 * MainActivity.kt — M1-A 範圍的最小 UI：啟動/停止、狀態、格式、log。
 *
 * transport 選擇目前只有 WiFi（寫死在 StreamerService），之後 U1/U2/U3/BT
 * 驗收通過後再補上選單（§10.3：新增選項不動既有邏輯）。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var running = false

    private val notificationPermissionLauncher =
        registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.RequestPermission()) { }

    private val statusListener = object : StatusListener {
        override fun onStateChanged(state: ServiceState) {
            runOnUiThread { renderState(state) }
        }

        override fun onFormatChanged(format: AudioFormat?) {
            runOnUiThread {
                binding.formatText.text = format?.let {
                    "${it.sampleRate}Hz / ${it.channels}ch / ${it.encoding}"
                } ?: "—"
            }
        }

        override fun onLog(message: String) {
            runOnUiThread { appendLog(message) }
        }

        override fun onError(message: String) {
            runOnUiThread { appendLog("[錯誤] $message") }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.startStopButton.setOnClickListener { onToggleStartStop() }

        requestNotificationPermissionIfNeeded()
    }

    override fun onResume() {
        super.onResume()
        StreamerService.listener = statusListener
        renderState(StreamerService.currentState)
        binding.formatText.text = StreamerService.currentFormat?.let {
            "${it.sampleRate}Hz / ${it.channels}ch / ${it.encoding}"
        } ?: "—"
    }

    override fun onPause() {
        StreamerService.listener = null
        super.onPause()
    }

    private fun onToggleStartStop() {
        if (running) {
            val intent = Intent(this, StreamerService::class.java).apply {
                action = StreamerService.ACTION_STOP
            }
            startService(intent)
        } else {
            val intent = Intent(this, StreamerService::class.java).apply {
                action = StreamerService.ACTION_START
            }
            ContextCompat.startForegroundService(this, intent)
        }
    }

    private fun renderState(state: ServiceState) {
        running = state == ServiceState.DISCOVERING ||
            state == ServiceState.HANDSHAKE ||
            state == ServiceState.STREAMING
        binding.startStopButton.text = getString(if (running) R.string.btn_stop else R.string.btn_start)
        binding.statusText.text = when (state) {
            ServiceState.IDLE -> getString(R.string.status_idle)
            ServiceState.DISCOVERING -> getString(R.string.status_discovering)
            ServiceState.HANDSHAKE -> getString(R.string.status_handshaking)
            ServiceState.STREAMING -> getString(R.string.status_streaming)
            ServiceState.STOPPED -> getString(R.string.status_stopped)
        }
    }

    private fun appendLog(message: String) {
        binding.logText.append(message + "\n")
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                this, Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
            if (!granted) {
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }
}

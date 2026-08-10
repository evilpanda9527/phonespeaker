package com.phonespeaker.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.phonespeaker.app.core.AudioFormat
import com.phonespeaker.app.databinding.ActivityMainBinding

/**
 * MainActivity.kt — 最小 UI：transport 選擇、啟動/停止、狀態、格式、log。
 *
 * transport 選單目前有 WiFi、USB (USB 網路共享)、USB (adb) 三項（見
 * [transportOptions]）；U3/BT 驗收通過後，比照 U2 在 [transportOptions]
 * 加一行即可（§10.3：新增選項不動既有邏輯）。選到的模式透過 Intent extra
 * 傳給 StreamerService，實際建立哪個 Transport 由 StreamerService 決定。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var running = false

    /** 顯示文字（跟 PC 端 gui.py 的 TRANSPORT_FACTORIES 顯示名稱保持一致） → TransportMode。 */
    private val transportOptions = listOf(
        "WiFi" to TransportMode.WIFI,
        "USB (USB 網路共享)" to TransportMode.USB_RNDIS,
        "USB (adb)" to TransportMode.USB_ADB,
    )

    /**
     * transport 引導提示（見 todo08-1）：選到需要手機端先開開關的 transport
     * 時顯示一行說明文字，純 UI 提示，不影響任何連線/傳輸邏輯。WiFi 沒有
     * 額外開關需求，不在表中即代表空字串。
     */
    private fun transportHintFor(mode: TransportMode): String = when (mode) {
        TransportMode.USB_RNDIS -> getString(R.string.hint_transport_usb_rndis)
        TransportMode.USB_ADB -> getString(R.string.hint_transport_usb_adb)
        else -> ""
    }

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

        binding.transportSpinner.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            transportOptions.map { it.first },
        )
        binding.transportSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                binding.transportHintText.text = transportHintFor(transportOptions[position].second)
            }

            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
        binding.transportHintText.text = transportHintFor(transportOptions[0].second)

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
            val selectedMode = transportOptions[binding.transportSpinner.selectedItemPosition].second
            val intent = Intent(this, StreamerService::class.java).apply {
                action = StreamerService.ACTION_START
                putExtra(StreamerService.EXTRA_TRANSPORT_MODE, selectedMode.name)
            }
            ContextCompat.startForegroundService(this, intent)
        }
    }

    private fun renderState(state: ServiceState) {
        running = state == ServiceState.DISCOVERING ||
            state == ServiceState.HANDSHAKE ||
            state == ServiceState.STREAMING
        binding.startStopButton.text = getString(if (running) R.string.btn_stop else R.string.btn_start)
        binding.transportSpinner.isEnabled = !running
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

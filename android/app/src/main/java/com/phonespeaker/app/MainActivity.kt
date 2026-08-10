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
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.os.LocaleListCompat
import com.phonespeaker.app.core.AudioFormat
import com.phonespeaker.app.databinding.ActivityMainBinding

/**
 * MainActivity.kt — 最小 UI：transport 選擇、啟動/停止、狀態、格式、log。
 *
 * transport 選單目前有 WiFi、USB (USB 網路共享)、USB (adb) 三項（見
 * [transportOptions]）；U3/BT 驗收通過後，比照 U2 在 [transportOptions]
 * 加一行即可（§10.3：新增選項不動既有邏輯）。選到的模式透過 Intent extra
 * 傳給 StreamerService，實際建立哪個 Transport 由 StreamerService 決定。
 *
 * 雙語（todo010）：所有面向使用者的文字改用 @string 資源（見 res/values ＝
 * 英文 fallback、res/values-zh(-rTW) ＝ 繁中），系統語言跟隨交給 Android
 * 資源解析本身處理；手動切換／持久化見 [setupLanguageSpinner]。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var running = false

    /**
     * 顯示文字（跟 PC 端 pc/i18n.py 的 transport.<id>.name 對齊） → TransportMode。
     * 用 @string 資源組出來，隨語言變化；用 position（不是顯示文字本身）
     * 分派 TransportMode，切換語言不影響選到哪個 transport（見 onCreate 賦值）。
     */
    private lateinit var transportOptions: List<Pair<String, TransportMode>>

    private fun buildTransportOptions(): List<Pair<String, TransportMode>> = listOf(
        getString(R.string.transport_wifi_name) to TransportMode.WIFI,
        getString(R.string.transport_usb_rndis_name) to TransportMode.USB_RNDIS,
        getString(R.string.transport_usb_adb_name) to TransportMode.USB_ADB,
    )

    /**
     * 語言偏好（BCP-47 tag，""＝跟隨系統）→ 選單顯示用字串資源。「自動」
     * 跟著目前介面語言變化；「繁體中文」「English」用語言自身名稱顯示，
     * 讓使用者永遠看得懂怎麼切回自己要的語言（跟 PC 端 i18n.py 的
     * language_preference_label() 同一個設計）。
     */
    private val languageOptions = listOf(
        "" to R.string.lang_auto,
        "zh-TW" to R.string.lang_zh_tw,
        "en" to R.string.lang_en,
    )
    private var languageSpinnerInitializing = true

    /**
     * transport 引導提示（見 todo08-1；WiFi 提示為 todo010 新增）：選到
     * 對應 transport 時顯示一行說明文字，純 UI 提示，不影響任何連線/傳輸
     * 邏輯。
     */
    private fun transportHintFor(mode: TransportMode): String = when (mode) {
        TransportMode.WIFI -> getString(R.string.hint_transport_wifi)
        TransportMode.USB_RNDIS -> getString(R.string.hint_transport_usb_rndis)
        TransportMode.USB_ADB -> getString(R.string.hint_transport_usb_adb)
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
            runOnUiThread { appendLog(getString(R.string.error_prefix, message)) }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupLanguageSpinner()

        transportOptions = buildTransportOptions()
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

    /**
     * 語言手動切換（todo010）：透過 [AppCompatDelegate.setApplicationLocales]
     * 套用；appcompat 會自動持久化選擇（見 AndroidManifest.xml 的
     * `AppLocalesMetadataHolderService` 宣告），下次啟動沿用，不用自己寫
     * SharedPreferences。純 UI 文字層設定，不影響任何連線/傳輸邏輯。
     */
    private fun setupLanguageSpinner() {
        binding.languageSpinner.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            languageOptions.map { getString(it.second) },
        )

        val currentTag = AppCompatDelegate.getApplicationLocales().toLanguageTags()
        val currentIndex = languageOptions.indexOfFirst { it.first == currentTag }.let { if (it >= 0) it else 0 }
        languageSpinnerInitializing = true
        binding.languageSpinner.setSelection(currentIndex)

        binding.languageSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                // Spinner 在初始設定選取值時也會觸發一次 onItemSelected；
                // 這裡跳過那一次，避免啟動時就呼叫 setApplicationLocales()
                // 造成不必要的 Activity recreate。
                if (languageSpinnerInitializing) {
                    languageSpinnerInitializing = false
                    return
                }
                val tag = languageOptions[position].first
                val locales = if (tag.isEmpty()) {
                    LocaleListCompat.getEmptyLocaleList()
                } else {
                    LocaleListCompat.forLanguageTags(tag)
                }
                AppCompatDelegate.setApplicationLocales(locales)
            }

            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
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

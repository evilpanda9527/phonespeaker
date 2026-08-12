package com.phonespeaker.app

import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.Locale

/**
 * UsbTetheringDetector.kt — todo011「加強 U1/U2 的前置狀態偵測與提示」二：
 * Android 端主動偵測「USB 網路共享（USB tethering）」目前是否已開啟，供
 * [MainActivity] 在選到 U1（[TransportMode.USB_RNDIS]）時顯示真實狀態，
 * 取代原本固定不變的靜態提示文字。
 *
 * 獨立成自己的檔案（§10.3 檔案隔離精神）：純讀取系統網路介面資訊的小工具，
 * 不 import、不修改任何 transport/連線邏輯，MainActivity 只呼叫
 * [isUsbTetheringOn]，壞掉/查不到最壞情況就是顯示「尚未開啟」提示，不影響
 * 實際連線能力。
 *
 * ## 採用方式與可靠度（依 todo011 要求說明）
 *
 * 用標準 Java `NetworkInterface.getNetworkInterfaces()` 列舉目前作業系統
 * 認得的所有網路介面，找「名稱符合 USB tethering 介面命名慣例、且已啟用
 * （[NetworkInterface.isUp]）、且配到非 loopback/非 link-local 的 IPv4
 * 位址」的介面。這是 `java.net` 標準 API（不是 Android 的 hidden／
 * `@SystemApi`），從 API 1 就存在、不需要任何權限、在所有 Android 版本／
 * OEM 上行為一致——可靠度來源是「作業系統核心網路介面清單」本身。
 *
 * 相對地，`ConnectivityManager.getTetheredIfaces()` 這類方法技術上更貼近
 * 「官方直接答案」，但屬於 `@UnsupportedAppUsage`（hidden API）：Android
 * 9+ 的 hidden API 限制（greylist/blacklist，依 targetSdk 而定）可能讓它
 * 在特定裝置／版本上直接丟例外或悄悄失效，且日後 Android 版本更新有機會
 * 直接拔掉這個路——可靠度、相容性都不如標準 `NetworkInterface`，因此這裡
 * 刻意不採用（不用 reflection 呼叫隱藏方法）。
 *
 * **命名慣例與相容性考量**：USB tethering 在 Android 底層走 USB gadget 的
 * RNDIS 或 NCM function driver，核心配出來的介面名稱以 `rndis`（最常見，
 * PC 端 `usb_rndis.py` 認的 Windows 網卡描述也是「Remote NDIS」同一族）或
 * `ncm` 開頭；少數裝置（較舊機型／特定 SoC）可能是 `usb0`。三種都認、
 * 大小寫不拘，涵蓋目前已知的主流命名法。
 *
 * **已知限制**：如果日後遇到用其他命名慣例的裝置（目前清單沒涵蓋到），
 * 偵測會判定為「尚未開啟」——這是保守方向的誤判（頂多多顯示一次不必要的
 * 提示，不會誤判成「已開啟」讓使用者卡在別的地方），且跟 PC 端
 * `usb_rndis.py` 用網卡描述關鍵字比對是同一個等級的已知取捨，是非 root
 * 限制下可接受的方案。
 */
object UsbTetheringDetector {

    private val TETHERING_INTERFACE_PREFIXES = listOf("rndis", "ncm", "usb0")

    /** 目前是否偵測到一張「看起來是 USB tethering」的網卡：已啟用、且配到可用 IPv4。 */
    fun isUsbTetheringOn(): Boolean {
        return try {
            NetworkInterface.getNetworkInterfaces().asSequence().any { iface ->
                val name = iface.name.lowercase(Locale.ROOT)
                val looksLikeTethering = TETHERING_INTERFACE_PREFIXES.any { name.startsWith(it) }
                looksLikeTethering && iface.isUp && hasUsableIpv4(iface)
            }
        } catch (e: Exception) {
            // 列舉網路介面理論上不該失敗，但這只是一個 UI 提示用的偵測，任何
            // 非預期例外都不該讓呼叫端（UI 執行緒）崩潰——安全降級為「偵測不到」。
            false
        }
    }

    private fun hasUsableIpv4(iface: NetworkInterface): Boolean {
        return iface.inetAddresses.asSequence().any { addr ->
            addr is Inet4Address && !addr.isLoopbackAddress && !addr.isLinkLocalAddress
        }
    }
}

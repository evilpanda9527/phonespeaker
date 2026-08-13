# U3（USB / AOA 自訂 bulk data channel）— PoC 評估報告

依 todo09.md 與 SPEC3.md §14「先 PoC、逐項測試通過才前進」：本輪**只評估、不實作、
不動任何既有檔案**。以下是評估結果與建議，回報後停下等待你確認是否要進入實作。

---

## 1. 可行性：能不能建立 AOA accessory 模式？

**結論：技術上可行，但這台環境（Windows 11 Home）是目前三個 USB 變體裡風險最高的一個。**

### 1.1 協定本身

AOA（Android Open Accessory Protocol）分兩階段：

1. **握手階段**：PC（host）對還在正常模式（MTP/adb 等 composite 裝置）的手機送一系列
   USB **control transfer**（`GET_PROTOCOL` → 依序 `SEND_STRING`（manufacturer/model/
   description/version/uri/serial）→ `START_ACCESSORY`）。
2. **切換階段**：手機收到 `START_ACCESSORY` 後**重新列舉（re-enumerate）**成一個全新的
   USB 裝置，**VID 固定變成 Google 的 `0x18D1`**，PID 依模式是 `0x2D00`（accessory）或
   `0x2D01`（accessory + adb 同時開）。PC 端要偵測到這次重新列舉、重新開啟新的裝置控制
   代碼，才能用 bulk endpoint 收送資料。

Android 端 API 是穩定、非新東西：`UsbManager.getAccessoryList()` /
`openAccessory(UsbAccessory)` 拿到 `ParcelFileDescriptor`，轉成 `InputStream`/
`OutputStream` 做 bulk 讀寫。查了目前公開文件（[USB accessory overview | Android
Developers](https://developer.android.com/develop/connectivity/usb/accessory)），
minSdk 12 起支援、**沒有看到官方標示已淘汰**，這部分風險較低。

**已知限制（跟先前確認的一致）**：accessory 模式內建的「audio」子功能（PID `0x2D02`
`0x2D03`）在 **Android 8 之後已被移除**，所以必須用純 bulk data channel 自己傳
PCM，不能指望 AOA 幫忙處理音訊——這點原本規劃就已經考慮到，做法正確。

### 1.2 PC 端要用什麼

- **Python 側**：`pyusb` + libusb-1.0 backend（不是 socket，這點原規劃是對的）。
- **驅動**：`GET_PROTOCOL` 等 control transfer 是對**整個裝置**（device-level control
  request，非某個 interface），Windows 上要能發這種 raw control transfer，該裝置在
  Windows 底下必須綁定 **WinUSB**（或 libusb-win32/libusbK）驅動，而不是系統預設的
  `usbccgp`（USB 複合裝置驅動，正常模式下手機走這個）。也就是說：**握手階段就要先把
  WinUSB 綁到手機原本的裝置節點上**，然後 `START_ACCESSORY` 後裝置換了新的 VID/PID
  重新列舉，這個**新裝置又要再綁一次 WinUSB**（不過因為新 VID/PID `18D1:2D00` 是
  Google 固定值、跟手機廠牌無關，這次可以透過安裝檔預先裝好對應的 driver package，
  不需要每次手動配對）。
- Android 端：沿用/擴充 Transport 介面新增 `UsbAoaTransport.kt`，用
  `UsbManager`/`UsbAccessory` API，不需要 root。

---

## 2. 驅動負擔：Windows 11 這台環境有一個目前看起來沒解的已知問題

這是這次查證後**新發現、比原本預期更嚴重的風險**，值得特別提出：

- `libwdi`（Zadig 底層函式庫，§11 規劃拿來做「安裝流程內自動裝 WinUSB」的那個庫）從
  1.1.0 版起，對官方預設的 WinUSB/libusb0/libusbK 驅動檔本身**不需要額外簽章**，因為
  這些驅動檔案本身已經是 Microsoft 簽過的——這符合原本「唯一一次未簽章警告在 U3」的
  預期。
- 但實測上，**Windows 11 有一個目前仍在追蹤中、看起來沒有乾淨解法的已知問題**
  （[libwdi issue #242](https://github.com/pbatard/libwdi/issues/242)、
  [OSR 開發社群討論串](https://community.osr.com/t/windows-11-and-alternative-driver-installation-method-in-libwdi/57493)）：
  libwdi 在**執行當下產生的自簽憑證**放進「受信任的發行者」（Trusted Publishers）
  這個機制，**Windows 11 已經不再信任這種執行期自簽的憑證**（libwdi 作者本人在
  issue 裡的說法：「Microsoft is no longer trusting certificates that are installed
  in Trusted Publishers for the signing of driver packages」）。結果是：**在 Windows
  11 上，libwdi/Zadig 自動安裝驅動這條路，目前不保證能無感完成**，很可能卡在
  「找不到受信任的驅動程式」，需要使用者自己到裝置管理員手動指定驅動、或關閉某些
  簽章強制設定才能裝上。
- 對照這台開發機的環境（`Windows 11 Home`，見本 session 環境資訊），**這不是理論
  風險，是這台機器本身就可能會踩到的問題**。

**這關係到 §11「單一安裝檔全自動裝驅動」的可行性評估**：目前看起來**沒辦法保證
Windows 11 上 100% 全自動、零感知**地裝好 WinUSB 驅動；比較實際的作法可能是：
安裝檔嘗試自動裝（多數情況、尤其 Windows 10 或某些 Windows 11 組態下會成功），失敗
時退回「引導使用者手動到裝置管理員更新驅動」的文字說明步驟，而不是原本設想的
「絕對無感」。

---

## 3. 開發複雜度與風險（相較 U1/U2）

U1/U2 全部複用同一條 TCP + 協定層，U3 完全是另一條路，主要新風險點：

1. **兩段式裝置生命週期**：握手前裝置一個身分（原生手機 composite 裝置）、
   `START_ACCESSORY` 後裝置重新列舉變成另一個身分（新 VID/PID、新的裝置路徑）。
   PC 端要正確處理「裝置消失又重新出現」這個轉場，包含裝置在系統上是不是同一個
   USB port、多手機/多裝置情境下如何精準對應，比 U1/U2 單純「connect 到一個
   已知位址」複雜得多。
2. **Windows 驅動綁定的副作用**：握手階段要把 WinUSB 綁到手機原本裝置節點——如果
   綁定範圍是整個 composite 裝置（而不是單一 interface），會暫時讓 Windows 認不出
   手機原本的其他功能（例如同時間的 MTP 檔案總管、或 adb）。需要在拔線/程式結束時
   正確處理，不然可能讓使用者困惑「怎麼手機在檔案總管不見了」。
3. **驅動安裝可靠度（見第 2 節）**：Windows 11 的 libwdi 自簽憑證問題目前沒有已知
   乾淨解法，這是目前最大的不確定點。
4. **Android 端首次連線仍有一次系統跳窗**：`UsbManager` 第一次連某個 accessory 會跳
   系統權限對話框（可以勾選「以後這個裝置都用這個 App 開」，之後才真正零操作）。也
   就是說「插上就用、完全零操作」這個賣點，嚴格說是「**第一次要點一下確認，之後才
   零操作**」，跟 U2 需要「先去設定裡開一次 USB 偵錯」比，方便一些但不是絕對零操作。
5. **頻寬**：以現有 `audio_capture.py`「保留實際格式、不轉檔」的作法，WASAPI loopback
   常見是 32-bit float，48kHz 立體聲 ≈ 48000×2×4 bytes/s ≈ **3.07 Mbps**（跟 todo09
   估的 3Mbps 吻合）。USB 2.0 High-Speed bulk 實際可用頻寬遠大於這個數字（理論上限
   480Mbps，bulk 實務吞吐量也有數十 MB/s 等級），**頻寬本身完全不是問題**，真正的
   風險在延遲穩定性跟裝置管理複雜度，不在頻寬。
6. **社群precedent 較少**：AOA host 端的實作案例多半在 Linux/嵌入式（車機、Arduino
   ADK 這類），**Windows 上的 AOA host 開發資料相對少**，不像 U1/U2 走的 TCP/adb
   forward 這種主流路徑資料豐富、遇到問題容易查到解法。這代表實作過程中卡住時，
   排錯速度可能比 U1/U2 慢。

---

## 4. 要新增/修改哪些檔案（先列規劃，不實作）

- **PC 端**：新增 `pc/transport/usb_aoa.py`（同一 Transport 介面），內部用 `pyusb` +
  libusb backend 做握手 + 重新列舉偵測 + bulk 收送；`gui.py` 下拉多一項
  「USB (AOA)」；`requirements.txt` 加 `pyusb`。
- **Android 端**：新增 accessory transport（例如
  `UsbAoaTransport.kt`，如 SPEC3 §13 目錄所列），用 `UsbManager`/`UsbAccessory`
  API；`AndroidManifest.xml` 加 `USB_ACCESSORY_ATTACHED` intent-filter +
  `accessory_filter.xml`（讓 App 收到 accessory 連線時自動跳出/預選）；
  `StreamerService.kt` 的 `createTransport()` 工廠加一個 case（跟 U1/U2 同模式，
  不動狀態機）；`MainActivity.kt` 選單加一項、比照 todo08-1 補上提示文字。
- **安裝檔（§11）**：需要把 WinUSB driver package（含兩個 VID/PID：手機原生的 +
  `18D1:2D00`/`2D01`）折進同一個安裝檔，並準備好「自動裝失敗時的手動引導」文案
  （見第 2 節的新發現）。

---

## 5. 建議

**我的建議是：U3 值得留著當一個可選加分項，但不建議現在優先做，優先度應該低於
「先把 U1/U2 穩定收尾、視需要才回頭做 U3」。**理由：

1. **邊際效益有限**：U2（adb）已經達成「執行期手機零操作、延遲最低」，U3 相對 U2
   唯一的差異是**省下那一次性的「開 USB 偵錯」設定動作**，換來的卻是全新一條路的
   工程複雜度。對自用情境，這個增量價值不高。
2. **這台機器（Windows 11）目前有明確、沒有乾淨解法的驅動自動安裝風險**（第 2
   節），會直接影響「單一安裝檔、一次裝完」（§11 硬性要求）能不能兌現，這是實質的
   blocker 等級風險，不是我可以憑經驗保證繞過的。
3. **Windows 端 AOA host 開發資料/precedent 較少**，實作時間與除錯時間可能明顯超過
   U1/U2 當初的量級，且沒辦法在這個純終端機環境事先驗證（跟 Android 端一樣，這塊
   高度依賴你在實機上反覆試裝置重新列舉、驅動綁定這些只能真機驗證的環節）。

**如果你仍想做**，建議的路是：先花一輪時間**只驗證這台 Windows 11 機器能不能順利把
WinUSB 綁到手機（不牽扯任何 PhoneSpeaker 程式碼，純粹拿 Zadig 或 libwdi 試裝）**，
確認第 2 節那個驅動信任問題在這台機器上到底會不會發生、有沒有可行 workaround，
這個「地雷排查」值得在投入正式開發前先做，成本低、能直接回答「值不值得投入」。

**如果你決定不做 U3**：目前 WiFi + U1 + U2 三種傳輸方式都已驗收通過，就使用情境
（同一顆 Wi-Fi 環境用 WiFi、線接電腦用 USB 網路共享或 adb）來說已經算完整，M1-B
可以視為功能完備，直接收尾轉向 §11 安裝檔或 M2（藍牙）。

---

## 6. 參考資料

- [USB accessory overview | Android Developers](https://developer.android.com/develop/connectivity/usb/accessory)
- [libwdi issue #242：Windows 11 驅動憑證信任問題](https://github.com/pbatard/libwdi/issues/242)
- [Windows 11 and alternative driver installation method in libwdi（OSR 開發社群討論）](https://community.osr.com/t/windows-11-and-alternative-driver-installation-method-in-libwdi/57493)
- [Zadig 官方頁面](https://zadig.akeo.ie/)
- [Android USB permissions：記住已授權的裝置](https://emteria.com/blog/remember-android-usb-permissions)

---

**回報完畢，停在這裡等你確認：要不要進入 U3 實作？或是先做第 5 節建議的「地雷排查」
小實驗？還是先跳過 U3、轉向 §11 安裝檔 / M2？**

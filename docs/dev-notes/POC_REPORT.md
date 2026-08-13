# M1-A WiFi — PoC 報告

依 SPEC3.md §10/§12/§14：只做 M1-A（Transport Interface 骨架 + WiFi），完成後回報、
停下等待驗收，未過關前不進入 M1-B（USB）。本檔就是那份回報。

---

## 1. 交付範圍

- `pc/`：完整可執行的 Windows PC 端程式（Python + customtkinter GUI）
- `android/`：完整的 Android Studio 專案原始碼（Kotlin）
- Transport Interface 骨架（PC `transport/base.py` / Android `transport/Transport.kt`），
  目前只有 WiFi 一種實作，之後 U1/U2/U3/BT 依 §10.3 各自新增檔案即可
- FORMAT/READY/FORMAT_UNSUPPORTED 握手、PC 靜音/還原、預設裝置熱切換、
  ring buffer（目標 20–60ms）、前景服務鎖屏續播、斷線重連

不在此次範圍：USB（U1/U2/U3）、Bluetooth、安裝檔（installer/）——依 §10 順序，
這些要等 WiFi 驗收通過才開始。

---

## 2. 測試方式與結果

### 2.1 PC 端：大量即時測試（在你這台機器上實際跑）

開發過程中直接在這台 Windows 機器上安裝相依套件、即時執行、觀察真實結果，
不是憑印象寫完就交差。測試涵蓋：

| 模組 | 測試方式 | 結果 |
|---|---|---|
| `audio_capture.py` | 開啟 loopback、實際讀取音訊（含真的播放系統音效驗證資料流） | ✅ 正常，數據量符合預期（如 44.1kHz/2ch/float32 時約 90 chunk/秒） |
| `mute_control.py` | 讀取真實裝置的 GetMute/GetMasterVolumeLevelScalar | ✅ API 正確（實際 SetMute 未在你不知情下觸發，見下方「刻意跳過的測試」） |
| `device_monitor.py` | 註冊/取消註冊 Windows 預設裝置變更通知，啟動/停止生命週期 | ✅ 正常（實際「切換裝置」情境未觸發，見已知限制） |
| `tcp_client.py` + `handshake.py` | 手刻 client/server 收送 FORMAT/READY/PCM frame | ✅ 協定 round-trip 正確 |
| `transport/wifi.py` | 真實 TCP connect/accept、zeroconf 註冊、`request_cancel()` 中斷阻塞中的 connect() | ✅ 全部正確，含取消場景 |
| `stream_engine.py`（整合） | 假手機 client 對真的 `StreamEngine` 收送完整流程：FORMAT→READY→連續 PCM→斷線→自動回到等待連線重新 accept | ✅ 多次重跑，行為一致；PCM 位元組數與速率符合預期 |
| `main.py` / `gui.py` | `customtkinter` 元件建立、byte-compile 全部檔案 | ✅ 正常 |

### 2.2 Android 端：**尚未實機/實際編譯驗證**

這個開發環境沒有 Android SDK/模擬器，無法在這裡跑 Gradle build 或裝置測試。
Android 端的程式碼是依照跟 PC 端**完全對齊**的協定（wire format 一致，見 §4）
仔細寫的，並反覆手動核對過，但**沒有經過編譯器和真機驗證**。這是目前風險最高、
最需要你協助的部分——麻煩用 Android Studio 開啟 `android/` 實際 build 一次、
接手機測試。

### 2.3 依 SPEC3.md §9 的正式驗收（影片實測）：**尚未執行**

§9 的驗收方式是「播有明顯聲畫節奏的影片，肉眼/耳判斷延遲、斷音卡頓、傳輸差異、
斷線恢復、開啟順序、PC 靜音/還原」——這需要兩端真的裝好、你在旁邊看畫面聽聲音，
我沒辦法在這個純終端機環境自己做。**這一步需要你來跑。**

---

## 3. 重要發現：PyAudioWPatch 在這個環境下的 crash-on-exit

開發過程中花了相當多時間追一個看起來很嚇人的問題，這裡誠實完整地寫出來，
而不是含糊帶過：

**現象**：整段錄音流程（開啟 loopback、持續讀取、關閉）完全正常、資料完全正確，
但 **Python 行程真正結束的那一刻**，偶爾會在原生層 segfault（無法被 Python 的
`except` 攔截，是 C 擴充套件層級的當機）。

**追查過程**（濃縮版）：
1. 一開始懷疑是 `comtypes`/`pycaw` 的 COM 呼叫（`device_monitor.py` 用到的
   `IMMNotificationClient`）跟 PyAudioWPatch 衝突——實測發現：**不是**，就算完全
   不 import comtypes，只用 PyAudioWPatch 單獨開關 stream，一樣會在「幾乎沒有真實
   音訊在播放（近乎靜音）」時出現讀不到資料、行程結束時 crash 的狀況。
2. 進一步排除：用真的在播放的音訊（另開一個獨立 process 播系統音效）反覆測試，
   **串流期間資料完全正常**（chunk 數、位元組數都符合預期），`device_monitor` 跟
   `mute_control` 同時運作也不影響資料正確性。
3. 最終定位：crash 只發生在**行程正常結束、Python 直譯器收尾（finalize/GC/atexit）
   的那一刻**，不是任何一次 API 呼叫當下崩潰，且跟 comtypes 完全無關——單純
   PyAudioWPatch 這個 build 在（很可能是）Python 3.14.2 這個很新的直譯器版本上，
   收尾時有原生層的穩定性問題。

**影響範圍**：只影響「整個 PC app 關閉」那一瞬間，**不影響串流期間的任何行為**
（含斷線重連、預設裝置熱切換都是在 process 存活期間發生，不會觸發這個問題）。

**已採取的對策**：`pc/gui.py` 關閉視窗時，在做完我們自己該做的清理（還原靜音、
中斷連線、寫 log）之後，改用 `os._exit(0)` 直接結束行程，跳過 Python 正常收尾流程，
測試確認可以完全避開這個 crash。**這是繞過，不是根治**——如果你在你的正式環境
（可能是別的 Python 版本或別台機器）重現，這個問題很可能自然消失；如果沒有，
`os._exit()` 這個對策應該足夠讓使用者不會看到崩潰視窗。

---

## 4. 已知限制 / 待你決定的事項

1. **裝置熱切換（§7 M1 必做項）尚未在「真的切換預設輸出裝置」情境下測試過**。
   `device_monitor.py` 的註冊/取消註冊機制已驗證正常運作，但「PC 播放中途切換
   預設輸出裝置 → 自動重建 capture → 重送 FORMAT → 手機不斷線續播」這個完整流程
   需要你實際切換裝置（例如插拔耳機、切換藍牙喇叭）觀察。
2. **`mute_control.py` 沒有在測試中真的觸發 `SetMute`**——刻意避免在你不知情、
   可能正在使用電腦的情況下無預警把系統靜音。這一部分建議由你在啟動 PC app 並
   確認手機端連上、進入 READY 狀態後，自己觀察是否正確靜音/還原。
3. **Android 端完全依賴你的實機驗證**（見 §2.2）。
4. 目前只支援單一手機同時連線；USB/Bluetooth 尚未開始（依 §10 順序）。

---

## 5. Wire 協定（PC ↔ Android，兩端已對齊）

```
每個 frame = [4 bytes length, big-endian, u32][1 byte type][payload]
length = 1(type) + payload 長度

type 0x01 FORMAT              payload = JSON({sample_rate, channels, encoding})
type 0x02 READY                payload = 空
type 0x03 FORMAT_UNSUPPORTED   payload = UTF-8 錯誤原因字串（可為空）
type 0x04 PCM                  payload = 原始 PCM bytes
```

握手：PC 送 FORMAT → 手機回 READY 或 FORMAT_UNSUPPORTED → PC 開始送 PCM、
同時靜音 → 斷線/關 app 時雙方各自還原（PC 還原音量、手機停止播放回到等待連線）。
PC 端偵測到預設裝置變更且格式改變時，會在同一條連線上再送一次 FORMAT，
手機收到非第一次的 FORMAT 時會重建 AudioTrack（不斷線）。

---

## 6. 交付檔案清單

首次交付，沒有「既有已通過驗收的檔案」需要保護，以下全部是新增：

```
PhoneSpeaker/
├─ README.md  .gitignore  POC_REPORT.md
├─ pc/
│  ├─ main.py  gui.py  config.py  requirements.txt
│  ├─ core/ audio_capture.py audio_format.py mute_control.py
│  │        device_monitor.py handshake.py tcp_client.py stream_engine.py
│  └─ transport/ base.py wifi.py
└─ android/（Gradle 專案，含 settings/build.gradle.kts、gradle-wrapper.properties）
   └─ app/src/main/
      ├─ AndroidManifest.xml  MainActivity.kt  StreamerService.kt
      ├─ core/ AudioFormat.kt Handshake.kt TcpClient.kt RingBuffer.kt AudioPlayer.kt
      ├─ transport/ Transport.kt WifiTransport.kt
      └─ res/（layout/values/mipmap）
```

Android 的 `gradlew`/`gradlew.bat`/`gradle-wrapper.jar` 二進位檔沒有附上（這個環境
無法下載產生），Android Studio 開啟專案時會自動處理 Gradle wrapper；如果你用命令列
建置，需要先在 `android/` 執行一次 `gradle wrapper`（需本機已裝 Gradle）。

---

## 7. 需要你做的事（驗收 Gate，§10.2）

1. 用 Android Studio 開啟 `android/`，實際 build 一次、修掉編譯期可能出現的小問題
   （如果有的話——已盡力手動核對，但沒有編譯器把關，不排除筆誤）
2. PC 端：`cd pc && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`
   然後 `.venv\Scripts\python main.py`
3. 依 SPEC3.md §9 的方式驗收：播一段有明顯聲畫節奏的影片，實際感受延遲、
   斷音卡頓、斷線恢復、不限開啟順序、PC 靜音/還原是否符合預期
4. 額外請驗證 §7 裝置熱切換（切換預設輸出裝置時是否正常續播）
5. 確認後告訴我「WiFi 過」或指出哪裡不行，我再依 §10.2 進入 M1-B（USB U1）

在你確認前，我不會繼續往下做 USB/Bluetooth。

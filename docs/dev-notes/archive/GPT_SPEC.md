# SPEC.md — PhoneSpeaker（Android 當 PC 喇叭）

> 依據 `Android_as_PC_Speaker_建置Prompt_1.md` 與目前需求確認結果產出。**本文件僅做設計，不含實作程式碼。**
> 依 strict-confirm-workflow：本文件 + 檔案/套件清單，待你回覆「ok」（或針對「10. 待確認事項」給出決定）後才開始寫程式。
>
> **核心需求：PhoneSpeaker 的目的，是讓 Android 手機成為 PC 的 Speaker。USB、WiFi、Bluetooth 是三種不同的音訊傳輸方式，不要求三者都使用 TCP/IP。低延遲優先。**

---

## 0. 專案路徑假設

專案名稱與資料夾統一為 `PhoneSpeaker`。

目前工作目錄若仍為 `D:\Claude_Desktop_Test\speakerApp`，應視為專案工作目錄；SPEC 中的專案根目錄名稱以 `PhoneSpeaker` 為正式名稱。

---

## 1. 目標（一句話）

**PC 播放中的系統音訊 → 透過使用者選擇的 USB / WiFi / Bluetooth 傳輸方式 → Android 手機 → 手機喇叭播放。**

使用者不需要修改 Windows 音效輸出設定；兩端 App 不限定開啟順序；傳輸成功後自動播放。

核心優先順序：

1. 低延遲
2. 穩定播放
3. 不改變 PC 原始音訊資料
4. 使用簡單
5. 相容性

---

## 2. 使用者流程（正式驗收依據）

### USB

- PC 與 Android 手機以 USB 線直接連接。
- **不需要 USB 網路共享（USB Tethering / RNDIS）。**
- 手機開啟 PhoneSpeaker App、PC 開啟 PhoneSpeaker App，或反過來，皆可。
- 建立 USB 音訊傳輸後，手機 Speaker 播放 PC 系統音訊。
- USB 的正式傳輸技術（標準 USB Audio Device 或自訂 USB 音訊資料通道）列為實機驗證項目，詳見第 6、11 節。

### WiFi

- PC 與手機位於同一 WiFi / LAN。
- 手機與 PC App 開啟順序不限。
- App 自動探索並建立連線。
- 手機 Speaker 播放 PC 系統音訊。

### Bluetooth

- PC 與手機先完成 Bluetooth 配對。
- 手機 App 選擇「當作 Speaker」。
- 手機 Speaker 播放 PC 系統音訊。
- **目標是 Bluetooth Audio Speaker，而不是 Bluetooth PAN 網路共享。**
- Bluetooth 的實際實作方式與 Android / Windows 能力必須先實機驗證，詳見第 6、11 節。

### 共通行為

- App 開啟順序不限。
- 尚未連線時，PC 正常播放，不應因等待手機而卡住 PC 音訊。
- 連線成功並確認 Android 已準備播放後，PC 預設自動靜音。
- 可由 GUI 開關「連線時 PC 同時出聲」。
- 斷線、手機 App 關閉或傳輸失敗時，PC 恢復原本的音量 / mute 狀態。
- 重新連線後自動恢復手機播放。

---

## 3. 架構總覽

```text
┌──────────────────── PC (Windows, Python) ────────────────────┐
│                                                              │
│  WASAPI Loopback                                             │
│       │                                                      │
│       ▼                                                      │
│  audio_capture.py                                            │
│       │  原始 PCM + format metadata                          │
│       ▼                                                      │
│  transport manager                                           │
│       │                                                      │
│       ├──────── USB ────────────────► Android                │
│       │                              USB transport           │
│       │                                                      │
│       ├──────── WiFi ───────────────► Android                │
│       │             discovery + TCP                          │
│       │                                                      │
│       └──────── Bluetooth ──────────► Android                │
│                     Bluetooth Audio path                     │
│                                                              │
│  mute_control.py                                             │
│  GUI / status / mode selection                               │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────── Android (Kotlin) ────────────────────────┐
│                                                              │
│  Transport Receiver                                          │
│       │                                                      │
│       ▼                                                      │
│  Small ring buffer                                           │
│       │                                                      │
│       ▼                                                      │
│  AudioPlayer / AudioTrack                                    │
│       │                                                      │
│       ▼                                                      │
│  Phone Speaker                                                │
│                                                              │
│  Foreground Service：螢幕關閉 / 切換 App 後仍持續播放         │
└──────────────────────────────────────────────────────────────┘
```

### 核心原則

- **USB、WiFi、Bluetooth 是獨立 transport。** 不強迫所有 transport 走 TCP/IP。
- WiFi 可以使用 TCP。
- USB 優先使用真正的 USB 資料通道，不使用 USB Tethering。
- Bluetooth 目標為 Bluetooth Audio，不使用 Bluetooth PAN。
- Transport 層只負責可靠、低延遲地把音訊資料送到 Android；播放層統一交給 `AudioTrack` 或對應的 Android Audio API。

---

## 4. 音訊資料流與格式策略

### 4.1 低延遲優先

PC 端擷取到的音訊，**原則上不重新取樣、不重新混音、不改 bit depth、不重新編碼。**

```text
WASAPI Loopback
  → 取得目前 Windows 輸出音訊的實際 PCM format
  → 傳送 format metadata（只在連線初始化時）
  → 原始 PCM bytes
  → Android 依 metadata 建立對應 AudioTrack
  → Speaker
```

### 4.2 不做 PC → Android 的格式轉換

PC 是什麼格式，就傳什麼格式。

例如：

```text
44.1 kHz / stereo / 16-bit
→ Android 以相同格式播放

48 kHz / stereo / 24-bit
→ Android 以相同格式播放

96 kHz / stereo / 32-bit
→ Android 以相同格式播放（前提是 Android 裝置 / AudioTrack 支援）
```

**不為了統一格式而在 PC 端 resample / remix / convert。**

### 4.3 Android 相容性處理

如果 Android 裝置的 `AudioTrack` / audio output 不支援 PC 當下的原始格式：

- M1 不在 PC 端偷偷轉檔。
- 不允許為了「看起來可以播放」而默默改變音訊資料。
- App 應明確顯示「目前裝置不支援此音訊格式」或該 transport 的相容性錯誤。
- 若未來要加入格式轉換，必須另列為明確功能，不屬於目前低延遲 M1。

### 4.4 Buffer

- 不做大量 queue。
- Android 保留**最小必要 ring buffer**，主要用來吸收 USB / WiFi / Bluetooth 的短暫 jitter。
- Buffer 優先保持在低延遲範圍，實際大小由實機測試決定。
- 發生 underrun 時應避免 App crash；必要時可補最短靜音資料，但不得建立無限延遲。

---

## 5. 傳輸資料格式

因為 PC 原始音訊格式不再固定，連線初始化時必須告知 Android 本次音訊格式。

### 5.1 共通初始化資訊

至少包含：

```text
sample_rate
channel_count
sample_format / encoding
```

初始化資訊只在**連線建立時**傳送，不放進每一個音訊 chunk。

### 5.2 WiFi TCP framing

WiFi M1 採用：

```text
┌──────────────────────┬──────────────────────────────┐
│ length (4B, BE, u32) │ raw PCM payload              │
└──────────────────────┴──────────────────────────────┘
```

- payload 是 PC 原始 PCM bytes。
- 不壓縮。
- 不重新取樣。
- 不做序號、不做 timestamp。
- chunk 大小以低延遲實測為準，不強制固定 20ms；可由 capture buffer 自然決定。

### 5.3 USB

USB 不使用 TCP。

USB 音訊資料通道的 framing 應盡量簡單，並避免不必要的 copy / queue。

正式方案需在實機驗證後決定：

1. Android 是否能以標準 USB Audio Device / Gadget 方式讓 Windows 直接辨識為 Audio Speaker；或
2. 使用自訂 USB bulk/isochronous 資料通道，由 Windows PhoneSpeaker App 與 Android PhoneSpeaker App 傳送原始 PCM。

**不採用 USB Tethering / RNDIS 作為正式方案。**

### 5.4 Bluetooth

Bluetooth 不使用 PAN。

目標為真正的 Bluetooth Audio Speaker 使用方式。

實際資料路徑必須先確認 Android / Windows 的能力；若標準 Bluetooth Audio profile 無法由 Android App 直接實現「手機作為 PC 音訊接收端」，則需評估平台層 / Bluetooth profile 限制，再決定是否採用自訂 Bluetooth transport。

---

## 6. 連線與探索機制

### WiFi

- PC 為服務端，Android 為 client。
- TCP port：`58482`，可由 config 覆寫。
- PC 使用 `zeroconf` 廣播 `_phonespeaker._tcp.local.`。
- Android 使用 `NsdManager` 探索 PC。
- 不需要手動輸入 IP。
- App 開啟順序不限；未找到 PC 時 Android 持續等待 / discovery，PC 後開啟即可自動連線。

### USB

- **不使用 USB Tethering / RNDIS。**
- 不依賴 IP、mDNS 或 TCP。
- 插入 USB 後，PC / Android App 應偵測 USB transport 是否可用。
- Android App 可在 USB 連接建立後等待 PC App；PC App 也可先啟動等待 Android。
- USB 實作方式在開始寫核心程式前必須完成實機 capability check。

### Bluetooth

- 不使用 Bluetooth PAN。
- PC 與手機先完成 Bluetooth pairing。
- Android App 提供「當作 Speaker」模式。
- App 啟動順序不限；若 Bluetooth link 尚未建立，App 應等待 / 重試。
- Bluetooth Audio profile 的可行實作方式列為 M2 技術驗證項目。

---

## 7. PC 端靜音行為

- **只有 Android 回覆 READY、表示已建立播放路徑後，PC 才執行自動靜音。**
- 連線建立但 Android 尚未準備好時，不立即靜音，避免產生無聲空窗。
- 靜音前保存目前預設輸出端點的 mute 狀態與音量。
- 斷線 / App 關閉 / transport error 時，還原原本狀態。
- GUI 開關「連線時 PC 同時出聲」打開時，不執行自動靜音。
- 使用 `pycaw` / `IAudioEndpointVolume` 控制 Windows endpoint。

### Default Audio Device 變更

M1 **必須支援** Windows 預設輸出裝置變更。

例如：

```text
PC Speaker
  ↓
插入 HDMI / USB Headset
  ↓
Windows Default Audio Device 改變
  ↓
重新建立 WASAPI Loopback
  ↓
手機繼續播放新的 PC 系統音訊
```

若需要 `IMMNotificationClient` / `comtypes` callback，應在 M1 實作，而不是列為 stretch item。

---

## 8. 模組職責

### PC（`pc/`）

| 檔案 | 職責 |
|---|---|
| `main.py` | 進入點、組裝模組、啟動 GUI、管理 transport |
| `audio_capture.py` | WASAPI loopback 擷取 PC 系統音訊；保留實際 PCM format，不自行轉檔 |
| `mute_control.py` | pycaw 靜音/還原、保存原始狀態 |
| `streamer.py` | WiFi TCP 音訊 framing / send；不修改 PCM |
| `transport_wifi.py` | zeroconf 廣播、WiFi TCP connection |
| `transport_usb.py` | USB 裝置偵測與 USB 音訊 transport；不使用 RNDIS |
| `transport_bluetooth.py` | Bluetooth transport；M2 技術驗證後實作 |
| `audio_format.py` | 保存 / 編碼 PC 原始 PCM format metadata |
| `device_monitor.py` | 監聽 Windows Default Audio Device 變更並觸發 capture 重建 |
| `gui.py` | USB / WiFi / Bluetooth 模式、連線狀態、Speaker 狀態、PC 同時出聲開關 |
| `config.py` | port、buffer、transport 等設定 |

### Android（`android/app/src/main/...`）

| 模組 | 職責 |
|---|---|
| `MainActivity` / UI | 選擇 USB / WiFi / Bluetooth Speaker 模式、顯示狀態 |
| `StreamerService` | Foreground Service；管理 transport、重連、收資料、維持播放 |
| `WifiTransport` | NsdManager discovery + TCP client |
| `UsbTransport` | Android USB transport / device connection |
| `BluetoothTransport` | Bluetooth Audio / transport（M2） |
| `AudioFormat` | 解析 PC 傳來的 format metadata |
| `AudioPlayer` | 依實際 format 建立 AudioTrack，低延遲播放 |
| `RingBuffer` | 最小必要 jitter buffer，避免 underrun |

---

## 9. M1 / M2 範圍

### M1：USB + WiFi

M1 必須完成：

- WiFi 低延遲 raw PCM streaming。
- USB direct audio/data transport，**不使用 USB Tethering**。
- PC 原始 PCM format 傳送，不 resample、不 remix、不轉檔。
- Android 依 format metadata 播放。
- PC 自動靜音 / 原狀態還原。
- Android READY handshake。
- App 開啟順序不限。
- 斷線自動恢復。
- Windows Default Audio Device 中途變更後重新 capture。
- Android Foreground Service。
- 螢幕關閉 / 切換 App 後仍持續播放。

### M2：Bluetooth

- Bluetooth Audio Speaker 路徑。
- Bluetooth 配對後自動建立 Speaker 使用狀態。
- 不採用 Bluetooth PAN。
- 若標準 Android Bluetooth Audio profile 無法由一般 App 完成，必須先確認平台限制，再決定替代方案。

### 不屬於目前 M1

- Opus / AAC 等壓縮。
- PC 端 resampling / format conversion。
- 多手機同時播放。
- 真正的數學 E2E latency calibration。
- 為了相容性而自動改變音訊格式。

---

## 10. 延遲與實際驗收方式

### 10.1 設計原則

不以複雜的 timestamp / NTP / waveform 計算作為主要驗收方式。

本專案最重要的是**實際聽感與影音同步是否達到可接受程度**。

### 10.2 實際驗收

使用 PC 播放具有明顯聲音與畫面同步特徵的影片，直接觀察手機播放結果。

確認：

- 是否有明顯延遲。
- 是否有爆音 / 卡頓 / underrun。
- 是否會斷續。
- USB / WiFi / Bluetooth 的實際延遲差異。
- App 開啟順序是否不限。
- 斷線後是否自動恢復。
- PC 靜音 / 還原是否正常。

可使用另一台手機直接錄影作為人工驗證，但不要求 waveform 或時間戳數學分析。

### 10.3 GUI 延遲顯示

如果提供延遲數字，必須標示為**估算值**，不可宣稱為精確的 end-to-end latency。

---

## 11. 風險與待確認事項

1. **USB direct audio 的實作方式**：必須先確認目標 Android 裝置是否能讓 Windows 以標準 USB Audio Device 方式辨識手機，或是否需要自訂 USB transport。**USB Tethering / RNDIS 不列入正式方案。**

2. **USB App 與 Windows 的 driver requirement**：若採自訂 USB transport，需確認 Windows 是否可使用 WinUSB/libusb 等方式而不需要安裝複雜的專用驅動程式。若需要額外 driver，README 必須明確說明。

3. **Bluetooth Audio Speaker 能力**：需要確認一般 Android App 是否能讓手機作為 PC 的 Bluetooth Audio 接收端。不能直接假設 Bluetooth PAN 可以取代 Bluetooth Audio，兩者不可混用。

4. **Android AudioTrack format compatibility**：PC 原始格式不轉換，因此某些 Android 裝置可能不支援某些格式。M1 不做隱式轉換，應顯示清楚錯誤。

5. **單一 client**：只需要一支手機。M1 / M2 都只支援一台手機同時連線。

6. **Windows Firewall**：WiFi TCP server 第一次 listen 時可正常觸發 Windows Firewall permission；不繞過 Windows 安全機制。

7. **App 開啟順序**：三種 transport 都必須設計成 App 可先開任一端，另一端稍後開啟仍能自動建立連線；不可要求固定啟動順序。

8. **PC Default Audio Device 熱切換**：列為 M1 必做，不接受只支援啟動時一次抓取。

9. **USB / Bluetooth capability 不可在未實機驗證前假設成功**：開始寫完整 transport 前，先做最小 PoC，確認目標手機與 Windows 實際能力。

---

## 12. 待新增檔案清單

```text
PhoneSpeaker/
├─ SPEC.md
├─ README.md
├─ .gitignore
├─ .env.example
├─ pc/
│  ├─ main.py
│  ├─ audio_capture.py
│  ├─ audio_format.py
│  ├─ mute_control.py
│  ├─ streamer.py
│  ├─ transport_wifi.py
│  ├─ transport_usb.py
│  ├─ transport_bluetooth.py
│  ├─ device_monitor.py
│  ├─ gui.py
│  ├─ config.py
│  └─ requirements.txt
└─ android/
   └─ app/src/main/
      ├─ java/.../MainActivity.kt
      ├─ java/.../StreamerService.kt
      ├─ java/.../WifiTransport.kt
      ├─ java/.../UsbTransport.kt
      ├─ java/.../BluetoothTransport.kt
      ├─ java/.../AudioFormat.kt
      ├─ java/.../AudioPlayer.kt
      ├─ java/.../RingBuffer.kt
      ├─ AndroidManifest.xml
      └─ res/...（基本 UI layout / values）
```

---

## 13. 第三方套件清單

### PC（`pc/requirements.txt`）

- `pyaudiowpatch` — WASAPI loopback 擷取
- `pycaw` — Windows Core Audio 靜音 / 音量控制
- `comtypes` — pycaw 與 Windows COM / device notification 所需
- `customtkinter` — GUI
- `zeroconf` — WiFi mDNS discovery
- USB transport 所需套件需依 PoC 結果決定，例如 WinUSB / libusb 相容方案；**未完成 PoC 前不要固定加入不必要的套件。**

### Android（Gradle）

- 優先使用 Android SDK 內建：`NsdManager`、`AudioTrack`、USB Host / USB API、Bluetooth API、Foreground Service。
- 不因為 M1 而加入不必要的第三方 audio streaming library。
- minSdk 暫定 26；target SDK 依實際 Android Studio / Gradle 專案版本決定。

---

## 14. 驗收條件

### WiFi

- [ ] 同一 LAN 下 PC 與手機可自動探索。
- [ ] PC App 先開、手機 App 後開：成功。
- [ ] 手機 App 先開、PC App 後開：成功。
- [ ] 連線後手機播放 PC 系統音訊。
- [ ] PC 預設自動靜音。
- [ ] 關閉連線後 PC 恢復原本 mute / volume 狀態。
- [ ] 斷線後可自動重連。
- [ ] 不需手動輸入 IP。

### USB

- [ ] 不需要 USB Tethering。
- [ ] USB 線直接連接 PC 與手機。
- [ ] App 開啟順序不限。
- [ ] 建立 USB 音訊傳輸後手機播放 PC 系統音訊。
- [ ] 不經 RNDIS / TCP。
- [ ] 低延遲。
- [ ] 若標準 USB Audio Device 路徑不可行，使用已驗證的自訂 USB transport。

### Bluetooth

- [ ] PC 與手機可完成 Bluetooth pairing。
- [ ] 手機可選擇「當作 Speaker」。
- [ ] 目標為 Bluetooth Audio，不是 PAN。
- [ ] App 開啟順序不限。
- [ ] 手機 Speaker 播放 PC 音訊。

### 音訊

- [ ] PC 原始 PCM format 不在 PC 端轉換。
- [ ] Format metadata 僅在連線初始化時傳送。
- [ ] Android 依 metadata 建立播放格式。
- [ ] 不使用 Opus / AAC 等壓縮。
- [ ] 不因固定 48kHz 而重新取樣。
- [ ] Buffer 不造成持續增加的延遲。

### 使用體驗

- [ ] Android 螢幕關閉後仍可播放。
- [ ] Android 切換到其他 App 後仍可播放。
- [ ] PC Default Audio Device 中途變更後，手機仍能繼續播放新的系統音訊。
- [ ] App 關閉 / 斷線後 PC 聲音正常恢復。
- [ ] 實際播放影片檢查延遲與卡頓，不要求 waveform / NTP 數學量測。

---

**下一步：**

在開始完整實作前，先完成 USB 與 Bluetooth 的最小技術可行性驗證（PoC），確認目標手機 / Windows 環境能採用哪一條 transport 路徑；WiFi M1 可直接依本 SPEC 開始實作。完成 PoC 後，再回覆「ok」進入正式實作。

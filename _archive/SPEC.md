# SPEC.md — PhoneSpeaker（Android 當 PC 喇叭）

> 依據 `Android_as_PC_Speaker_建置Prompt_1.md` 產出。**本文件僅做設計，不含實作程式碼。**
> 依 strict-confirm-workflow：本文件 + 檔案/套件清單，待你回覆「ok」（或針對「10. 待確認事項」給出決定）後才開始寫程式。

---

## 0. 專案路徑假設

Prompt 原文寫專案路徑為 `D:\Claude_Desktop_Test\PhoneSpeaker`，但目前工作目錄是
`D:\Claude_Desktop_Test\speakerApp`（且 prompt 檔案本身就放在這裡）。

**假設：直接把 `speakerApp` 當作專案根目錄**，不另外建立 `PhoneSpeaker` 資料夾。
若你希望維持 `PhoneSpeaker` 這個名稱（例如之後要開源／改名），請告知，我會相應調整。

<=已修正folder name "PhoneSpeaker"

---

## 1. 目標（一句話）

PC 播放中的系統音訊 → 透過 TCP 串流 → Android 手機播放。兩邊 app 開著、連線成功即自動出聲，
使用者不用碰 Windows 音效設定。

## 2. 使用者流程（驗收依據，照抄自 prompt，不偏離）

- **USB**：手機開「USB 網路共享」→ 接 USB 線 → 兩端開 app → 自動連線、手機出聲。
- **WiFi**：同一 WiFi → 兩端開 app → mDNS 自動探索配對 → 手機出聲。
- **BT（M2）**：先藍牙配對 → 手機開 app 選「當作 speaker」→ 走 Bluetooth PAN 網路共享 → 手機出聲。
- 不限開啟順序；斷線或關 app，聲音回到 PC；PC 預設自動靜音，可開關「連線時 PC 同時出聲」。

## 3. 架構總覽

```
┌─────────────── PC (Windows, Python) ───────────────┐        ┌──────── Android (Kotlin) ────────┐
│ audio_capture.py                                    │        │                                   │
│   WASAPI loopback (pyaudiowpatch) 抓預設輸出裝置    │        │  NsdManager（WiFi/USB 探索）      │
│        │ raw PCM 48k/stereo/S16LE                   │        │  TCP Client                       │
│        ▼                                            │        │       │                           │
│ streamer.py ── framing (4B length + PCM chunk) ──►  │  TCP   │       ▼                           │
│        │                     TCP Server (accept)    │◄──────►│  ring buffer (最小)               │
│        ▼                                            │  Wi-Fi │       ▼                           │
│ mute_control.py (pycaw)                              │  USB   │  AudioTrack (MODE_STREAM,         │
│   連線成功→靜音預設輸出端點；斷線→還原                │  BT    │   PERFORMANCE_MODE_LOW_LATENCY)   │
│                                                      │        │  foreground service (mediaPlayback)│
│ transport_usb.py / transport_wifi.py                │        │                                   │
│   mDNS 廣播 _phonespeaker._tcp（WiFi 與 USB-RNDIS 共用）│      │                                   │
│ gui.py (customtkinter)：模式選擇/狀態/開關            │        │                                   │
└──────────────────────────────────────────────────────┘        └───────────────────────────────────┘
```

核心原則：**PC 是 TCP server（listen），手機是 TCP client（connect）**，三種傳輸方式只差「怎麼建立
IP 層連線」，一旦連上，走的是同一套 framing / 播放邏輯（transport-agnostic）。

## 4. 資料流（路徑最短，見 prompt 4.5）

```
WASAPI loopback 讀取一塊 PCM
  → 加 4-byte 長度前綴
  → socket.send()（不落地、不排隊、不轉檔）
  → Android socket 讀 4-byte 長度 → 讀對應 bytes
  → 直接 write 進 AudioTrack
```

不做任何取樣率 / 聲道轉換；M1 不壓縮。中間只有一層 socket buffer，沒有額外 queue/thread hop
（PC 端頂多「擷取 thread → send」一次交接；Android 端「socket 讀取 thread → AudioTrack.write」一次交接，
這是低延遲下不可再省的最小結構）。

## 5. 封包格式

固定音訊格式：**48000 Hz, 2ch, S16LE**，全程不變、不寫進封包（兩邊寫死在常數裡，省 header）。

```
┌────────────────────┬───────────────────────────┐
│ length (4B, BE, u32) │  PCM payload (length bytes) │
└────────────────────┴───────────────────────────┘
```

- 每包對應 **20ms** 音訊 = 960 frames × 2ch × 2B = **3840 bytes** payload（固定值，M1 用固定分幀，
  不用可變長度判斷邏輯，最省事）。
- **M1 不需要 codec 標記**：M1 只有 PCM。**M2 加 Opus 時才需要分辨格式**——屆時的做法：
  在 TCP 連線建立當下（非每包）做一次性 1-byte handshake 告知本次連線用 PCM 或 Opus，
  而不是每個封包都加標記位元組（省頻寬、封包結構不變）。此設計現在先寫進 spec，M1 階段
  這個 handshake byte 固定送 `0x00`（PCM），Android 端讀了就忽略／確認即可。
- 不做序號、不做時間戳（M1 用不到；重連就整個 socket 重開）。

## 6. 連線與探索機制

- **TCP port**：固定 `58482`（可在 config 覆寫）。PC bind `0.0.0.0:58482`，同一時間只接受
  **一個 client**（M1 簡化；新連線進來就取代舊連線）。
- **WiFi**：`zeroconf` 廣播 service type `_phonespeaker._tcp.local.`，Android `NsdManager` 探索、
  拿到 IP:port 後直接 connect，不需手動輸入 IP。
- **USB（tethering）**：手機開「USB 網路共享」後，PC 會多一張 RNDIS 網卡並拿到手機配發的 IP
  （手機本身通常是該子網的 gateway，如 `192.168.42.129`）。
  **關鍵假設（需要在實機驗證，列入風險）**：這張 RNDIS 介面上 multicast/mDNS 可以正常通過，
  所以 Android 端可以**沿用同一套 NsdManager 探索邏輯**去找 PC，不用另外寫「掃描 IP」的程式碼。
  若實測 mDNS 在 RNDIS 介面上不通，退回方案：Android 端改用「已知手機自己在該子網的 IP，
  對整個 /24 做輕量 TCP connect 掃描」或「PC 端把自己在 RNDIS 介面的 IP 顯示在 GUI 讓使用者手動輸入」
  作為 USB 模式的 fallback（非 adb reverse，adb reverse 是更下一層的 fallback，見下）。
  - 更底層 fallback（tethering 不可用時）：`adb reverse tcp:58482 tcp:58482`，需要開 USB 偵錯。
    M1 先做 tethering 路徑，adb reverse 之後有空再補，不擋 M1 交付。
- **BT PAN（M2）**：手機開藍牙網路共享，PC 加入該 PAN，之後複用同一套 TCP + mDNS（或手動 IP）邏輯。
  M1 不實作，只保留架構空間。

## 7. PC 端靜音行為

- 連線建立（TCP accept 成功）瞬間：讀取並保存目前預設輸出端點的 mute 狀態與音量，然後設為靜音。
- 斷線（socket 斷開／app 關閉／連線中對方 socket 錯誤）：還原保存的 mute/音量狀態。
- GUI 開關「連線時 PC 同時出聲」：打開時連線不觸發靜音（其餘邏輯不變）。
- 用 `pycaw` 操作 `IAudioEndpointVolume`。
- **風險**：「跟隨預設輸出裝置變更重新抓 loopback」需要監聽裝置變更事件
  （`IMMNotificationClient`），`pycaw` 沒有直接包好這個 callback，可能要用 `comtypes` 自己刻一個
  COM callback class。M1 先做「啟動時抓當下預設裝置」，裝置變更中途熱切換列為 M1 內的 stretch item，
  若時間/複雜度不划算會先跳過並在交付時註明限制。

## 8. 模組職責

### PC（`pc/`）
| 檔案 | 職責 |
|---|---|
| `main.py` | 進入點，組裝各模組、啟動 GUI |
| `audio_capture.py` | WASAPI loopback 擷取，固定 48k/2ch/S16LE，yield 固定大小 PCM chunk |
| `mute_control.py` | pycaw 靜音/還原、保存原始音量狀態 |
| `streamer.py` | 收 PCM chunk → 加 4-byte length header → 送給目前連線的 socket；管理單一 client 連線生命週期 |
| `transport_usb.py` | 偵測/提示 USB tethering 狀態（能力有限，主要是 UI 提示 + 必要時列出偵測到的介面 IP） |
| `transport_wifi.py` | zeroconf 廣播 `_phonespeaker._tcp` |
| `gui.py` | customtkinter：模式選擇（USB/WiFi/BT）、連線狀態、"PC 同時出聲" 開關、啟停按鈕、延遲數字顯示 |
| `config.py` | port、chunk size 等常數 |

### Android（`android/app/src/main/...`）
| 模組 | 職責 |
|---|---|
| `MainActivity` / UI | 選連線模式、顯示連線狀態、啟停 |
| `StreamerService`（前景服務） | TCP client 連線管理、收封包、write 進 `AudioTrack`、斷線重連、`PARTIAL_WAKE_LOCK` |
| `NsdHelper` | `NsdManager` 探索 `_phonespeaker._tcp` |
| `AudioPlayer` | 封裝 `AudioTrack`（`MODE_STREAM` + `PERFORMANCE_MODE_LOW_LATENCY`），underrun 補靜音不崩潰 |

## 9. M1 / M2 範圍

- **M1（本次交付目標）**：USB(tethering) + WiFi(mDNS)，raw PCM，PC 靜音/還原，斷線重連，
  前景播放，達成 prompt 第 10 節驗收條件中除 BT 外的全部項目。
- **M2（之後再做，本次不動）**：Opus 壓縮、Bluetooth PAN、裝置熱切換（若 M1 未做完）。

## 10. 延遲量測方式

- 端到端估算 = 擷取區塊時長（20ms）+ 網路傳輸（區網 TCP，實測 <5ms 常見）+ Android `AudioTrack`
  buffer 時長（`getMinBufferSize()` 換算成 ms，通常 10–40ms）。
- 提供一個簡單量測法：PC 端在送出每包前記錄時間戳寫入 debug log（非封包內容），Android 端在
  `AudioTrack.write()` 前記錄收到時間戳寫入 debug log，兩邊系統時間先用 NTP/手動校時對齊，
  相減得到近似端到端延遲。這只在 debug/量測模式開啟，不影響正式路徑（讀 log 不在音訊 hot path 上）。
- GUI 上顯示的「延遲」數字 = 上述 buffer 估算值（非每次都做時間戳量測），量測模式是額外驗證手段。

## 11. 風險與待確認事項

1. **USB 模式下 mDNS 是否能過 RNDIS 介面** — 上面第 6 節已寫預設方案+fallback，若你已知答案（例如
   之前測過 AudioRelay/SoundWire 這類 app 在 USB 模式下就是這樣做），麻煩告知可省去我方驗證時間。
2. **單一 client 限制**：M1 只允許同時一個手機連線，符合 prompt 的使用情境（一支手機當喇叭），
   如果你其實想同時支援多手機，請告知（目前預設：不支援，先簡單化）。
3. **PC 端裝置變更熱切換**（第 7 節風險）：先只做啟動時抓一次預設裝置，若你的使用情境常常中途切換
   輸出裝置（例如插拔耳機/外接螢幕喇叭），這點會影響你能不能滿足需求，請提前告知重要程度。
4. **Windows 防火牆首次跳出詢問**：PC app 第一次 listen TCP port 時 Windows 會跳防火牆允許視窗，
   這是正常現象，README 會註明，不會特別做程式繞過（也不應該繞過）。
5. **adb reverse fallback** 排在 M1 之後的 nice-to-have，先不擋交付，若這是你在意的必要路徑
   請告知我提前排入 M1。

## 12. 待新增檔案清單

```
speakerApp/
├─ SPEC.md                     (本檔，已產出)
├─ README.md
├─ .gitignore
├─ .env.example                (M1 用不到密鑰，內容可能是空的/僅示範，先建立符合規範)
├─ pc/
│  ├─ main.py
│  ├─ audio_capture.py
│  ├─ mute_control.py
│  ├─ streamer.py
│  ├─ transport_usb.py
│  ├─ transport_wifi.py
│  ├─ gui.py
│  ├─ config.py
│  └─ requirements.txt
└─ android/
   └─ app/src/main/
      ├─ java/.../MainActivity.kt
      ├─ java/.../StreamerService.kt
      ├─ java/.../NsdHelper.kt
      ├─ java/.../AudioPlayer.kt
      ├─ AndroidManifest.xml
      └─ res/...（基本 UI layout / values）
```

## 13. 第三方套件清單

### PC（`pc/requirements.txt`）
- `pyaudiowpatch` — WASAPI loopback 擷取
- `pycaw` — Core Audio 靜音/音量控制
- `comtypes` — pycaw 依賴，且若做裝置變更監聽會直接用到
- `customtkinter` — GUI
- `zeroconf` — mDNS 廣播

### Android（Gradle）
- 無額外第三方庫：`NsdManager`、`AudioTrack`、前景服務都是 Android SDK 內建，
  Compose 或 XML UI 用內建即可（依 minSdk 26）。

---

## 14. 驗收條件

照抄 prompt 第 10 節，M1 範圍內全部照做，BT 相關項目排除（M2 才做）。

---

**下一步**：請針對第 11 節逐項回覆你的決定，或若都同意上面的預設方案，直接回「ok」即可開始寫程式。

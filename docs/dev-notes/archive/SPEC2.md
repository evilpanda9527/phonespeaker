# SPEC2.md — PhoneSpeaker（Android 當 PC 喇叭）整合定稿

> 本文件整合並取代先前三份的討論：
> 1. `SPEC.md`（Claude Code CLI 初版設計）
> 2. `GPT SPEC Review.md`（GPT 對初版的審查意見）
> 3. `GPT_SPEC.md`（GPT 依審查改寫的版本）
>
> **本文件僅做設計，不含實作程式碼。** 依 strict-confirm-workflow：待你針對第 12 節的決策點回覆後才開始寫程式。
>
> 撰寫立場：採納 GPT review 中所有「真正的技術改進」，但對 USB / BT 兩項不照 GPT_SPEC 的方向，改以**符合 Android 平台實際能力**的方式收斂，並把無法在非 root 下達成的理想版本明確標示，不假裝做得到。

---

## 0. 三份文件差異總表與裁決

| 項目 | SPEC.md（CLI 初版） | GPT_SPEC.md（GPT 改版） | 本文件裁決 |
|---|---|---|---|
| 音訊格式 | 全程固定 48k/2ch/S16LE | 動態 passthrough，PC 傳什麼手機播什麼，格式只在連線初始化傳一次 | **採 GPT**：passthrough + 一次性格式握手（符合你「低延遲優先、不轉檔」） |
| PC 靜音時機 | TCP accept 成功即靜音 | 等 Android 回 READY 才靜音 | **採 GPT**：READY 後才靜音，避免無聲空窗 |
| 預設輸出裝置熱切換 | M1 stretch，可能跳過 | M1 必做 | **採 GPT**：M1 必做 |
| 緩衝策略 | 最小、幾乎不 queue | 小型 ring buffer（約 40–100ms）吸收 jitter | **採 GPT**：小型 ring buffer |
| 延遲量測 | timestamp + NTP 估算 | 標為 estimated，看影片驗收 | **採 GPT**：丟掉 NTP/waveform，直接看影片 |
| 單一 client | 單一 | 單一 | 一致：維持單一手機 |
| **USB 傳輸** | USB 網路共享(RNDIS)→TCP | **USB Audio(UAC) 或自訂 USB protocol，拒用 tethering** | **不照 GPT**：原生 USB Audio 需 root，不可行；M1 走務實路線，見第 8 節決策點 |
| **BT 傳輸** | BT PAN→TCP | **Bluetooth Audio(A2DP sink)** | **不照 GPT**：A2DP sink 需 root，不可行；BT 為「網路 over BT」，列 M2，見第 8 節決策點 |
| WiFi 傳輸 | mDNS + TCP | mDNS + TCP | 一致：M1 主力，最穩 |

---

## 1. 必須先講清楚的硬限制（本專案的邊界）

以下是 Android 平台層級的限制，**非 root 的一般 app 無法突破**，與工程品質無關。GPT_SPEC.md 把 USB/BT 定義成的理想目標，正好落在這兩條限制上。

1. **USB：手機無法在非 root 下把自己呈現成 Windows 原生的「USB 喇叭」（USB Audio Class gadget）。**
   - 要讓 Windows 插上就看到一個 USB Speaker，手機端需要 UAC gadget 驅動 + 切換 USB gadget function，這需要 root 與改 kernel/ROM 設定。
   - 因此「插 USB → Windows 音效清單多一個手機喇叭 → 不裝驅動」這個版本，**M1 不做、也不建議做**。

2. **BT：手機無法在非 root 下當 PC 的 A2DP Sink（真正的藍牙音訊接收端）。**
   - A2DP Sink 在多數市售 Android 上被 OEM 關閉、且需系統/privileged 權限，app 打不開。
   - 因此「PC 配對後把手機當藍牙喇叭、音訊走 A2DP 自動流入」這個版本，**做不到**。

3. **可行的共同路線：雙端 app + 資料串流。** 三種傳輸最後都由 Android app 收到音訊資料，寫進 `AudioTrack` 播放。市面同類產品（AudioRelay、SoundWire）皆是此架構、手機端都要裝 app、也都不做上面 1/2 的原生版本——原因相同。

> 結論：**能百分百達成的是「app 串流」，不是「原生 USB/BT Audio 裝置」。** 本文件據此收斂。

---

## 2. 目標與優先序

一句話：**PC 播放中的系統音訊 → 經使用者選擇的 USB / WiFi / BT 傳輸 → Android app → 手機喇叭播放。**

優先序（你確認過）：
1. **低延遲**（最高）
2. 穩定播放（不斷音、不爆音）
3. 不改變 PC 原始音訊資料（不 resample / 不 remix / 不轉檔）
4. 使用簡單、不限 app 開啟順序
5. 相容性（最低）

---

## 3. 使用者流程（正式驗收依據，已按實際能力校正）

不限 PC app 與手機 app 的開啟先後；斷線或關 app 後聲音回到 PC；連線成功且手機 READY 後 PC 預設自動靜音（可開關）。

- **WiFi**：同一 WiFi → 兩端開 app → 自動探索連線 → 手機出聲。（**M1，最順**）
- **USB**：接 USB 線 → 依第 8 節選定的 USB 路線建立連線 → 兩端開 app → 手機出聲。（**M1，但需你先在第 12 節選定 U1/U2**）
- **BT**：先完成藍牙配對 → 手機 app 選「當作 speaker」→ 建立 BT 資料連線 → 手機出聲。（**M2；且為「網路 over BT」，非 A2DP，延遲較高、需壓縮**）

---

## 4. 架構總覽

```text
┌──────────────── PC (Windows, Python) ────────────────┐
│ WASAPI Loopback（抓當下預設輸出裝置的實際格式）        │
│      │  原始 PCM（不轉檔）+ 一次性 format metadata     │
│      ▼                                                │
│ transport manager ──┬── WiFi  : mDNS 探索 + TCP        │
│      │              ├── USB   : U1 RNDIS/TCP 或 U2 adb │
│      │              └── BT(M2): PAN/RFCOMM 串流         │
│ device_monitor.py：預設輸出裝置變更→重建 capture       │
│ mute_control.py：Android READY 後靜音；斷線還原         │
│ gui.py：模式選擇 / 狀態 / "PC 同時出聲" 開關            │
└───────────────────────────────────────────────────────┘
                        │  傳輸層只負責把 PCM 低延遲送達
                        ▼
┌──────────────── Android (Kotlin) ────────────────┐
│ Transport Receiver → Small Ring Buffer(40–100ms) │
│      → AudioPlayer(AudioTrack, 依 metadata 建立)   │
│      → Phone Speaker                               │
│ Foreground Service：鎖屏/切背景仍持續播放          │
└───────────────────────────────────────────────────┘
```

核心原則：傳輸方式只差「怎麼把 PCM 送到手機」；一旦連上，走同一套握手 / 播放邏輯。

---

## 5. 音訊格式策略（採 passthrough，符合你的低延遲優先）

- PC 端 **不 detect-and-convert、不 resample、不 remix、不改 bit depth**。WASAPI loopback 拿到什麼格式，就原封不動送出。
- **唯一必要的動作：連線建立時傳一次 format metadata**（`sample_rate` / `channels` / `encoding`），讓 Android 的 `AudioTrack` 知道怎麼解讀 PCM。這**不是**格式轉換或比對，只是一次性告知；不做這步 AudioTrack 無法正確播放。
- 之後每個封包只有純 PCM，不重複帶格式、不加序號、不加 timestamp。
- **相容性態度（你的選擇：低延遲 > 相容性）**：若某手機的 AudioTrack 不支援 PC 當下的格式（例如 96kHz/32-bit float），**M1 不在 PC 端偷偷轉檔**，而是直接顯示「此格式不支援」錯誤。要不要做格式轉換是未來獨立功能，不屬於低延遲 M1。

---

## 6. 連線握手與 PC 靜音行為

握手序（避免 PC 先靜音卻沒聲音的空窗）：
```text
(建立傳輸連線)
PC → HELLO + FORMAT(sample_rate, channels, encoding)
Android → READY（AudioTrack 已建立、準備好播放）
PC → 開始送 PCM，同時執行「保存原音量/靜音狀態 → 靜音預設輸出端點」
(斷線 / 關 app / 傳輸錯誤) → 還原先前保存的音量/靜音狀態
```
- 靜音用 `pycaw` / `IAudioEndpointVolume` 控制預設輸出端點。
- GUI 開關「連線時 PC 同時出聲」打開時，跳過靜音，其餘不變。

---

## 7. 預設輸出裝置熱切換（M1 必做）

日常常見：插拔 HDMI / 耳機 → Windows 預設輸出裝置改變。M1 必須處理：
```text
偵測 Default Audio Device 變更（IMMNotificationClient / comtypes callback）
  → 停止舊 WASAPI loopback
  → 對新預設裝置重建 capture（可能是新格式 → 重送 FORMAT 給 Android）
  → 手機持續播放新的系統音訊
```
> 註：裝置變更後格式可能改變，需重新走一次 FORMAT 告知（Android 依新格式重建 AudioTrack）。

---

## 8. 各傳輸方式詳解與決策點

### 8.1 WiFi（M1，無爭議）
- PC 為 TCP server（bind `0.0.0.0:58482`，可覆寫），Android 為 client。
- PC 用 `zeroconf` 廣播 `_phonespeaker._tcp.local.`；Android 用 `NsdManager` 探索，免手動輸入 IP。
- 不限開啟順序：任一端先開，另一端後開會被自動發現並連上；斷線持續 re-discovery / reconnect。
- framing：`length(4B, BE, u32) + PCM payload`，不壓縮。

### 8.2 USB（M1，**需你在第 12 節二選一**）
你要的「不開 USB 網路共享、插上就用、像真 USB 喇叭」在非 root 下不可得（見第 1 節）。實際可行的排序如下：

- **U1（務實，建議 M1 預設）— USB 網路共享(RNDIS/NCM) → TCP**
  - 使用者需開一次手機的「USB 網路共享」開關；之後插線、開 app 即自動連線。
  - 純 Python、無需驅動、可靠；複用 WiFi 那套 TCP + 探索邏輯。
  - 代價：不是「零設定」，要撥一個系統開關。
- **U2（自用/開發者友善）— adb forward → TCP**
  - 手機開 USB 偵錯、PC 端內含 `adb`；執行期手機端零操作。
  - 代價：需 USB 偵錯 + 隨附 platform-tools，不適合給一般使用者。
- **U3（最接近你理想、但成本高）— AOA 自訂 USB bulk 協定**
  - 不需 tethering、延遲低；但 **PC 端需安裝 WinUSB/libusb 驅動（Zadig）**，Android 走 accessory 模式，且 AOA 內建 audio 已於 Android 8 淘汰，須自刻資料通道。開發與部署複雜度高。→ 建議列為之後的研究項，不進 M1。
- **U4（真正「手機=Windows USB 喇叭」）— UAC gadget**
  - 需 root + 改 kernel gadget。**排除，不列入本專案。**

> **建議：M1 採 U1；若此機器主要你自用，可加 U2 當替代。U3 列 backlog、U4 排除。**

### 8.3 Bluetooth（M2，且為「網路 over BT」）
真正的 Bluetooth Audio Speaker（A2DP sink）非 root 做不到（第 1 節）。BT 能做的是把音訊當資料串流：

- **B1（建議）— BT PAN → TCP**：手機開藍牙網路共享，PC 加入，複用同一套 TCP。需壓縮（見下）。
- **B2 — RFCOMM/SPP 自訂 socket + 壓縮**：不需 PAN，但 Windows 端用 Python 做 RFCOMM 麻煩（可能需改 C#/32feet 或 pybluez），仍需壓縮。
- **B3（你理想的 A2DP sink）**：需 root/系統權限。**排除。**

> BT 共同限制須先接受：頻寬約 <1 Mbps，**無損 PCM 塞不下 → 必須用 Opus 等壓縮**（這是 M1「不壓縮」原則在 BT 上的唯一例外）；延遲明顯高於 USB/WiFi，**看影片可能對不上嘴**。因此 BT 一律列 M2，且定位為「聽音樂/Podcast 可接受、看影片建議改 USB/WiFi」。

---

## 9. 緩衝、延遲與驗收

- **Ring buffer（小）**：Android 端保留約 40–100ms 的 jitter buffer（實測微調），吸收 USB/WiFi 抖動；underrun 時補最短靜音、不 crash，不做無限增長的大 queue。
- **延遲顯示**：GUI 若顯示數字，一律標示為「estimated（network + buffer）」，**不宣稱為精確 end-to-end**。
- **驗收方式（依你的意見）**：不做 NTP / waveform / 麥克風錄音比對。直接播放有明顯聲畫節奏的影片，肉眼/耳判斷延遲、是否斷音卡頓、三種傳輸差異、斷線是否自動恢復、app 開啟順序是否不拘、PC 靜音/還原是否正常。

---

## 10. M1 / M2 範圍

**M1（本次交付）**
- WiFi 串流（mDNS + TCP，raw PCM passthrough）
- USB 串流（U1 為主；視第 12 節決定是否加 U2）
- 一次性 FORMAT 握手 + Android READY 握手
- PC 依 READY 靜音 / 斷線還原
- 預設輸出裝置熱切換重建 capture
- Android 前景服務、鎖屏/切背景持續播放、斷線自動重連
- 小型 ring buffer

**M2（之後）**
- Bluetooth（B1 為主；網路 over BT + Opus 壓縮）
- U3（AOA 自訂 USB）研究（若你要更接近「免 tethering」）
- 可選的格式轉換相容層（若某些手機格式不支援）

**不屬於本專案**
- U4 UAC gadget、B3 A2DP sink（需 root）
- 多手機同時播放
- 精確數學化 E2E latency 量測

---

## 11. 模組 / 檔案 / 套件清單

```text
PhoneSpeaker/
├─ SPEC2.md（本檔）
├─ README.md
├─ .gitignore
├─ pc/
│  ├─ main.py
│  ├─ audio_capture.py        # WASAPI loopback，保留實際格式，不轉檔
│  ├─ audio_format.py         # 格式 metadata 封裝
│  ├─ mute_control.py         # pycaw 靜音/還原
│  ├─ device_monitor.py       # 預設輸出裝置變更監聽 + 重建 capture
│  ├─ streamer.py             # framing + send（不修改 PCM）
│  ├─ transport_wifi.py       # zeroconf 廣播 + TCP
│  ├─ transport_usb.py        # U1(RNDIS/TCP)；(選)U2 adb
│  ├─ transport_bluetooth.py  # M2
│  ├─ gui.py                  # customtkinter
│  ├─ config.py
│  └─ requirements.txt
└─ android/app/src/main/
   ├─ MainActivity.kt / UI
   ├─ StreamerService.kt      # 前景服務、transport 管理、reconnect
   ├─ WifiTransport.kt        # NsdManager + TCP client
   ├─ UsbTransport.kt         # 對應 U1/U2；(選)U3 AOA
   ├─ BluetoothTransport.kt   # M2
   ├─ AudioFormat.kt          # 解析 FORMAT metadata
   ├─ AudioPlayer.kt          # AudioTrack, MODE_STREAM, LOW_LATENCY
   ├─ RingBuffer.kt
   ├─ AndroidManifest.xml
   └─ res/...
```

PC 套件：`pyaudiowpatch`、`pycaw`、`comtypes`、`customtkinter`、`zeroconf`；（U2 才需要隨附 `adb`；U3 才需 libusb/WinUSB，先不加）。
Android：優先用 SDK 內建（`NsdManager`、`AudioTrack`、Foreground Service）；M1 不引入第三方音訊串流庫；minSdk 26。

---

## 12. 待你拍板的決策（回覆後才進實作）

1. **USB 路線**：M1 採 **U1（USB 網路共享，需撥一次開關）** 為預設，是否可接受？若此機主要你自用，要不要**同時加 U2（adb，手機零操作但需開 USB 偵錯）**？（U3/U4 依上面建議不進 M1。）
2. **BT**：確認 **BT 全部列 M2**、且接受它是「網路 over BT + 壓縮、延遲較高、看影片可能對不上嘴」，而非 A2DP。是否同意？
3. **格式 passthrough**：確認 M1 遇到手機不支援的格式時「直接報錯、不轉檔」，而不是自動降轉。是否同意？
4. **單一 client**：維持只支援一支手機同時連線。是否同意？

> 以上四點回覆（或直接說「都同意」）後，即依本 SPEC2.md 進入 M1 實作。

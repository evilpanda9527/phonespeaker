# SPEC3.md — PhoneSpeaker（Android 當 PC 喇叭）第三版整合定稿

> 承接並取代 `SPEC2.md`，整合 `GPT_SPEC2_Review.md` 審查意見，並加入使用者最新指示（增量開發順序、檔案隔離、單一安裝檔）。
> 來源鏈：`SPEC.md` → `GPT_SPEC.md` → `SPEC2.md` → `GPT_SPEC2_Review.md` → **本檔 SPEC3.md（作用中唯一規格）**。
>
> **本文件僅做設計，不含實作程式碼。** 依 strict-confirm-workflow：§15 決策已定（自用、驅動不簽章），採「先 PoC、逐項測試通過才前進」，可從 M1-A WiFi 開工。

---

## 0. 相對前版的變更摘要

| # | 來源 | 處置 |
|---|---|---|
| 格式報錯用詞精準化（裝置/API 層級 → `FORMAT_UNSUPPORTED`） | GPT SPEC2 Review | 採納，§5 |
| Ring buffer 改 target 20–60ms | GPT SPEC2 Review | 採納，§9 |
| BT 不寫死 Opus，先測 raw PCM | GPT SPEC2 Review | 採納，§8.3 |
| Transport Interface 抽象、不綁 TCP | GPT SPEC2 Review | 採納，§4/§13 |
| U3(AOA) 不完全否定；U1 不當唯一方案 | GPT SPEC2 Review | 採納，§8.2 |
| 「非 root 下 USB 無零設定路；U2(adb) 對自用最划算」 | 本方補充 | 保留，§1/§8.2 |
| **U1/U2/U3 全做、簡單→複雜逐一完成、測試通過才前進** | **使用者指示** | **新增，§10** |
| **WiFi→USB→BT 亦簡單→複雜逐一完成** | **使用者指示** | **新增，§10** |
| **檔案隔離、不得因新增 B 而弄壞已通過的 A** | **使用者指示** | **新增，§10/§13** |
| **Windows 端所有安裝（app、U3 driver 等）包成單一安裝檔、一次裝完** | **使用者指示** | **新增，§11** |

---

## 1. 硬限制與「USB 沒有零設定路」

非 root 一般 app 無法突破（有 Android 官方文件佐證）：
1. 手機無法呈現為 Windows 原生 USB 喇叭（UAC gadget，需 root/kernel）→ **排除**。
2. 手機無法當 PC 的 A2DP Sink（真藍牙音訊接收端，需系統權限）→ **排除**。
3. 可行共同路線＝雙端 app + 資料串流，最後由 Android app 寫進 `AudioTrack`。

**USB「不開網路共享」的實話**：非 root 沒有零設定路，差別只是那一次設定放哪——
U1＝手機撥「USB 網路共享」開關（PC 免驅動）；U2＝手機開一次「USB 偵錯」（PC 需 adb + 一次性驅動，執行期手機零操作）；U3＝執行期手機零操作但 PC 需裝 WinUSB 驅動。**三者本版全做**（見 §10），順序由簡到繁。

---

## 2. 目標與優先序

**PC 系統音訊 → 使用者選的 USB / WiFi / BT → Android app → 手機喇叭。**
優先序：**① 低延遲 ＞ ② 穩定 ＞ ③ 不改變原始音訊(不 resample/remix/轉檔) ＞ ④ 使用簡單/不限開啟順序 ＞ ⑤ 相容性。**

---

## 3. 使用者流程（驗收依據）

不限 PC/手機 app 開啟先後；斷線或關 app 後聲音回到 PC；連線成功且手機回 READY 後 PC 預設自動靜音（可開關）。
- **WiFi**：同一 WiFi → 兩端開 app → 自動探索連線 → 手機出聲。
- **USB**：接 USB 線 → 依當前已完成的變體(U1/U2/U3)建立連線 → 兩端開 app → 手機出聲。
- **BT（M2）**：先藍牙配對 → 手機 app 選「當作 speaker」→ 建立 BT 資料連線 → 手機出聲。（資料串流非 A2DP；延遲較高、看影片可能對不上嘴。）

---

## 4. 架構總覽（Transport Interface 抽象）

```text
           PC (Windows, Python)                          Android (Kotlin)
┌───────────────────────────────────┐        ┌───────────────────────────────────┐
│ WASAPI Loopback（實際格式，不轉檔）│        │      Transport (依模式，各自獨立檔) │
│        │ PCM + 一次性 FORMAT       │        │  ┌──────┬──────┬──────┐            │
│        ▼                           │        │  WiFi   USB    BT                  │
│  AudioSource（core，穩定層）       │        │  └──────┴──────┴──────┘            │
│        ▼                           │        │        │ read PCM                  │
│  ┌──── Transport Interface ────┐   │◄──────►│        ▼                           │
│  │ connect/disconnect/         │   │  bytes │  Ring Buffer (target 20–60ms)      │
│  │ read/write PCM              │   │        │        ▼                           │
│  │  ├ wifi.py                  │   │        │  AudioPlayer(AudioTrack, LOW_LAT)  │
│  │  ├ usb_rndis.py (U1)        │   │        │        ▼                           │
│  │  ├ usb_adb.py   (U2)        │   │        │   Phone Speaker                    │
│  │  ├ usb_aoa.py   (U3)        │   │        │  Foreground Service（鎖屏續播）    │
│  │  └ bluetooth.py (M2)        │   │        │                                   │
│  └─────────────────────────────┘   │        │                                   │
│ device_monitor / mute_control / gui│        │                                   │
└───────────────────────────────────┘        └───────────────────────────────────┘
```

**核心原則**：音訊格式、READY 握手、ring buffer、AudioTrack 播放邏輯**不綁死任何 transport**。每種 transport 只實作統一介面 `connect / disconnect / read / write PCM`，且各自一個檔案（見 §10 隔離規則）。

---

## 5. 音訊格式策略（passthrough）

- PC 端**不 detect-and-convert、不 resample、不 remix、不改 bit depth**，WASAPI 拿到什麼原封不動送。
- **唯一必要動作**：連線建立時傳一次 `FORMAT(sample_rate, channels, encoding)`。
- 每封包只有純 PCM，不重複帶格式、不加序號/timestamp。
- **相容性**：Android 以 PC 的原始 format 建立 AudioTrack；**若當前裝置/API 無法以該 format 建立播放，回報 `FORMAT_UNSUPPORTED`，PC 端不轉檔**。

---

## 6. 握手與 PC 靜音

```text
(建立 transport 連線)
PC → HELLO + FORMAT
Android → READY  或  FORMAT_UNSUPPORTED（PC 顯示錯誤，不靜音）
PC → 送 PCM，同時「保存原音量/靜音 → 靜音預設輸出端點」
(斷線/關 app/錯誤) → 還原保存狀態
```
- `pycaw` / `IAudioEndpointVolume`；GUI「連線時 PC 同時出聲」開關可跳過靜音。**務必等 READY 才靜音**。

---

## 7. 預設輸出裝置熱切換（M1 必做）

偵測 Default Audio Device 變更（`IMMNotificationClient`/`comtypes`）→ 停舊 loopback → 重建 capture → 若格式改變重送 FORMAT → 手機續播。

---

## 8. 各傳輸方式詳解

### 8.1 WiFi（最簡單，第一個做）
PC=TCP server(`0.0.0.0:58482`)，Android=client；`zeroconf` 廣播 `_phonespeaker._tcp.local.`，Android `NsdManager` 探索，免手動 IP；不限開啟順序、斷線 reconnect；framing `length(4B,BE,u32)+PCM`，不壓縮。

### 8.2 USB（三個變體全做，U1→U2→U3）
> UI 顯示名稱（使用者看得懂的）：U1 =「USB (USB 網路共享)」。U2/U3 之後定名。
- **U1 — USB 網路共享(RNDIS/NCM) → TCP**：手機撥開關；PC 免驅動、純 Python；複用 §8.1 的 TCP。**最簡單，先做。UI 名稱「USB (USB 網路共享)」。**
- **U2 — adb forward → TCP**：手機開 USB 偵錯；PC 隨附 adb（USB 驅動多半自動）；執行期手機零操作、延遲極低。**次之。**
- **U3 — AOA 自訂 accessory bulk data → PCM**：AOA 的「audio」雖淘汰，但**自訂 accessory bulk data channel 仍可用**；執行期手機零操作，但 PC 需 WinUSB 驅動 + libusb，開發最複雜。**最後做。**
- **U4 — UAC gadget**：root，排除。

### 8.3 Bluetooth（M2，最後；資料串流非 A2DP）
- **B1 — BT PAN → TCP**（複用同一介面）；**B2 — RFCOMM/SPP 自訂 socket**（Windows 端 Python 較麻煩，可能改 C#/32feet 或 pybluez）；**B3 — A2DP Sink** 需 root，排除。
- **壓縮策略**：**不預先寫死 Opus**。先 benchmark raw PCM（`48k/16/stereo`、`44.1k/16/stereo`、`32k/16/stereo`）能否穩定傳，塞不下才評估 Opus。

---

## 9. 緩衝、延遲與驗收

- **Ring buffer**：target **20–60ms**，必要時才到 100ms；underrun 補最短靜音、不 crash、無無限 queue。
- **延遲顯示**：標「estimated（network + buffer）」，不宣稱精確 E2E。
- **驗收**：不做 NTP/waveform/麥克風比對；直接播有明顯聲畫節奏的影片，肉眼/耳判斷延遲、斷音卡頓、傳輸差異、斷線恢復、開啟順序、PC 靜音/還原。

---

## 10. 增量開發順序、測試閘門與不回歸原則（使用者指示，最高流程規範）

### 10.1 全域順序（簡單 → 複雜，逐一完成）
```
傳輸層：  WiFi  →  USB  →  BT
USB 內部：U1(RNDIS) → U2(adb) → U3(AOA)
```
三種傳輸都要做、USB 三個變體都要做；**一律由簡到繁，一次只推進一項。**

### 10.2 測試閘門（Gate）
每一項的定義完成＝**「實作完成」＋「通過該項的影片實測驗收（§9）」**。
**未通過驗收，不得開始下一項。** 順序範例：
`WiFi 過 → U1 過 → U2 過 → U3 過 → (M2) BT 過`。

### 10.3 檔案隔離（避免「做 B 弄壞 A」）
- 每個 transport／每個 USB 變體**各自一個獨立檔案**（見 §13 樹狀圖），只實作共同 `Transport Interface`。
- 共同核心（capture / format / mute / ring buffer / AudioTrack / handshake / 一個凍結的 TcpClient 輔助）為**穩定層**。
- **新增某一項時，不得修改任何「已通過驗收」的既有檔案。** 新變體只能新增自己的檔案 + 在 GUI 註冊一個選項。
- 各 transport 在 GUI 可**獨立選用、互不依賴**；停用 B 不影響 A。

### 10.4 不回歸規則（Regression Rule）
- 若某新項目**必須**改到共同核心（例如修共用 bug），改完後**必須重跑所有「已通過」項目的影片實測**，全部仍通過才算數。
- 每完成一項交付時附「**回歸檢查清單**」：列出本次改了哪些檔案、既有已通過項目是否仍全綠、以及變更範圍 diff。
- 目標：任何時間點，先前已通過的傳輸方式都保持可用，不因後續開發而退化。

### 10.5 每項交付內容
每完成並通過一項，交付：(a) 該項可獨立執行的版本；(b) 影片實測驗收結果；(c) 未動到既有已通過檔案的證明（變更檔案清單/diff 範圍）。

---

## 11. Windows 單一安裝檔（全包、一次安裝，使用者指示）

- **Windows 端交付永遠是「單一安裝檔」**：使用者執行一次、一次 UAC 提權，**全部裝完**；**不得要求分次安裝或手動另裝驅動**。
- 安裝檔內含（依當前已完成階段）：PC app（PyInstaller 打包 exe）、U2 所需 `adb`（+ 必要 USB 驅動）、U3 所需 WinUSB 驅動安裝、首次 Windows 防火牆允許提示。
- **隨功能增量，一律折進「同一個」安裝檔**，不產生多個安裝檔。早期階段（WiFi、USB U1）安裝檔不含驅動；到 U2/U3 階段才把對應項目加進同一安裝檔，最終成為 all-in-one。
- 建置工具建議：**Inno Setup** 或 **NSIS**（或 MSI/WiX）。驅動安裝可於安裝流程內以 `pnputil` 或 `libwdi`（Zadig 底層函式庫）程式化完成，使用者不需開 Zadig。
- **定位：自用、驅動一律不簽章（已定案）。** WiFi 與 U1 完全不裝驅動、無警告；U2 用的 Google/OEM USB 驅動本就已簽章、零負擔；**唯一會有一次「未簽章驅動」警告的是 U3（WinUSB），安裝當下按允許即可**，之後正常使用。安裝驅動需系統管理員權限（安裝檔會請求一次 UAC 提權）。
- 不採 EV 簽章：簽章需向 CA 申請、每年約 US$200–400 且需身分/公司驗證，對自用不划算，故排除。

---

## 12. M1 / M2 範圍（反映增量順序）

**M1-A**：Transport Interface 骨架 + **WiFi**（PCM passthrough、FORMAT/READY 握手、PC 靜音/還原、預設裝置熱切換、前景服務/鎖屏續播、斷線重連、ring buffer）。過關才進 M1-B。
**M1-B**：USB，依序 **U1 → U2 → U3**，每個獨立檔案、逐一過關。
**M2**：**Bluetooth**（B1 為主，網路 over BT；先 benchmark raw PCM，必要時才 Opus）。
**不屬於本專案**：U4 UAC gadget、B3 A2DP sink（需 root）、多手機同時、精確 E2E 數學量測。

---

## 13. 模組 / 檔案 / 套件（強化隔離）

```text
PhoneSpeaker/
├─ SPEC3.md（本檔，作用中唯一規格）
├─ README.md  .gitignore
├─ pc/
│  ├─ main.py
│  ├─ core/                        # 穩定層，凍結後改動須觸發回歸(§10.4)
│  │  ├─ audio_capture.py          # WASAPI loopback，保留實際格式，不轉檔
│  │  ├─ audio_format.py           # FORMAT metadata
│  │  ├─ mute_control.py           # pycaw 靜音/還原
│  │  ├─ device_monitor.py         # 預設裝置變更 → 重建 capture
│  │  ├─ handshake.py              # HELLO/FORMAT/READY/FORMAT_UNSUPPORTED
│  │  ├─ tcp_client.py             # 凍結共用（wifi/u1/u2 用）
│  │  └─ stream_engine.py          # AudioSource ↔ Transport 串接
│  ├─ transport/                   # 每項一檔，互相隔離
│  │  ├─ base.py                   # Transport Interface
│  │  ├─ wifi.py                   # WiFi（第 1 個做）
│  │  ├─ usb_rndis.py              # U1（第 2 個）
│  │  ├─ usb_adb.py                # U2（第 3 個）
│  │  ├─ usb_aoa.py                # U3（第 4 個，libusb）
│  │  └─ bluetooth.py              # BT（M2，最後）
│  ├─ gui.py                       # customtkinter，各 transport 獨立選項
│  ├─ config.py
│  └─ requirements.txt
├─ android/app/src/main/
│  ├─ MainActivity.kt / UI
│  ├─ StreamerService.kt           # 前景服務、transport 管理、reconnect
│  ├─ core/                        # 穩定層
│  │  ├─ AudioFormat.kt            # 解析 FORMAT，含 FORMAT_UNSUPPORTED
│  │  ├─ AudioPlayer.kt            # AudioTrack, MODE_STREAM, LOW_LATENCY（與 transport 解耦）
│  │  ├─ RingBuffer.kt
│  │  ├─ Handshake.kt
│  │  └─ TcpClient.kt              # 凍結共用（wifi/u1/u2 用）
│  ├─ transport/
│  │  ├─ Transport.kt              # 介面
│  │  ├─ WifiTransport.kt          # WiFi
│  │  ├─ UsbTcpTransport.kt        # U1/U2（TCP over RNDIS / adb-forward，target 位址不同）
│  │  ├─ UsbAoaTransport.kt        # U3（accessory）
│  │  └─ BluetoothTransport.kt     # M2
│  ├─ AndroidManifest.xml
│  └─ res/...
└─ installer/                      # Windows 單一安裝檔（§11）
   ├─ installer.iss                # Inno Setup（或 NSIS）腳本
   └─ resources/                   # 依階段打包：app exe、adb、winusb 驅動 inf/libwdi 等
```

PC 套件：`pyaudiowpatch`、`pycaw`、`comtypes`、`customtkinter`、`zeroconf`；(U2 隨附 `adb`；U3 才需 `libusb`/WinUSB，對應階段才加)。
Android：優先 SDK 內建（`NsdManager`、`AudioTrack`、Foreground Service、USB Host/Accessory、Bluetooth）；M1 不引入第三方音訊庫；minSdk 26。

---

## 14. 實作前先交付（PoC 報告）

大規模實作前先回報：(1) USB U1/U2/U3 各自 PoC 可行性、相容性、驅動負擔、延遲；(2) BT raw PCM bandwidth/latency 測試方案；(3) 單一安裝檔的建置方式（Inno/NSIS + 驅動程式化安裝）確認。暫不直接開始完整實作。

---

## 15. 決策（已全部定案）

全部依你的指示定案，無待決項：
- **定位**：自用；**驅動一律不簽章**（U3 安裝時一次未簽章警告，按允許即可；WiFi/U1 無驅動、U2 驅動本就已簽章）。
- USB 三變體全做；順序 **WiFi→USB→BT** 與 **U1→U2→U3**，簡單到複雜、逐項測試通過才前進。
- 檔案隔離、不回歸（§10）。
- Windows 單一安裝檔全包、一次裝完（§11）。
- BT 先測 raw PCM、不寫死 Opus；`FORMAT_UNSUPPORTED` 不轉檔；ring buffer 20–60ms；單一 client。

> 據此，下一步依 §10 順序先做 **M1-A WiFi**（含 §14 PoC 回報），過關再往下。

---

## 16. M1-A WiFi 實測待修項（實機驗收發現，逐一分開修，勿合併）

實機測試（PC Windows + 真實 Android 手機）陸續發現，依 §10「一次只推進一項、修 A 不動 B」逐項處理：

1. **【已修正✓】手機端無聲（float 播放路徑）**：協商格式 `48000Hz/2ch/pcm_f32le`，連線/握手/串流皆正常，但手機無聲。根因為 `AudioPlayer.kt` 對 `ENCODING_PCM_FLOAT` 使用 `AudioTrack.write(byte[], ...)` 多載（float 軌道不支援），已改用 `write(ByteBuffer, size, WRITE_BLOCKING)`（LITTLE_ENDIAN）。**實機驗證：手機已正常出聲，延遲幾乎無感。** 僅改 `AudioPlayer.kt`，未動 PC 端/協定層/`WifiTransport`/`RingBuffer`。

2. **【已完成✓】移除失效的「連線時 PC 同時出聲（不自動靜音）」開關**：實測發現此開關無作用（勾選後 PC 仍不出聲），使用者決定直接移除。**已移除完成**：現行為「連線即靜音、只有手機出聲」，斷線還原正常（實測確認）。

3. **【已完成✓】zeroconf 挑錯網卡**：PC 端 zeroconf 廣播時挑到虛擬網卡 IP（VirtualBox `192.168.56.1`）而非真正對外 WiFi 網卡。**已修正並實機驗證**：改用「依網卡描述（nice_name）排除虛擬網卡（virtualbox/vmware/virtual/loopback/tap-windows/vpn）、其餘全保留並以預設路由排序提示」——而非舊版「只宣告預設路由那張」（舊法在 USB tethering 開著時可能把 WiFi 排掉）。實測確認：VirtualBox `192.168.56.1` 被排除、WiFi `192.168.18.11` 保留、RNDIS `SAMSUNG Mobile USB Remote NDIS Network Device` **不會被誤擋**（已為 U1 鋪好路）。不寫死網段而用驅動描述字串（更穩定）。僅改 `pc/transport/wifi.py`。

**目前狀態總覽**：§16-1 無聲✓、§16-2 移除開關✓、§16-3 zeroconf 網卡✓、§16-4 停止關 app✓ + 破音✓ + 停止逾時✓（第四次診斷根治，見下）。**→ M1-A WiFi 已全面結案，可進 M1-B（U1）。** 附帶發現（對 U1 有利）：實測確認 **USB tethering 下 mDNS 能跨 RNDIS 連上**（PC `10.132.200.88` ↔ 手機 `10.132.200.64`），U1 可以 mDNS 為主路徑、子網掃描降為保底。

4. **【待修—已找到穩定重現】連線後未傳任何音訊即按「停止」會關閉整個 app**：
   - **穩定重現條件**：連線、手機回 READY 後，在「尚未有任何 PCM 傳給手機」的空窗（例如系統当下無聲）按「停止」→ app 自動關閉；若已傳過音訊再按停止則正常（回到待機、可重啟）。
   - **log 佐證**：正常（有音訊）停止走 `送出 PCM 失敗，判定為斷線` → 還原静音 → 重新等待連線；異常（無音訊）停止只有 `已還原静音` 一行後直接結束，沒有「判定斷線→重新等待」那段。
   - **根因判斷**：正常停止是靠串流迴圈「送 PCM 失敗→判定斷線」這條路回到待機；若連一筆 PCM 都還沒送過就按停止，串流迴圈不會觸發那條路徑，停止流程因而走進另一條收尾路徑（很可能是 `os._exit()`），將整個 app 關掉。
   - **修正方向**：「停止」應不論有無傳過 PCM 都回到「待機、可再啟動」狀態；`os._exit()` 只能屬於「關閉整個 app」路徑，不可被「停止串流」路徑誤觸發。修改應限於 PC 端停止/收尾邏輯（`stream_engine.py` / `gui.py`），不動協定層、Android 端。
   - **【第一次修正結果】**：停止不再關 app（✓ 主 bug 已止血），但帶出兩個新問題，需一併解決：
     - **A 停止逾時**：log 出現 `停止逾時：背景執行線尚未結束`——改用正常停止流程後，某背景執行線（擷取/收送）卡在阻塞未能及時結束；需停止時主動中斷阻塞（關 socket 唑醒 recv、嗚醒擷取迴圈）。
     - **B 破音（回歸）**：修正前串流播放正常無破音，修正後出現破音（延遲未變差）。研判為為了讓執行線可停而改動串流迴圈/緩衝/讀送節奏，影響資料連續性。**此為回歸，必須修掉**：串流品質需回到修正前。
     - **原則**：三點（停止不關 app、停止不逾時、播放不破音）需同時滿足；若停止機制與串流品質有取捨，以「串流品質優先、靠關 socket/事件旗標嗚醒而非在熱路徑加檢查」為原則。待第二次修正。
   - **【第二次修正結果】**：✓ 破音（B）已修好、✓ 停止不關 app 維持；但 A 停止逾時仍未解決。
   - **【第三次診斷結果 + 決定暫緩】**：診斷 log 確認停止逾時時仍存活的是 **`stream-engine`（主串流迴圈執行線本身）**，非擷取/收送子執行線（難怪前兩次針對子執行線都沒修中）。**使用者決定：此項降級為「已知小瑕疵、暫緩」。** 理由：實際後果僅為「按停止後印一行紅字、可能卡 3～4 秒才回到待機」，app 不崩、靜音有還原、能重啟，功能性是好的。已花三輪不再繼續。**待日後有空或它造成困擾再回頭修；已知線索：`stream-engine` 主迴圈在停止時未及時退出（可能迴圈結束條件未讀到停止旗標、或卡在對子操作的等待且未被唑醒、或 join 對象/順序不對）。**
   - **【第四次：加逐段計時診斷 → 根治✓】**：先在 `stream_engine.py`／`audio_capture.py`／`device_monitor.py`／`gui.py` 加逐段計時 log（純觀察、不改行為），量出真實數字後發現：子執行線（`pcm-sender`／`audio-capture`／`device_monitor`）**每次**都乾淨結束、毫秒級、`仍存活=False`；11 次樣本 **100%** 精準卡在 `_engine_thread.join(timeout=5.0s)`，卡的時長固定在 ~5000ms——這個「精準卡滿一個固定數字」指向確定性機制，而非隨機的 I/O 等待。
     - **真因**：使用者按停止時，GUI 主執行線同步卡在 `engine.stop()` 的 `_engine_thread.join(5.0)` 裡，沒有在跑 Tk event loop；同時 `stream-engine` 執行線收尾跑到 `_run()` 最後一行 `_set_state(STOPPED)` → `on_state_changed` → 舊版 `gui.py` 的 `_threadsafe()` **直接在 engine 執行線呼叫 `self.after(0, ...)`**。tkinter 規則：從非主執行線呼叫任何 Tk 方法都會被 marshal 回主執行線、並「同步等待」主執行線處理完才返回——不是單純排程。於是主執行線等 engine 執行線結束、engine 執行線等主執行線處理 `after()`，兩邊互卡，直到 `join()` 5 秒逾時、主執行線才脫身，engine 執行線才跟著解卡、`_run()` 才真正結束。這正是「精準卡滿 5000ms」與殭屍 `stream-engine` 執行線累積的根因，跟原本猜的「recvFrame 卡住」不是同一回事（子執行線／socket 收送其實都很快，卡的是 GUI 跨執行線呼叫本身）。
     - **修法**（僅改 `pc/gui.py`）：`_threadsafe()` 改成 engine 執行線只做純 Python `queue.put()`（不呼叫任何 Tk API、不會卡呼叫端），真正的 UI 更新交給主執行線既有的 `after(100, ...)` 輪詢迴圈自己取出執行，徹底不再有跨執行線 Tk 呼叫。`stream_engine.py`／`audio_capture.py`／`device_monitor.py`、任何 transport 檔案、協定層、Android 端**完全未動**。
     - **實測驗證（使用者確認）**：`_engine_thread.join` 從固定 5000ms 降到幾百 ms 內、`仍存活=False`、不再有 `[ERROR] 停止逾時`；反覆啟停後存活背景執行線維持 `(0)` 不累積；WiFi 與 **USB（USB 網路共享）** 都確認正常。**§16-4 全部三點（停止不關 app、停止不逾時、播放不破音）同時滿足，正式結案。** 診斷 log 保留在程式碼中（純觀察用，未來若又有停止相關問題可直接看數字）。

### 觀察項（尚需確認是否新問題）

- **週期性「滋」一聲雜音**：播放一段時間後偶發一聲細微雜音，週期不固定。使用者不確定一開始（修正前）是否就有。可能性：(1) 本來就有只是這次才注意到；(2) WiFi 傳輸 underrun（ring buffer 遇網路抖動來不及供料，補靜音/不連續）——週期不固定符合此特徵，屬 §9 buffer 微調範疇、非 bug；(3) 本次改動殘留副作用（機率較低，熱路徑已還原）。**決定：先不交 CLI（避免憑空推測），待 A 修好後放一段夠長的音樂（5～10 分）觀察滋聲頻率/規律、並看是否與 WiFi 訊號/PC 忙碌相關，確認是 underrun 還是真 bug 再處理。**
  **【todo07-3 補充觀察】**：實測確認**只有 WiFi 會偶爾雜音，USB（USB 網路共享）沒有**——支持「WiFi 傳輸 underrun」這個猜測（USB 網路共享的傳輸更穩定/低抖動）。**先記著、暫不處理**，待使用者確認是否要修再排。
- **zeroconf 關閉偶爾慢／`WinError 59`（Python 3.14）**：todo07-2 診斷停止逾時時發現，`transport.disconnect()` 內的 `zeroconf.unregister_service()`／`close()` 偶爾耗時約 3 秒，log 伴隨 `asyncio`/`zeroconf` 內部 proactor event loop 的 `[WinError 59] 出现了意外的网络错误` traceback（Python 3.14 + zeroconf 的已知組合問題）。**已確認跟 §16-4 停止逾時（`stream-engine` 主迴圈卡死）是不同機制、不同源**（前者是 zeroconf 函式庫自己耗時，後者是 GUI 跨執行線呼叫互卡），故未一併修。**先記著、暫不處理**，待使用者確認是否要修再排。

# 專案：把 Android 手機當成 PC 的喇叭（PhoneSpeaker）

> 這是要交給 VS Code 內 Claude Code 執行的開發指示。
> 請**先產出 `SPEC.md` 與檔案/套件清單，取得我明確回覆「ok」後才開始寫程式**（遵循 strict-confirm-workflow）。程式碼精簡，不擴張範圍。有不確定先提案問我，不要腦補。

---

## 0. 一句話目標
做一套「PC 端 app + Android 端 app」，把 **PC 正在播放的系統音訊**擷取後串流到 **Android 手機喇叭**播出。兩邊 app 開著、連線成功，聲音就從手機出來。

---

## 1. 使用者使用流程（這是驗收的最終依據，不可偏離）
> 不在乎 PC app 與手機 app 的開啟先後順序，兩邊都開好就要能連。

1. **連線方式選項**：app 內可選 **USB / BT / WiFi** 三種。
2. **USB**：USB 線接上 → 手機開 app、PC 開 app → 音訊直接從手機輸出。
3. **BT**：手機與 PC 先完成藍牙配對 → 手機開 app 選「當作 speaker」→ 音訊直接從手機輸出。
4. **WiFi**：同一個 WiFi → 手機開 app、PC 開 app → 兩端 app 自動配對連線 → 音訊直接從手機輸出。

「音訊直接輸出」的定義：連線成功後，**app 自動擷取 PC 當下的系統輸出聲音**（YouTube / Spotify / 遊戲皆可），使用者**不需要進 Windows 設定切換任何輸出裝置**。斷線或關閉 app，聲音回到 PC。

## 2. PC 靜音行為（重要）
- **預設：連線成功時自動把 PC 本機喇叭靜音，只有手機出聲。**
- 提供一個開關「連線時 PC 同時出聲」，使用者可隨時切回雙邊都響。
- 斷線 / 關閉 app 時，自動把 PC 音量還原成連線前的狀態（記得先保存原本的靜音/音量值）。
- 實作提示：可用 Windows Core Audio（pycaw / IAudioEndpointVolume）控制預設輸出端點的靜音狀態；擷取聲音用的是 WASAPI loopback，與靜音互不衝突（loopback 抓的是 render 資料流，靜音只是不送到實體喇叭）。請自行驗證這點在實機成立。

---

## 3. 必讀技術前提（不要往死路走）
- **不要**嘗試把 Android 做成標準 A2DP Sink 或 USB Audio(UAC) 裝置，也**不要**去做讓手機出現在「Windows 輸出裝置清單」裡的虛擬音訊驅動。這些需要系統權限 / gadget 驅動 / root / 驅動簽章，不在本專案範圍。
- 正確方向：**自訂雙端 app + 網路音訊串流**。手機端一定要裝 app。市面同類產品（如 AudioRelay、SoundWire）即是此架構，可作為對標參考。

## 4. 核心架構（transport-agnostic）
把三種連線方式**統一抽象成一條 TCP/IP 連線**。app 本體只做：擷取 → (可選編碼) → 送出 → 接收 → (可選解碼) → 播放。**PC 當 server（listen），手機當 client（connect）**，三種傳輸共用同一套連線邏輯。

- **USB（主力、延遲最低、免 root、免 adb）**：走 **USB 網路共享 / tethering（RNDIS）**。使用者在手機開「USB 網路共享」開關，PC 取得區網 IP，走 TCP 串流。**不需要 USB 偵錯、不需要 adb。**
  - 備選：若 tethering 不可用，才退回 `adb reverse tcp:<PORT> tcp:<PORT>`（此路需 USB 偵錯 + platform-tools adb）。標為 fallback。
- **WiFi（同網段）**：PC 以 mDNS 廣播 `_phonespeaker._tcp`，手機用 `NsdManager` 探索後自動連線，**不需手動輸入 IP**。
- **BT（進階）**：走 **Bluetooth PAN 網路共享**（手機開藍牙網路共享，PC 加入），複用同一套 TCP 串流。頻寬低（<1 Mbps），**必須開 Opus 壓縮**，延遲較高，看影片可能對不上嘴——此為藍牙原理限制，非 bug。

## 4.5 首要設計原則：路徑最短、低延遲、高音質（優先於一切）
> 這是本專案的最高指導原則。任何設計/取捨若與此衝突，以本節為準。「音效從輸入到輸出的路徑越短越好，不做無謂的中間層。」

- **路徑最短**：擷取 → 傳輸 → 播放，中間**不落地存檔、不轉檔、不經多餘的佇列或執行緒跳轉**。每多一層 buffer / queue / 執行緒交接都會加延遲與抖動，除非有明確必要，否則不要加。
- **格式全程一致，避免重取樣**：兩端固定 48kHz / 立體聲 / S16LE。**不要**在中間做取樣率轉換或聲道轉換（重取樣是延遲與音質殺手）。
- **高音質優先於省頻寬**：USB / WiFi 頻寬充足，**M1 直接傳無損 raw PCM，不做有損壓縮**。只有 BT(M2) 頻寬不足時才用 Opus，且用高位元率設定。
- **低延遲優先於大緩衝**：緩衝取「能穩定不 underrun 的最小值」，不要為求保險灌大 buffer。Android 用低延遲路徑（`PERFORMANCE_MODE_LOW_LATENCY`），PC 端擷取用小區塊、即抓即送。
- **延遲與音質有衝突時的預設**：先滿足高音質（無損、48k），再把延遲壓到不斷音的最低。若某環節被迫二選一，於 SPEC 標出並問我。
- **可量測**：提供端到端延遲的量測方式或估算（擷取區塊 + 網路 + 播放 buffer 的總和），讓延遲是可驗證的數字，而非「感覺很快」。

## 5. 技術棧（除非有硬理由，照這個做）
### PC 端（Windows 11，Python）
- Python 3.11+
- 系統音訊擷取：`pyaudiowpatch`（WASAPI **loopback**，抓預設輸出裝置）
- 靜音控制：`pycaw`（Core Audio，控制預設輸出端點靜音/音量）
- GUI：`customtkinter`（連線方式選擇、連線狀態、「PC 連線時是否出聲」開關、啟停）
- mDNS：`zeroconf`
- M1 傳 **raw PCM**（免 codec 依賴）；M2（BT）才引入 Opus

### Android 端（Kotlin）
- minSdk 26（Android 8+），Compose 或 XML 皆可
- 播放：`AudioTrack`，`MODE_STREAM`，`PERFORMANCE_MODE_LOW_LATENCY`
- WiFi 探索：`NsdManager`
- 前景服務：`foregroundServiceType="mediaPlayback"`，螢幕關閉/切背景仍持續播放；必要時 `PARTIAL_WAKE_LOCK`
- 權限：`INTERNET`、`FOREGROUND_SERVICE`、`FOREGROUND_SERVICE_MEDIA_PLAYBACK`(API34+)、藍牙相關(M2)

## 6. 音訊規格與緩衝策略（寫進實作）
- 格式：**48000 Hz / 立體聲 / S16LE PCM**，兩端一致
- 分幀：每包約 **10–20 ms**（480–960 frames）+ 4-byte 長度標頭
- Android `AudioTrack` bufferSize = `getMinBufferSize()` × 2 起跳；underrun 補短暫靜音，不崩潰
- 延遲目標：**USB < 200 ms**，連續播放 10 分鐘不斷音
- 斷線自動重連（USB 拔插、WiFi 掉線後）
- PC 端跟隨「預設輸出裝置變更」重新抓 loopback

## 7. 里程碑
- **M1（先做，交付可用版）**：USB(tethering) + WiFi(mDNS)，raw PCM，含 PC 靜音控制（預設靜音）。達成「開兩邊 → 自動連 → 手機出聲、PC 靜音」。
- **M2（選配）**：Opus 壓縮 + Bluetooth PAN 串流。

## 8. 專案結構（建議）
```
PhoneSpeaker/
├─ SPEC.md
├─ pc/   main.py audio_capture.py mute_control.py streamer.py transport_usb.py transport_wifi.py gui.py requirements.txt
└─ android/  app/src/main/...  (AudioTrack 播放、NsdManager、前景服務)
```

## 9. 工作流程要求
1. **先只產出 `SPEC.md`**（架構、資料流、封包格式、模組職責、M1/M2 範圍、風險、待確認項），**先不要寫實作程式碼**。
2. 列出要新增/修改的**檔案清單**與**第三方套件清單**，等我「ok」再動手。
3. 有不確定先提案問我。
4. 程式碼精簡，不加沒要求的功能。
5. 完成後給出可自行驗證的通過條件。

## 10. 驗收條件（Definition of Done, M1）
- [ ] PC 播放影音，聲音從**手機喇叭**出來
- [ ] 全程 48kHz/立體聲/S16LE，**無重取樣、無有損壓縮（M1）**，音質與原始輸出一致
- [ ] 端到端延遲有明確量測值，USB 模式 < 200 ms（越低越好）
- [ ] 連線成功時 **PC 本機自動靜音**；開關可切回雙邊出聲；斷線後 PC 音量還原
- [ ] USB：手機開 USB 網路共享 + 兩端 app → **無需輸入 IP、無需 adb/偵錯**即自動連線，延遲 < 200 ms
- [ ] WiFi：同網段 mDNS 自動探索並連線，無需手動輸入 IP
- [ ] 不論 PC app 或手機 app 先開，都能連上
- [ ] 連續播放 10 分鐘無明顯斷音/爆音
- [ ] 手機螢幕關閉 / app 切背景仍持續播放
- [ ] USB 拔除再插上能自動重連
- [ ] README 說明各模式啟動步驟

---
（開發環境：Windows + Claude Desktop / Claude Code。專案路徑：`D:\Claude_Desktop_Test\PhoneSpeaker`。）

**Prompt(M1-B / U1:「USB (USB 網路共享)」實作)**

現在做 M1-B 第一個變體 **U1 =「USB (USB 網路共享)」**。


**背景(PoC 已驗證的事實):**
- USB 網路共享(RNDIS)下,mDNS 探索**能跨 RNDIS 連上**(實測 PC `10.132.200.88` ↔ 手機 `10.132.200.64`,介面描述含 `Remote NDIS`)。所以 **U1 以 mDNS 為主路徑、子網掃描/手動 IP 為保底**。
- 架構複用現有 TCP + 協定 + 播放,不重造。
- zeroconf 網卡選擇已修好、不會誤擋 RNDIS 介面(nice_name 含 `Remote NDIS`)。

**要做的:**
1. **PC 端**:新增獨立檔 `pc/transport/usb_rndis.py`,實作同一 Transport 介面。與 WiFi 幾乎相同(TCP + mDNS),差別在**綁定/廣播到 USB 網路共享的 RNDIS 網卡**;mDNS 為主,探索失敗則 fallback(子網掃描該網段 or 手動輸入 IP);GUI 顯示偵測到的 RNDIS IP 當保底資訊。
2. **PC 端 UI(`gui.py`)**:下拉/選項新增一項,**顯示名稱「USB (USB 網路共享)」**,對應 `usb_rndis.py`;沿用現有 log 區塊。
3. **Android 端**:新增對應的 USB TCP transport(依 §13 用 `UsbTcpTransport.kt`,與 WiFi 檔案隔離);UI 新增「USB (USB 網路共享)」選項。
4. **Android `StreamerService.kt`**:目前 `runEngine()` 裡寫死 `WifiTransport(...)`。**只把「new 哪個 transport」這一處改成依使用者選的模式建立對應 transport**——狀態機(連線/握手/串流/重連/前景服務)其餘邏輯**一行都不要動**。

**約束(§10):**
- 除上述 `StreamerService.kt` 那一處 transport 建立邏輯外,**不得修改任何已通過的檔案**:WiFi transport、協定層(Handshake/TcpClient/AudioFormat)、AudioPlayer、mute_control、stream_engine 核心、RingBuffer。
- 依 §10.4:完成後附「改了/新增哪些檔案」的清單與 diff 範圍。

**驗收方式(請告訴我怎麼測):**
1. **回歸(先測)**:選「WiFi」測一次——確認 WiFi 仍正常出聲、可停可啟,沒被 transport 選擇邏輯改壞。
2. **U1 本身**:手機開 USB 網路共享 → 兩端 UI 選「USB (USB 網路共享)」→ 播影片,確認手機出聲、延遲、斷線恢復。

兩者都過我才算 U1 通過。**完成後再 `git commit`(message 例如「U1 完成並通過回歸+實測」)。** 我實測確認後才進 U2。

---
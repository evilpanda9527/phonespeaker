**Prompt(M1-B / U2:「USB (adb)」實作)**

> 現在做 M1-B 第二個變體 **U2 =「USB (adb)」**。開工前先 `git commit` 存檔現況(含 WiFi 雜音修正)。
>
> **U2 原理與已知事實:**
> - U2 走 **adb forward**:PC 端執行 `adb forward tcp:<PORT> tcp:<PORT>`(或 `adb reverse`,由你判斷哪個對「PC 當 server、手機當 client」最合適),讓手機透過 USB 連到 PC。**不需要 USB 網路共享**(這是跟 U1 的關鍵差別);需要手機開「USB 偵錯」、PC 端有 `adb`。
> - 手機執行期零操作(不像 U1 要撥網路共享開關),延遲預期最低。
> - 架構複用現有 TCP + 協定 + 播放,不重造。
>
> **要做的:**
> 1. **PC 端**:新增獨立檔 `pc/transport/usb_adb.py`,實作同一 Transport 介面。它負責:偵測 adb 是否可用、列出已連線的 adb 裝置、自動執行 `adb forward`/`reverse` 建立 USB 通道,然後走 TCP。若 adb 不存在或沒有裝置,要在 GUI 給清楚提示(引導使用者開 USB 偵錯 / 安裝 adb)。
> 2. **PC 端 UI(`gui.py`)**:下拉新增一項,顯示名稱 **「USB (adb)」**,對應 `usb_adb.py`;沿用現有 log 區塊。
> 3. **Android 端**:U2 手機端連的是 adb 轉發到的本機 port(例如 `127.0.0.1:<PORT>`)。沿用/擴充現有的 USB TCP transport(`UsbTcpTransport.kt`),讓它在 U2 模式下連 localhost;UI 新增「USB (adb)」選項。
> 4. **Android `StreamerService.kt`**:transport 選擇機制已在 U1 建好,U2 只是**在既有的 `createTransport()` 工廠多加一個 case**,不需再動狀態機。
>
> **約束(§10):**
> - 除了在既有工廠/選單「新增 U2 這個選項」之外,**不得修改任何已通過的檔案**:WiFi transport、usb_rndis(U1)、協定層、AudioPlayer、mute_control、剛修好的停止/生命週期邏輯、ring buffer。
> - adb 這次先假設「PC 上已有 adb」即可(之後 §11 單一安裝檔才處理隨附 adb);但請在找不到 adb 時給明確錯誤訊息,不要當掉。
> - 依 §10.4 回報改了/新增哪些檔案。
>
> **驗收方式(請告訴我怎麼測,包含 PC 端要不要先手動裝 adb):**
> 1. **回歸**:先測 WiFi 和 U1(USB 網路共享)仍正常(因為又在 `StreamerService.kt`/`UsbTcpTransport.kt` 動了選擇邏輯)。
> 2. **U2 本身**:手機開 USB 偵錯 → 接 USB 線 → 兩端選「USB (adb)」→ 確認自動建立 adb 通道、連上、播影片出聲、延遲、斷線恢復。
>
> 都過我才算 U2 通過。完成後 `git commit`(message 例如「U2 完成:USB adb」)。
>
> **PoC 提醒**:U2 依賴 adb + USB 偵錯,若你在實作前判斷有任何環境未知數(例如 adb forward 對這個 server/client 方向是否合適、或需要 adb reverse),先簡短說明再動手,不要盲目假設。

---
請進行一次 **A2DP Sink capability investigation**，目的只有確認「這支實際連接的 Android 手機，目前的 Android framework / Bluetooth stack 是否已經具備 A2DP Sink，以及如果具備，是否只是目前未啟用」。

### 嚴格限制

本次任務 **只允許唯讀查詢**。

允許：

* `adb shell dumpsys bluetooth_manager`
* `adb shell dumpsys bluetooth`
* 其他明確為唯讀的 `dumpsys` 指令
* `adb shell pm list packages`
* `adb shell service list`
* `adb shell getprop`
* `adb shell cmd ...` 但只有明確的唯讀查詢
* 讀取 Android framework / Bluetooth stack 的 source、jar、API metadata 或裝置上既有的唯讀資訊
* 檢查 A2DP Sink 相關 class、service、profile、UUID、feature、property 是否存在

禁止：

* 任何寫入檔案、修改專案檔案或修改 Android 裝置檔案
* 任何修改 Android system setting / global setting / secure setting
* `settings put`
* `setprop`
* 啟用或停用任何 Bluetooth profile
* 嘗試啟動、註冊或切換 A2DP Sink
* 修改 Bluetooth configuration
* 安裝 APK
* 修改 APK / framework
* 修改 boot image / system image
* root / su
* remount
* adb root
* 解鎖 bootloader
* flash
* 任何需要 root 權限的操作
* 任何可能改變手機目前狀態的操作
* 不要自行嘗試「修好」或「啟用」A2DP Sink
* 不要寫任何實作程式碼

### 要調查的重點

請只回答以下問題：

1. Android framework / Bluetooth stack 中是否存在 A2DP Sink implementation，例如：

   * `BluetoothA2dpSink`
   * A2DP Sink profile/service
   * A2DP Sink UUID / profile definition
   * 相關 Bluetooth service / package / class

2. 目前這支手機的 Bluetooth framework 是否已載入或註冊 A2DP Sink。

3. 如果 A2DP Sink implementation 存在：

   * 是「存在且已啟用」
   * 還是「存在但目前關閉/未啟用」
   * 還是只能確認 framework class/source 存在，但無法證明裝置 ROM 實際包含可用 implementation

4. 如果完全找不到 A2DP Sink implementation，請明確判定為：
   **「A2DP Sink 完全沒有」**

### 非常重要

不要自行嘗試啟用 A2DP Sink。

不要修改任何東西。

不要提出或執行 workaround。

不要開始設計 Bluetooth PAN、RFCOMM、Opus 或其他替代方案。

本次只做 capability investigation。

### 最終回報格式

請最後只用以下其中一種主要結論：

**A. A2DP Sink 完全沒有**

或

**B. A2DP Sink 有，但目前關閉/未啟用**

或

**C. Framework 有 A2DP Sink，但無法確認本機 ROM 是否具備可啟用的完整 implementation**

然後用簡短條列列出支持這個結論的唯讀證據，包括實際查到的：

* dumpsys 結果
* package/service
* class/framework evidence
* Bluetooth profile evidence
* 相關 system properties

如果證據不足，請明確說「無法確認」，不要猜測。

**本次查詢完成後立即停止，不要進行任何後續操作。**

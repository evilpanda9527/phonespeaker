U1 功能確認通過(走 USB 10.132.200.82、mDNS 直連、有聲音、延遲比 WiFi 好)。先把 U1 的成果 commit 存檔(message 例如「U1 完成:USB 網路共享,mDNS 直連通過」),再處理停止/當機問題——兩件事分開,不要因為改停止問題而動到 U1 或 WiFi 的 transport/串流邏輯。

停止問題同意你的做法:先加逐段計時診斷 log,量出到底是哪個 join、卡多久(sender/capture/device_monitor 各段耗時、外層 _engine_thread.join() 的逾時設定),先讓真實數字出現在 log,再對症修。這次特別要解決的是:(a) 反覆「停止→啟動」會累積殭屍執行緒導致當機;(b) 每次啟動應該先確認舊 engine 執行緒真的死了才建新的。

加診斷這一步先做、先讓我看數字,不要同一輪就把修改一起做完。修改僅限 PC 端停止/生命週期邏輯,不動協定層、Android、AudioPlayer、也不動 U1/WiFi 的 transport 本身。依 §10.4 回報,並在加完診斷後告訴我怎麼測。
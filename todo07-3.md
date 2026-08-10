停止逾時確認根治:log 顯示 _engine_thread.join 從固定 5000ms 降到幾百 ms 內、仍存活=False、不再有 [ERROR] 停止逾時、反覆啟停後存活背景執行緒維持 (0) 不累積。USB (USB 網路共享) 也確認正常。這兩項都通過,請 commit。

診斷 log 可以留著沒關係。剩兩個小項先記著、這次不用動:(1) WiFi 偶爾雜音(疑似 WiFi underrun,USB 沒有);(2) 那個 zeroconf 關閉偶爾慢/WinError 59(Python 3.14)。等我確認要不要處理再說。
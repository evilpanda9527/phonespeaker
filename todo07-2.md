請去確認pc/logs/app.log

診斷成功,真凶明確:所有子執行緒都乾淨結束(pcm-sender/audio-capture/device_monitor 全部「仍存活=False」、毫秒級),唯獨 stream-engine 主迴圈執行緒自己卡住,一路撐到 _engine_thread.join(timeout=5.0s) 逾時、仍存活=True。 前幾輪修子執行緒都沒中,因為病根一直是主迴圈本身。

規律:有傳過音訊時主迴圈靠「送 PCM 失敗→判定斷線」自然跳出、不逾時;剛連上沒傳音訊就停時主迴圈卡住(研判卡在 recvFrame()/接收操作等一個不會來的封包),停止旗標喚不醒它,只能等 5 秒逾時。每次逾時留下一個 stream-engine 殭屍執行緒,累積 + log 裡那個 Python 3.14 zeroconf WinError 59 就是偶發當機的來源。

請針對這個明確目標修:讓 stream-engine 主迴圈在停止時能被立即喚醒、乾淨跳出——核心是讓它卡住的那個阻塞接收操作(recvFrame / socket recv)在 stop() 時被主動中斷(例如停止時 shutdown/close 該 socket 喚醒 recv,並確保迴圈每次阻塞前後都檢查停止旗標),使 _engine_thread 能在 5 秒內正常結束、不再留殭屍執行緒。

要求:(1) 停止時 stream-engine 不再逾時、log 顯示 仍存活=False;(2) 反覆啟停不再累積殭屍執行緒(每次啟動前存活數維持 0、且停止後也應為 0);(3) 不得回歸破音、不動 U1/WiFi 的 transport 與播放邏輯,修改僅限 PC 端停止/生命週期(stream_engine.py 等);(4) 診斷 log 可保留或收乾淨,你決定,但要讓我能從 log 驗證上述。先 commit 現況(含診斷)再改。依 §10.4 回報。

另外那個 Python 3.14 的 zeroconf WinError 59 traceback,先記著、這次不用一起修(除非它跟主迴圈卡住是同源),避免混在一起。
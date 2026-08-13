連線這關全過了——兩端都「串流中」、握手完成、格式一致(48000Hz / 2ch / **pcm_f32le**)。剩最後一哩:有連線、有資料流,但手機不出聲。

這正是我一開始標記的**頭號嫌疑犯,現在確診了**。

格式是 `pcm_f32le`(32-bit float)。Android 端 `AudioPlayer` 把它設成 `ENCODING_PCM_FLOAT`,卻用 `audioTrack.write(byte[], ...)` 這個多載餵資料——**float 軌道用 byte[] 這個 write 版本,Android 不會正確播放**(它會回 `ERROR_INVALID_OPERATION` 或直接不出聲),float 軌道必須改用 `write(ByteBuffer, size, WRITE_BLOCKING)` 或 `write(float[], ...)`。連線、資料、格式全對,就卡在這個播放 API 用錯多載。

這一刻正是把它交給 CLI 的最佳時機——你有了確切症狀,不是猜測。給你可以直接貼給 Claude Code 的指令:

---

**M1-A WiFi 實測發現 bug:手機端無聲。請修正,修正範圍限制在 Android AudioPlayer,不要動已驗證正常的 PC 端與協定層。**

**現象(實測,非推測):**
- PC 與手機成功連線、握手完成,兩端都顯示「串流中」
- 協商格式為 `48000Hz / 2ch / pcm_f32le`
- PC 播放影片時,手機**完全沒有聲音**(有連線、有資料流)

**根因判斷:**
- `AudioPlayer.kt` 對 `pcm_f32le` 使用 `AudioTrack` 的 `ENCODING_PCM_FLOAT`,但透過 `audioTrack.write(byte[], offset, size)` 這個 byte[] 多載寫入資料。
- float 編碼的 AudioTrack 不支援用 byte[] 多載正確播放,需改用 `write(ByteBuffer, sizeInBytes, WRITE_BLOCKING)`(將收到的 little-endian float bytes 包成 ByteBuffer 並設為 `ByteOrder.LITTLE_ENDIAN`),或改用 `write(float[], ...)`。

**要求:**
1. 只修改 `AudioPlayer.kt`(必要時含 `RingBuffer` 的資料型別),**不得修改**已通過的 PC 端、協定層(`Handshake`/`TcpClient`/`AudioFormat`)、`WifiTransport`。
2. 修正 float 播放路徑,讓 `pcm_f32le` 能正確出聲;同時保留對 `pcm_s16le` / `pcm_s32le` 的正確處理(各自用對應的 write 多載或統一走 ByteBuffer)。
3. 依 §10.4:說明改了哪些檔案,並確認未動到已通過的檔案。
4. 修正後告訴我如何重新 build 驗證。

---

修好、你重新 build 裝上手機、確認有聲音之後,再回頭把我 C 段那幾項(延遲感受、PC 靜音、斷線還原、不限開啟順序、裝置熱切換)測完,WiFi 這關才算正式通過。

另外提醒:別忘了剛剛為了測試**停用的虛擬網卡**和**改成私人網路**——虛擬網卡那個(zeroconf 挑錯 IP)也是一個該給 CLI 修的正解項,不然你每次都要手動停。可以等這個無聲 bug 修完、WiFi 驗收過了,再一起交代給 CLI。先把聲音搞出來。
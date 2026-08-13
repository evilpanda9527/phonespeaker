**Prompt(最終批:README + LICENSE + 開源門面)**

> WiFi + U1 + U2 全部完成並通過真機驗收,PC v1.1.4 已 push。現在做最後一批:讓專案準備好正式開源發佈。先出一份簡短計畫給我確認再動手。
>
> **一、README.md(繁中 + 英文雙語):**
> 內容需涵蓋:專案簡介、Features(WiFi/USB網路共享/USB adb 三種傳輸)、各自使用前提與開法、安裝步驟(PC portable zip 解壓即用、Android debug APK 側載)、**必須說明的使用者會遇到的狀況**——(a) PC exe 首次執行可能遇到 Windows 防火牆詢問,需按允許;(b) Android 側載會經過 Google Play Protect「建議掃描應用程式」流程,掃描通過後才能安裝;(c) APK 是 debug 簽章、不同開發機重新編譯後可能需要先解除安裝舊版;(d) USB 網路共享/USB 偵錯的開啟位置。Known Limitations 註明:BT 不支援(手機無可用 A2DP Sink,已實測查證)、USB U3 未做(Windows 11 libwdi 驅動 blocker)。開發方式註明「使用 Claude Code 開發」。
>
> **截圖使用方式:** 我這邊有 `images/` 資料夾裡 25 張實測截圖(pc001-010、an001-015),涵蓋:PC 主介面/三種傳輸提示與連線成功畫面/防火牆詢問;Android 側載全流程(選安裝程式→確認→Google Play掃描→通過→完成)、app 主介面、通知權限、英文介面示範、USB網路共享開關、開發者選項/USB偵錯開關、U1/U2串流成功畫面。**我會告訴你每張圖對應什麼內容,你負責安排進 README 的正確位置、配上雙語說明文字**,不用重新截圖。
>
> **二、LICENSE:** MIT(已確認與 adb 的 Apache-2.0 相容)。
>
> **三、THIRD_PARTY_NOTICES.md:** 確認 adb 授權聲明已在裡面且正確。
>
> **四、隱私/責任聲明(併入 README):** 只擷取 PC 系統輸出音訊、只在區網/USB傳輸給自己的手機、不上傳任何資料到任何伺服器、原始碼公開可自行檢查。
>
> **五、整理開發過程檔案:** 把 `note.txt`、`todo010-*.md`、`todo011-*.md` 等移進 `docs/dev-notes/`(或你建議的合適位置),當作開發歷程保留,不要留在專案根目錄干擾門面;`images/` 保留在原位供 README 引用。
>
> **六、確認 `.gitignore` 最終狀態正確**(不夾帶金鑰、二進位、build 中間產物)。
>
> **約束:** 不動任何已驗收的功能程式碼。先出計畫,列出 README 的章節結構草稿給我確認,再實際填內容。

---
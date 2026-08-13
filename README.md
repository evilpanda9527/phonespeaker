# PhoneSpeaker

🇹🇼 繁體中文 ｜ [English](README.en.md)

把 Android 手機變成 PC 的喇叭：即時擷取 PC 系統輸出音訊，透過 WiFi 或 USB 串流到手機播放。

## Features

- **三種傳輸方式**，依環境自由切換：
  - **WiFi**：免設定，兩端在同一個 WiFi 網路即可，手機自動探索 PC、免手動輸入 IP
  - **USB（USB 網路共享）**：手機接 USB 線、開「USB 網路共享」，走 USB 有線網路，比 WiFi 更穩定、延遲更低
  - **USB（adb）**：手機開「USB 偵錯」即可，不需要另外開 USB 網路共享
- PC 端擷取目前系統輸出裝置的 loopback 音訊，原封不動送到手機（不 resample/remix/轉檔）
- 連線後 PC 自動靜音、只有手機出聲；斷線自動還原、自動回到等待連線狀態
- 手機端前景服務，鎖屏也能持續播放
- PC / Android 雙端介面皆支援繁體中文 + 英文，跟隨系統語言、也可手動切換

## 系統需求

- **PC**：Windows 10 / 11
- **手機**：Android 8.0（API 26）以上
- WiFi 傳輸需兩端在同一個 WiFi 網路；USB 傳輸需一條 USB 線

## 安裝

### PC：下載 portable zip，免安裝

1. 到 [Releases](../../releases) 下載 `PhoneSpeaker-PC-portable-vX.Y.Z.zip`
2. 解壓到任意資料夾——裡面是 `PhoneSpeaker.exe`、`_internal/`（執行期相依檔案）、`adb/`（U2 用，已內附，不用自己裝 Android SDK）：

   ![解壓後的資料夾內容](images/pc001.png)
3. 雙擊 `PhoneSpeaker.exe` 執行

> ⚠️ **首次執行會遇到 Windows 防火牆詢問**，請按「允許存取」——這是 portable 版沒有安裝程式自動放行的正常現象，不允許的話 WiFi/USB 網路共享都連不上：
>
> ![Windows 防火牆詢問](images/pc004.png)
>
> 如果你要用 **USB（adb）**，還會**再跳一次**針對內附 `adb.exe` 的防火牆詢問（跟上面是分開的兩支程式），一樣要允許：
>
> ![adb.exe 的防火牆詢問](images/pc009.png)

<details>
<summary>開發者：想直接跑原始碼(可略過，一般使用者用上面的 portable zip 就好)</summary>

```
cd pc
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

想自己打包 portable zip：`cd pc && build.bat`（會產出
`pc\dist\PhoneSpeaker-PC-portable-vX.Y.Z.zip`）。

</details>

### Android：側載 debug APK

目前發佈的是 **debug 簽章**的 APK（沒有上架 Google Play，需要側載安裝）：

1. 到 [Releases](../../releases) 下載 APK，傳到手機（例如用 USB 傳檔、雲端硬碟、或直接用手機瀏覽器下載）
2. 點檔案安裝，會經過以下畫面（Android 系統對「非商店來源」安裝的標準流程，每支側載的 app 都會遇到）：

   | 1. 選擇開啟工具 | 2. 確認安裝 | 3. Google Play 防護掃描 |
   |---|---|---|
   | ![選擇開啟工具](images/an001.png) | ![確認安裝這個應用程式](images/an002.png) | ![Google Play 建議掃描應用程式](images/an003.png) |

   | 4. 掃描通過 | 5. 安裝完成 |
   |---|---|
   | ![掃描完成，應該沒有問題](images/an004.png) | ![已安裝應用程式](images/an005.png) |

   > ⚠️ 第 3 步「**建議掃描應用程式**」是 Google Play Protect 對側載 app 的標準安全檢查，**選「掃描應用程式」讓它掃完、確認沒問題（第 4 步）才能繼續安裝**——這不是 PhoneSpeaker 專屬的警告，任何非 Play 商店來源的 APK 都會遇到。

3. 第一次開啟 app 時，系統會詢問通知權限（前景服務——鎖屏續播——需要用到）：

   ![允許傳送通知](images/an007.png)

> ⚠️ **這是 debug 簽章的 APK**：如果你之前在同一支手機裝過「不同開發機重新編譯」的版本，Android 可能會因為簽章不一致拒絕直接覆蓋安裝——遇到「應用程式未安裝」之類的錯誤，先解除安裝舊版再裝新版即可。

## 主介面

| PC | 手機 |
|---|---|
| ![PC 主介面](images/pc003.png) | ![手機主介面](images/an008.png) |

兩端介面都一樣簡單：**Transport** 下拉選傳輸方式、**語言**下拉切換介面語言（預設跟隨系統）、按**啟動**開始。

## 使用方式

### WiFi

不需要額外設定，PC、手機連同一個 WiFi 網路，兩邊都按啟動即可自動連線：

| PC 連線成功 | 手機連線成功 |
|---|---|
| ![PC WiFi 連線成功、串流中](images/pc005.png) | ![手機 WiFi 連線成功、串流中](images/an009.png) |

### USB（USB 網路共享）

1. 手機接上 USB 線，到系統設定開啟「行動無線基地台與網路共享」→「USB 網路共享」：

   ![開啟 USB 網路共享](images/an011.png)
2. PC 端 Transport 選「USB（USB 網路共享）」：

   ![U1 使用前提提示](images/pc006.png)
3. 連線成功後，PC 端會顯示偵測到的 USB 網段 IP（手機自動探索失敗時可用來手動確認）：

   ![U1 連線成功、顯示偵測到的 PC IP](images/pc007.png)

### USB（adb）

不需要開 USB 網路共享，只要手機開發者選項裡的「USB 偵錯」：

1. 開啟開發人員選項（連續點手機「軟體資訊」裡的版本號碼幾下）：

   ![連點版本號碼啟用開發者模式](images/an013.png)
2. 到「開發人員選項」開啟「USB 偵錯」：

   ![開啟 USB 偵錯](images/an014.png)
3. PC 端 Transport 選「USB（adb）」：

   ![U2 使用前提提示](images/pc008.png)
4. 手機接上 USB 線後按啟動，第一次會跳 adb.exe 的防火牆詢問（見上方安裝章節），允許後即可連線：

   | PC 連線成功 | 手機連線成功 |
   |---|---|
   | ![PC U2 連線成功、串流中](images/pc010.png) | ![手機 U2 連線成功、串流中](images/an015.png) |

### 語言切換

介面預設跟隨系統語言，也可以手動切換（例如切成英文）：

![英文介面示範：Language/Transport/Not started](images/an010.png)

## 設定（進階）

以下參數在 `pc/config.py`，一般使用不需要調整：

| 參數 | 預設值 | 說明 |
|---|---|---|
| `TCP_LISTEN_PORT` | 58482 | PC 端監聽埠（WiFi/U1/U2 共用） |
| `ADB_COMMAND_TIMEOUT_S` | 5.0 秒 | U2：一般 `adb` 指令逾時 |
| `ADB_COLD_START_TIMEOUT_S` | 12.0 秒 | U2：adb server 完全冷啟動（首次接觸）用的較寬鬆逾時 |
| `RING_BUFFER_TARGET_MS_MIN/MAX` | 20–60ms | 播放端 ring buffer 目標延遲範圍（估算值，非精確 E2E） |
| `CAPTURE_CHUNK_FRAMES` | 480（約 10ms @ 48kHz） | PC 端每次擷取的音訊區塊大小 |

## 隱私與資料

- PhoneSpeaker **只擷取 PC 目前系統輸出裝置的 loopback 音訊**，不錄製麥克風、不存取其他應用程式資料
- 音訊**只透過區域網路（WiFi/USB 網路共享）或 USB 線（adb）傳給你自己的手機**，兩端都在你自己的裝置與網路內
- **不會把任何資料上傳到任何伺服器**——沒有雲端帳號、沒有遙測、沒有分析套件
- 原始碼完全公開（見下方 License），你可以自行檢查程式碼行為是否符合以上說明

## Known Limitations

- **Bluetooth 不支援**：實機查證測試手機沒有可用的 A2DP Sink（真藍牙音訊接收端，需系統權限），技術上無法在不 root 的情況下實作，故排除
- **USB U3（AOA）未實作**：Windows 11 上遇到 libwdi 驅動安裝的相容性問題，詳見
  [`docs/dev-notes/U3_AOA_POC_REPORT.md`](docs/dev-notes/U3_AOA_POC_REPORT.md)
- 目前只支援**單一手機**同時連線
- Android APK 是 **debug 簽章**（未上架 Google Play），見上方安裝章節的側載說明
- PC 端結束整個程式時，`PyAudioWPatch` 在特定環境下偶爾會在行程真正結束的那一刻於原生層 crash（跟串流邏輯無關，串流期間功能正常）；已用 `os._exit()` 繞過，使用者不會看到崩潰視窗

## 開發方式

本專案使用 **[Claude Code](https://claude.com/claude-code)** 開發。

## License

本專案採用 [MIT License](LICENSE)。所使用的第三方套件（PC 端 Python 套件、
Android 端 Gradle 依賴、隨附的 adb）授權條款列在
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

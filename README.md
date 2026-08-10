# PhoneSpeaker

把 Android 手機變成 PC 的喇叭：PC 系統音訊即時串流到手機播放。

> **目前進度：M1-A（WiFi）PoC 已完成，等待驗收。** 完整規格見 [SPEC3.md](SPEC3.md)；
> USB（U1/U2/U3）與 Bluetooth 尚未開始，依 SPEC3.md §10 的規則要 WiFi 驗收通過才會往下做。
> 詳細測試結果、已知限制、待確認事項見 [POC_REPORT.md](POC_REPORT.md)。

## Features

- PC（Windows）擷取目前系統輸出裝置的 loopback 音訊，原封不動（不 resample/remix/轉檔）送到手機
- WiFi 傳輸：PC 當 TCP server，手機用 zeroconf/NsdManager 自動探索、免手動輸入 IP
- 連線握手（FORMAT/READY/FORMAT_UNSUPPORTED），READY 後 PC 自動靜音（可關閉）、斷線自動還原
- PC 端偵測「預設輸出裝置變更」並自動重建擷取（見 POC_REPORT.md 已知限制）
- 手機端前景服務，鎖屏可續播；斷線自動回到等待連線、重新可連

## Requirements

- **PC**：Windows 10/11、Python 3.10+（開發時使用 3.14.2）
- **手機**：Android 8.0（API 26）以上
- 兩端在同一個 WiFi 網路

## Installation

### PC

```
cd pc
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

首次啟動 Windows 防火牆可能會跳出允許提示，請允許（TCP 58482 為監聽埠）。

### Android

M1-A 階段還沒有打包好的 APK/安裝檔（單一安裝檔要等 U2/U3 都完成才會是 all-in-one，見
SPEC3.md §11）。目前請用 Android Studio 開啟 `android/` 這個資料夾自行建置安裝：

1. Android Studio 開啟 `android/`（Gradle sync 會自動處理相依套件與 wrapper）
2. 接上手機（或用模擬器，但模擬器沒有真喇叭意義不大）安裝執行
3. 兩端在同一 WiFi 下，PC 先啟動、手機再開 app（或反過來，不限順序）

## Usage

1. PC：執行 `pc/main.py`，按「啟動」
2. 手機：開啟 PhoneSpeaker app，按「啟動」
3. 手機自動探索到 PC 並連線、完成握手後開始播放 PC 的系統音訊
4. PC 預設會在手機 READY 後自動靜音（GUI 可勾選「連線時 PC 同時出聲」跳過靜音）
5. 關閉任一端 app 或斷線，PC 聲音自動還原、雙方回到可重新連線的狀態

## Configuration

| 位置 | 參數 | 說明 |
|---|---|---|
| `pc/config.py` | `TCP_LISTEN_PORT` | PC 端監聽埠，預設 58482 |
| `pc/config.py` | `RING_BUFFER_TARGET_MS_MIN/MAX` | ring buffer 目標延遲範圍（20–60ms） |
| `pc/config.py` | `AUTO_MUTE_ON_READY_DEFAULT` | 連線後是否自動靜音 PC，GUI 可覆蓋 |
| `pc/config.py` | `CAPTURE_CHUNK_FRAMES` | 每次擷取的 frame 數，影響延遲/CPU 權衡 |

目前沒有需要放進 `.env` 的機密（無 API key/密碼），所以本專案暫無 `.env.example`。

## Known Limitations

以下事項在 [POC_REPORT.md](POC_REPORT.md) 有更詳細的重現步驟與根因分析：

- **PC 端結束整個程式時，PyAudioWPatch 在這個開發環境（Python 3.14.2）下偶爾會在
  行程真正結束的那一刻於原生層 crash**，跟串流邏輯本身無關（串流期間功能正常）。
  已用 `os._exit()` 繞過（見 `pc/gui.py`），但這是繞過而非根治，建議之後換裝置/
  版本組合再驗證一次。
- Android 端程式碼**尚未在真實 Android Studio + 實機環境編譯驗證**（本開發環境沒有
  Android SDK/模擬器），只有仔細 review、對照協定手動核對；PC 端則已大量即時測試
  （見 POC_REPORT.md）。**這是本次交付前最需要你協助驗證的部分**：`android/` 是
  一個完整、可直接用 Android Studio 開啟建置的專案，麻煩你實際 build 一次並接手機測試。
- 目前只支援單一手機同時連線（依 SPEC3.md §15 決策，非本階段要修的問題）
- USB（U1/U2/U3）、Bluetooth 尚未實作（依 SPEC3.md §10 順序，WiFi 驗收通過才會做）
- 尚無單一安裝檔（installer/，等後續階段才會補齊，見 SPEC3.md §11）

## License

僅供自用（依 SPEC3.md §15 決策：自用、驅動不簽章），暫不設定開源授權條款。

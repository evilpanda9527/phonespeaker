"""config.py — 使用者可調整的執行期設定。

依 CLAUDE.md 慣例：機密放 .env，使用者可調參數放這裡（未來可外部化成 config.json）。
M1-A 範圍：只有 WiFi transport 相關設定；U1(USB 網路共享) 通過後加了對應
設定；U2(USB adb) 通過後比照辦理，U3/BT 留待對應階段再加，不在此檔預先塞
入尚未實作的選項（避免誤導使用者以為已支援）。
"""

from __future__ import annotations

# --- WiFi transport (§8.1) ---
TCP_LISTEN_HOST: str = "0.0.0.0"
TCP_LISTEN_PORT: int = 58482

ZEROCONF_SERVICE_TYPE: str = "_phonespeaker._tcp.local."
ZEROCONF_SERVICE_NAME: str = "PhoneSpeaker._phonespeaker._tcp.local."

# --- U2: USB (adb) transport (§8.2 U2) ---
# 先假設 PC 上已經有 adb 且在 PATH 裡（§11 單一安裝檔隨附 adb 留待之後處理）。
ADB_EXECUTABLE: str = "adb"
# `adb reverse` 只把「手機端 127.0.0.1:PORT」轉發到這裡；PC 端只需要監聽
# loopback 就夠了，不像 WiFi/U1 需要監聽 0.0.0.0——U2 走的是 USB 傳輸線，
# 本來就不該（也不需要）暴露在區網上。PORT 沿用 TCP_LISTEN_PORT，跟
# `adb reverse tcp:<PORT> tcp:<PORT>` 兩端用同一個號碼對稱。
ADB_HOST: str = "127.0.0.1"
ADB_COMMAND_TIMEOUT_S: float = 5.0

# adb server（adb 常駐背景 daemon，就是工作管理員裡那個 `adb.exe`）預設監聽
# 的本機 TCP port。connect() 前用它探測「這次連線前 adb server 是不是已經
# 在跑」，藉此判斷 disconnect() 收尾時能不能安全地 `adb kill-server`——只清
# 理「本程式為了 U2 啟動的」adb server，不誤殺使用者自己開著的（例如
# Android Studio）（見 todo010-4，usb_adb.py 的取捨說明）。使用者若透過
# `ANDROID_ADB_SERVER_PORT` 環境變數自訂了 port，usb_adb.py 會改讀那個值，
# 這裡的數字只是 adb 官方預設值。
ADB_SERVER_HOST: str = "127.0.0.1"
ADB_SERVER_PORT: int = 5037
ADB_SERVER_PROBE_TIMEOUT_S: float = 0.3

# --- Ring buffer / 延遲 target（§9，PC 端僅用於顯示 estimated 延遲）---
RING_BUFFER_TARGET_MS_MIN: int = 20
RING_BUFFER_TARGET_MS_MAX: int = 60

# --- 音訊擷取 ---
# WASAPI loopback 讀取區塊大小（frames）。過大增加延遲，過小增加 CPU/underrun 風險。
CAPTURE_CHUNK_FRAMES: int = 480  # 約 10ms @ 48kHz

# --- 靜音行為 ---
# 連線且 READY 後一律自動靜音 PC 預設輸出、只有手機出聲（§16 第 2 項：
# 原本 GUI 上「連線時 PC 同時出聲」開關實測無作用，已移除，此行為固定不可調）。
# 由 core/stream_engine.py 的 StreamEngine(auto_mute=True 預設值) 套用。

# --- Logging（依 CLAUDE.md 標準）---
LOG_DIR: str = "logs"
LOG_FILE: str = "app.log"
LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

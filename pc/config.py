"""config.py — 使用者可調整的執行期設定。

依 CLAUDE.md 慣例：機密放 .env，使用者可調參數放這裡（未來可外部化成 config.json）。
M1-A 範圍：只有 WiFi transport 相關設定；USB/BT 設定留待對應階段再加，
不在此檔預先塞入尚未實作的選項（避免誤導使用者以為已支援）。
"""

from __future__ import annotations

# --- WiFi transport (§8.1) ---
TCP_LISTEN_HOST: str = "0.0.0.0"
TCP_LISTEN_PORT: int = 58482

ZEROCONF_SERVICE_TYPE: str = "_phonespeaker._tcp.local."
ZEROCONF_SERVICE_NAME: str = "PhoneSpeaker._phonespeaker._tcp.local."

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

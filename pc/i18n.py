"""i18n.py — PC 端介面雙語資源（zh-TW / en，todo010）。

只負責「文字」，不涉及任何連線/協定/播放邏輯（§10 約束：本批只動 UI 文字
層）。字典式資源＋一個 `t(key, **kwargs)` 查表函式，日後要加語言只需要在
`_STRINGS` 多加一個語言代碼、把 keys 對應的譯文填齊即可，不需要動呼叫端
（gui.py）的邏輯。

語言選擇規則（見 SPEC3 §18）：
1. 預設跟隨系統語言：系統為中文（不分繁簡）→ zh-TW，其餘 → en。
2. 使用者可在 GUI 手動切換覆寫；手動選擇（含「自動」本身）存進
   `pc/config.json`（已在 .gitignore，符合 CLAUDE.md「config.json 放使用者
   可調設定」慣例），下次啟動沿用。
"""

from __future__ import annotations

import ctypes
import json
import locale
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 語言偏好設定（"auto" / "zh-TW" / "en"）存放位置；跟 pc/config.py（開發者
# 預設值）不同檔——這個是「使用者可調、會被程式寫回」的執行期設定。
_SETTINGS_FILE = Path(__file__).resolve().parent / "config.json"

# 實際可用的介面語言（"auto" 不是介面語言本身，是一種「偏好」，解析後一定
# 會落到下面兩者之一）。
SUPPORTED_LANGUAGES = ("zh-TW", "en")
_FALLBACK_LANGUAGE = "en"

# 語言偏好（含 "auto"）；手動切換下拉選單顯示用。
LANGUAGE_PREFERENCES = ("auto", "zh-TW", "en")

_STRINGS: dict[str, dict[str, str]] = {
    "zh-TW": {
        "app.window_title": "PhoneSpeaker（電腦端）",
        "label.transport": "傳輸方式：",
        "label.status": "狀態：",
        "label.format": "目前音訊格式：",
        "label.log": "Log：",
        "label.language": "語言：",
        "btn.start": "啟動",
        "btn.stop": "停止",
        "state.idle": "尚未啟動",
        "state.waiting": "等待手機連線…",
        "state.handshake": "握手中…",
        "state.streaming": "串流中 ✅",
        "state.stopped": "已停止",
        "latency.label": "（estimated latency target: {lo}–{hi}ms，network + buffer，非精確 E2E）",
        "format.placeholder": "—",
        "usb_fallback.label": (
            "USB 網段偵測到的 PC IP：{ip}"
            "（手機自動探索失敗時，可用這個位址手動確認在同一個 USB 網段）"
        ),
        "transport.wifi.name": "WiFi",
        "transport.usb_rndis.name": "USB（USB 網路共享）",
        "transport.usb_adb.name": "USB（adb）",
        "transport.wifi.hint": "PC 與手機需連線至同一個 WiFi 網路。",
        "transport.usb_rndis.hint": "請先在手機開啟「USB 網路共享 / USB tethering」。",
        "transport.usb_adb.hint": "請先在手機開啟「USB 偵錯」（開發者選項）。",
        "log.started": "已啟動 {transport} transport",
        "log.stopped": "已停止",
        "log.error_prefix": "[錯誤] {msg}",
        "lang.auto": "自動（跟隨系統）",
    },
    "en": {
        "app.window_title": "PhoneSpeaker (PC)",
        "label.transport": "Transport:",
        "label.status": "Status:",
        "label.format": "Current Audio Format:",
        "label.log": "Log:",
        "label.language": "Language:",
        "btn.start": "Start",
        "btn.stop": "Stop",
        "state.idle": "Not started",
        "state.waiting": "Waiting for phone to connect…",
        "state.handshake": "Handshaking…",
        "state.streaming": "Streaming ✅",
        "state.stopped": "Stopped",
        "latency.label": "(estimated latency target: {lo}–{hi}ms, network + buffer, not precise E2E)",
        "format.placeholder": "—",
        "usb_fallback.label": (
            "PC IP detected on the USB subnet: {ip}"
            " (if auto-discovery fails on the phone, use this address to"
            " manually confirm you're on the same USB subnet)"
        ),
        "transport.wifi.name": "WiFi",
        "transport.usb_rndis.name": "USB (Tethering)",
        "transport.usb_adb.name": "USB (adb)",
        "transport.wifi.hint": "PC and phone must be connected to the same Wi-Fi network.",
        "transport.usb_rndis.hint": "First enable “USB tethering” on your phone.",
        "transport.usb_adb.hint": "First enable “USB debugging” in Developer options on your phone.",
        "log.started": "Started {transport} transport",
        "log.stopped": "Stopped",
        "log.error_prefix": "[Error] {msg}",
        "lang.auto": "Auto (System)",
    },
}

# 手動切換下拉選單裡「繁體中文」「English」這兩個選項本身用語言自己的名稱
# 顯示（跟目前介面語言無關，讓使用者永遠看得懂怎麼切回自己要的語言）；
# 只有「自動」需要跟著目前介面語言變化（見 lang.auto）。
_LANGUAGE_SELF_NAME = {"zh-TW": "繁體中文", "en": "English"}

_current_language: str = _FALLBACK_LANGUAGE
_current_preference: str = "auto"


def _detect_system_language() -> str:
    """偵測系統語言；中文（不分繁簡）→ zh-TW，其餘一律 en。"""
    try:
        if hasattr(ctypes, "windll"):
            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            lang_name = locale.windows_locale.get(langid, "")
            if lang_name:
                return "zh-TW" if lang_name.startswith("zh") else "en"
    except (AttributeError, OSError) as e:
        logger.warning("偵測 Windows UI 語言失敗，改用 locale 模組: %s", e)
    try:
        loc = locale.getlocale()[0] or ""
        if loc.lower().startswith("zh"):
            return "zh-TW"
    except (ValueError, TypeError) as e:
        logger.warning("偵測系統語言失敗，改用預設語言 en: %s", e)
    return _FALLBACK_LANGUAGE


def _read_settings() -> dict:
    if not _SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("讀取 %s 失敗，改用預設設定: %s", _SETTINGS_FILE, e)
        return {}


def _load_saved_preference() -> Optional[str]:
    pref = _read_settings().get("language")
    return pref if pref in LANGUAGE_PREFERENCES else None


def _save_preference(pref: str) -> None:
    data = _read_settings()
    data["language"] = pref
    try:
        _SETTINGS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        logger.warning("寫入語言設定失敗（下次啟動將無法記住手動選擇）: %s", e)


def init_language() -> str:
    """啟動時呼叫一次：讀取已存的偏好，沒有的話偵測系統語言。回傳解析後的介面語言。"""
    global _current_language, _current_preference
    _current_preference = _load_saved_preference() or "auto"
    _current_language = (
        _detect_system_language() if _current_preference == "auto" else _current_preference
    )
    return _current_language


def get_language() -> str:
    """回傳目前實際使用的介面語言（一定是 zh-TW 或 en，不會是 "auto"）。"""
    return _current_language


def get_preference() -> str:
    """回傳目前的語言偏好設定（"auto" / "zh-TW" / "en"），給下拉選單預選用。"""
    return _current_preference


def set_preference(pref: str) -> str:
    """套用並記住使用者手動選的語言偏好；回傳解析後的介面語言。"""
    global _current_language, _current_preference
    if pref not in LANGUAGE_PREFERENCES:
        raise ValueError(f"不支援的語言偏好: {pref}")
    _current_preference = pref
    _current_language = _detect_system_language() if pref == "auto" else pref
    _save_preference(pref)
    return _current_language


def t(key: str, **kwargs) -> str:
    """查表取翻譯字串；找不到 key 時退回英文，兩邊都找不到就回傳 key 本身（方便發現漏翻）。"""
    table = _STRINGS.get(_current_language, _STRINGS[_FALLBACK_LANGUAGE])
    template = table.get(key) or _STRINGS[_FALLBACK_LANGUAGE].get(key) or key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError) as e:
        logger.warning("翻譯字串格式化失敗 key=%s: %s", key, e)
        return template


def language_preference_label(pref: str) -> str:
    """語言選單裡每個選項要顯示的文字：'自動' 跟著目前介面語言變、'zh-TW'/'en' 用自身語言名稱。"""
    if pref == "auto":
        return t("lang.auto")
    return _LANGUAGE_SELF_NAME.get(pref, pref)


# 模組載入時就先解析一次，讓其他模組（gui.py）import 完就能直接呼叫
# t(...)，不必額外記得呼叫 init_language()；GUI 若要提供手動切換，仍可
# 再呼叫 set_preference() 覆寫。
init_language()

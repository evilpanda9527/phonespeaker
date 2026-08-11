"""paths.py — 打包後（PyInstaller frozen）vs. 開發模式的路徑解析（todo010-1）。

全新檔案，不改動任何既有檔案的邏輯；`main.py`／`i18n.py` 之後會改成呼叫
這裡的 `writable_data_dir()`（見 todo010-1 計畫），行為對齊如下：

- 開發模式（`python main.py` 直接跑）：`writable_data_dir()` 回傳 `pc/`
  本身（`_PC_DIR`），跟目前（改動前）的行為完全一樣，不影響你現在的
  開發習慣。
- 打包後（PyInstaller onedir frozen exe）：`app_dir()` 回傳 exe 所在目錄
  （通常在 `Program Files` 底下，一般使用者權限下不可寫）；
  `writable_data_dir()` 改回傳 `%LOCALAPPDATA%/PhoneSpeaker`（自動建立），
  確保 log／語言偏好一定寫得進去。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# pc/ 目錄本身；跟 main.py 現有的 `_PC_DIR = Path(__file__).resolve().parent`
# 算法一致（這裡是獨立算一次，不 import main.py，避免循環 import）。
_PC_DIR = Path(__file__).resolve().parent

_APP_DATA_DIR_NAME = "PhoneSpeaker"


def is_frozen() -> bool:
    """是否正在跑 PyInstaller 打包後的 frozen exe（而非 `python main.py`）。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """程式本體所在目錄：frozen 時是 exe 所在目錄，開發模式是 `pc/`。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _PC_DIR


def writable_data_dir() -> Path:
    """log／使用者設定（config.json）該寫去哪裡。

    frozen 模式下 `app_dir()` 可能在 `Program Files`（一般使用者不可寫），
    改用 `%LOCALAPPDATA%/PhoneSpeaker`；開發模式維持寫在 `pc/` 底下
    （跟改動前的行為一致）。目錄不存在時自動建立。
    """
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA")
        target = Path(base) / _APP_DATA_DIR_NAME if base else app_dir()
    else:
        target = app_dir()
    target.mkdir(parents=True, exist_ok=True)
    return target

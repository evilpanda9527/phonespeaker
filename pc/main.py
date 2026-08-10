"""main.py — PC 端進入點。

用法： 在 pc/ 目錄下執行 `python main.py`（或用 .venv 內的 python）。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# 讓 core/ transport/ 可以用絕對 import（無論從哪個 cwd 執行這個檔案）。
_PC_DIR = Path(__file__).resolve().parent
if str(_PC_DIR) not in sys.path:
    sys.path.insert(0, str(_PC_DIR))

import config  # noqa: E402  (需先調整 sys.path 才能 import)


def _setup_logging() -> None:
    log_dir = _PC_DIR / config.LOG_DIR
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"無法建立 log 目錄 {log_dir}: {e}", file=sys.stderr)
        log_dir = None

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_dir is not None:
        try:
            handlers.append(
                logging.FileHandler(log_dir / config.LOG_FILE, encoding="utf-8")
            )
        except OSError as e:
            print(f"無法開啟 log 檔案: {e}", file=sys.stderr)

    logging.basicConfig(
        level=logging.INFO,
        format=config.LOG_FORMAT,
        handlers=handlers,
    )


def main() -> int:
    if os.name != "nt":
        logging.getLogger(__name__).warning(
            "此專案設計為 Windows 專用（WASAPI/pycaw），在非 Windows 系統上可能無法運作"
        )

    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("PhoneSpeaker PC 啟動（M1-A WiFi PoC）")

    try:
        import gui
    except ImportError as e:
        logger.error(
            "缺少必要套件，請先執行 `pip install -r requirements.txt`: %s", e
        )
        return 1

    gui.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

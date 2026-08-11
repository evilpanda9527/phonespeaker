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

import comtypes.client  # noqa: E402  (需先調整 sys.path 才能 import)

# 打包後（PyInstaller frozen exe）comtypes 預設把 COM 介面產生的 wrapper
# 程式碼快取寫進 site-packages/comtypes/gen/，那個路徑打包後通常不可寫，
# 是常見的 frozen + comtypes 地雷（todo010-1）。改成 None：每次執行期即時
# 產生、不落地快取，避開寫入權限問題；開發模式下同樣適用、無副作用（只是
# 不再快取，多花極短的產生時間）。必須在任何會觸發 COM codegen 的 import
# （core.mute_control／core.device_monitor 用到的 pycaw）之前設定好。
comtypes.client.gen_dir = None

import config  # noqa: E402  (需先調整 sys.path 才能 import)
import paths  # noqa: E402


def _setup_logging() -> None:
    log_dir = paths.writable_data_dir() / config.LOG_DIR
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

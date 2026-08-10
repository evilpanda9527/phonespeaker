"""device_monitor.py — 偵測 Windows 預設音訊輸出裝置變更（§7）。

用一顆背景執行緒監聽 IMMNotificationClient 的 OnDefaultDeviceChanged，
變更時呼叫上層（stream_engine）給的 callback，讓它去停舊 loopback、
重建 capture、必要時重送 FORMAT。

實作依據：實際跑過 `pycaw.callbacks.MMNotificationClient` +
`AudioUtilities.GetDeviceEnumerator().RegisterEndpointNotificationCallback()`
確認可用（見開發時的 smoke test），不是憑印象猜 API。

用 MTA（Multi-Threaded Apartment）而非 STA：MTA 的 COM callback 由 COM
內部的 RPC worker thread 直接呼叫，不需要這顆執行緒自己跑 message pump
（STA 若不跑 pump 迴圈，callback 可能收不到或被延遲）。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import comtypes
from pycaw.callbacks import MMNotificationClient
from pycaw.pycaw import AudioUtilities

logger = logging.getLogger(__name__)

# comtypes COM 呼叫失敗拋 COMError（不是 OSError 子類別），兩種都要接。
_ComErrors = (OSError, comtypes.COMError)

# 只關心「輸出（render）裝置」且角色是使用者實際會聽到聲音的 eConsole。
# WASAPI shared-mode loopback 對應的正是這個角色的預設輸出裝置。
_WATCHED_FLOW = "eRender"
_WATCHED_ROLE = "eConsole"

OnDeviceChanged = Callable[[], None]


class DeviceMonitorError(Exception):
    pass


class _Client(MMNotificationClient):
    def __init__(self, on_changed: OnDeviceChanged):
        super().__init__()
        self._on_changed = on_changed

    def on_default_device_changed(
        self, flow, flow_id, role, role_id, default_device_id
    ) -> None:
        if flow != _WATCHED_FLOW or role != _WATCHED_ROLE:
            return
        logger.info("偵測到預設輸出裝置變更: %s", default_device_id)
        try:
            self._on_changed()
        except Exception as e:  # noqa: BLE001 — callback 出錯不可讓監聽執行緒死掉
            logger.exception("device change callback 發生例外: %s", e)


class DeviceMonitor:
    """啟動/停止背景執行緒監聽預設輸出裝置變更。"""

    def __init__(self, on_changed: OnDeviceChanged):
        self._on_changed = on_changed
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._start_error: Optional[BaseException] = None

    def start(self) -> None:
        if self._thread is not None:
            raise DeviceMonitorError("DeviceMonitor 已在執行中")
        self._stop_event.clear()
        self._ready_event.clear()
        self._start_error = None
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="device-monitor"
        )
        self._thread.start()
        got_ready = self._ready_event.wait(timeout=5.0)
        if not got_ready:
            self._thread = None
            raise DeviceMonitorError("device_monitor 啟動逾時")
        if self._start_error is not None:
            error = self._start_error
            self._thread = None
            raise DeviceMonitorError(f"device_monitor 啟動失敗: {error}") from error

    def _run(self) -> None:
        enumerator = None
        client = None
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            client = _Client(self._on_changed)
            enumerator = AudioUtilities.GetDeviceEnumerator()
            enumerator.RegisterEndpointNotificationCallback(client)
            logger.info("device_monitor 已啟動，監聽預設輸出裝置變更")
        except _ComErrors as e:
            self._start_error = e
            return
        finally:
            self._ready_event.set()

        # MTA 不需要 pump message，用 Event.wait 讓這顆執行緒活著直到被要求停止。
        self._stop_event.wait()

        try:
            enumerator.UnregisterEndpointNotificationCallback(client)
        except _ComErrors as e:
            logger.debug("取消監聽 callback 時發生非致命錯誤: %s", e)
        finally:
            comtypes.CoUninitialize()

    def stop(self) -> None:
        # 診斷用（見 todo07-1）：只加計時/存活 log，不改行為/邏輯——這裡原本
        # 就沒有 is_alive() 判斷、逾時後也直接把 self._thread 設回 None，
        # 這次先不動這段行為，只讓「逾時後其實還活著」這件事在 log 裡看得到
        # （這可能正是 (a) 殭屍執行緒累積的來源之一，下一輪再對症修）。
        if self._thread is None:
            return
        self._stop_event.set()
        t0 = time.monotonic()
        self._thread.join(timeout=3.0)
        join_elapsed = time.monotonic() - t0
        logger.info(
            "[停止診斷] device_monitor: thread.join(timeout=3.0s) 耗時 %.0fms，逾時後仍存活=%s",
            join_elapsed * 1000,
            self._thread.is_alive(),
        )
        self._thread = None

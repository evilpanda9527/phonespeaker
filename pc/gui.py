"""gui.py — customtkinter GUI（§13）。

M1-A 範圍：只有 WiFi 這個 transport 選項。之後 U1/U2/U3/BT 驗收通過後，
只需要在 TRANSPORT_FACTORIES 這個字典加一行，不需要動這個檔案其他邏輯
（§10.3 檔案隔離原則的精神也適用在「新增選項」這件事上）。
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Callable, Optional

import customtkinter as ctk

import config
from core.stream_engine import EngineCallbacks, EngineState, StreamEngine
from transport.base import Transport
from transport.usb_rndis import UsbRndisTransport
from transport.wifi import WifiTransport

logger = logging.getLogger(__name__)

# transport 顯示名稱 → 建立函式。U1(USB 網路共享) 通過後在這裡加一行；
# U2/U3/BT 通過驗收後比照辦理，不需要動這個檔案其他邏輯（§10.3 檔案隔離
# 原則的精神也適用在「新增選項」這件事上）。
TRANSPORT_FACTORIES: dict[str, Callable[[], Transport]] = {
    "WiFi": lambda: WifiTransport(),
    "USB (USB 網路共享)": lambda: UsbRndisTransport(),
}

_STATE_LABELS = {
    EngineState.IDLE: "尚未啟動",
    EngineState.WAITING: "等待手機連線…",
    EngineState.HANDSHAKE: "握手中…",
    EngineState.STREAMING: "串流中 ✅",
    EngineState.STOPPED: "已停止",
}


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PhoneSpeaker (PC) — M1-A WiFi PoC")
        self.geometry("620x520")
        self.minsize(520, 440)

        self._engine: Optional[StreamEngine] = None
        self._active_transport: Optional[Transport] = None
        # engine 背景執行緒 → 主執行緒的 callback 一律先進這個 queue，
        # 由主執行緒自己的輪詢迴圈取出執行（見 _threadsafe / _drain_callback_queue，
        # 修正緣由見 todo07-2）。
        self._callback_queue: "queue.Queue[tuple[Callable, tuple, dict]]" = queue.Queue()
        self._running = False

        self._build_ui()
        self.after(100, self._drain_callback_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    # UI 建構
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=12, pady=(12, 6))

        ctk.CTkLabel(top, text="Transport：").pack(side="left", padx=(4, 4))
        self.transport_var = ctk.StringVar(value=next(iter(TRANSPORT_FACTORIES)))
        self.transport_menu = ctk.CTkOptionMenu(
            top, values=list(TRANSPORT_FACTORIES), variable=self.transport_var
        )
        self.transport_menu.pack(side="left", padx=(0, 16))

        self.start_stop_btn = ctk.CTkButton(
            top, text="啟動", command=self._on_toggle_start_stop, width=100
        )
        self.start_stop_btn.pack(side="left")

        status_frame = ctk.CTkFrame(self)
        status_frame.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(status_frame, text="狀態：").pack(side="left", padx=(4, 4))
        self.status_label = ctk.CTkLabel(
            status_frame, text=_STATE_LABELS[EngineState.IDLE]
        )
        self.status_label.pack(side="left")

        latency_lo = config.RING_BUFFER_TARGET_MS_MIN
        latency_hi = config.RING_BUFFER_TARGET_MS_MAX
        self.latency_label = ctk.CTkLabel(
            status_frame,
            text=f"（estimated latency target: {latency_lo}–{latency_hi}ms，network + buffer，非精確 E2E）",
            text_color=("gray40", "gray60"),
        )
        self.latency_label.pack(side="left", padx=(12, 4))

        format_frame = ctk.CTkFrame(self)
        format_frame.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(format_frame, text="目前音訊格式：").pack(side="left", padx=(4, 4))
        self.format_label = ctk.CTkLabel(format_frame, text="—")
        self.format_label.pack(side="left")

        # U1(USB 網路共享) 保底資訊：mDNS 探索失敗/不穩時，顯示 PC 端偵測到
        # 的 RNDIS IP 供使用者手動確認。只有 transport 有 `detected_ip`
        # 屬性（目前只有 UsbRndisTransport）時才會顯示文字，WiFi 模式下
        # 這行永遠是空的，不影響既有畫面（見 _on_state_changed）。
        usb_fallback_frame = ctk.CTkFrame(self)
        usb_fallback_frame.pack(fill="x", padx=12, pady=(0, 6))
        self.usb_fallback_label = ctk.CTkLabel(
            usb_fallback_frame, text="", text_color=("gray40", "gray60")
        )
        self.usb_fallback_label.pack(side="left", padx=(4, 4))

        ctk.CTkLabel(self, text="Log：").pack(anchor="w", padx=12)
        self.log_box = ctk.CTkTextbox(self, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # 事件處理
    # ------------------------------------------------------------------ #

    def _on_toggle_start_stop(self) -> None:
        if self._running:
            self._stop_engine()
        else:
            self._start_engine()

    def _start_engine(self) -> None:
        # 診斷用（見 todo07-1）：只加 log，不改行為/邏輯。啟動新 engine 前先
        # 印出目前所有背景執行緒，用來觀察「反覆停止→啟動」是否會累積上一輪
        # 沒有真正結束的殭屍執行緒（例如仍看到多個同名 "audio-capture"、
        # "device-monitor"、"pcm-sender"、"stream-engine"）。
        self._log_alive_threads("_start_engine() 啟動前")

        transport_name = self.transport_var.get()
        factory = TRANSPORT_FACTORIES[transport_name]
        transport = factory()
        self._active_transport = transport

        callbacks = EngineCallbacks(
            on_state_changed=self._threadsafe(self._on_state_changed),
            on_log=self._threadsafe(self._append_log),
            on_error=self._threadsafe(lambda msg: self._append_log(f"[錯誤] {msg}")),
        )
        # 連線時 PC 一律靜音、只有手機出聲（原本可切換「不自動靜音」的開關
        # 實測無作用，已移除；StreamEngine 的 auto_mute 預設就是 True）。
        self._engine = StreamEngine(transport, callbacks=callbacks)
        self._engine.start()
        self._running = True
        self.start_stop_btn.configure(text="停止")
        self.transport_menu.configure(state="disabled")
        self._append_log(f"已啟動 {transport_name} transport")

    def _stop_engine(self) -> None:
        # 診斷用（見 todo07-1）：量出「使用者按停止」到「engine.stop() 真的
        # 返回」的呼叫端總耗時，並在前後都印出背景執行緒清單，方便跟
        # stream_engine 內部各段的計時 log 對照。只加 log，不改行為/邏輯。
        if self._engine is not None:
            t0 = time.monotonic()
            self._engine.stop()
            elapsed = time.monotonic() - t0
            msg = f"[停止診斷] GUI _stop_engine(): engine.stop() 呼叫端總耗時 {elapsed * 1000:.0f}ms"
            logger.info(msg)
            self._append_log(msg)
            self._engine = None
        self._active_transport = None
        self._running = False
        self.start_stop_btn.configure(text="啟動")
        self.transport_menu.configure(state="normal")
        self.status_label.configure(text=_STATE_LABELS[EngineState.IDLE])
        self.format_label.configure(text="—")
        self.usb_fallback_label.configure(text="")
        self._append_log("已停止")
        self._log_alive_threads("_stop_engine() 結束後")

    def _on_state_changed(self, state: EngineState) -> None:
        self.status_label.configure(text=_STATE_LABELS.get(state, str(state)))
        if self._engine is not None and self._engine.current_format is not None:
            self.format_label.configure(text=str(self._engine.current_format))
        # `detected_ip` 只有 UsbRndisTransport 才有；WiFi 模式下這裡永遠是
        # None，標籤維持空白，不影響既有畫面。
        detected_ip = getattr(self._active_transport, "detected_ip", None)
        self.usb_fallback_label.configure(
            text=(
                f"USB 網段偵測到的 PC IP：{detected_ip}"
                "（手機自動探索失敗時，可用這個位址手動確認在同一個 USB 網段）"
                if detected_ip
                else ""
            )
        )
        if state == EngineState.STOPPED:
            self._running = False
            self.start_stop_btn.configure(text="啟動")
            self.transport_menu.configure(state="normal")

    def _log_alive_threads(self, label: str) -> None:
        """診斷用（見 todo07-1）：印出目前所有非 main 的背景執行緒名稱。

        跨「啟動→停止→再啟動」多輪比對這份清單的數量/名稱，就能看出
        (a) 是否有上一輪的執行緒沒真的結束就被留下來（殭屍執行緒累積）。
        只讀 threading.enumerate()、不影響任何執行緒的生命週期。
        """
        alive_names = sorted(
            t.name for t in threading.enumerate() if t is not threading.main_thread()
        )
        logger.info(
            "[停止診斷] %s：目前存活背景執行緒(%d): %s",
            label,
            len(alive_names),
            alive_names,
        )

    def _on_close(self) -> None:
        if self._running:
            self._stop_engine()
        self.destroy()
        # 已知問題（見 PoC 報告）：PyAudioWPatch 在這個環境下，即使整段錄音
        # 流程完全正常，Python 直譯器正常收尾（GC/atexit）時仍可能在原生
        # 層 segfault——跟 comtypes/COM、執行緒配置都無關，且只發生在「整個
        # process 要結束」的那一刻，不影響執行期間的 reconnect / 裝置熱切換。
        # 對策：我們自己該做的清理（還原靜音、關 socket、寫 log）都已在
        # _stop_engine() 完成，這裡改用 os._exit() 跳過 Python 正常收尾，
        # 避開那個原生層的 crash-on-exit。
        logging.shutdown()
        os._exit(0)

    # ------------------------------------------------------------------ #
    # 執行緒安全的 log/callback 處理
    # ------------------------------------------------------------------ #

    def _threadsafe(self, fn: Callable[..., None]) -> Callable[..., None]:
        """把 engine 背景執行緒的 callback 轉成主執行緒（Tk）安全的呼叫。

        根因（見 todo07-2 診斷 log）：舊實作在呼叫端（engine 背景執行緒）
        直接呼叫 `self.after(0, ...)`。tkinter 從非主執行緒呼叫任何 Tk
        方法（包含 after()）都會被底層 marshal 回主執行緒、並「同步等待」
        主執行緒的 Tcl event loop 處理完才返回呼叫端——這不是單純排程，是
        會阻塞呼叫端的跨執行緒呼叫。

        而使用者按停止時，主執行緒正卡在 `engine.stop()` 內的
        `_engine_thread.join(timeout=5.0)`（見 stream_engine.py），沒有在
        跑 Tk event loop；這時 engine 執行緒剛好在 `_run()` 收尾呼叫
        `_set_state(STOPPED)` → on_state_changed → 這裡的 `self.after(0,
        ...)`，因此卡住等主執行緒把它處理掉——但主執行緒又在 join() 裡等
        engine 執行緒結束，兩邊互卡，直到 join() 5 秒逾時、主執行緒才脫身
        繼續跑、engine 執行緒的 after() 呼叫才跟著返回、_run() 才真正結束。
        這就是診斷 log 顯示「每次停止都精準卡滿 ~5000ms、逾時判定仍存活，
        但其實幾乎同時就結束了」、以及殭屍 stream-engine 執行緒累積的真因。

        修法：呼叫端只做純 Python 的 `queue.put()`——不呼叫任何 Tk API，
        GIL 保護下必為 O(1) 非阻塞操作，不會卡呼叫端。真正的 UI 更新留給
        主執行緒自己的 `self.after(100, self._drain_callback_queue)` 輪詢
        迴圈自己排程、自己執行，不會再有跨執行緒呼叫 Tk 方法的情況。
        """

        def wrapper(*args, **kwargs) -> None:
            self._callback_queue.put((fn, args, kwargs))

        return wrapper

    def _append_log(self, msg: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _drain_callback_queue(self) -> None:
        """主執行緒輪詢迴圈：取出 engine 背景執行緒排進來的 callback 並執行。

        只有這裡（主執行緒自己的 after() 迴圈裡）才真正呼叫 Tk 方法，
        engine 執行緒那邊只管 put()，兩者之間不會有跨執行緒 Tk 呼叫。
        """
        while True:
            try:
                fn, args, kwargs = self._callback_queue.get_nowait()
            except queue.Empty:
                break
            fn(*args, **kwargs)
        self.after(100, self._drain_callback_queue)


def run() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()

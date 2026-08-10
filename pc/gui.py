"""gui.py — customtkinter GUI（§13）。

M1-A 範圍：只有 WiFi 這個 transport 選項。之後 U1/U2/U3/BT 驗收通過後，
只需要在 TRANSPORT_FACTORIES 這個字典加一行，不需要動這個檔案其他邏輯
（§10.3 檔案隔離原則的精神也適用在「新增選項」這件事上）。
"""

from __future__ import annotations

import logging
import os
import queue
from typing import Callable, Optional

import customtkinter as ctk

import config
from core.stream_engine import EngineCallbacks, EngineState, StreamEngine
from transport.base import Transport
from transport.wifi import WifiTransport

logger = logging.getLogger(__name__)

# transport 顯示名稱 → 建立函式。M1-A 只有 WiFi；U1/U2/U3/BT 通過驗收後
# 各自在自己的檔案裡定義好 Transport 實作，再回來這裡加一行即可。
TRANSPORT_FACTORIES: dict[str, Callable[[], Transport]] = {
    "WiFi": lambda: WifiTransport(),
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
        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._running = False

        self._build_ui()
        self.after(100, self._drain_log_queue)
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
        transport_name = self.transport_var.get()
        factory = TRANSPORT_FACTORIES[transport_name]
        transport = factory()

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
        if self._engine is not None:
            self._engine.stop()
            self._engine = None
        self._running = False
        self.start_stop_btn.configure(text="啟動")
        self.transport_menu.configure(state="normal")
        self.status_label.configure(text=_STATE_LABELS[EngineState.IDLE])
        self.format_label.configure(text="—")
        self._append_log("已停止")

    def _on_state_changed(self, state: EngineState) -> None:
        self.status_label.configure(text=_STATE_LABELS.get(state, str(state)))
        if self._engine is not None and self._engine.current_format is not None:
            self.format_label.configure(text=str(self._engine.current_format))
        if state == EngineState.STOPPED:
            self._running = False
            self.start_stop_btn.configure(text="啟動")
            self.transport_menu.configure(state="normal")

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
        """把 engine 背景執行緒的 callback 轉成主執行緒（Tk）安全的呼叫。"""

        def wrapper(*args, **kwargs) -> None:
            self.after(0, lambda: fn(*args, **kwargs))

        return wrapper

    def _append_log(self, msg: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _drain_log_queue(self) -> None:
        # 保留給未來（logging handler 想把訊息也導進這個 queue 時使用）。
        while True:
            try:
                msg = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(msg)
        self.after(100, self._drain_log_queue)


def run() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()

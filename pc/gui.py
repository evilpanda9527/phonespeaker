"""gui.py — customtkinter GUI（§13）。

M1-A 範圍：只有 WiFi 這個 transport 選項。之後 U1/U2/U3/BT 驗收通過後，
只需要在 TRANSPORT_FACTORIES 這個字典加一行，不需要動這個檔案其他邏輯
（§10.3 檔案隔離原則的精神也適用在「新增選項」這件事上）。

雙語（todo010）：所有面向使用者的文字改透過 i18n.t() 查表，不寫死中文，
方便介面隨系統語言/手動切換即時重繪（見 _apply_language()）。transport
的「內部代號」（wifi / usb_rndis / usb_adb）跟「顯示名稱」分開——顯示名稱
會隨語言變、代號不會，選單的 command callback 用代號分派，不受語言影響。
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
import i18n
from core.stream_engine import EngineCallbacks, EngineState, StreamEngine
from transport.base import Transport
from transport.usb_adb import UsbAdbTransport
from transport.usb_rndis import UsbRndisTransport
from transport.wifi import WifiTransport

logger = logging.getLogger(__name__)

# transport 內部代號（順序＝下拉選單順序，WiFi 為預設選項）→ 建立函式。
# U1(USB 網路共享)/U2(USB adb) 通過驗收後依序加入；U3/BT 依此類推，不需要
# 動這個檔案其他邏輯（§10.3 檔案隔離原則的精神也適用在「新增選項」這件事
# 上）。顯示名稱／引導提示改放 i18n.py（見 transport.<id>.name / .hint），
# 不在這裡寫死語言。
TRANSPORT_IDS: list[str] = ["wifi", "usb_rndis", "usb_adb"]
TRANSPORT_FACTORIES: dict[str, Callable[[], Transport]] = {
    "wifi": lambda: WifiTransport(),
    "usb_rndis": lambda: UsbRndisTransport(),
    "usb_adb": lambda: UsbAdbTransport(),
}

_STATE_KEYS = {
    EngineState.IDLE: "state.idle",
    EngineState.WAITING: "state.waiting",
    EngineState.HANDSHAKE: "state.handshake",
    EngineState.STREAMING: "state.streaming",
    EngineState.STOPPED: "state.stopped",
}


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.geometry("620x520")
        self.minsize(520, 440)

        self._engine: Optional[StreamEngine] = None
        self._active_transport: Optional[Transport] = None
        # engine 背景執行緒 → 主執行緒的 callback 一律先進這個 queue，
        # 由主執行緒自己的輪詢迴圈取出執行（見 _threadsafe / _drain_callback_queue，
        # 修正緣由見 todo07-2）。
        self._callback_queue: "queue.Queue[tuple[Callable, tuple, dict]]" = queue.Queue()
        self._running = False

        # 目前選中的 transport 代號、engine 狀態、格式顯示——語言切換時要
        # 靠這些「目前狀態」重繪對應文字（見 _apply_language），不能只在
        # 事件發生的當下寫死文字（否則切語言不會回頭更新舊文字）。
        self._selected_transport_id: str = TRANSPORT_IDS[0]
        self._current_state: EngineState = EngineState.IDLE
        self._current_format_text: Optional[str] = None  # None＝顯示 placeholder

        self._build_ui()
        self._apply_language()
        self.after(100, self._drain_callback_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    # UI 建構
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=12, pady=(12, 6))

        self.transport_caption = ctk.CTkLabel(top, text="")
        self.transport_caption.pack(side="left", padx=(4, 4))
        self.transport_var = ctk.StringVar()
        self.transport_menu = ctk.CTkOptionMenu(
            top,
            values=[],
            variable=self.transport_var,
            command=self._on_transport_selected,
        )
        self.transport_menu.pack(side="left", padx=(0, 16))

        self.start_stop_btn = ctk.CTkButton(
            top, text="", command=self._on_toggle_start_stop, width=100
        )
        self.start_stop_btn.pack(side="left")

        # 語言切換（todo010）：靠右放一個下拉選單，選項含「自動（跟隨系統）」
        # 與明確的 zh-TW / en。純 UI 文字層設定，不影響任何連線/傳輸邏輯。
        self.language_caption = ctk.CTkLabel(top, text="")
        self.language_caption.pack(side="right", padx=(4, 4))
        self.language_var = ctk.StringVar()
        self.language_menu = ctk.CTkOptionMenu(
            top,
            values=[],
            variable=self.language_var,
            command=self._on_language_selected,
            width=140,
        )
        self.language_menu.pack(side="right", padx=(0, 4))

        # transport 引導提示（見 todo08-1；WiFi 提示為 todo010 新增）：選到
        # 需要手機端先開開關／同一網路的 transport 時，在下拉選單下方顯示
        # 一行不擋流程的說明文字。用粗體黃色跟其他一般說明文字（灰色）區隔，
        # 讓使用者一眼就注意到（使用者反饋：原本的灰色不夠醒目）。淺色模式
        # 用較深的琥珀色維持可讀對比，深色模式用較亮的金黃色。
        hint_frame = ctk.CTkFrame(self)
        hint_frame.pack(fill="x", padx=12, pady=(0, 6))
        self.transport_hint_label = ctk.CTkLabel(
            hint_frame,
            text="",
            text_color=("#946200", "#FFD54F"),
            font=ctk.CTkFont(weight="bold"),
        )
        self.transport_hint_label.pack(side="left", padx=(4, 4))

        status_frame = ctk.CTkFrame(self)
        status_frame.pack(fill="x", padx=12, pady=6)

        self.status_caption = ctk.CTkLabel(status_frame, text="")
        self.status_caption.pack(side="left", padx=(4, 4))
        self.status_label = ctk.CTkLabel(status_frame, text="")
        self.status_label.pack(side="left")

        self.latency_label = ctk.CTkLabel(
            status_frame, text="", text_color=("gray40", "gray60")
        )
        self.latency_label.pack(side="left", padx=(12, 4))

        format_frame = ctk.CTkFrame(self)
        format_frame.pack(fill="x", padx=12, pady=6)
        self.format_caption = ctk.CTkLabel(format_frame, text="")
        self.format_caption.pack(side="left", padx=(4, 4))
        self.format_label = ctk.CTkLabel(format_frame, text="")
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

        self.log_caption = ctk.CTkLabel(self, text="")
        self.log_caption.pack(anchor="w", padx=12)
        self.log_box = ctk.CTkTextbox(self, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # 語言（todo010）：目前解析後的介面語言變動時，重繪所有靜態文字。
    # 只動文字內容，不動任何 widget 的存在與否／版面結構／連線邏輯。
    # ------------------------------------------------------------------ #

    def _apply_language(self) -> None:
        self.title(i18n.t("app.window_title"))

        self.transport_caption.configure(text=i18n.t("label.transport"))
        self._transport_label_to_id = {
            i18n.t(f"transport.{tid}.name"): tid for tid in TRANSPORT_IDS
        }
        transport_labels = list(self._transport_label_to_id)
        self.transport_menu.configure(values=transport_labels)
        self.transport_var.set(i18n.t(f"transport.{self._selected_transport_id}.name"))
        self._refresh_transport_hint()

        self.start_stop_btn.configure(
            text=i18n.t("btn.stop" if self._running else "btn.start")
        )

        self.language_caption.configure(text=i18n.t("label.language"))
        self._language_label_to_pref = {
            i18n.language_preference_label(p): p for p in i18n.LANGUAGE_PREFERENCES
        }
        self.language_menu.configure(values=list(self._language_label_to_pref))
        self.language_var.set(i18n.language_preference_label(i18n.get_preference()))

        self.status_caption.configure(text=i18n.t("label.status"))
        self.status_label.configure(text=i18n.t(_STATE_KEYS.get(self._current_state, "state.idle")))

        self.latency_label.configure(
            text=i18n.t(
                "latency.label",
                lo=config.RING_BUFFER_TARGET_MS_MIN,
                hi=config.RING_BUFFER_TARGET_MS_MAX,
            )
        )

        self.format_caption.configure(text=i18n.t("label.format"))
        self.format_label.configure(text=self._current_format_text or i18n.t("format.placeholder"))

        self._refresh_usb_fallback_label()

        self.log_caption.configure(text=i18n.t("label.log"))

    def _refresh_transport_hint(self) -> None:
        """todo08-1：選到需要手機端先開開關/同一網路的 transport 時，顯示
        對應的靜態引導提示。

        todo011-4：U2(USB adb) 原本在這裡疊加一層背景輪詢即時偵測結果
        （todo011 §2），已整個移除——U2 現在跟 WiFi/U1 一樣，standby 狀態
        不主動做任何背景 adb 呼叫，「找不到裝置／unauthorized／正常連線」
        這三種狀態的判斷全部挪到使用者按下 START 那一刻，由 connect() 一次
        性完成並透過既有的 on_error callback 回報（見 transport/usb_adb.py
        `_MSG_NOT_FOUND`／`_MSG_UNAUTHORIZED`），不再需要獨立的即時提示。
        根因見 todo011-1～-4 這幾輪診斷：背景輪詢執行緒跟 connect() 各自
        呼叫 adb 的時機重疊，會讓 adb 的 client-server 協定被打斷。"""
        self.transport_hint_label.configure(
            text=i18n.t(f"transport.{self._selected_transport_id}.hint")
        )

    def _refresh_usb_fallback_label(self) -> None:
        # `detected_ip` 只有 UsbRndisTransport 才有；WiFi 模式下這裡永遠是
        # None，標籤維持空白，不影響既有畫面。
        detected_ip = getattr(self._active_transport, "detected_ip", None)
        self.usb_fallback_label.configure(
            text=i18n.t("usb_fallback.label", ip=detected_ip) if detected_ip else ""
        )

    # ------------------------------------------------------------------ #
    # 事件處理
    # ------------------------------------------------------------------ #

    def _on_transport_selected(self, choice: str) -> None:
        """下拉選單 command callback：純 UI 提示更新，不動連線邏輯（todo08-1）。
        todo011-4：U2 不再有背景輪詢需要啟動/停止，這裡跟 WiFi/U1 完全一致。
        """
        self._selected_transport_id = self._transport_label_to_id.get(choice, self._selected_transport_id)
        self._refresh_transport_hint()

    def _on_language_selected(self, choice: str) -> None:
        """語言下拉選單 command callback（todo010）：套用＋記住偏好，並重繪介面文字。"""
        pref = self._language_label_to_pref.get(choice)
        if pref is None:
            return
        i18n.set_preference(pref)
        self._apply_language()

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

        transport_id = self._selected_transport_id
        factory = TRANSPORT_FACTORIES[transport_id]
        transport = factory()
        self._active_transport = transport

        callbacks = EngineCallbacks(
            on_state_changed=self._threadsafe(self._on_state_changed),
            on_log=self._threadsafe(self._append_log),
            on_error=self._threadsafe(
                lambda msg: self._append_log(i18n.t("log.error_prefix", msg=msg))
            ),
        )
        # 連線時 PC 一律靜音、只有手機出聲（原本可切換「不自動靜音」的開關
        # 實測無作用，已移除；StreamEngine 的 auto_mute 預設就是 True）。
        self._engine = StreamEngine(transport, callbacks=callbacks)
        self._engine.start()
        self._running = True
        self.start_stop_btn.configure(text=i18n.t("btn.stop"))
        self.transport_menu.configure(state="disabled")
        self._append_log(
            i18n.t("log.started", transport=i18n.t(f"transport.{transport_id}.name"))
        )

    def _stop_engine(self) -> None:
        # 診斷用（見 todo07-1）：量出「使用者按停止」到「engine.stop() 真的
        # 返回」的呼叫端總耗時，並在前後都印出背景執行緒清單，方便跟
        # stream_engine 內部各段的計時 log 對照。只加 log，不改行為/邏輯。
        # （診斷用文字比照 core 層的診斷 log，本批刻意不雙語化，見 SPEC3 §18。
        # todo010-1：發佈版不在畫面 log 區顯示這行工程調試字樣，但仍寫進
        # pc/logs/app.log，供之後排查問題用——只拿掉 self._append_log()，
        # logger.info() 完全不動。）
        if self._engine is not None:
            t0 = time.monotonic()
            self._engine.stop()
            elapsed = time.monotonic() - t0
            msg = f"[停止診斷] GUI _stop_engine(): engine.stop() 呼叫端總耗時 {elapsed * 1000:.0f}ms"
            logger.info(msg)
            self._engine = None
        self._active_transport = None
        self._running = False
        self._current_state = EngineState.IDLE
        self._current_format_text = None
        self.start_stop_btn.configure(text=i18n.t("btn.start"))
        self.transport_menu.configure(state="normal")
        self.status_label.configure(text=i18n.t("state.idle"))
        self.format_label.configure(text=i18n.t("format.placeholder"))
        self.usb_fallback_label.configure(text="")
        self._append_log(i18n.t("log.stopped"))
        self._log_alive_threads("_stop_engine() 結束後")
        self._refresh_transport_hint()

    def _on_state_changed(self, state: EngineState) -> None:
        self._current_state = state
        self.status_label.configure(text=i18n.t(_STATE_KEYS.get(state, "state.idle")))
        if self._engine is not None and self._engine.current_format is not None:
            self._current_format_text = str(self._engine.current_format)
            self.format_label.configure(text=self._current_format_text)
        self._refresh_usb_fallback_label()
        if state == EngineState.STOPPED:
            self._running = False
            self.start_stop_btn.configure(text=i18n.t("btn.start"))
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
        # todo011-4：U2 不再有背景輪詢，所以也不再需要「輪詢有沒有順帶啟動
        # adb server、關閉時要不要收尾」這一段（原本的 _adb_poll_owns_server／
        # kill_orphaned_probe_server()，todo011-1 加的）——U2 連線期間如果
        # 真的由本程式啟動了 adb server，走的是 todo010-4 那條既有路徑：
        # _stop_engine() → engine.stop() → transport.disconnect() →
        # UsbAdbTransport._kill_adb_server_if_owned()，跟這裡完全無關、
        # 不受影響。
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

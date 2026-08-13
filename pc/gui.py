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
from transport.usb_adb import (
    AdbState,
    UsbAdbTransport,
    diag_snapshot as _adb_diag_snapshot,  # 診斷用（todo011-1）
    is_adb_server_listening as _adb_server_listening,
    kill_orphaned_probe_server as _kill_orphaned_adb_probe_server,
    probe_state as probe_adb_state,
)
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

# todo011 §2：U2 前置狀態主動偵測的輪詢間隔。只在「選到 USB(adb) 且目前
# 閒置(未啟動)」時才會跑（見 _start_adb_poll / _on_transport_selected），
# 2 秒夠即時反映使用者剛在手機上開偵錯/按允許的動作，又不會頻繁到造成
# 明顯負擔（每次輪詢就是一次 `adb devices`，跟使用者自己在命令列打是
# 同一件事）。
_ADB_POLL_INTERVAL_S = 2.0

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

        # todo011 §2：U2(USB adb) 前置狀態主動偵測——None＝還沒偵測出結果
        # （沿用舊的靜態提示當 placeholder），偵測到結果後改顯示對應狀態
        # （見 _refresh_transport_hint / _adb_poll_loop）。
        self._adb_probe_state: Optional[AdbState] = None
        self._adb_poll_stop = threading.Event()
        self._adb_poll_thread: Optional[threading.Thread] = None

        # bug fix（使用者實測回報）：U2 前置偵測輪詢若在 adb server 還沒
        # 啟動時跑起來，會順帶把它啟動、卻從沒人收尾（[probe_state] 故意
        # 不管 server 生命週期，見該函式 docstring）。這裡記「輪詢啟動當下
        # server 是不是已經在跑」，True 才代表這次 app 執行期間可能是我們
        # 自己讓它啟動的，_on_close() 才需要負責關掉，不誤殺使用者自己另外
        # 開著的 adb server（例如 Android Studio）。一旦記到 True 就維持
        # 到 app 關閉，不會被之後幾次「已經在跑」的輪詢重置回 False。
        self._adb_poll_owns_server: bool = False

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
        """todo011 §2：U2(USB adb) 選到時顯示主動偵測到的即時狀態（見
        [_adb_hint_text]）；其餘 transport（或 U2 還沒偵測出結果時）維持
        原本 todo08-1 的靜態引導提示，行為不變。"""
        if self._selected_transport_id == "usb_adb" and self._adb_probe_state is not None:
            self.transport_hint_label.configure(text=self._adb_hint_text(self._adb_probe_state))
        else:
            self.transport_hint_label.configure(
                text=i18n.t(f"transport.{self._selected_transport_id}.hint")
            )

    @staticmethod
    def _adb_hint_text(state: AdbState) -> str:
        if state is AdbState.READY:
            return ""  # 情況 3：就緒，不顯示警告（todo011 §2 一）
        if state is AdbState.UNAUTHORIZED:
            return i18n.t("adb_status.unauthorized")
        return i18n.t("adb_status.not_found")

    def _start_adb_poll(self) -> None:
        """todo011 §2：只在「選到 USB(adb) 且目前閒置」時才跑的背景偵測
        輪詢（見 _on_transport_selected / _start_engine / _stop_engine 呼叫
        時機）。用背景執行緒＋既有的 _threadsafe/callback_queue 機制回主
        執行緒更新 UI，不直接在輪詢執行緒呼叫任何 Tk 方法（§16-4 教訓：
        跨執行緒直接呼叫 Tk 方法會互相卡住，這裡完全比照既有作法）。"""
        if self._adb_poll_thread is not None:
            return
        # bug fix：只在還沒判定過「是我們啟動的」之前才需要探測——探測本身
        # 是一次同步的短逾時 TCP connect，不會啟動 adb，比照 connect() 裡
        # 同一個探測的用法（見 usb_adb.py「adb server 生命週期」說明）。
        if not self._adb_poll_owns_server and not _adb_server_listening():
            self._adb_poll_owns_server = True
        # 診斷用（todo011-1）
        _adb_diag_snapshot(f"_start_adb_poll()：_adb_poll_owns_server={self._adb_poll_owns_server}")
        self._adb_poll_stop.clear()
        thread = threading.Thread(target=self._adb_poll_loop, name="adb-status-poll", daemon=True)
        self._adb_poll_thread = thread
        thread.start()

    def _stop_adb_poll(self) -> None:
        # 只設旗標、不 join()：輪詢執行緒可能正卡在一次 `adb devices`
        # 呼叫中（最長 config.ADB_COMMAND_TIMEOUT_S），比照 §16-4 教訓，
        # 呼叫端（主執行緒）絕不能等它——旗標設完就返回，執行緒會在下一次
        # 迴圈檢查點自然結束（daemon=True，就算真的卡住也不會擋 app 關閉）。
        self._adb_poll_stop.set()
        self._adb_poll_thread = None
        self._adb_probe_state = None

    def _adb_poll_loop(self) -> None:
        on_result = self._threadsafe(self._on_adb_state_probed)
        while not self._adb_poll_stop.is_set():
            try:
                state = probe_adb_state()
            except Exception as e:  # noqa: BLE001 — 偵測執行緒本身的例外不該拖垮整個 GUI
                logger.warning("U2 主動偵測 adb 狀態時發生非預期例外: %s", e)
                state = None
            if state is not None and not self._adb_poll_stop.is_set():
                on_result(state)
            self._adb_poll_stop.wait(_ADB_POLL_INTERVAL_S)

    def _on_adb_state_probed(self, state: AdbState) -> None:
        self._adb_probe_state = state
        self._refresh_transport_hint()

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

        todo011 §2：切到 USB(adb) 且目前閒置時啟動主動偵測輪詢；切離開時
        停止（沒必要在使用者根本沒選 U2 時一直背景執行 `adb devices`）。
        """
        self._selected_transport_id = self._transport_label_to_id.get(choice, self._selected_transport_id)
        if self._selected_transport_id == "usb_adb":
            self._adb_probe_state = None
            if not self._running:
                self._start_adb_poll()
        else:
            self._stop_adb_poll()
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

        # todo011 §2：真的要連線了，U2 主動偵測輪詢沒有必要繼續跑（避免跟
        # transport.connect() 自己的 `adb devices` 同時搶著跑，也沒有 UI
        # 意義——選單本身接下來就會被 disable，使用者看不到也改不了選擇）。
        #
        # 診斷用（todo011-1）：_stop_adb_poll() 只設旗標、不 join()（見該
        # 函式註解），所以這裡「呼叫完就返回」不代表輪詢執行緒真的已經停下
        # 來——如果它當下正卡在一次 probe_adb_state()／`adb devices` 呼叫
        # 中，接下來 transport.connect() 幾乎同時也會呼叫 adb 指令，兩者就
        # 可能重疊。這裡記一次「呼叫 _stop_adb_poll() 前，輪詢執行緒是否還
        # 活著」，藉此驗證/推翻這個猜測（見本檔 usb_adb.py 開頭的診斷說明）。
        poll_thread_alive_before_stop = (
            self._adb_poll_thread is not None and self._adb_poll_thread.is_alive()
        )
        logger.info(
            "[診斷] _start_engine()：呼叫 _stop_adb_poll() 前，輪詢執行緒存活=%s",
            poll_thread_alive_before_stop,
        )
        self._stop_adb_poll()

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

        # todo011 §2：回到閒置了，如果使用者選的還是 USB(adb)，重新開始
        # 主動偵測輪詢（跟 _on_transport_selected 選到 U2 時的邏輯一致）。
        if self._selected_transport_id == "usb_adb":
            self._adb_probe_state = None
            self._start_adb_poll()
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
            # todo011 §2：這裡是唯一保證「回到閒置」都會經過的地方——包含
            # 使用者按停止（_stop_engine() 也會另外立刻恢復一次，見該處
            # 註解）、以及 connect() 一啟動就失敗（例如 U2 未授權）這種
            # engine 自己結束、使用者根本沒按過停止的情況。兩種情況都要讓
            # 主動偵測輪詢恢復，不能只靠 _stop_engine() 那一份。
            if self._selected_transport_id == "usb_adb":
                self._adb_probe_state = None
                self._start_adb_poll()
                self._refresh_transport_hint()

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
        # 診斷用（todo011-1）：關閉流程最開頭先記一次快照＋當下的
        # _adb_poll_owns_server 旗標值，抓「第二次啟動 U2 連不上」這個 bug。
        _adb_diag_snapshot(
            f"_on_close() 開始（_adb_poll_owns_server={self._adb_poll_owns_server}）"
        )
        if self._running:
            self._stop_engine()
        # todo011 §2：關閉前把主動偵測輪詢的旗標設起來。跟 _stop_adb_poll()
        # 一貫的原則一樣不 join()——反正接下來就是 os._exit(0)，daemon
        # 執行緒本來就會跟著 process 一起結束，這裡純粹是不留著旗標沒設的
        # 習慣性收尾，不是必要條件。
        self._stop_adb_poll()
        # bug fix（使用者實測回報：關閉 app 後 adb.exe 還留著）：只有這次
        # app 執行期間，U2 前置偵測輪詢真的把原本沒在跑的 adb server 啟動
        # 起來時（見 _start_adb_poll 設 _adb_poll_owns_server 的地方）才
        # 呼叫這裡收尾；使用者自己另外開著的 adb server 不會被動到。這裡
        # 是同步呼叫（最長 config.ADB_COMMAND_TIMEOUT_S），在 os._exit()
        # 之前執行完，不影響下面既有的 destroy()/os._exit() 收尾流程。
        if self._adb_poll_owns_server:
            _kill_orphaned_adb_probe_server()
            self._adb_poll_owns_server = False
        _adb_diag_snapshot("_on_close()：adb 收尾完成，即將 destroy()/os._exit()")  # 診斷用（todo011-1）
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

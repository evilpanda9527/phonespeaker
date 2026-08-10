"""stream_engine.py — AudioSource ↔ Transport 串接（§4 核心穩定層）。

跑一顆背景「engine 執行緒」，狀態機大致為：

    IDLE → WAITING（等 client 連線，transport.connect() 阻塞）
         → HANDSHAKE（送 FORMAT，等 READY/FORMAT_UNSUPPORTED）
         → STREAMING（靜音 PC、擷取 loopback、持續送 PCM）
         → 斷線／錯誤 → 還原靜音 → 回到 WAITING（reconnect，§3）
    使用者按停止 → STOPPED（還原靜音、關閉所有資源）

不綁死任何 transport：只透過 transport.base.Transport 介面互動（§4）。
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

import config
from core.audio_capture import AudioCapture, AudioCaptureError
from core.audio_format import AudioFormat
from core.device_monitor import DeviceMonitor, DeviceMonitorError
from core.handshake import (
    FormatUnsupportedError,
    HandshakeError,
    MsgType,
    make_format_frame,
    make_pcm_frame,
)
from core.mute_control import MuteControl
from transport.base import Transport, TransportCancelled, TransportError

logger = logging.getLogger(__name__)

_READY_TIMEOUT_S = 8.0


class EngineState(Enum):
    IDLE = auto()
    WAITING = auto()
    HANDSHAKE = auto()
    STREAMING = auto()
    STOPPED = auto()


@dataclass
class EngineCallbacks:
    on_state_changed: Callable[[EngineState], None] = lambda state: None
    on_log: Callable[[str], None] = lambda msg: None
    on_error: Callable[[str], None] = lambda msg: None


class StreamEngine:
    """把 AudioCapture、Transport、MuteControl、DeviceMonitor 串起來的協調層。"""

    def __init__(
        self,
        transport: Transport,
        callbacks: Optional[EngineCallbacks] = None,
        auto_mute: bool = True,
    ):
        self._transport = transport
        self._callbacks = callbacks or EngineCallbacks()
        self.auto_mute = auto_mute

        self._capture = AudioCapture(chunk_frames=config.CAPTURE_CHUNK_FRAMES)
        self._mute = MuteControl()
        self._device_monitor = DeviceMonitor(self._on_default_device_changed)

        self._pcm_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=8)
        self._sender_thread: Optional[threading.Thread] = None
        self._sender_stop = threading.Event()

        self._engine_thread: Optional[threading.Thread] = None
        self._stop_requested = threading.Event()
        self._state = EngineState.IDLE

        self._current_format: Optional[AudioFormat] = None
        self._format_dirty = threading.Event()  # 預設裝置變更時設置

    # ------------------------------------------------------------------ #
    # 對外 API（GUI 呼叫）
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._engine_thread is not None:
            logger.debug("StreamEngine 已在執行中")
            return
        self._stop_requested.clear()
        self._engine_thread = threading.Thread(
            target=self._run, daemon=True, name="stream-engine"
        )
        self._engine_thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        self._transport.request_cancel()
        self._transport.disconnect()
        if self._engine_thread is not None:
            self._engine_thread.join(timeout=5.0)
            if self._engine_thread.is_alive():
                # 不應該發生（會卡在這裡的兩個已知成因——音訊擷取的阻塞式
                # read()、transport 送出時卡住的 sendall()——分別在
                # core/audio_capture.py 與 transport/wifi.py 修正為主動中斷），
                # 但保留這層保護：engine 執行緒真的還沒結束時，不清空它的
                # 參照，避免 start() 又疊一個新的 engine 執行緒上去、造成
                # 重複擷取／重複連線。
                #
                # 診斷用：把目前仍存活的執行緒名稱也印出來，之後若又發生
                # 逾時，直接從 log 就能看出是哪一個（例如 "audio-capture"、
                # "pcm-sender"），不必再靠猜的——上面兩個個別位置也各自有
                # 更明確的 log（見 audio_capture.stop() 與 _teardown_stream()）。
                alive_names = sorted(
                    t.name for t in threading.enumerate() if t is not threading.main_thread()
                )
                self._error(
                    "停止逾時：背景執行緒尚未結束，請查看 log（可能需要重啟 app）"
                    f"｜目前仍存活的執行緒: {alive_names}"
                )
            else:
                self._engine_thread = None
        self._set_state(EngineState.STOPPED)

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def current_format(self) -> Optional[AudioFormat]:
        return self._current_format

    # ------------------------------------------------------------------ #
    # 內部：狀態機主迴圈
    # ------------------------------------------------------------------ #

    def _set_state(self, state: EngineState) -> None:
        self._state = state
        try:
            self._callbacks.on_state_changed(state)
        except Exception as e:  # noqa: BLE001 — GUI callback 出錯不可讓 engine 掛掉
            logger.exception("on_state_changed callback 發生例外: %s", e)

    def _log(self, msg: str) -> None:
        logger.info(msg)
        try:
            self._callbacks.on_log(msg)
        except Exception as e:  # noqa: BLE001
            logger.exception("on_log callback 發生例外: %s", e)

    def _error(self, msg: str) -> None:
        logger.error(msg)
        try:
            self._callbacks.on_error(msg)
        except Exception as e:  # noqa: BLE001
            logger.exception("on_error callback 發生例外: %s", e)

    def _run(self) -> None:
        try:
            self._device_monitor.start()
        except DeviceMonitorError as e:
            self._error(f"預設裝置監聽啟動失敗（熱切換將無法運作）: {e}")

        try:
            while not self._stop_requested.is_set():
                self._set_state(EngineState.WAITING)
                self._log(f"等待 {self._transport.display_name} client 連線…")
                try:
                    self._transport.connect()
                except TransportCancelled:
                    break
                except TransportError as e:
                    self._error(f"連線失敗: {e}")
                    break

                self._set_state(EngineState.HANDSHAKE)
                try:
                    self._do_handshake_and_stream()
                except FormatUnsupportedError as e:
                    self._error(str(e))
                except HandshakeError as e:
                    self._error(f"握手失敗: {e}")
                except TransportError as e:
                    self._log(f"連線中斷: {e}")
                finally:
                    self._teardown_stream()
                    # 不論成功串流一段後斷線、握手失敗或逾時，這條連線都已經
                    # 結束了，必須明確 disconnect() 才能讓下一輪 connect()
                    # 重新接受新的 client（否則 transport 會誤判「還有舊連線」）。
                    self._transport.disconnect()

                if self._stop_requested.is_set():
                    break
                self._log("已斷線，回到等待連線狀態（§3 reconnect）")
        finally:
            self._device_monitor.stop()
            self._capture.close()
            self._set_state(EngineState.STOPPED)

    def _do_handshake_and_stream(self) -> None:
        fmt = self._capture.open_for_default_device()
        self._current_format = fmt
        self._format_dirty.clear()

        self._transport.send_frame(make_format_frame(fmt))
        self._log(f"已送出 FORMAT: {fmt}，等待手機回應…")

        frame = self._recv_with_timeout(_READY_TIMEOUT_S)
        if frame.type == MsgType.FORMAT_UNSUPPORTED:
            reason = frame.payload.decode("utf-8", errors="replace")
            raise FormatUnsupportedError(reason)
        if frame.type != MsgType.READY:
            raise HandshakeError(f"預期收到 READY，卻收到 type={frame.type}")

        self._log("手機已回 READY，開始串流")
        self._set_state(EngineState.STREAMING)

        if self.auto_mute:
            try:
                self._mute.mute_output()
            except Exception as e:  # noqa: BLE001 — 靜音失敗不該中止串流
                self._error(f"靜音 PC 輸出失敗（將繼續串流但 PC 仍會出聲）: {e}")

        self._start_sender()
        self._capture.start(on_chunk=self._on_capture_chunk)

        # 主執行緒在這裡輪詢：發生斷線（sender 回報）或需要重送 FORMAT 就跳出。
        while not self._stop_requested.is_set():
            if self._sender_stop.wait(timeout=0.2):
                break
            if self._format_dirty.is_set():
                self._resend_format_if_needed()

    def _recv_with_timeout(self, timeout_s: float):
        """簡易逾時包裝：background thread 呼叫 recv_frame()，主執行緒等待。"""
        result: dict = {}
        done = threading.Event()

        def _worker():
            try:
                result["frame"] = self._transport.recv_frame()
            except TransportError as e:
                result["error"] = e
            finally:
                done.set()

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        if not done.wait(timeout=timeout_s):
            raise HandshakeError(f"等待手機回應逾時（{timeout_s}s）")
        if "error" in result:
            raise result["error"]
        return result["frame"]

    def _on_capture_chunk(self, data: bytes) -> None:
        try:
            self._pcm_queue.put_nowait(data)
        except queue.Full:
            # 依 §9：underrun/塞車時不得無限累積 queue，寧可丟棄最舊資料。
            try:
                self._pcm_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._pcm_queue.put_nowait(data)
            except queue.Full:
                pass

    def _start_sender(self) -> None:
        self._sender_stop.clear()
        while not self._pcm_queue.empty():
            try:
                self._pcm_queue.get_nowait()
            except queue.Empty:
                break
        self._sender_thread = threading.Thread(
            target=self._sender_loop, daemon=True, name="pcm-sender"
        )
        self._sender_thread.start()

    def _sender_loop(self) -> None:
        while not self._sender_stop.is_set():
            try:
                data = self._pcm_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._transport.send_frame(make_pcm_frame(data))
            except TransportError as e:
                logger.info("送出 PCM 失敗，判定為斷線: %s", e)
                self._sender_stop.set()
                return

    def _resend_format_if_needed(self) -> None:
        self._format_dirty.clear()
        try:
            new_fmt = self._capture.open_for_default_device()
        except AudioCaptureError as e:
            self._error(f"預設裝置變更後重建 capture 失敗: {e}")
            return

        if new_fmt == self._current_format:
            self._capture.start(on_chunk=self._on_capture_chunk)
            return

        self._current_format = new_fmt
        self._log(f"預設裝置變更，格式改變為 {new_fmt}，重送 FORMAT")
        try:
            self._transport.send_frame(make_format_frame(new_fmt))
        except TransportError as e:
            logger.info("重送 FORMAT 失敗，判定為斷線: %s", e)
            self._sender_stop.set()
            return
        self._capture.start(on_chunk=self._on_capture_chunk)

    def _on_default_device_changed(self) -> None:
        # 在 device_monitor 的 COM callback 執行緒被呼叫，這裡只設 flag，
        # 真正的重建工作留給 engine 主迴圈處理，避免在 COM callback 裡做重活。
        self._format_dirty.set()

    def _teardown_stream(self) -> None:
        self._sender_stop.set()
        if self._sender_thread is not None:
            self._sender_thread.join(timeout=2.0)
            if self._sender_thread.is_alive():
                # 診斷用：明確指出是 pcm-sender 這個執行緒逾時未結束，不要
                # 讓呼叫端只看到「整體逾時」卻不知道是哪一個。
                logger.error(
                    "停止診斷：pcm-sender 執行緒逾時未結束"
                    "（理論上 transport.disconnect() 的主動 close() 應該已經"
                    "讓卡住的 send_frame() 立刻出錯返回，見 transport/wifi.py）"
                )
            else:
                self._sender_thread = None
        self._capture.stop()
        if self.auto_mute:
            self._mute.restore_output()

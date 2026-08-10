"""audio_capture.py — WASAPI loopback 擷取（§4 AudioSource／§5 passthrough 原則）。

重要限制（誠實揭露，供 PoC 報告與使用者決策參考）：
    Windows WASAPI 在 shared mode 下，所有應用程式的音訊會先被 Windows Audio
    Engine 混音成單一「mix format」（依裝置/驅動而定，常見為
    48000Hz / 2ch / 32-bit float），loopback 擷取到的就是這個已完成混音的
    資料流。本模組拿到什麼就直接往下送、不再額外 resample / remix / 改
    bit depth（符合 §5「不 detect-and-convert」的字面要求）。
    但若期待的是「完全繞過 Windows 混音引擎、原始來源 app 的位元完全不變」，
    在 shared-mode loopback 架構下無法達成——那需要 exclusive mode，而
    exclusive mode 會獨占裝置、其他程式無法同時出聲，不適合「擷取系統當前
    輸出」這個使用情境，因此本專案不採用。此限制已記在 PoC 報告 §已知限制。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import pyaudiowpatch as pyaudio

from .audio_format import AudioFormat

logger = logging.getLogger(__name__)

# WASAPI shared-mode loopback 幾乎一律是 32-bit float。
_LOOPBACK_PORTAUDIO_FORMAT = pyaudio.paFloat32
_LOOPBACK_ENCODING = "pcm_f32le"


class AudioCaptureError(Exception):
    pass


class AudioCapture:
    """擷取「目前系統預設輸出裝置」的 loopback 音訊。

    使用方式：
        cap = AudioCapture()
        fmt = cap.open_for_default_device()
        cap.start(on_chunk=lambda data: ...)
        ...
        cap.stop()
        cap.close()
    """

    def __init__(self, chunk_frames: int = 480):
        self._chunk_frames = chunk_frames
        self._pa = pyaudio.PyAudio()
        self._stream: Optional[pyaudio.Stream] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._current_format: Optional[AudioFormat] = None
        self._device_index: Optional[int] = None

    @property
    def current_format(self) -> Optional[AudioFormat]:
        return self._current_format

    def _resolve_default_loopback_device(self) -> dict:
        """找出目前預設輸出裝置對應的 WASAPI loopback 輸入裝置。"""
        try:
            wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError as e:
            raise AudioCaptureError("此系統找不到 WASAPI host API（需要 Windows）") from e

        default_output_index = wasapi_info.get("defaultOutputDevice", -1)
        if default_output_index is None or default_output_index < 0:
            raise AudioCaptureError("找不到目前的預設輸出裝置")

        default_speakers = self._pa.get_device_info_by_index(default_output_index)
        if default_speakers.get("isLoopbackDevice"):
            return default_speakers

        for loopback in self._pa.get_loopback_device_info_generator():
            if default_speakers["name"] in loopback["name"]:
                return loopback

        raise AudioCaptureError(
            f"找不到裝置「{default_speakers['name']}」對應的 loopback 裝置，"
            "請確認 Windows 音效驅動支援 WASAPI loopback"
        )

    def open_for_default_device(self) -> AudioFormat:
        """開啟目前預設輸出裝置的 loopback stream，回傳其實際格式。"""
        self.close_stream()

        device = self._resolve_default_loopback_device()
        channels = int(device["maxInputChannels"])
        sample_rate = int(device["defaultSampleRate"])
        if channels <= 0:
            raise AudioCaptureError(f"loopback 裝置 channel 數異常: {channels}")

        self._device_index = int(device["index"])
        self._stream = self._pa.open(
            format=_LOOPBACK_PORTAUDIO_FORMAT,
            channels=channels,
            rate=sample_rate,
            input=True,
            input_device_index=self._device_index,
            frames_per_buffer=self._chunk_frames,
        )
        self._current_format = AudioFormat(
            sample_rate=sample_rate, channels=channels, encoding=_LOOPBACK_ENCODING
        )
        logger.info(
            "已開啟 loopback 裝置「%s」：%dHz / %dch / %s",
            device["name"],
            sample_rate,
            channels,
            _LOOPBACK_ENCODING,
        )
        return self._current_format

    def start(self, on_chunk: Callable[[bytes], None]) -> None:
        if self._stream is None:
            raise AudioCaptureError("尚未呼叫 open_for_default_device()")
        if self._thread is not None:
            raise AudioCaptureError("擷取執行緒已在執行中")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop, args=(on_chunk,), daemon=True, name="audio-capture"
        )
        self._thread.start()

    def _capture_loop(self, on_chunk: Callable[[bytes], None]) -> None:
        # 維持最原始、單純的阻塞式讀取（不在熱路徑加任何 poll/節奏改動）：
        # §16-4 之後的第一版曾改成「先 get_read_available() 才 read()」來
        # 避免卡在阻塞 read() 裡，結果因為讀取節奏被打亂、跟 stream 開啟時
        # 設的小緩衝區（frames_per_buffer=chunk_frames）對不齊，造成串流播
        # 放破音（回歸）。改為在 stop() 主動中斷阻塞（見下方），而不是動這裡。
        assert self._stream is not None
        while not self._stop_event.is_set():
            try:
                data = self._stream.read(self._chunk_frames, exception_on_overflow=False)
            except OSError as e:
                # 裝置被拔掉/切換、或 stop() 主動呼叫 stop_stream() 中斷了
                # 這次阻塞讀取，都會走到這裡；兩種情況都直接結束迴圈即可。
                logger.warning("讀取 loopback stream 失敗，停止擷取迴圈: %s", e)
                return
            if data:
                try:
                    on_chunk(data)
                except Exception as e:  # noqa: BLE001 — callback 例外不可讓擷取執行緒死掉
                    logger.exception("on_chunk callback 發生例外: %s", e)

    def stop(self) -> None:
        self._stop_event.set()
        if self._stream is not None:
            try:
                # 主動中斷：系統無聲時 stream.read() 可能長時間卡在阻塞呼叫
                # 裡不會自己返回。呼叫 stop_stream() 讓 PortAudio 主動停止這
                # 個 stream，卡在 read() 的擷取執行緒會因此收到錯誤並返回
                # （見 _capture_loop 的 except），而不是被動等 join() 逾時。
                # 這不會影響熱路徑本身的讀取節奏，正常播放時的行為不受影響。
                self._stream.stop_stream()
            except OSError as e:
                logger.debug("stop_stream() 時發生非致命錯誤: %s", e)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                # 保險：stop_stream() 理論上已經能喚醒卡住的 read()，這裡
                # 只是防呆——執行緒真的還沒結束就絕對不能往下呼叫
                # stream.close()，避免跟還在讀取的執行緒併發存取同一個
                # stream 物件（PortAudio 不保證 thread-safe，可能讓整個
                # 行程崩潰）。寧可留著這個 thread 物件、記 log，也不要冒險。
                logger.error(
                    "擷取執行緒逾時未結束（stop_stream 未能即時喚醒阻塞中的 read）"
                )
                return
            self._thread = None

    def close_stream(self) -> None:
        self.stop()
        if self._thread is not None:
            # stop() 判定執行緒還活著、已經拒絕往下關閉，這裡照樣不能關閉
            # stream，維持跟 stop() 一致的保護。
            return
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except OSError as e:
                logger.debug("關閉 stream 時發生非致命錯誤: %s", e)
            self._stream = None
        self._current_format = None

    def close(self) -> None:
        self.close_stream()
        if self._thread is not None:
            # 同上：擷取執行緒還活著就不能 terminate() PyAudio（底下的
            # stream 還在被用），寧可跳過這次 terminate，也不要冒險崩潰。
            logger.error("擷取執行緒仍在執行，暫不 terminate PyAudio")
            return
        try:
            self._pa.terminate()
        except Exception as e:  # noqa: BLE001 — 關閉流程不應拋出讓程式崩潰
            logger.debug("terminate PyAudio 時發生非致命錯誤: %s", e)

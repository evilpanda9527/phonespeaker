"""base.py — Transport Interface（§4）。

音訊格式、READY 握手、ring buffer、播放邏輯都不綁死任何 transport；
每種 transport 只需要實作這裡定義的介面：connect / disconnect /
send_frame / recv_frame。上層（stream_engine）透過 Frame（見
core/handshake.py）在這層之上跑 FORMAT/READY 握手，再持續送 PCM frame。

依 SPEC3.md §10.3：這個檔案是所有 transport 共用的抽象介面，屬於穩定層，
凍結後改動要走 §10.4 回歸流程。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.handshake import Frame


class TransportError(Exception):
    """連線建立失敗、或已連線狀態下讀寫失敗時拋出。"""


class TransportCancelled(TransportError):
    """connect() 等待中被 request_cancel() 中斷時拋出（非錯誤，屬正常取消）。"""


class Transport(ABC):
    """單一 client 的 transport 抽象（§15：單一 client，不做多手機同時）。"""

    @abstractmethod
    def connect(self) -> None:
        """建立連線（可能是等待 client 連進來，也可能是主動連出去）。

        會阻塞呼叫的執行緒直到連線建立成功、發生錯誤、或被
        request_cancel() 取消。取消時拋 TransportCancelled。
        """

    @abstractmethod
    def disconnect(self) -> None:
        """中斷目前連線（若有）。可重複呼叫，不應拋例外。"""

    @abstractmethod
    def request_cancel(self) -> None:
        """讓阻塞在 connect() 的呼叫盡快返回（GUI 按下停止時使用）。"""

    @abstractmethod
    def send_frame(self, frame: Frame) -> None:
        """送出一個 frame（FORMAT / PCM 皆透過這裡送出）。連線中斷時拋 TransportError。"""

    @abstractmethod
    def recv_frame(self) -> Frame:
        """收一個完整 frame（READY / FORMAT_UNSUPPORTED 透過這裡收）。連線中斷時拋 TransportError。"""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """給 GUI 顯示用的簡短名稱，例如 'WiFi'。"""

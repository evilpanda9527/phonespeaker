"""handshake.py — HELLO/FORMAT/READY/FORMAT_UNSUPPORTED 訊息定義（§6）。

Wire 協定（所有 transport 共用同一套 framing，見 tcp_client.py 實際收送）：

    每個 frame = [4 bytes length, big-endian, u32][1 byte type][payload]
    length = 1(type) + len(payload)

    type 0x01 FORMAT              payload = JSON({sample_rate, channels, encoding})
    type 0x02 READY                payload = 空
    type 0x03 FORMAT_UNSUPPORTED   payload = UTF-8 錯誤原因字串（可為空）
    type 0x04 PCM                  payload = 原始 PCM bytes（不重複帶格式、不加序號/timestamp）

設計理由：
    - §5 規定「每封包只有純 PCM，不重複帶格式」——這裡的 PCM payload 完全是
      原始 audio bytes，type byte 只是「這個 frame 是哪一種」的最小 framing
      開銷，跟 §8.1 本來就要求的 4-byte length prefix 屬於同一層級，不算格式。
    - §7 要求「預設裝置變更、格式改變時重送 FORMAT」，所以 FORMAT 訊息必須能在
      連線建立後、PCM 已經在傳輸時再次出現，因此需要一個 type 欄位來跟 PCM
      frame 區分，不能只在連線最開頭出現一次就假設之後全是 PCM。
    - HELLO 併入 FORMAT 一起送（送出 FORMAT 本身即代表「我準備好了、這是我的
      格式」，不需要額外的空 HELLO 訊息）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .audio_format import AudioFormat


class MsgType(IntEnum):
    FORMAT = 0x01
    READY = 0x02
    FORMAT_UNSUPPORTED = 0x03
    PCM = 0x04


@dataclass(frozen=True)
class Frame:
    type: MsgType
    payload: bytes


def make_format_frame(fmt: AudioFormat) -> Frame:
    return Frame(MsgType.FORMAT, fmt.to_json_bytes())


def make_ready_frame() -> Frame:
    return Frame(MsgType.READY, b"")


def make_format_unsupported_frame(reason: str = "") -> Frame:
    return Frame(MsgType.FORMAT_UNSUPPORTED, reason.encode("utf-8"))


def make_pcm_frame(pcm: bytes) -> Frame:
    return Frame(MsgType.PCM, pcm)


class HandshakeError(Exception):
    """READY 逾時、FORMAT_UNSUPPORTED、或收到非預期訊息時拋出。"""


class FormatUnsupportedError(HandshakeError):
    def __init__(self, reason: str = ""):
        self.reason = reason
        super().__init__(f"手機回報 FORMAT_UNSUPPORTED: {reason or '(無原因)'}")

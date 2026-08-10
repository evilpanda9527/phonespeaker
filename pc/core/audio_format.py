"""audio_format.py — FORMAT metadata（§5 音訊格式策略）。

PC 端不 detect-and-convert、不 resample、不 remix、不改 bit depth。
這裡只描述 WASAPI loopback 實際吐出的格式，供連線建立時傳給 Android 一次。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

# 目前 WASAPI loopback 常見的封裝方式。若遇到其他格式，Android 端一律回
# FORMAT_UNSUPPORTED，PC 端不轉檔（§5）。
Encoding = Literal["pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le"]


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int
    channels: int
    encoding: Encoding

    def bytes_per_frame(self) -> int:
        """一個 frame（所有 channel 各一個 sample）的位元組數。"""
        bits_map = {
            "pcm_s16le": 16,
            "pcm_s24le": 24,
            "pcm_s32le": 32,
            "pcm_f32le": 32,
        }
        bits = bits_map[self.encoding]
        return (bits // 8) * self.channels

    def bytes_per_second(self) -> int:
        return self.bytes_per_frame() * self.sample_rate

    def to_json_bytes(self) -> bytes:
        payload = {
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "encoding": self.encoding,
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def from_json_bytes(data: bytes) -> "AudioFormat":
        try:
            obj = json.loads(data.decode("utf-8"))
            return AudioFormat(
                sample_rate=int(obj["sample_rate"]),
                channels=int(obj["channels"]),
                encoding=obj["encoding"],
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            raise ValueError(f"無法解析 FORMAT payload: {data!r}") from e

    @staticmethod
    def from_pyaudio_format(
        sample_rate: int, channels: int, sample_format: str
    ) -> "AudioFormat":
        """由 pyaudiowpatch 回報的裝置格式轉為 AudioFormat。

        sample_format 預期為 pyaudiowpatch/portaudio 的格式字串
        （例如 'paInt16' / 'paInt24' / 'paInt32' / 'paFloat32'）。
        遇到未知格式時直接拋錯，交由呼叫端決定是否中止連線
        （不得靜默轉檔，符合 §5 passthrough 原則）。
        """
        mapping: dict[str, Encoding] = {
            "paInt16": "pcm_s16le",
            "paInt24": "pcm_s24le",
            "paInt32": "pcm_s32le",
            "paFloat32": "pcm_f32le",
        }
        if sample_format not in mapping:
            raise ValueError(f"未支援的 PortAudio sample format: {sample_format}")
        return AudioFormat(
            sample_rate=sample_rate, channels=channels, encoding=mapping[sample_format]
        )

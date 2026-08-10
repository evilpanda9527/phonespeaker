"""mute_control.py — PC 端靜音/還原（§6）。

務必等 Android 回 READY 才靜音；斷線/關 app/錯誤時要還原原本的音量/靜音狀態。
使用 pycaw 操作預設輸出端點的 IAudioEndpointVolume。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import comtypes
from pycaw.pycaw import AudioUtilities
from pycaw.api.endpointvolume import IAudioEndpointVolume

# COM 呼叫失敗時 comtypes 拋 COMError（不是 OSError 的子類別），統一一起接。
_ComErrors = (OSError, comtypes.COMError)

logger = logging.getLogger(__name__)


class MuteControlError(Exception):
    pass


@dataclass
class _SavedState:
    was_muted: bool
    master_volume: float  # 0.0–1.0，僅記錄供除錯／未來還原音量用途


class MuteControl:
    """管理「目前預設輸出裝置」的靜音狀態，可保存/還原。"""

    def __init__(self) -> None:
        self._saved: Optional[_SavedState] = None

    def _get_endpoint_volume(self) -> IAudioEndpointVolume:
        try:
            device = AudioUtilities.GetSpeakers()
            return device.EndpointVolume
        except _ComErrors as e:
            raise MuteControlError(f"無法取得預設輸出裝置的音量介面: {e}") from e

    def mute_output(self) -> None:
        """靜音預設輸出端點，並保存靜音前的狀態以供 restore_output() 還原。

        若已經保存過狀態（尚未 restore），不重複覆蓋，避免多次呼叫把
        「已靜音」誤存成原始狀態。
        """
        if self._saved is not None:
            logger.debug("mute_output() 被重複呼叫，略過（已有保存狀態）")
            return
        try:
            endpoint = self._get_endpoint_volume()
            was_muted = bool(endpoint.GetMute())
            master_volume = float(endpoint.GetMasterVolumeLevelScalar())
            self._saved = _SavedState(was_muted=was_muted, master_volume=master_volume)
            endpoint.SetMute(1, None)
            logger.info("已靜音 PC 預設輸出（原狀態 muted=%s）", was_muted)
        except MuteControlError:
            raise
        except _ComErrors as e:
            raise MuteControlError(f"靜音失敗: {e}") from e

    def restore_output(self) -> None:
        """還原到 mute_output() 呼叫前的靜音狀態。找不到保存狀態時安全跳過。"""
        if self._saved is None:
            logger.debug("restore_output() 被呼叫但沒有保存狀態，略過")
            return
        saved = self._saved
        self._saved = None
        try:
            endpoint = self._get_endpoint_volume()
            endpoint.SetMute(1 if saved.was_muted else 0, None)
            logger.info("已還原 PC 預設輸出靜音狀態 muted=%s", saved.was_muted)
        except _ComErrors as e:
            # 還原失敗不應該讓程式崩潰，但務必記錄，使用者可能需要手動取消靜音。
            logger.error("還原靜音狀態失敗，請手動檢查 PC 音量: %s", e)

    @property
    def has_saved_state(self) -> bool:
        return self._saved is not None

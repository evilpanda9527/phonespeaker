"""tcp_client.py — 凍結共用 TCP framing 輔助（§13：wifi / u1 / u2 共用）。

只負責「怎麼在一條已建立的 socket 上收送 Frame」，完全不知道 socket 是怎麼
建立的（server accept 或 client connect），也不知道上層是誰在用它
（WiFi / U1 RNDIS / U2 adb-forward 之後都走同一條 TCP，複用同一套 framing）。

依 §10.3 檔案隔離原則：這個檔案一旦通過 WiFi 驗收就視為凍結，之後 U1/U2
只能「使用」它，不應該為了某個 transport 的特殊需求去修改它的行為。
"""

from __future__ import annotations

import logging
import socket
import struct
from typing import Optional

from .handshake import Frame, MsgType

logger = logging.getLogger(__name__)

_LENGTH_STRUCT = struct.Struct(">I")  # 4 bytes, big-endian, u32
_HEADER_LEN = _LENGTH_STRUCT.size
_TYPE_LEN = 1
_MAX_FRAME_LEN = 64 * 1024 * 1024  # 64MB 上限，防止壞資料造成記憶體暴衝


class ConnectionClosed(Exception):
    """對端關閉連線或讀到不完整資料時拋出。"""


def send_frame(sock: socket.socket, frame: Frame) -> None:
    """送出一個 frame：[4B length][1B type][payload]。"""
    body = bytes([frame.type]) + frame.payload
    header = _LENGTH_STRUCT.pack(len(body))
    sock.sendall(header + body)


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """讀滿 n bytes，對端提早關閉則拋 ConnectionClosed。"""
    chunks = bytearray()
    while len(chunks) < n:
        chunk = sock.recv(n - len(chunks))
        if not chunk:
            raise ConnectionClosed("對端關閉連線（recv 回傳空資料）")
        chunks.extend(chunk)
    return bytes(chunks)


def recv_frame(sock: socket.socket) -> Frame:
    """讀一個完整 frame。長度或 type 不合法時拋 ValueError。"""
    header = recv_exact(sock, _HEADER_LEN)
    (length,) = _LENGTH_STRUCT.unpack(header)
    if length < _TYPE_LEN or length > _MAX_FRAME_LEN:
        raise ValueError(f"frame 長度不合法: {length}")
    body = recv_exact(sock, length)
    type_byte = body[0]
    try:
        msg_type = MsgType(type_byte)
    except ValueError as e:
        raise ValueError(f"未知的 frame type: {type_byte}") from e
    return Frame(msg_type, body[_TYPE_LEN:])


def configure_socket_for_streaming(sock: socket.socket) -> None:
    """低延遲導向的 socket 選項：關掉 Nagle，避免小封包被延遲合併。"""
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


def try_close(sock: Optional[socket.socket]) -> None:
    """盡力關閉 socket，任何錯誤都吞掉並記 log（關閉流程不該讓程式炸掉）。"""
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError as e:
        logger.debug("關閉 socket 時發生非致命錯誤: %s", e)

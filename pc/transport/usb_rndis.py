"""usb_rndis.py — U1: USB 網路共享（RNDIS）transport（§8.2 U1，M1-B 第一個變體）。

架構跟 wifi.py 幾乎一樣：PC 仍是 TCP server（沿用同一個 port，複用
core/tcp_client.py 的 framing），Android 端仍是 client，mDNS 探索為主
（PoC 已實測：mDNS 能跨 USB 網路共享的 RNDIS 介面，見 §16-3 前置調查）。

跟 wifi.py 唯一的差別：**廣播/顯示哪一張網卡的 IP**。這裡只認「USB 網路
共享(RNDIS) 對應的那張網卡」，不是 WiFi、也不是「排除虛擬網卡後剩下的
全部」——WifiTransport 的邏輯服務的是完全不同的問題（避開誤連虛擬網卡），
這裡的目標很單純：只鎖定 RNDIS 這一張。

依 §10.3 檔案隔離：這是 U1 專屬檔案，刻意不 import、不修改 wifi.py 的任何
內部邏輯（即使兩者程式碼結構相似也分開維護，避免以後改 WiFi 波及 U1，
反之亦然）。TCP accept/send/recv 這段跟 wifi.py 看起來重複，是刻意的取捨
（見 U1 PoC 報告 §風險清單：檔案隔離優先於程式碼共用）。
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Optional

import ifaddr
from zeroconf import ServiceInfo, Zeroconf

import config
from core.handshake import Frame
from core.tcp_client import ConnectionClosed
from core.tcp_client import configure_socket_for_streaming
from core.tcp_client import recv_frame as _recv_frame
from core.tcp_client import send_frame as _send_frame
from core.tcp_client import try_close
from transport.base import Transport, TransportCancelled, TransportError

logger = logging.getLogger(__name__)

_ACCEPT_POLL_INTERVAL_S = 0.5

# 依 PoC 實測（§16-3 前置調查）：Windows 上 USB 網路共享(RNDIS) 的網卡描述
# 固定含這個字樣——這是 USB gadget 的標準 class driver 名稱，不是廠牌專屬
# 的字串，實測過的 SAMSUNG 手機顯示成
# "SAMSUNG Mobile USB Remote NDIS Network Device"，通用性應該不錯。
_RNDIS_ADAPTER_KEYWORDS = ("remote ndis", "rndis")


def _find_rndis_ipv4_addresses() -> list[str]:
    """列舉目前作業系統上，USB 網路共享(RNDIS) 對應網卡的 IPv4 位址。

    只認「介面描述含 Remote NDIS/RNDIS 字樣」的網卡；其他介面（包含 WiFi
    本身）一律不管——跟 wifi.py 的「排除虛擬網卡、保留其餘」邏輯方向相反。
    """
    addrs: list[str] = []
    try:
        for adapter in ifaddr.get_adapters():
            lowered = adapter.nice_name.lower()
            if not any(keyword in lowered for keyword in _RNDIS_ADAPTER_KEYWORDS):
                continue
            for ip in adapter.ips:
                if not ip.is_IPv4:
                    continue
                addr = ip.ip
                if addr == "127.0.0.1" or addr.startswith("169.254."):
                    continue
                addrs.append(addr)
    except Exception as e:  # noqa: BLE001 — 列舉網卡失敗不該讓整個 transport 掛掉
        logger.warning("列舉 USB 網路共享(RNDIS) 網卡位址失敗: %s", e)
    return addrs


class UsbRndisTransport(Transport):
    """U1：USB 網路共享（RNDIS）。跟 WifiTransport 幾乎一樣的 TCP + mDNS，
    只是廣播/顯示鎖定在 RNDIS 網卡上。"""

    def __init__(
        self,
        host: str = config.TCP_LISTEN_HOST,
        port: int = config.TCP_LISTEN_PORT,
    ):
        self._host = host
        self._port = port
        self._listen_sock: Optional[socket.socket] = None
        self._conn: Optional[socket.socket] = None
        self._zeroconf: Optional[Zeroconf] = None
        self._service_info: Optional[ServiceInfo] = None
        self._send_lock = threading.Lock()

        # 給 GUI 當「保底資訊」顯示用：mDNS 探索失敗/不穩時，使用者可以照
        # 這個 IP 手動確認 PC 端是否在同一個 USB 網段。connect() 開始執行
        # 後才會有值；找不到 RNDIS 網卡時維持 None。
        self.detected_ip: Optional[str] = None

    @property
    def display_name(self) -> str:
        return "USB (USB 網路共享)"

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    def connect(self) -> None:
        """開 TCP server 並阻塞等待第一個 client 連進來，同時廣播 zeroconf
        （只認 RNDIS 網卡的位址）。"""
        if self._conn is not None:
            raise TransportError("已經有連線中的 client，請先 disconnect()")

        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listen_sock.bind((self._host, self._port))
        except OSError as e:
            try_close(listen_sock)
            raise TransportError(f"無法監聽 {self._host}:{self._port}: {e}") from e
        listen_sock.listen(1)
        listen_sock.settimeout(_ACCEPT_POLL_INTERVAL_S)
        self._listen_sock = listen_sock

        self._start_zeroconf()
        try:
            while self._listen_sock is not None:
                try:
                    conn, addr = listen_sock.accept()
                except socket.timeout:
                    continue
                except OSError as e:
                    raise TransportCancelled("connect() 被取消") from e
                configure_socket_for_streaming(conn)
                self._conn = conn
                logger.info("USB (RNDIS) client 已連線: %s", addr)
                return
            raise TransportCancelled("connect() 被取消")
        finally:
            self._stop_zeroconf()
            if self._listen_sock is not None:
                try_close(self._listen_sock)
                self._listen_sock = None

    def request_cancel(self) -> None:
        sock = self._listen_sock
        self._listen_sock = None
        try_close(sock)

    def disconnect(self) -> None:
        self.request_cancel()

        # 主動中斷（沿用 wifi.py §16-4 的教訓，實測驗證過的作法）：在拿
        # _send_lock 之前直接對 socket 呼叫完整的 close()，讓卡在阻塞式
        # sendall() 裡的 sender 執行緒立刻出錯返回；若先進鎖才 close()，
        # 持鎖中的阻塞呼叫會讓這裡卡死等鎖。
        conn = self._conn
        if conn is not None:
            try_close(conn)

        with self._send_lock:
            self._conn = None
        self._stop_zeroconf()

    def send_frame(self, frame: Frame) -> None:
        conn = self._conn
        if conn is None:
            raise TransportError("尚未連線")
        try:
            with self._send_lock:
                _send_frame(conn, frame)
        except OSError as e:
            self._conn = None
            raise TransportError(f"送出資料失敗: {e}") from e

    def recv_frame(self) -> Frame:
        conn = self._conn
        if conn is None:
            raise TransportError("尚未連線")
        try:
            return _recv_frame(conn)
        except (ConnectionClosed, OSError, ValueError) as e:
            self._conn = None
            raise TransportError(f"接收資料失敗: {e}") from e

    def _start_zeroconf(self) -> None:
        addresses = _find_rndis_ipv4_addresses()
        self.detected_ip = addresses[0] if addresses else None

        if not addresses:
            logger.warning(
                "找不到 USB 網路共享(RNDIS) 網卡的 IPv4 位址——請確認手機已開啟"
                "「USB 網路共享」且電腦已經抓到對應的網卡。zeroconf 廣播略過，"
                "手機端仍可能靠子網掃描 fallback 連上。"
            )
            return

        try:
            packed = [socket.inet_aton(a) for a in addresses]
            hostname = socket.gethostname()
            info = ServiceInfo(
                config.ZEROCONF_SERVICE_TYPE,
                config.ZEROCONF_SERVICE_NAME,
                addresses=packed,
                port=self._port,
                properties={"v": "1"},
                server=f"{hostname}.local.",
            )
            zc = Zeroconf()
            zc.register_service(info)
            self._zeroconf = zc
            self._service_info = info
            logger.info(
                "USB (RNDIS) zeroconf 廣播已啟動: %s @ %s:%d",
                config.ZEROCONF_SERVICE_NAME,
                addresses,
                self._port,
            )
        except OSError as e:
            logger.warning(
                "USB (RNDIS) zeroconf 廣播啟動失敗（不影響手機端子網掃描 fallback）: %s", e
            )

    def _stop_zeroconf(self) -> None:
        if self._zeroconf is not None:
            try:
                if self._service_info is not None:
                    self._zeroconf.unregister_service(self._service_info)
                self._zeroconf.close()
            except OSError as e:
                logger.debug("關閉 zeroconf 時發生非致命錯誤: %s", e)
            self._zeroconf = None
            self._service_info = None

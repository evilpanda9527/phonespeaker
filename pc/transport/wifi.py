"""wifi.py — WiFi transport（§8.1，M1-A 第一個做的 transport）。

PC = TCP server（預設 0.0.0.0:58482），Android = client；用 zeroconf 廣播
`_phonespeaker._tcp.local.` 讓 Android NsdManager 探索，不用手動輸入 IP。
單一 client（§15 決策）；framing 完全委由 core/tcp_client.py 處理，這裡只
負責「怎麼建立/維持/取消這條 TCP 連線」與 zeroconf 廣播生命週期。

依 §10.3 檔案隔離：這是 WiFi 專屬檔案，之後做 U1/U2/U3/BT 不應該修改這個檔案。
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


# 已知虛擬網卡軟體在 Windows 上的 adapter 描述（ifaddr 的 nice_name）常見
# 字樣，不分大小寫比對。用「軟體名稱關鍵字」而非「IP 網段」排除：虛擬網卡
# 的網段設定因軟體、因使用者環境而異且可被改掉，寫死網段（例如
# `192.168.56.x`）不準確，也可能誤擋到剛好用同網段的真實網卡；軟體名稱是
# 驅動安裝時決定的，相對穩定，跨機器/跨網段設定都能認得出來。
#
# 刻意不比對 "usb"／"remote ndis"／"rndis" 之類的字——那正是 U1(USB
# tethering)會用到的介面（實測 Windows 上會顯示成類似
# "SAMSUNG Mobile USB Remote NDIS Network Device"），必須保留、不能排除。
_VIRTUAL_ADAPTER_KEYWORDS = (
    "virtualbox",
    "vmware",
    "virtual",  # 涵蓋 "Hyper-V Virtual Ethernet Adapter"、
    # "Microsoft Wi-Fi Direct Virtual Adapter" 等
    "loopback",
    "tap-windows",
    "vpn",
)


def _is_virtual_adapter(nice_name: str) -> bool:
    lowered = nice_name.lower()
    return any(keyword in lowered for keyword in _VIRTUAL_ADAPTER_KEYWORDS)


def _local_ipv4_addresses() -> list[str]:
    """列舉本機可廣播的 IPv4 位址，供 zeroconf 廣播用。

    排除：loopback、link-local（169.254.x，通常代表 DHCP 沒要到位址、介面
    其實沒真的連上）、以及介面描述判斷出來是虛擬網卡的（見
    `_VIRTUAL_ADAPTER_KEYWORDS`）。刻意**不**排除實體 WiFi 網卡以外的其他
    實體介面——USB tethering(RNDIS) 的介面也要保留（§16-3）。
    """
    addrs: list[str] = []
    try:
        for adapter in ifaddr.get_adapters():
            if _is_virtual_adapter(adapter.nice_name):
                continue
            for ip in adapter.ips:
                if not ip.is_IPv4:
                    continue
                addr = ip.ip
                if addr == "127.0.0.1" or addr.startswith("169.254."):
                    continue
                addrs.append(addr)
    except Exception as e:  # noqa: BLE001 — 列舉網卡失敗不該讓整個 transport 掛掉
        logger.warning("列舉本機網卡位址失敗: %s", e)
    return addrs


def _default_route_ipv4_address() -> Optional[str]:
    """找出作業系統預設路由會選用的那張網卡 IP（排序用的優先提示，不是過濾器）。

    §16-3 之前這個函式曾經被當成「唯一過濾器」用——只宣告這一個位址，藉此
    避開虛擬網卡。但那個策略跟 U1 衝突：USB tethering(RNDIS) 開著時，預設
    路由通常還是走 WiFi，只宣告預設路由會把 RNDIS 那個位址整個排除掉。

    現在的角色改成單純的「排序提示」：`_local_ipv4_addresses()` 已經用介面
    描述排除掉虛擬網卡，剩下的都是可以宣告的位址；這裡只是把「作業系統認為
    最常用來對外連線」的那個排到清單最前面（多數 mDNS 客戶端行為下，越前面
    的位址越可能被優先嘗試），不會拿掉其他候選位址。

    作法：對一個公用位址呼叫 UDP `connect()`（UDP connect 只是讓 kernel 依
    路由表選定來源介面並記錄對端，*不會*真的送出任何封包，也不需要目的地
    可達），再用 `getsockname()` 讀出 kernel 選定的來源 IP。
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError as e:
        logger.debug("偵測預設路由來源位址失敗（將 fallback 用全部列舉到的位址）: %s", e)
        return None
    finally:
        try_close(probe)


class WifiTransport(Transport):
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

    @property
    def display_name(self) -> str:
        return "WiFi"

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    def connect(self) -> None:
        """開 TCP server 並阻塞等待第一個 client 連進來，同時廣播 zeroconf。"""
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
                logger.info("WiFi client 已連線: %s", addr)
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

        # 主動中斷：若 sender 執行緒正卡在 send_frame() 的阻塞式 sendall()
        # 裡（此時它持有 _send_lock），下面直接 `with self._send_lock:` 會
        # 卡在搶鎖那步等到死鎖。
        #
        # 這裡曾經先呼叫 shutdown() 再進鎖才 close()，但實測證實 shutdown()
        # 不會讓另一個執行緒裡卡住的 sendall() 返回（實測卡了 60 秒以上還
        # 是原地不動）；只有完整呼叫 close()（shutdown+close）才會讓對方的
        # sendall() 立刻用 ConnectionAbortedError 返回（實測 <1ms）。所以
        # 這裡直接在拿鎖之前對 socket 呼叫完整的 close()——這是對 fd 的
        # 操作，不需要 _send_lock，把持鎖的那個阻塞呼叫打醒、讓它釋放鎖之
        # 後，才進鎖內做狀態清理。
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
        addresses = _local_ipv4_addresses()
        if not addresses:
            logger.warning("找不到可廣播的本機 IPv4 位址，zeroconf 略過（仍可手動連線）")
            return

        # 策略（§16-3）：宣告所有通過篩選（非虛擬網卡、非 loopback/link-
        # local）的位址，讓手機自行挑可達的那個連——不能只宣告單一位址，
        # 否則 WiFi 和 USB tethering(RNDIS) 同時開著時，只宣告其中一個會
        # 讓另一個連線方式的手機探索不到（§16-3 item 2 明確要求 RNDIS 介面
        # 不可被排除掉）。只是把「作業系統預設路由」對應的位址排到最前面，
        # 常見的單一 WiFi 情境下跟只宣告一個位址的行為一致。
        preferred = _default_route_ipv4_address()
        if preferred and preferred in addresses:
            addresses = [preferred] + [a for a in addresses if a != preferred]
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
                "zeroconf 廣播已啟動: %s @ %s:%d",
                config.ZEROCONF_SERVICE_NAME,
                addresses,
                self._port,
            )
        except OSError as e:
            logger.warning("zeroconf 廣播啟動失敗（不影響手動連線）: %s", e)

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

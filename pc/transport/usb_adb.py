"""usb_adb.py — U2: USB (adb) transport（§8.2 U2，M1-B 第二個變體）。

**方向判斷（動手前先確認,避免盲目假設)：** 這個 app 的架構固定是「PC 當
TCP server、手機當 TCP client」（wifi.py／usb_rndis.py 皆如此）。adb 有兩個
方向的 port 轉發：

- `adb forward`：轉發「PC 端本機 port」的連線給「手機端」——用在手機上有
  server 在聽、PC 想連過去的情境。跟這裡的架構相反，不適用。
- `adb reverse`：轉發「手機端 127.0.0.1:PORT」的連線給「PC 端本機 port」
  ——用在 PC 上有 server 在聽、手機想連過去的情境。這正是這個 app 的架構：
  PC 開 TCP server 等連線，手機端只要連 127.0.0.1:PORT 就會被轉發過來。

所以這裡用 `adb reverse tcp:<PORT> tcp:<PORT>`，不是 `adb forward`。

跟 wifi.py／usb_rndis.py 的差別：不需要 zeroconf 廣播（手機端固定連
127.0.0.1，不需要探索 PC 的 IP），改成「先偵測 adb / 裝置、建立 adb
reverse 轉發規則，再開 TCP server 等 client」。TCP accept/send/recv 這段
跟其他兩個 transport 看起來重複，是刻意的取捨（§10.3 檔案隔離：這是 U2
專屬檔案，不 import／不修改 wifi.py、usb_rndis.py 的任何內部邏輯）。

**adb server 生命週期（todo010-4 修 bug）：** 第一次對 adb 下指令（例如
`adb devices`）時，如果 adb server（一個常駐背景執行的 `adb.exe`）還沒在
跑，adb 會自動 fork 一個起來、然後繼續留著跑，不會跟著當次指令的 client
process 一起結束。這個 app 原本只在 disconnect() 移除 `adb reverse` 規則，
從沒主動關過這個常駐的 server process，於是每次 U2 連線都會留下一個孤兒
`adb.exe`：關閉 app／拔 USB 後它還在，繼續對已經斷線的裝置輪詢，每隔一段
時間跳出 Windows「該設備已停止響應或已斷開連接」的警告。

修法：connect() 一開始、還沒對 adb 下任何指令之前，先探測 adb server 是否
已經在監聽（見 `_is_adb_server_listening()`）。

- 沒在監聽 → 這次連線期間用到的 adb server 一定是**我們自己**啟動的，
  disconnect() 收尾（或 connect() 中途失敗）時就負責 `adb kill-server`
  把它關掉，不留孤兒。
- 已經在監聽 → 代表使用者自己另外有 adb server 在跑（例如開著 Android
  Studio、或手動执行過 adb 指令），這種情況下**不會**呼叫 kill-server，
  避免把不屬於我們啟動的 server 也一併殺掉、影響到使用者其他的 adb 工作
  流程。

**已知取捨（技術上無法百分之百精準區分「這個 server 是不是我們啟的」）：**
如果使用者的 adb server 剛好在「我們探測完、判定沒在跑」跟「我們自己那次
adb 指令實際把它啟動起來」中間的極短空檔被别的程式一起用上，我們收尾時的
`adb kill-server` 還是會把它關掉——這裡優先選擇「不留孤兒 process／不留
斷線警告」，而不是絕對保守。另外，`adb kill-server` 沒有「只殺這個 client
建立的規則」這種粒度，指令本身就是整台機器唯一一份 adb server 的開關；
一旦判定要關，就是關掉整個 server（連同其他裝置的 adb reverse/forward
規則都會一起消失），這點會影響到系統整體的 adb 使用者，請知悉。
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import os
import shutil
import socket
import subprocess
import threading
from typing import Optional

import config
import paths
from core.handshake import Frame
from core.tcp_client import ConnectionClosed
from core.tcp_client import configure_socket_for_streaming
from core.tcp_client import recv_frame as _recv_frame
from core.tcp_client import send_frame as _send_frame
from core.tcp_client import try_close
from transport.base import Transport, TransportCancelled, TransportError

logger = logging.getLogger(__name__)

_ACCEPT_POLL_INTERVAL_S = 0.5

# Windows 上用 pythonw 執行 GUI 時，subprocess 預設仍可能彈出一個黑色主控台
# 視窗；加這個旗標避免使用者看到跟本次操作無關的視窗閃現。
_SUBPROCESS_CREATIONFLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@dataclasses.dataclass
class _AdbDevice:
    serial: str
    state: str


class AdbNotFoundError(TransportError):
    """PATH 裡找不到 adb 執行檔時拋出（§11 之前先假設使用者自行安裝好）。"""


class AdbState(enum.Enum):
    """todo011 §2：U2 前置狀態偵測——把 `adb devices` 的結果收斂成使用者
    看得懂的三種狀態（跟手機端 log 顯示邏輯一一對應，見本檔 [probe_state]
    docstring）。"""

    NOT_FOUND = "not_found"  # 情況 1：完全沒偵測到裝置（含 adb 逾時/失敗，一律視同找不到）
    UNAUTHORIZED = "unauthorized"  # 情況 2：偵測到裝置但尚未在手機上按「允許」
    READY = "ready"  # 情況 3：至少一台已授權（state == "device"），可以連線


# 跟 [AdbState] 三種狀態一一對應的使用者訊息，供 connect() 失敗路徑跟
# [probe_state] 共用同一份文字，避免兩處各寫一次、日後改一邊漏改另一邊。
# READY 沒有對應訊息：就緒不顯示警告（見 todo011 §2 一）。
_MSG_NOT_FOUND = "請確認手機已用 USB 連接電腦，並開啟「USB 偵錯」（開發人員選項）。"
_MSG_UNAUTHORIZED = "請在手機上點擊「允許 USB 偵錯」的授權對話框（若沒跳出過，拔掉 USB 線重插一次）。"


def _classify_devices(devices: list[_AdbDevice]) -> AdbState:
    """把 `adb devices` 列出的裝置清單分類成 [AdbState]。跟裝置數量無關，
    只要有一台已授權就視為就緒；沒有已授權但有未授權的就是「等待授權」；
    其餘（含完全沒有裝置、或只有 offline 等其他過渡態）一律視同「找不到
    裝置」——這三種是使用者實際會看到、會採取行動的狀態，其餘細節只留在
    log 裡（見呼叫端）。"""
    if any(d.state == "device" for d in devices):
        return AdbState.READY
    if any(d.state == "unauthorized" for d in devices):
        return AdbState.UNAUTHORIZED
    return AdbState.NOT_FOUND


def probe_state(timeout: float = None) -> AdbState:
    """todo011 §2：U2 前置狀態主動偵測——只查詢 `adb devices`、不建立任何
    連線或 `adb reverse` 規則，供 GUI 每隔數秒呼叫一次、即時顯示對應提示
    （見 pc/gui.py 的 U2 偵測輪詢）。

    刻意跟 [UsbAdbTransport.connect] 分開、不管 adb server 生命週期收尾
    （不呼叫 `adb kill-server`）：todo010-4 那個孤兒 adb.exe 問題的根因是
    「建立過 `adb reverse` 規則、裝置後來斷線，殘留的規則讓 adb server
    持續對著已消失的裝置跳警告」——這裡從頭到尾只讀 `adb devices`、從不
    建立任何規則，就算持續呼叫這個函式順帶讓 adb server 保持啟動，也只是
    等同使用者自己在命令列反覆打 `adb devices`，是 adb 本身的正常行為，
    不會重現那個孤兒規則的情境，不需要特別收尾。"""
    if timeout is None:
        timeout = config.ADB_COMMAND_TIMEOUT_S
    adb_path = _find_adb_executable()
    if adb_path is None:
        return AdbState.NOT_FOUND
    try:
        devices = _list_adb_devices(adb_path, timeout)
    except TransportError as e:
        logger.debug("probe_state(): %s（歸類為 not_found）", e)
        return AdbState.NOT_FOUND
    return _classify_devices(devices)


def _adb_server_port() -> int:
    """回傳 adb server 監聽的 port。使用者可能透過 `ANDROID_ADB_SERVER_PORT`
    環境變數自訂（adb 官方支援的用法）；我們的探測跟實際下 adb 指令用的是
    同一個 process 環境，兩邊要看同一個 port 才會判斷一致，所以這裡也讀
    同一個環境變數，沒設定才退回官方預設值 `config.ADB_SERVER_PORT`。"""
    raw = os.environ.get("ANDROID_ADB_SERVER_PORT", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning(
                "ANDROID_ADB_SERVER_PORT=%r 不是合法的數字，改用預設 port %d",
                raw, config.ADB_SERVER_PORT,
            )
    return config.ADB_SERVER_PORT


def _is_adb_server_listening() -> bool:
    """探測 adb server 是不是已經在監聽（見本檔開頭「adb server 生命週期」
    說明）。只是短逾時的 TCP connect 探測，不牽動 adb 本身。"""
    try:
        with socket.create_connection(
            (config.ADB_SERVER_HOST, _adb_server_port()),
            timeout=config.ADB_SERVER_PROBE_TIMEOUT_S,
        ):
            return True
    except OSError:
        return False


def _find_adb_executable() -> Optional[str]:
    """優先找隨附的 adb（打包後安裝檔會放在 exe 旁的 adb/ 子目錄，見
    todo010-1 pc/paths.py），這樣使用者不需要自己裝 Android SDK Platform-
    Tools 或設定 PATH。找不到隨附版本時，fallback 回原本的 PATH 查找
    （開發模式 / 使用者自行安裝 adb 的既有行為完全不變）。"""
    bundled = paths.app_dir() / "adb" / "adb.exe"
    if bundled.is_file():
        return str(bundled)
    return shutil.which(config.ADB_EXECUTABLE)


def _run_adb(adb_path: str, args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        [adb_path, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_SUBPROCESS_CREATIONFLAGS,
    )


def _list_adb_devices(adb_path: str, timeout: float) -> list[_AdbDevice]:
    """回傳 `adb devices` 列出的所有裝置（含未授權/離線的，讓呼叫端自行判斷要不要用）。

    todo011 §2：逾時／指令本身失敗這幾種情況，使用者看到的都應該是「情況1：
    找不到裝置」那句清楚指引，而不是技術性的逾時錯誤字樣——技術細節（逾時
    秒數、stderr 等）改成寫進 log，供之後排查問題用，不再進到拋給使用者看
    的例外訊息裡。"""
    try:
        result = _run_adb(adb_path, ["devices"], timeout)
    except subprocess.TimeoutExpired as e:
        logger.warning("執行 `adb devices` 逾時（%.1fs）: %s", timeout, e)
        raise TransportError(_MSG_NOT_FOUND) from e
    except OSError as e:
        logger.warning("執行 `adb devices` 失敗: %s", e)
        raise TransportError(_MSG_NOT_FOUND) from e
    if result.returncode != 0:
        logger.warning(
            "`adb devices` 回傳非 0（%d）: %s", result.returncode, result.stderr.strip()
        )
        raise TransportError(_MSG_NOT_FOUND)

    devices: list[_AdbDevice] = []
    # 第一行固定是 "List of devices attached" 標題，跳過。
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        devices.append(_AdbDevice(serial=parts[0], state=parts[1]))
    return devices


class UsbAdbTransport(Transport):
    """U2：USB (adb)。PC 是 TCP server，手機端連 127.0.0.1:PORT，靠 PC 端
    先執行的 `adb reverse` 轉發過來（見本檔開頭的方向判斷）。"""

    def __init__(
        self,
        host: str = config.ADB_HOST,
        port: int = config.TCP_LISTEN_PORT,
    ):
        self._host = host
        self._port = port
        self._listen_sock: Optional[socket.socket] = None
        self._conn: Optional[socket.socket] = None
        self._send_lock = threading.Lock()

        # adb reverse 規則的擁有者資訊，只有成功建立規則後才會有值；
        # disconnect() / connect() 失敗時的清理都靠這兩個欄位判斷「有沒有
        # 規則需要移除」，避免對一個從沒建立過的規則呼叫 `adb reverse
        # --remove`（雖然無害，但沒必要）。
        self._adb_path: Optional[str] = None
        self._serial: Optional[str] = None

        # todo010-4：這次 connect() 用到的 adb server 是不是我們自己啟動
        # 的（connect() 一開始探測、disconnect()／連線失敗收尾時消費）。
        # 只有 True 時，收尾才會呼叫 `adb kill-server`，避免誤殺使用者自己
        # 開著的 adb server（見本檔開頭說明）。
        self._server_owned_by_us: bool = False

    @property
    def display_name(self) -> str:
        return "USB (adb)"

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    def connect(self) -> None:
        """偵測 adb / 裝置 → 建立 adb reverse → 開 TCP server 阻塞等 client。"""
        if self._conn is not None:
            raise TransportError("已經有連線中的 client，請先 disconnect()")

        adb_path = _find_adb_executable()
        if adb_path is None:
            raise AdbNotFoundError(
                f"找不到 adb 執行檔（PATH 裡沒有 `{config.ADB_EXECUTABLE}`）。"
                "請先安裝 Android SDK Platform-Tools，並確認能在命令列直接"
                "執行 `adb version` 成功後再試一次。"
            )

        # todo010-4：還沒對 adb 下任何指令之前先探測——沒在監聽就代表接下來
        # 任何一個 adb 指令（`adb devices`／`adb reverse`）若真的觸發 adb
        # 自動啟動 server，那個 server 就是「我們啟動的」，收尾時要負責關掉
        # （見本檔開頭「adb server 生命週期」說明）。
        self._server_owned_by_us = not _is_adb_server_listening()

        try:
            devices = _list_adb_devices(adb_path, config.ADB_COMMAND_TIMEOUT_S)
        except TransportError:
            self._kill_adb_server_if_owned(adb_path)
            raise

        usable = [d for d in devices if d.state == "device"]
        if not usable:
            self._kill_adb_server_if_owned(adb_path)
            if devices:
                # 情況 1/2 的詳細裝置清單只寫進 log（供排查），使用者看到的
                # 例外訊息統一用 _MSG_NOT_FOUND / _MSG_UNAUTHORIZED 兩句固定
                # 文字（todo011 §2，跟 [probe_state] 共用同一份分類與文字）。
                logger.info(
                    "adb 偵測到裝置但目前無法使用: %s",
                    "、".join(f"{d.serial}({d.state})" for d in devices),
                )
            state = _classify_devices(devices)
            if state is AdbState.UNAUTHORIZED:
                raise TransportError(_MSG_UNAUTHORIZED)
            raise TransportError(_MSG_NOT_FOUND)
        if len(usable) > 1:
            logger.warning(
                "adb 偵測到多台已授權裝置，PhoneSpeaker 目前只支援單一裝置"
                "（§15），將使用第一台: %s（其餘: %s）",
                usable[0].serial,
                [d.serial for d in usable[1:]],
            )
        serial = usable[0].serial

        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listen_sock.bind((self._host, self._port))
        except OSError as e:
            try_close(listen_sock)
            self._kill_adb_server_if_owned(adb_path)
            raise TransportError(f"無法監聽 {self._host}:{self._port}: {e}") from e
        listen_sock.listen(1)
        listen_sock.settimeout(_ACCEPT_POLL_INTERVAL_S)
        self._listen_sock = listen_sock

        # 先確保 PC 端已經在聽，再建立 adb reverse 規則，避免手機那邊剛好
        # 在這個時間點連過來卻撲空。
        try:
            self._adb_reverse(adb_path, serial)
        except TransportError:
            try_close(listen_sock)
            self._listen_sock = None
            self._kill_adb_server_if_owned(adb_path)
            raise

        accepted = False
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
                accepted = True
                logger.info("USB (adb) client 已連線: %s（裝置序號 %s）", addr, serial)
                return
            raise TransportCancelled("connect() 被取消")
        finally:
            if self._listen_sock is not None:
                try_close(self._listen_sock)
                self._listen_sock = None
            if not accepted:
                # 還沒真的建立連線就結束（取消/逾時等）：adb reverse 規則
                # 沒有用武之地了，清掉它，不留下沒人用的轉發規則；如果這次
                # 連線用到的 adb server 是我們啟動的，也一併關掉，不留孤兒
                # process（todo010-4）。
                self._adb_reverse_remove()
                self._kill_adb_server_if_owned(adb_path)

    def request_cancel(self) -> None:
        sock = self._listen_sock
        self._listen_sock = None
        try_close(sock)

    def disconnect(self) -> None:
        self.request_cancel()

        # 主動中斷（沿用 wifi.py／usb_rndis.py §16-4 的教訓）：在拿
        # _send_lock 之前直接對 socket 呼叫完整的 close()，讓卡在阻塞式
        # sendall() 裡的 sender 執行緒立刻出錯返回；若先進鎖才 close()，
        # 持鎖中的阻塞呼叫會讓這裡卡死等鎖。
        conn = self._conn
        if conn is not None:
            try_close(conn)

        with self._send_lock:
            self._conn = None

        # _adb_reverse_remove() 會把 self._adb_path 清成 None，所以要在呼叫
        # 前先留一份給後面 kill-server 用（如果這次是我們啟動的 adb server）。
        adb_path = self._adb_path

        # 連線已經建立過（或正要建立）的 adb reverse 規則，這裡才是真正
        # 「這條連線结束了」的時間點，移除規則不留殘留。
        self._adb_reverse_remove()

        # todo010-4：這條 U2 連線真正結束了，如果這次連線用到的 adb server
        # 是我們自己啟動的，這裡負責關掉，不留孤兒 adb.exe 繼續對已斷線的
        # 裝置跳「已停止響應」警告（見本檔開頭「adb server 生命週期」說明）。
        self._kill_adb_server_if_owned(adb_path)

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

    def _adb_reverse(self, adb_path: str, serial: str) -> None:
        try:
            result = _run_adb(
                adb_path,
                ["-s", serial, "reverse", f"tcp:{self._port}", f"tcp:{self._port}"],
                config.ADB_COMMAND_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as e:
            raise TransportError(f"建立 `adb reverse` 逾時（{config.ADB_COMMAND_TIMEOUT_S}s）: {e}") from e
        except OSError as e:
            raise TransportError(f"執行 `adb reverse` 失敗: {e}") from e
        if result.returncode != 0:
            raise TransportError(
                f"`adb reverse tcp:{self._port} tcp:{self._port}` 失敗: "
                f"{(result.stderr or result.stdout).strip()}"
            )
        self._adb_path = adb_path
        self._serial = serial
        logger.info(
            "adb reverse 已建立：裝置 %s 的 127.0.0.1:%d → PC 的 %s:%d",
            serial, self._port, self._host, self._port,
        )

    def _adb_reverse_remove(self) -> None:
        adb_path, serial = self._adb_path, self._serial
        self._adb_path = None
        self._serial = None
        if adb_path is None or serial is None:
            return
        try:
            _run_adb(
                adb_path,
                ["-s", serial, "reverse", "--remove", f"tcp:{self._port}"],
                config.ADB_COMMAND_TIMEOUT_S,
            )
            logger.info("adb reverse 規則已移除（裝置 %s，port %d）", serial, self._port)
        except (subprocess.TimeoutExpired, OSError) as e:
            # 移除失敗不該讓 disconnect() 拋例外（介面約定：disconnect() 不拋）；
            # 常見成因是手機已經拔線，adb 早已認不到這台裝置，安全忽略即可。
            logger.debug("移除 adb reverse 時發生非致命錯誤（可忽略）: %s", e)

    def _kill_adb_server_if_owned(self, adb_path: Optional[str]) -> None:
        """todo010-4：只在「這次連線用到的 adb server 是我們自己啟動的」
        （見 connect() 開頭 `_is_adb_server_listening()` 探測）才真的執行
        `adb kill-server`，把常駐的 adb.exe 一起結束掉，不留孤兒 process
        持續對已斷線的裝置跳「已停止響應」警告。使用者自己另外開著的 adb
        server（探測時就已經在監聽）完全不會被這裡動到。

        `self._server_owned_by_us` 用完立刻重置為 False：disconnect() 跟
        connect() 失敗收尾都可能呼叫到這裡，重置後才不會同一次探測結果被
        重複消費、對一個早就關掉的 server 再呼叫一次 kill-server（雖然無害，
        但沒必要）。
        """
        owned, self._server_owned_by_us = self._server_owned_by_us, False
        if not owned or adb_path is None:
            return
        try:
            _run_adb(adb_path, ["kill-server"], config.ADB_COMMAND_TIMEOUT_S)
            logger.info("adb server 已結束（本程式為 U2 啟動的，非使用者既有的 adb server）")
        except (subprocess.TimeoutExpired, OSError) as e:
            # 跟 _adb_reverse_remove() 同樣的考量：不該讓 disconnect() 拋例外，
            # 安全忽略即可（常見成因：裝置已拔線、adb 早已找不到它）。
            logger.debug("結束 adb server 時發生非致命錯誤（可忽略）: %s", e)

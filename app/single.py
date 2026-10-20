"""창은 하나만. 이미 켜져 있으면 연 파일을 그 창에 넘기고(탭으로 열린다) 이 프로그램은 바로 끝난다.

탐색기에서 여러 파일을 골라 열면 윈도우가 파일마다 프로그램을 따로 켠다. 거의 동시에 켜지므로
먼저 뮤텍스를 잡은 하나가 받는 쪽이 되고, 나머지는 받는 쪽 서버가 뜰 때까지 잠깐 기다렸다가 넘긴다.
받는 쪽 창이 닫히는 중이면 뮤텍스를 놓으므로, 기다리던 쪽이 그 자리를 이어받아 새 창이 된다.
"""
from __future__ import annotations

import json
import os
import sys
import time

from .appinfo import APP_ID, ORG

# 설치본과 소스 실행(개발)은 따로 논다. 개발 중에 띄운 창이 설치된 RPDF 로 넘어가지 않게
_TAG = f"{ORG}.{APP_ID}" + ("" if getattr(sys, "frozen", False) else ".dev")
_USER = os.environ.get("USERNAME", "")
SERVER = f"{_TAG}.open.{_USER}"
MUTEX = f"{_TAG}.first.{_USER}"
_mutex = None


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def claim_first() -> bool:
    """처음 켜진 프로그램이면 True(뮤텍스를 쥔다). 윈도우가 아니면 늘 True."""
    global _mutex
    if os.name != "nt":
        return True
    if _mutex:
        return True
    import ctypes
    k = _kernel32()
    h = k.CreateMutexW(None, False, MUTEX)
    if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
        # 손잡이를 쥐고 있으면 첫 프로그램이 끝나도 뮤텍스가 안 사라진다. 바로 놓는다
        if h:
            k.CloseHandle(h)
        return False
    _mutex = h
    return True


def release():
    """창을 닫을 때. 이 뒤로 켜지는 프로그램은 넘기지 않고 제 창을 띄운다."""
    global _mutex
    if os.name == "nt" and _mutex:
        _kernel32().CloseHandle(_mutex)
    _mutex = None


def send(paths: list[str], wait: float = 8.0) -> bool:
    """켜져 있는 창에 파일을 넘긴다. 넘겼으면 True(이 프로그램은 끝내면 된다).
    False 면 이 프로그램이 창을 띄운다(받는 쪽이 닫혀 이쪽이 첫 프로그램이 됐거나, 끝내 못 넘김)."""
    from PySide6.QtNetwork import QLocalSocket
    if os.name == "nt":
        try:   # 받는 창이 앞으로 나올 수 있게(윈도우는 남의 프로그램이 앞으로 나오는 것을 막는다)
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except Exception:  # noqa: BLE001
            pass
    data = json.dumps([os.path.abspath(p) for p in paths], ensure_ascii=False).encode("utf-8")
    end = time.monotonic() + wait
    while True:
        s = QLocalSocket()
        s.connectToServer(SERVER)
        if s.waitForConnected(500):
            # 받는 쪽이 「받았다」고 답할 때까지 본다. 답이 없으면 다시 넘긴다(같은 파일은 한 탭으로만 열린다)
            s.write(data + b"\n")
            ok = s.waitForBytesWritten(2000) and s.waitForReadyRead(5000) and bytes(s.readAll()).startswith(b"ok")
            s.disconnectFromServer()
            if ok:
                return True
        if claim_first() or time.monotonic() > end:
            return False
        time.sleep(0.15)


class Receiver:
    """첫 프로그램 쪽. 넘어온 파일 목록을 on_paths(list) 로 부른다."""

    def __init__(self, on_paths):
        from PySide6.QtNetwork import QLocalServer
        self.on_paths = on_paths
        QLocalServer.removeServer(SERVER)   # 지난번에 튕기고 남은 자리
        self.server = QLocalServer()
        self.server.newConnection.connect(self._new)
        self.listen()

    def listen(self):
        if not self.server.isListening():
            self.server.listen(SERVER)

    def stop(self):
        self.server.close()

    def _new(self):
        while self.server.hasPendingConnections():
            c = self.server.nextPendingConnection()
            buf = bytearray()

            def read(c=c, buf=buf):
                buf.extend(bytes(c.readAll()))
                if buf.endswith(b"\n"):
                    try:
                        paths = json.loads(buf.decode("utf-8"))
                    except ValueError:
                        paths = []
                    buf.clear()
                    c.write(b"ok\n"); c.flush()
                    self.on_paths([p for p in paths if isinstance(p, str)])

            c.readyRead.connect(read)
            c.disconnected.connect(c.deleteLater)
            if c.bytesAvailable():   # 이벤트 루프가 돌기 전에 이미 와 있던 것
                read()

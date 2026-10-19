"""새 버전 확인·받기·설치 시작. Qt 모름(화면 쪽은 ui/update.py).

배포 자리는 GitHub 공개 저장소 RELEASE_REPO 의 릴리스다(2026-10-19 사용자 결정: 집·회사 어디서나 받게).
릴리스마다 setup exe 와 latest.json 이 붙고(release.py 가 올림), 앱은 늘 같은 주소
`releases/latest/download/latest.json` 을 읽어 버전을 대조한다.
시험할 때는 PDFAPP_UPDATE_SOURCE 에 폴더(latest.json 과 setup 이 든 곳)나 다른 주소를 주면 그곳을 본다.

설치는 setup 을 조용히(/VERYSILENT) 띄우고 앱은 바로 끝낸다. setup 은 앱이 꺼지기를 기다렸다가
(MUTEX_NAME) 덮어 설치하고 `--after-update` 로 다시 켠다. 설정(%APPDATA%)은 setup 이 건드리지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .appinfo import VERSION

RELEASE_REPO = "kyijgnes/pdf-app-releases"
LATEST_URL = f"https://github.com/{RELEASE_REPO}/releases/latest/download/latest.json"
MUTEX_NAME = "PDFEditor.kyijgnes.Running"   # setup 이 앱이 켜져 있는지 보는 이름(release.py 가 setup.iss 에 넘긴다)
SOURCE_ENV = "PDFAPP_UPDATE_SOURCE"
AFTER_FLAG = "--after-update"               # setup 이 업데이트 뒤 다시 켤 때 붙인다
REOPEN_KEY = "reopen_after_update"          # settings.json: 업데이트 직전에 열려 있던 문서
_UA = {"User-Agent": f"PDFEditor-updater/{VERSION}"}   # 머리말은 latin-1 만 된다(앱 이름이 한글이라 쓰지 않음)
_DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "PDFEditor-update")
_mutex = None


def parse_version(v) -> tuple[int, int, int]:
    """'0.1.2' · 'v0.1.2' → (0, 1, 2). 숫자가 아닌 꼬리는 버린다."""
    nums = []
    for part in str(v).strip().lstrip("vV").split(".")[:3]:
        digits = ""
        for ch in part:
            if not ch.isdigit():
                break
            digits += ch
        nums.append(int(digits or 0))
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)  # type: ignore[return-value]


def installed() -> bool:
    """설치본(PyInstaller exe)으로 도는가. 소스로 띄운 개발 실행은 켤 때 저절로 보지 않는다."""
    return bool(getattr(sys, "frozen", False))


def hold_running_mutex():
    """켜져 있는 동안 이름 붙은 뮤텍스를 쥔다. setup·제거가 이것으로 앱이 켜져 있는지 본다."""
    global _mutex
    if os.name != "nt" or _mutex:
        return
    import ctypes
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)


@dataclass
class Release:
    version: str
    setup: str            # setup 파일 이름
    url: str              # 받을 곳(주소 또는 로컬 경로)
    sha256: str = ""
    size: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def newer(self) -> bool:
        return parse_version(self.version) > parse_version(VERSION)


def source() -> str:
    return os.environ.get(SOURCE_ENV, "").strip() or LATEST_URL


def _is_url(s: str) -> bool:
    return s.lower().startswith(("http://", "https://"))


def check(timeout: float = 10) -> Release:
    """배포 자리의 최신 버전. 닿지 않거나 형식이 틀리면 예외를 그대로 올린다."""
    src = source()
    if _is_url(src):
        req = urllib.request.Request(src, headers={**_UA, "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
            final = r.geturl()
        url = data.get("url") or urllib.parse.urljoin(final, urllib.parse.quote(data["setup"]))
    else:
        path = os.path.join(src, "latest.json") if os.path.isdir(src) else src
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        url = os.path.join(os.path.dirname(path), data["setup"])
    return Release(str(data["version"]), str(data["setup"]), url, str(data.get("sha256", "")),
                   int(data.get("size") or 0), [str(n) for n in (data.get("notes") or [])])


def download(rel: Release, progress=None) -> str:
    """setup 을 임시 폴더에 받고 sha256 을 대조한다. 받은 파일 경로를 돌려준다."""
    os.makedirs(_DOWNLOAD_DIR, exist_ok=True)
    for name in os.listdir(_DOWNLOAD_DIR):   # 지난번에 받은 것
        try:
            os.remove(os.path.join(_DOWNLOAD_DIR, name))
        except OSError:
            pass
    dest = os.path.join(_DOWNLOAD_DIR, os.path.basename(rel.setup))
    part = dest + ".part"
    if _is_url(rel.url):
        src = urllib.request.urlopen(urllib.request.Request(rel.url, headers=_UA), timeout=30)
        total = int(src.headers.get("Content-Length") or rel.size or 0)
    else:
        src = open(rel.url, "rb")
        total = os.path.getsize(rel.url)
    h = hashlib.sha256()
    done = 0
    with src, open(part, "wb") as out:
        while True:
            b = src.read(1 << 20)
            if not b:
                break
            out.write(b); h.update(b); done += len(b)
            if progress:
                progress(done, total, f"받는 중 {done / 1048576:.0f} / {total / 1048576:.0f} MB" if total else "받는 중")
    if rel.sha256 and h.hexdigest().lower() != rel.sha256.lower():
        os.remove(part)
        raise ValueError("받은 파일이 올린 파일과 다릅니다(sha256 불일치). 다시 받아 보세요")
    os.replace(part, dest)
    return dest


def clean_env() -> dict:
    """setup·다시 켜질 앱에 줄 환경변수. 이 exe 의 PyInstaller 자국을 걷어낸다(새 버전이 옛 자리를 보지 않게)."""
    env = dict(os.environ)
    for k in list(env):
        if k.startswith(("_PYI", "_MEI")) or k in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
            env.pop(k)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    base = getattr(sys, "_MEIPASS", "")
    if base:
        b = os.path.normcase(os.path.abspath(base))
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                      if p and not os.path.normcase(os.path.abspath(p)).startswith(b))
    return env


def run_setup(path: str) -> None:
    """setup 을 조용히 띄운다. 부른 쪽은 곧바로 끝나야 한다(setup 이 앱이 꺼지길 기다렸다 덮어쓰고 다시 켠다)."""
    log = os.path.join(os.path.dirname(path), "setup.log")
    args = [path, "/VERYSILENT", "/NORESTART", "/SP-", f"/LOG={log}", "/RELAUNCH"]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:   # 클로드 같은 job 안에서 띄워졌으면 빠져나간다(앱이 끝날 때 같이 죽지 않게)
        subprocess.Popen(args, env=clean_env(), close_fds=True, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
    except OSError:
        subprocess.Popen(args, env=clean_env(), close_fds=True, creationflags=flags)

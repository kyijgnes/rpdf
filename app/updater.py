"""새 버전 확인·받기·설치 시작. Qt 모름(화면 쪽은 ui/update.py).

배포 자리는 GitHub 공개 저장소 RELEASE_REPO 의 릴리스다(2026-10-19 사용자 결정: 집·회사 어디서나 받게).
릴리스마다 setup exe 와 latest.json 이 붙고(태그를 밀면 GitHub Actions 가 올림, release.py·.github/workflows/release.yml), 앱은 늘 같은 주소
`releases/latest/download/latest.json` 을 읽어 버전을 대조한다.
시험할 때는 PDFAPP_UPDATE_SOURCE 에 폴더(latest.json 과 setup 이 든 곳)나 다른 주소를 주면 그곳을 본다.

믿는 근거는 배포자 서명이다(2026-10-21). latest.json 옆의 latest.sig 가 배포자 비밀키로 서명한 것이어야 하고
(app/signing.py, 서명은 release.py 가 이 PC 에서 붙인다. GitHub 에는 비밀키가 없다), setup 은 거기 적힌 sha256·크기와 같아야 한다.
그래서 PDFAPP_UPDATE_SOURCE 로 다른 곳을 가리켜도 서명 없는 setup 은 안 깔린다. 주소는 https 의 GitHub 자리
(ALLOWED_HOSTS)만 받고 넘겨주기(redirect)도 그 안에서만 따라간다. 지금보다 낮거나 같은 버전은 받지 않는다.

설치는 setup 을 조용히(/VERYSILENT) 띄우고 앱은 바로 끝낸다. setup 은 앱이 꺼지기를 기다렸다가
(MUTEX_NAME) 덮어 설치하고 `--after-update` 로 다시 켠다. 설정(%APPDATA%)은 setup 이 건드리지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import signing
from .appinfo import VERSION

RELEASE_REPO = "kyijgnes/rpdf"   # 10-20 pdf-app-releases 에서 이름을 바꿈(옛 주소는 GitHub 이 넘겨 주어 0.1.0 도 여기를 찾는다)
LATEST_URL = f"https://github.com/{RELEASE_REPO}/releases/latest/download/latest.json"
MUTEX_NAME = "RPDF.kyijgnes.Running"          # setup 이 앱이 켜져 있는지 보는 이름(make_setup.py 가 setup.iss 에 넘긴다)
SOURCE_ENV = "PDFAPP_UPDATE_SOURCE"
SIG_NAME = "latest.sig"                     # latest.json 의 배포자 서명(release.py 가 릴리스에 붙인다)
AFTER_FLAG = "--after-update"               # setup 이 업데이트 뒤 다시 켤 때 붙인다
REOPEN_KEY = "reopen_after_update"          # settings.json: 업데이트 직전에 열려 있던 문서
# 받을 수 있는 자리. GitHub 릴리스 파일은 github.com 에서 release-assets(예전엔 objects).githubusercontent.com 으로 넘겨준다
ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
MAX_SMALL = 64 * 1024                       # latest.json·서명·정책 파일은 작다. 이보다 크면 읽지 않는다
_UA = {"User-Agent": f"RPDF-updater/{VERSION}"}   # 머리말은 latin-1 만 된다
# 받은 setup 은 내 사용자 폴더에만(TEMP 가 C:\Users\Public 아래로 잡힌 PC 가 있다. 남이 바꿔 끼울 수 있는 자리에서 실행하지 않게)
_DOWNLOAD_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "Temp", "RPDF-update")
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


def allowed_url(u: str) -> bool:
    try:
        p = urllib.parse.urlsplit(u)
    except ValueError:
        return False
    return p.scheme == "https" and (p.hostname or "").lower() in ALLOWED_HOSTS and not p.username and not p.password


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise urllib.error.URLError(f"허용하지 않은 곳으로 넘겨줌: {urllib.parse.urlsplit(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_Redirect)


def open_url(url: str, timeout: float, extra: dict | None = None):
    """GitHub 자리만 연다(넘겨주기 포함). 응답 객체를 돌려준다."""
    if not allowed_url(url):
        raise ValueError(f"허용하지 않은 주소입니다: {url}")
    return _opener.open(urllib.request.Request(url, headers={**_UA, **(extra or {})}), timeout=timeout)


def read_small(src: str, timeout: float = 10) -> tuple[bytes, str, str]:
    """작은 파일(주소 또는 로컬 경로)을 읽는다. (내용, 최종 자리, 서버 Date 머리말 또는 '')."""
    date = ""
    if _is_url(src):
        with open_url(src, timeout, {"Cache-Control": "no-cache"}) as r:
            data = r.read(MAX_SMALL + 1)
            final = r.geturl()
            date = r.headers.get("Date", "")
    else:
        with open(src, "rb") as f:
            data = f.read(MAX_SMALL + 1)
        final = src
    if len(data) > MAX_SMALL:
        raise ValueError("배포 자리의 파일이 너무 큽니다")
    return data, final, date


def _sig_source(src: str) -> str:
    if _is_url(src):
        return src.rsplit("/", 1)[0] + "/" + SIG_NAME   # releases/latest/download/latest.sig 처럼 같은 줄기
    return os.path.join(os.path.dirname(src), SIG_NAME)


def check(timeout: float = 10) -> Release:
    """배포 자리의 최신 버전. 닿지 않거나 형식·서명이 틀리면 예외를 그대로 올린다."""
    src = source()
    if not _is_url(src) and os.path.isdir(src):
        src = os.path.join(src, "latest.json")
    raw, final, _ = read_small(src, timeout)
    try:
        sig, _, _ = read_small(_sig_source(src), timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError("새 버전 안내에 배포자 서명이 아직 없습니다. 잠시 뒤 다시 확인하세요") from e
        raise
    except FileNotFoundError as e:
        raise ValueError("새 버전 안내에 배포자 서명이 없습니다") from e
    if not signing.ok(signing.DOMAIN_LATEST, raw, sig.decode("ascii", "replace")):
        raise ValueError("새 버전 안내의 배포자 서명이 맞지 않습니다. 설치하지 않습니다")
    data = json.loads(raw.decode("utf-8"))
    name = str(data["setup"])
    if os.path.basename(name) != name or not name.lower().endswith(".exe"):
        raise ValueError(f"setup 이름이 이상합니다: {name}")
    sha = str(data.get("sha256", "")).lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("새 버전 안내에 sha256 이 없습니다")
    if _is_url(final):
        url = str(data.get("url") or urllib.parse.urljoin(final, urllib.parse.quote(name)))
        if not allowed_url(url):
            raise ValueError(f"허용하지 않은 받을 곳입니다: {url}")
    else:
        url = os.path.join(os.path.dirname(final), name)
    return Release(str(data["version"]), name, url, sha,
                   int(data.get("size") or 0), [str(n) for n in (data.get("notes") or [])])


def _fresh_dir() -> str:
    """받을 자리: 내 사용자 폴더 아래, 받을 때마다 새 하위 폴더. 지난번 것은 지운다."""
    os.makedirs(_DOWNLOAD_DIR, exist_ok=True)
    for name in os.listdir(_DOWNLOAD_DIR):
        p = os.path.join(_DOWNLOAD_DIR, name)
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
        except OSError:
            pass
    return tempfile.mkdtemp(prefix="get-", dir=_DOWNLOAD_DIR)


def download(rel: Release, progress=None) -> str:
    """setup 을 임시 폴더에 받고 sha256·크기·코드 서명을 본다. 받은 파일 경로를 돌려준다."""
    if not rel.newer:
        raise ValueError(f"지금 버전({VERSION})보다 높지 않아 받지 않습니다: {rel.version}")
    if len(rel.sha256) != 64:
        raise ValueError("sha256 이 없는 setup 은 받지 않습니다")
    folder = _fresh_dir()
    dest = os.path.join(folder, os.path.basename(rel.setup))
    part = dest + ".part"
    if _is_url(rel.url):
        src = open_url(rel.url, 30)
        total = int(src.headers.get("Content-Length") or rel.size or 0)
    else:
        src = open(rel.url, "rb")
        total = os.path.getsize(rel.url)
    limit = (rel.size or total) + (1 << 20) if (rel.size or total) else 1 << 30
    h = hashlib.sha256()
    done = 0
    with src, open(part, "xb") as out:
        while True:
            b = src.read(1 << 20)
            if not b:
                break
            done += len(b)
            if done > limit:
                break
            out.write(b); h.update(b)
            if progress:
                progress(done, total, f"받는 중 {done / 1048576:.0f} / {total / 1048576:.0f} MB" if total else "받는 중")
    if done > limit or (rel.size and done != rel.size):
        os.remove(part)
        raise ValueError("받은 파일 크기가 안내와 다릅니다. 다시 받아 보세요")
    if h.hexdigest().lower() != rel.sha256.lower():
        os.remove(part)
        raise ValueError("받은 파일이 올린 파일과 다릅니다(sha256 불일치). 다시 받아 보세요")
    os.replace(part, dest)
    if authenticode(dest) == "bad":
        os.remove(dest)
        raise ValueError("받은 setup 의 코드 서명이 깨져 있습니다. 설치하지 않습니다")
    return dest


def authenticode(path: str) -> str:
    """윈도우 코드 서명 상태: 'signed'(믿을 수 있는 서명) · 'unsigned'(서명 없음) · 'bad'(서명이 있는데 틀림) · 'unknown'.
    RPDF setup 은 아직 코드 서명을 하지 않는다(인증서 없음). 그래서 'unsigned' 는 통과시키고, 믿는 근거는 배포자 서명+sha256 이다.
    나중에 코드 서명을 하게 되면 여기서 'signed' 만 받게 바꾼다."""
    if os.name != "nt":
        return "unknown"
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    class FILE_INFO(ctypes.Structure):
        _fields_ = [("cbStruct", wintypes.DWORD), ("pcwszFilePath", wintypes.LPCWSTR),
                    ("hFile", wintypes.HANDLE), ("pgKnownSubject", ctypes.c_void_p)]

    class TRUST_DATA(ctypes.Structure):
        _fields_ = [("cbStruct", wintypes.DWORD), ("pPolicyCallbackData", ctypes.c_void_p),
                    ("pSIPClientData", ctypes.c_void_p), ("dwUIChoice", wintypes.DWORD),
                    ("fdwRevocationChecks", wintypes.DWORD), ("dwUnionChoice", wintypes.DWORD),
                    ("pFile", ctypes.POINTER(FILE_INFO)), ("dwStateAction", wintypes.DWORD),
                    ("hWVTStateData", wintypes.HANDLE), ("pwszURLReference", wintypes.LPCWSTR),
                    ("dwProvFlags", wintypes.DWORD), ("dwUIContext", wintypes.DWORD),
                    ("pSignatureSettings", ctypes.c_void_p)]

    # WINTRUST_ACTION_GENERIC_VERIFY_V2 {00AAC56B-CD44-11d0-8CC2-00C04FC295EE}
    action = GUID(0x00AAC56B, 0xCD44, 0x11D0, (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))
    fi = FILE_INFO(ctypes.sizeof(FILE_INFO), path, None, None)
    td = TRUST_DATA(cbStruct=ctypes.sizeof(TRUST_DATA), dwUIChoice=2, fdwRevocationChecks=0,   # WTD_UI_NONE
                    dwUnionChoice=1, pFile=ctypes.pointer(fi), dwStateAction=1, dwProvFlags=0x1000)  # VERIFY · CACHE_ONLY_URL_RETRIEVAL
    try:
        wt = ctypes.WinDLL("wintrust")
        wt.WinVerifyTrust.restype = ctypes.c_long
        wt.WinVerifyTrust.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.c_void_p]
        r = wt.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(td)) & 0xFFFFFFFF
        td.dwStateAction = 2   # CLOSE
        wt.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(td))
    except OSError:
        return "unknown"
    if r == 0:
        return "signed"
    if r in (0x800B0100, 0x800B0003, 0x800B0001):   # TRUST_E_NOSIGNATURE · SUBJECT_FORM_UNKNOWN · PROVIDER_UNKNOWN
        return "unsigned"
    return "bad"


def clean_env() -> dict:
    """setup·다시 켜질 앱에 줄 환경변수. 이 exe 의 PyInstaller 자국을 걷어낸다(새 버전이 옛 자리를 보지 않게).
    시험용 자리(PDFAPP_*_SOURCE)도 걷어 다시 켜진 앱이 그것을 물려받지 않게 한다."""
    env = dict(os.environ)
    for k in list(env):
        if k.startswith(("_PYI", "_MEI")) or k in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                                                    SOURCE_ENV, "PDFAPP_POLICY_SOURCE"):
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
    if not os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(os.path.abspath(_DOWNLOAD_DIR)) + os.sep):
        raise ValueError(f"받은 자리 밖의 setup 은 띄우지 않습니다: {path}")
    log = os.path.join(os.path.dirname(path), "setup.log")
    args = [path, "/VERYSILENT", "/NORESTART", "/SP-", f"/LOG={log}", "/RELAUNCH"]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:   # 클로드 같은 job 안에서 띄워졌으면 빠져나간다(앱이 끝날 때 같이 죽지 않게)
        subprocess.Popen(args, env=clean_env(), close_fds=True, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
    except OSError:
        subprocess.Popen(args, env=clean_env(), close_fds=True, creationflags=flags)

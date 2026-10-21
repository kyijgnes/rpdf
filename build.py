"""PyInstaller onedir 빌드. `python build.py` → dist\\<APP_ID>\\<APP_ID>.exe (이름은 app/appinfo.py)

빌드는 한 번에 한 세션만(공용 규칙). 다른 빌드가 돌고 있으면 기다린다.
설치 프로그램은 make_setup.py, 새 버전 내기는 release.py(태그를 밀면 GitHub Actions 가 이 파일과 make_setup.py 를 돌린다).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from app.appinfo import APP_ID, APP_NAME, ORG, VERSION  # noqa: E402

NAME = APP_ID
EXCLUDE = ("torch", "torchvision", "torchgen", "functorch", "scipy", "matplotlib", "mpl_toolkits", "pandas",
           "networkx", "sympy", "mpmath", "tqdm", "fsspec", "contourpy", "pytest", "_pytest", "IPython", "tkinter")


VERSION_FILE = "_version_info.txt"   # 빌드하는 동안만 있다

# PyInstaller 가 PySide6 에서 같이 싣지만 앱이 안 쓰는 것(_internal\PySide6 기준). 10-20 측정: 설치 폴더 248MB 중 약 45MB.
# 누가 쓰는지는 측정\dll_deps.py 로 PE import 표를 보고 골랐다.
PRUNE = (
    "opengl32sw.dll",                     # 소프트웨어 OpenGL(그래픽 드라이버가 없을 때 쓰는 대체품). 앱은 OpenGL 을 안 씀
    # Qt Quick·Qml 묶음: 가상 키보드 플러그인만 이것들을 쓴다(앱은 위젯만)
    "Qt6Quick.dll", "Qt6Qml.dll", "Qt6QmlModels.dll", "Qt6QmlMeta.dll", "Qt6QmlWorkerScript.dll", "Qt6OpenGL.dll",
    "Qt6VirtualKeyboard.dll", os.path.join("plugins", "platforminputcontexts"),
    # Qt 의 TLS 와 그것만 쓰는 OpenSSL 한 벌. 업데이트 확인(HTTPS)은 파이썬 ssl(_ssl.pyd → libssl-3.dll)을 쓴다
    os.path.join("plugins", "tls"), os.path.join("..", "libssl-3-x64.dll"), os.path.join("..", "libcrypto-3-x64.dll"),
)
KEEP_QM = "_ko.qm"   # Qt 번역은 한국어만 남긴다


def prune(internal: str) -> int:
    """빌드한 _internal 에서 PRUNE 과 한국어가 아닌 Qt 번역을 지운다. 지운 바이트 수."""
    def size(p):
        if os.path.isfile(p):
            return os.path.getsize(p)
        return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs)
    qt = os.path.join(internal, "PySide6")
    gone = 0
    targets = [os.path.normpath(os.path.join(qt, p)) for p in PRUNE]
    tr = os.path.join(qt, "translations")
    if os.path.isdir(tr):
        targets += [os.path.join(tr, f) for f in os.listdir(tr) if not f.endswith(KEEP_QM)]
    for p in targets:
        if not os.path.exists(p):
            continue
        gone += size(p)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    return gone


def write_notices(dist: str) -> str:
    """제3자 라이선스 고지(THIRD-PARTY-NOTICES.txt). 실은 패키지의 dist-info 에서 LICENSE·COPYING 을 모은다."""
    from importlib import metadata
    names = ("PyMuPDF", "PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "pikepdf", "pillow", "numpy",
             "python-docx", "python-pptx", "openpyxl", "psutil", "pywin32", "lxml", "cryptography")
    out = [f"{APP_NAME} {VERSION} 에 들어 있는 오픈소스 부품과 라이선스",
           f"{APP_NAME} 자체는 AGPL-3.0 이다(PyMuPDF 가 AGPL). 소스: https://github.com/{ORG}/rpdf",
           "Qt(PySide6)는 LGPL-3.0 이다. Qt 소스: https://download.qt.io/official_releases/qt/ · https://code.qt.io/",
           "Python 런타임은 PSF License 이다: https://docs.python.org/3/license.html", ""]
    for n in names:
        try:
            d = metadata.distribution(n)
        except metadata.PackageNotFoundError:
            continue
        lic = d.metadata.get("License-Expression") or d.metadata.get("License") or ""
        out += ["=" * 78, f"{d.metadata['Name']} {d.version}  {lic.splitlines()[0] if lic else ''}".rstrip(), "=" * 78]
        for f in d.files or []:
            base = f.name.upper()
            if base.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")) and f.suffix.lower() in ("", ".txt", ".md", ".rst"):
                try:
                    out.append(open(f.locate(), encoding="utf-8", errors="replace").read().strip())
                except (OSError, FileNotFoundError):
                    pass
        out.append("")
    path = os.path.join(dist, "THIRD-PARTY-NOTICES.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    shutil.copy(os.path.join(HERE, "LICENSE"), os.path.join(dist, "LICENSE.txt"))
    return path


def write_version_file() -> str:
    """exe 버전 정보(파일 설명·제품 이름·버전·회사). 비어 있으면 탐색기 「연결 프로그램」이 이름을 못 붙인다(10-20)."""
    nums = (VERSION.split(".") + ["0"] * 4)[:4]
    t = ", ".join(str(int(n)) for n in nums)
    strings = {"CompanyName": ORG, "FileDescription": APP_NAME, "FileVersion": VERSION, "InternalName": APP_ID,
               "OriginalFilename": APP_ID + ".exe", "ProductName": APP_NAME, "ProductVersion": VERSION}
    items = ",\n".join(f"          StringStruct({k!r}, {v!r})" for k, v in strings.items())
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({t}), prodvers=({t}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041204B0', [
{items}
    ])]),
    VarFileInfo([VarStruct('Translation', [0x0412, 1200])])
  ]
)
"""
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    return VERSION_FILE


def main() -> int:
    os.chdir(HERE)
    for d in ("build", "dist"):
        shutil.rmtree(os.path.join(HERE, d), ignore_errors=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir", "--name", NAME,
           "--collect-all", "pymupdf", "--collect-all", "fitz", "--hidden-import", "PySide6.QtPrintSupport", "--hidden-import", "PySide6.QtNetwork",
           "--hidden-import", "win32com.client", "--hidden-import", "docx", "--hidden-import", "openpyxl", "--hidden-import", "pptx",
           "--hidden-import", "pikepdf", "--hidden-import", "PIL",
           "run.py"]
    # 앱이 안 쓰는데 훅이 끌어오는 무거운 패키지(첫 빌드 783MB 가운데 torch 366MB·scipy 71MB 등)
    for m in EXCLUDE:
        cmd[-1:-1] = ["--exclude-module", m]
    # 앱 아이콘(있으면): exe·바로 가기 아이콘으로 쓰고, 창 아이콘용으로 assets\ 를 통째로 _internal\assets 에 싣는다
    if os.path.exists(os.path.join("assets", "app.ico")):
        cmd[-1:-1] = ["--icon", os.path.join("assets", "app.ico")]
    if os.path.isdir("assets"):
        cmd[-1:-1] = ["--add-data", "assets;assets"]
    with open("run.py", "w", encoding="utf-8") as f:
        f.write("from app.main import main\nimport sys\nsys.exit(main())\n")
    cmd[-1:-1] = ["--version-file", write_version_file()]
    try:
        r = subprocess.call(cmd)
    finally:
        os.remove(VERSION_FILE)
    if r == 0:
        gone = prune(os.path.join(HERE, "dist", NAME, "_internal"))
        print(f"안 쓰는 Qt 덩어리 {gone / 2**20:.0f}MB 지움")
        print("라이선스 고지:", write_notices(os.path.join(HERE, "dist", NAME)))
        print("빌드 끝:", os.path.join(HERE, "dist", NAME, NAME + ".exe"))
    return r


if __name__ == "__main__":
    sys.exit(main())

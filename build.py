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


def write_version_file() -> str:
    """exe 버전 정보(파일 설명·제품 이름·버전·회사). 비어 있으면 탐색기 「연결 프로그램」이 이름을 못 붙인다(10-20)."""
    nums = (VERSION.split(".") + ["0"] * 4)[:4]
    t = ", ".join(str(int(n)) for n in nums)
    strings = {"CompanyName": ORG, "FileDescription": APP_NAME, "FileVersion": VERSION, "InternalName": APP_ID,
               "OriginalFilename": APP_ID + ".exe", "ProductName": APP_NAME, "ProductVersion": VERSION}
    items = ",
".join(f"          StringStruct({k!r}, {v!r})" for k, v in strings.items())
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
           "--collect-all", "pymupdf", "--collect-all", "fitz", "--hidden-import", "PySide6.QtPrintSupport",
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
        print("빌드 끝:", os.path.join(HERE, "dist", NAME, NAME + ".exe"))
    return r


if __name__ == "__main__":
    sys.exit(main())

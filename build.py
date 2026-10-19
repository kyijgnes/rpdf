"""PyInstaller onedir 빌드. `python build.py` → dist\\<APP_ID>\\<APP_ID>.exe (이름은 app/appinfo.py)

빌드는 한 번에 한 세션만(공용 규칙). 다른 빌드가 돌고 있으면 기다린다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from app.appinfo import APP_ID  # noqa: E402

NAME = APP_ID
EXCLUDE = ("torch", "torchvision", "torchgen", "functorch", "scipy", "matplotlib", "mpl_toolkits", "pandas",
           "networkx", "sympy", "mpmath", "tqdm", "fsspec", "contourpy", "pytest", "_pytest", "IPython", "tkinter")


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
    with open("run.py", "w", encoding="utf-8") as f:
        f.write("from app.main import main\nimport sys\nsys.exit(main())\n")
    r = subprocess.call(cmd)
    if r == 0:
        print("빌드 끝:", os.path.join(HERE, "dist", NAME, NAME + ".exe"))
    return r


if __name__ == "__main__":
    sys.exit(main())

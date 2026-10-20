"""앱 시작 시간: 프로세스를 띄운 때부터 창이 보일 때까지(밖에서 잼).

PDFAPP_SHOT 을 주면 앱이 켜진 창과 상관없이 혼자 뜨고(단일 창 넘기기 안 함) 3.5초 뒤 스스로 끝난다.
APPDATA 를 임시 폴더로 바꿔 사용자 설정(최근 파일)을 건드리지 않는다.

python 측정/startup.py [횟수] [문서이름]
"""
import os
import subprocess
import sys
import tempfile
import time

import win32gui
import win32process

sys.path.insert(0, os.path.dirname(__file__))
import docs  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.environ.get("RPDF_EXE") or os.path.join(os.environ["LOCALAPPDATA"], "Programs", "RPDF", "RPDF.exe")  # 시험 빌드는 RPDF_EXE 로


def window_of(pid: int):
    found = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32process.GetWindowThreadProcessId(h)[1] == pid:
            if "RPDF" in win32gui.GetWindowText(h) or ".pdf" in win32gui.GetWindowText(h):
                found.append(win32gui.GetWindowText(h))
        return True
    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def run(cmd, cwd, doc=None):
    env = dict(os.environ)
    tmp = tempfile.mkdtemp(prefix="rpdf_appdata_")
    env["APPDATA"] = tmp
    env["PDFAPP_SHOT"] = os.path.join(tmp, "shot.png")
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd + ([doc] if doc else []), cwd=cwd, env=env)
    shown = titled = None
    while p.poll() is None and time.perf_counter() - t0 < 30:
        w = window_of(p.pid)
        if w and shown is None:
            shown = time.perf_counter() - t0
        if w and doc and ".pdf" in w and titled is None:
            titled = time.perf_counter() - t0
        if shown and (titled or not doc):
            break
        time.sleep(0.01)
    p.wait(20)
    return shown, titled


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    doc = docs.path(sys.argv[2]) if len(sys.argv) > 2 else None
    for label, cmd, cwd in (("설치본 exe", [EXE], os.path.dirname(EXE)),
                            ("소스(python run.py)", [sys.executable, "run.py"], HERE)):
        if not os.path.exists(cmd[0]) and cmd[0] == EXE:
            print(label, "없음"); continue
        rs = [run(cmd, cwd, doc) for _ in range(n)]
        print(f"{label}: 창 보임 " + ", ".join(f"{r[0]:.2f}" for r in rs if r[0]) +
              ("" if not doc else "  / 문서 탭 " + ", ".join(f"{r[1]:.2f}" for r in rs if r[1])))


if __name__ == "__main__":
    main()

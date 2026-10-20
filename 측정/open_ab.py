"""열기 대조 실험: 썸네일 일꾼을 그대로 둘 때 / 막을 때 열기가 UI 를 얼마나 잡나.
앱 코드는 안 고치고, 이 프로세스 안에서만 ThumbWorker.start 를 바꿔 끼운다.

python 측정/open_ab.py <문서이름>
"""
from __future__ import annotations

import cProfile
import io
import pstats
import sys
import time

import app_bench as B
import docs
from app.ui import sidebar


def once(win, work, label):
    B.ST.start()
    t = time.perf_counter()
    win.open_path(work)
    sync = time.perf_counter() - t
    v = win.cur().viewer
    B.pump(0.12)
    B.wait(lambda: B.rendered(v), 30)
    total = time.perf_counter() - t
    st = B.ST.stop()
    print(f"{label}: 걸림 {sync:.2f}s / 첫 화면 {total:.2f}s / 최대 멈춤 {st['max_stall']:.2f}s")
    t_ = win.cur()
    B.wait(lambda: not (t_.thumbs.thumbs.busy() or t_.organize.thumbs.busy()), 300)
    t_.doc.modified = False
    win.close_tab(0); B.pump(0.3)


def main():
    name = sys.argv[1]
    work = docs.path(name)
    win = B.MainWindow(); win.show_initial(); win.resize(1360, 820); B.pump(0.2)
    once(win, work, "지금대로")
    orig = sidebar.ThumbWorker.start
    sidebar.ThumbWorker.start = lambda self, *a: None
    once(win, work, "썸네일·구성 일꾼 막음")
    # 일꾼 없이 남는 열기 비용을 쪼갠다(이 프로파일은 UI 스레드만 남는다)
    pr = cProfile.Profile(); pr.enable(); win.open_path(work); pr.disable()
    s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(15)
    print("\n".join(l for l in s.getvalue().splitlines() if l.strip())[:4000])
    win.cur().doc.modified = False; win.close_tab(0)
    sidebar.ThumbWorker.start = orig
    win.close()


if __name__ == "__main__":
    main()

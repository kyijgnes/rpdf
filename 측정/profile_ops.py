"""UI 스레드에서 오래 걸리는 동작을 cProfile 로 쪼갠다: 열기·되돌리기·회전. 썸네일 일꾼이 실제로 얼마나 그렸나도 본다.

python 측정/profile_ops.py <문서이름>
"""
from __future__ import annotations

import cProfile
import io
import os
import pstats
import sys
import time

import app_bench as B  # 창·APPDATA 준비를 같이 쓴다
import docs




def prof(label, fn, n=14):
    pr = cProfile.Profile()
    t = time.perf_counter()
    pr.enable(); fn(); pr.disable()
    print(f"\n### {label}: {time.perf_counter() - t:.3f}s")
    s = io.StringIO()
    st = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    st.print_stats(n)
    out = s.getvalue()
    # 경로를 짧게
    out = out.replace(os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + os.sep, "")
    print("\n".join(l for l in out.splitlines() if l.strip() and not l.startswith(("   Ordered", "   List"))))


def main():
    name = sys.argv[1]
    win = B.MainWindow(); win.show_initial(); win.resize(1360, 820); B.pump(0.2)
    work = docs.path(name)
    prof("열기(open_path)", lambda: win.open_path(work))
    t = win.cur(); v = t.viewer
    t0 = time.perf_counter()
    B.wait(lambda: not (t.thumbs.thumbs.busy() or t.organize.thumbs.busy()), 300)
    print(f"썸네일·구성 일꾼 다 끝남: 열고 나서 {time.perf_counter() - t0:.1f}s 더")
    B.wait(lambda: B.rendered(v), 20)
    from app.engine import annots as A
    import fitz
    A.rect(t.doc, 0, fitz.Rect(72, 72, 200, 150), (1, 0, 0), None, 1.5, 1.0, ""); t.changed([0])
    B.pump(0.3)
    prof("되돌리기(undo)", lambda: win.on_action("undo"))
    B.wait(lambda: not t.thumbs.thumbs.busy(), 300)
    prof("회전(pages_action rotate_right)", lambda: win.pages_action("rotate_right", [0]))
    t.doc.modified = False
    win.close_tab(0)
    win.close()


if __name__ == "__main__":
    main()

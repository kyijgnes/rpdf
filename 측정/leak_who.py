"""닫은 탭이 메모리에 남나, 남으면 누가 붙잡고 있나.

python 측정/leak_who.py <문서이름>
"""
from __future__ import annotations

import gc
import sys
import weakref

import app_bench as B
import docs


def main():
    work = docs.path(sys.argv[1] if len(sys.argv) > 1 else "small_b4")
    win = B.MainWindow(); win.show_initial(); B.pump(0.2)
    win.open_path(work)
    t = win.cur(); v = t.viewer
    B.wait(lambda: B.rendered(v), 30)
    B.wait(lambda: not (t.thumbs.worker.isRunning() or t.organize.worker.isRunning()), 120)
    refs = {"DocTab": weakref.ref(t), "PageView": weakref.ref(v), "Document": weakref.ref(t.doc),
            "RenderWorker": weakref.ref(v.worker), "ThumbWorker": weakref.ref(t.thumbs.worker)}
    fz = t.doc.fitz
    win.close_tab(0)
    del t, v
    B.pump(0.5); B.flush_deletes(); gc.collect(); B.pump(0.2); gc.collect()
    import shiboken6
    for k, r in refs.items():
        o = r()
        alive_c = o is not None and k != "Document" and shiboken6.isValid(o)
        print(k, "남음" if o is not None else "사라짐", "(Qt 쪽 객체도 살아 있음)" if alive_c else "")
        if k == "PageView" and alive_c:
            print("   장면의 쪽 그림 수", sum(1 for it in o.items if it.pm is not None))
        if o is not None and k in ("DocTab", "Document"):
            for ref in gc.get_referrers(o)[:8]:
                desc = type(ref).__name__
                if isinstance(ref, dict):
                    keys = [kk for kk, vv in ref.items() if vv is o][:3]
                    desc += f" 열쇠 {keys}"
                elif hasattr(ref, "__code__"):
                    desc += f" {ref.__code__.co_name} {ref.__code__.co_filename.split(chr(92))[-1]}:{ref.__code__.co_firstlineno}"
                elif type(ref).__name__ == "cell":
                    desc += " (lambda 가 잡은 칸)"
                print("   ←", desc)
    print("fitz 문서 닫힘", fz.is_closed)
    win.close()


if __name__ == "__main__":
    main()

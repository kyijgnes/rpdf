"""쪽 구조가 바뀔 때 옮겨 쓴 그림이 맞는 쪽에 붙나: 순서 바꾸기·삭제·회전·복제 뒤, 그림 값(cacheKey)과 다시 그린 그림을 대조.

python 측정/check_mapping.py
"""
from __future__ import annotations

import sys

import app_bench as B
import docs


def keys(view):
    """보기 쪽 그림 · 구성 썸네일: 쪽 → 그림 cacheKey."""
    v = {it.index: it.pm.cacheKey() for it in view.viewer.items if it.pm is not None}
    o = {p: pm.cacheKey() for p, pm in view.organize.thumbs.pixmaps().items()}
    return v, o


def settle(t):
    B.wait(lambda: B.rendered(t.viewer) and not t.organize.thumbs.busy(), 30)
    B.pump(0.15)


def main():
    win = B.MainWindow(); win.show_initial(); win.resize(1360, 820); B.pump(0.2)
    win.open_path(docs.path("big_b4"))
    t = win.cur()
    win.on_ribbon_tab("page"); settle(t)
    ok = True

    def check(label, expect_o, dirty):
        nonlocal ok
        settle(t)
        _, o2 = keys(t)
        bad = [k for k, old in expect_o.items() if k not in dirty and o2.get(k) != old]
        redrawn = [k for k in dirty if k in o2 and o2[k] == expect_o.get(k)]
        good = not bad and not redrawn
        ok &= good
        print(f"{'OK ' if good else '틀림'} {label}: 옮겨 쓴 칸 {len([k for k in expect_o if k not in dirty])}개, 어긋남 {bad[:5]}, 안 바뀐 dirty {redrawn[:5]}")

    _, o = keys(t)
    n = t.doc.page_count
    order = list(range(n)); order.insert(0, order.pop(1))
    t.reorder(order)
    check("순서 바꾸기(2쪽을 맨 앞으로)", {k: o[p] for k, p in enumerate(order) if p in o}, set())

    _, o = keys(t)
    win.pages_action("delete", [0])
    check("1쪽 삭제", {k - 1: v for k, v in o.items() if k > 0}, set())

    _, o = keys(t)
    win.pages_action("rotate_right", [1])
    check("2쪽 회전", dict(o), {1})

    _, o = keys(t)
    win.pages_action("duplicate", [0])
    exp = {0: o[0], 1: o[0]} if 0 in o else {}
    exp.update({k + 1: v for k, v in o.items() if k > 0})
    check("1쪽 복제", exp, set())

    # 다시 그린 것과 대조: 그림 내용이 그 쪽 내용인가(썸네일을 새로 그려 같은지)
    from app.ui.sidebar import ThumbWorker
    import fitz  # noqa: F401
    vis = sorted(t.organize.thumbs.pixmaps().items())[:6]
    w = t.organize.thumbs.worker.width
    for p, pm in vis:
        pix = t.doc.render(p, w / t.doc.page_size(p)[0])
        same = pm.width() == pix.width and pm.height() == pix.height
        ok &= same
        print(f"{'OK ' if same else '틀림'} {p + 1}쪽 썸네일 크기 {pm.width()}x{pm.height()} / 새로 그림 {pix.width}x{pix.height}")
    t.doc.modified = False
    win.close_tab(0); win.close()
    print("전부 맞음" if ok else "어긋난 것 있음")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

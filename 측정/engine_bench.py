"""엔진만 따로 재기(창 없이): 검색 내역, 쪽 그리기, 글자 뽑기, 저장(subset_fonts), 되돌리기 사본, GIL.

python 측정/engine_bench.py <문서이름> [search|render|text|save|gil|all]
"""
from __future__ import annotations

import cProfile
import os
import pstats
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import fitz  # noqa: E402

import docs  # noqa: E402
from app.engine.document import Document, find_text, search_pattern  # noqa: E402


def tm(fn, n=1):
    t = time.perf_counter()
    for _ in range(n):
        r = fn()
    return (time.perf_counter() - t) / n, r


def search(d: Document):
    from collections import Counter
    c = Counter(w[4] for i in range(min(5, d.page_count)) for w in d.fitz[i].get_text("words") if len(w[4]) >= 2)
    word = c.most_common(1)[0][0]
    s, hits = tm(lambda: d.search(word))
    print(f"검색 「{word}」 {len(hits)}건: doc.search {s:.3f}s")
    ctx, _ = tm(lambda: [d.text_in_rect(h.page, fitz.Rect(h.rect.x0 - 80, h.rect.y0 - 2, h.rect.x1 + 80, h.rect.y1 + 2)) for h in hits])
    print(f"  결과 목록 앞뒤 글자(get_textbox 건마다) {ctx:.3f}s = 건당 {ctx / max(1, len(hits)) * 1000:.1f}ms")
    rx = search_pattern(word)
    a, _ = tm(lambda: [d.fitz[i].get_text("text") for i in range(d.page_count)])
    b, _ = tm(lambda: [d.fitz[i].get_text("rawdict") for i in range(d.page_count)])
    print(f"  쪽 글자 text {a:.3f}s / rawdict {b:.3f}s (전체 쪽)")
    # 한 번 뽑은 글자(TextPage)를 다시 쓰면
    def reuse():
        out = 0
        for i in range(d.page_count):
            tp = d.fitz[i].get_textpage()
            out += len(tp.extractText())
            tp.extractRAWDICT()
        return out
    r, _ = tm(reuse)
    print(f"  TextPage 한 벌로 text+rawdict {r:.3f}s")
    pr = cProfile.Profile(); pr.enable(); d.search(word); [d.text_in_rect(h.page, h.rect) for h in hits[:50]]; pr.disable()
    pstats.Stats(pr).sort_stats("cumulative").print_stats(12)


def render(d: Document):
    for z in (1.0, 1.5, 2.0):
        s, pix = tm(lambda: d.render(0, z), 3)
        print(f"쪽 그리기 zoom {z}: {s * 1000:.0f}ms  {pix.width}x{pix.height}  {pix.width * pix.height * 3 / 2**20:.1f}MB(RGB)")
    n = min(30, d.page_count)
    s, _ = tm(lambda: [d.render(i, 1.5) for i in range(n)])
    print(f"  zoom 1.5 쪽 평균 {s / n * 1000:.0f}ms ({n}쪽)")
    s, _ = tm(lambda: [d.render(i, 120 / d.fitz[i].rect.width) for i in range(n)])
    print(f"  썸네일(폭 120px) 쪽 평균 {s / n * 1000:.1f}ms")
    # 쪽 목록 미리 그리기(display list) 를 두면 확대 바꿀 때 다시 해석 안 함
    page = d.fitz[0]
    dl = page.get_displaylist()
    s, _ = tm(lambda: dl.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)), 3)
    print(f"  display list 로 다시 그리기 zoom 1.5: {s * 1000:.0f}ms")
    s, _ = tm(lambda: [d.fitz[i].rect for i in range(d.page_count)])
    print(f"쪽 크기 읽기 전체 {d.page_count}쪽: {s * 1000:.0f}ms (확대·relayout 마다)")


def text(d: Document):
    i = 0
    for kind in ("words", "dict", "rawdict", "text"):
        s, _ = tm(lambda: d.fitz[i].get_text(kind), 3)
        print(f"get_text({kind}) 1쪽: {s * 1000:.1f}ms")
    s, _ = tm(lambda: d.fitz[i].get_links(), 20)
    print(f"get_links 1쪽: {s * 1000:.2f}ms")
    s, _ = tm(lambda: list(d.fitz[i].widgets()), 20)
    print(f"widgets 1쪽: {s * 1000:.2f}ms")
    from app.engine import annots as A
    s, _ = tm(lambda: A.list_annots(d))
    print(f"주석 목록 전체(패널 새로 고침마다): {s * 1000:.0f}ms")
    s, _ = tm(lambda: A.fields(d))
    print(f"양식 칸 목록 전체(패널 새로 고침마다): {s * 1000:.0f}ms")
    from app.engine import pages as P
    s, _ = tm(lambda: P.labels(d))
    print(f"쪽 이름표 전체: {s * 1000:.0f}ms")


def save(d: Document, name: str):
    out = os.path.join(docs.DIR, f"{name}_eng_save.pdf")
    s, _ = tm(lambda: d.fitz.tobytes(garbage=0, deflate=False, encryption=fitz.PDF_ENCRYPT_KEEP))
    snap = d.fitz.tobytes(garbage=0, deflate=False, encryption=fitz.PDF_ENCRYPT_KEEP)
    print(f"되돌리기 사본 1벌: {s * 1000:.0f}ms, {len(snap) / 2**20:.1f}MB (최대 40벌 = {len(snap) * 40 / 2**20:.0f}MB)")
    s2, _ = tm(lambda: d.fitz.tobytes(garbage=0, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP))
    print(f"  deflate=True 로 뜨면 {s2 * 1000:.0f}ms")
    a, _ = tm(lambda: d.fitz.subset_fonts())
    b, _ = tm(lambda: d.fitz.save(out, garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP))
    c, _ = tm(lambda: Document(out))
    print(f"저장: subset_fonts {a:.3f}s + save(garbage=3) {b:.3f}s + 다시 열기 {c:.3f}s")
    # 글자 하나 넣은 뒤(맑은 고딕을 실음)
    from app.engine import annots as A
    d.snapshot()
    pg = d.fitz[0]
    from app.engine.fonts import korean_fontfile
    pg.insert_text((100, 100), "가나다", fontname="malgunX", fontfile=korean_fontfile(), fontsize=12)
    del pg
    a, _ = tm(lambda: d.fitz.subset_fonts())
    b, _ = tm(lambda: d.fitz.save(out, garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP))
    print(f"한글 글자 넣은 뒤 저장: subset_fonts {a:.3f}s + save {b:.3f}s, 파일 {os.path.getsize(out) / 2**20:.1f}MB")


def gil(d: Document):
    """일꾼 스레드가 쪽을 그리는 동안 다른 파이썬 스레드(UI)가 도나: 5ms 잠깐씩 깨는 스레드의 가장 긴 틈."""
    gaps = []
    stop = False

    def ticker():
        last = time.perf_counter()
        while not stop:
            time.sleep(0.005)
            now = time.perf_counter(); gaps.append(now - last); last = now
    th = threading.Thread(target=ticker); th.start()
    time.sleep(0.05)
    t0 = time.perf_counter()
    for i in range(min(8, d.page_count)):
        d.render(i, 1.5)
    dt = time.perf_counter() - t0
    stop = True; th.join()
    print(f"쪽 8장 그리는 {dt:.2f}s 동안 다른 스레드 가장 긴 틈 {max(gaps) * 1000:.0f}ms (5ms 면 GIL 을 풀어 주는 것)")


def main():
    name = sys.argv[1]
    what = sys.argv[2] if len(sys.argv) > 2 else "all"
    p = docs.path(name)
    t, d = tm(lambda: Document(p))
    print(f"== {name} {d.page_count}쪽: Document() 열기 {t:.3f}s")
    for k, fn in (("text", text), ("render", render), ("search", search), ("gil", gil)):
        if what in (k, "all"):
            fn(d)
    if what in ("save", "all"):
        save(d, name)


if __name__ == "__main__":
    main()

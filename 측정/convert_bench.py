"""변환·압축·OCR 대표 동작 시간(창 없이 엔진 함수를 바로 부름). 결과 파일은 사본 폴더에만 쓴다.

python 측정/convert_bench.py <문서이름> [쪽 수 제한]
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import fitz  # noqa: E402

import docs  # noqa: E402
from app.engine import convert as C  # noqa: E402
from app.engine import tools as T  # noqa: E402


def main():
    name = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    src = docs.path(name)
    base = fitz.open(src)
    if limit and base.page_count > limit:
        base.select(range(limit))
    data = base.tobytes()
    n = base.page_count
    outdir = os.path.join(docs.DIR, f"{name}_conv")
    os.makedirs(outdir, exist_ok=True)

    def fresh():
        return fitz.open("pdf", data)

    jobs = [
        ("Word(docx)", lambda d: C.to_word(d, os.path.join(outdir, "a.docx"))),
        ("Excel(xlsx)", lambda d: C.to_excel(d, os.path.join(outdir, "a.xlsx"))),
        ("한글(hwpx)", lambda d: C.to_hwpx(d, os.path.join(outdir, "a.hwpx"))),
        ("PowerPoint(pptx 150dpi)", lambda d: C.to_pptx(d, os.path.join(outdir, "a.pptx"))),
        ("이미지 png 150dpi", lambda d: C.to_images(d, outdir, fmt="png", dpi=150)),
        ("압축 medium", lambda d: T.compress(d, os.path.join(outdir, "c.pdf"), level="medium")),
    ]
    print(f"== {name} {n}쪽")
    if os.environ.get("NO_HWPX"):  # 한글 COM 이 이 PC 에서 Open 하다 죽는 일이 있어 뺄 수 있게
        jobs = [j for j in jobs if "hwpx" not in j[0]]
    for label, fn in jobs:
        d = fresh()
        t = time.perf_counter()
        try:
            fn(d)
            dt = time.perf_counter() - t
            print(f"{label}: {dt:.2f}s  (쪽당 {dt / n * 1000:.0f}ms)")
        except Exception as e:  # noqa: BLE001
            print(f"{label}: 실패 {e}")
        d.close()
    if len(sys.argv) > 3 and sys.argv[3] == "ocr":
        from app.engine import ocr as O
        d = fresh()
        t = time.perf_counter()
        k = O.ocr_pages(d, pages=[0, 1], lang="ko", dpi=300)
        print(f"OCR 2쪽 300dpi: {time.perf_counter() - t:.2f}s, 글자 {k}")


if __name__ == "__main__":
    main()

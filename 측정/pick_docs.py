"""잴 문서 후보: 쪽 수·크기·첫 쪽 글자 수·쪽 크기·만든 프로그램. 원본은 읽기만 한다.

python 측정/pick_docs.py <PDF 경로 목록.txt> → 측정/docs.txt (utf-8)
"""
import os
import sys

import fitz

root = r"C:\Users\kyijgnes\Desktop\코딩"
rows = []
for line in open(sys.argv[1], encoding="utf-8"):
    p = os.path.normpath(os.path.join(root, line.strip()))
    try:
        d = fitz.open(p)
        r = d[0].rect
        txt = sum(len(d[k].get_text().strip()) for k in range(min(3, d.page_count)))
        rows.append((d.page_count, os.path.getsize(p) // 1024, txt,
                     f"{r.width:.0f}x{r.height:.0f}", (d.metadata or {}).get("producer", "")[:25], p))
        d.close()
    except Exception:  # noqa: BLE001
        pass
rows.sort()
with open(os.path.join(os.path.dirname(__file__), "docs.txt"), "w", encoding="utf-8") as f:
    for r in rows:
        print(*r, sep=" | ", file=f)

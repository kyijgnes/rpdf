"""인쇄 글자 잘림 확인: 벡터 인쇄(print_vector)로 그린 종이와 MuPDF 비트맵 종이를 대조한다.

python 측정/print_clip_check.py [--driver] [--out 폴더] [PDF ...]

- 기본: 인쇄와 같은 plan·draw_sheet 로 A4 한 면을 150dpi 그림에 두 번 그린다(벡터 / 비트맵). 다른 점의 수와
  그 테두리를 쪽마다 적고, 차이가 큰 쪽은 「원본 | 벡터 | 차이」 세 칸 그림으로 남긴다.
- --driver: Microsoft Print to PDF 드라이버로 실제로 보내(종이 안 나옴) 나온 PDF 를 다시 그림으로 떠서 대조한다.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPageSize, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui import printing as PR  # noqa: E402

ROOT = r"C:\Users\kyijgnes\Desktop\코딩\11. 한글 변환기"
DEFAULT = [
    ROOT + r"\프로젝트\06. 오탈자검사\변철수P 위클리\35회\261019_35회(~전범위).pdf",
    ROOT + r"\프로젝트\04. 위클리\10월 3주차 위클리(수학)\10-3 위클리 해설_변환.pdf",
    ROOT + r"\프로젝트\10. 선대특강 집몰반\결과\윤선비 선형대수 특강(집몰) 4주차 문제+해설.pdf",
    ROOT + r"\프로젝트\01. 기출\26학년도\26학년도 명지대 해설.pdf",
    ROOT + r"\프로젝트\03. 화장실 데일리\화장실 공식데일리\화장실 공식데일리 10_261108.pdf",
    ROOT + r"\프로젝트\02. 선행반 계산력960\참고 원본\메일 수신.pdf",
]
DPI = 150
A4 = QPageSize(QPageSize.PageSizeId.A4)
MARGINS = (12.0, 12.0, 12.0, 12.0)  # 레이저 프린터 흔한 인쇄 불가 여백(pt)
PRINTER = "Microsoft Print to PDF"


def arr(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
    return a[:, :img.width() * 3].reshape(img.height(), img.width(), 3).copy()


def sheet_image(doc, sh, vector, color=True) -> np.ndarray:
    k = DPI / 72
    img = QImage(round(sh.w * k), round(sh.h * k), QImage.Format.Format_RGB888)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    PR.draw_sheet(p, sh, doc, QPointF(0, 0), k, DPI, color, True, vector=vector)
    p.end()
    return arr(img)


def _near_min(g: np.ndarray, r=2) -> np.ndarray:
    """둘레 r 칸 안에서 가장 어두운 값(선 굵기·번짐 차이는 잘림이 아니다)."""
    out = g.copy()
    h, w = g.shape
    p = np.pad(g, r, constant_values=255)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out = np.minimum(out, p[r + dy:r + dy + h, r + dx:r + dx + w])
    return out


def diff_box(a: np.ndarray, b: np.ndarray):
    """원본(a)에 잉크가 있는데 b 에서 둘레 2칸 안에 잉크가 없는 점(빠진 것)과 그 반대(덧그린 것)."""
    ga, gb = a.min(axis=2).astype(int), b.min(axis=2).astype(int)
    bad = ((ga < 110) & (_near_min(gb) > 200)) | ((gb < 110) & (_near_min(ga) > 200))
    d = np.where(bad, 255, 0)
    n = int(bad.sum())
    if not n:
        return 0, None, d
    ys, xs = np.nonzero(bad)
    return n, (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())), d


def triptych(a, b, d, path):
    h, w = a.shape[:2]
    out = np.full((h, w * 3 + 20, 3), 255, np.uint8)
    out[:, :w] = a
    out[:, w + 10:2 * w + 10] = b
    heat = np.full((h, w, 3), 255, np.uint8)
    m = d > 96
    heat[m] = (255, 0, 0)
    out[:, 2 * w + 20:] = heat
    fitz.Pixmap(fitz.csRGB, w * 3 + 20, h, out.tobytes(), False).save(path)


def check(path: str, out_dir: str, driver: bool, pages=None, **kw):
    doc = fitz.open(path)
    name = os.path.splitext(os.path.basename(path))[0]
    idx = pages if pages is not None else list(range(min(len(doc), 6)))
    o = PR.PrintOptions(pages=idx, page_size=A4, paper="A4", **kw)
    sheets = PR.plan(doc, o, PR.paper_wh(o, doc), MARGINS)
    color = o.color
    vec = PR.VectorPages(doc, color, True)
    rows = []
    for n, sh in enumerate(sheets):
        ref = sheet_image(doc, sh, None, color)
        got = sheet_image(doc, sh, vec, color)
        fell = all(vec.get(c.page) is None for c in sh.cells if c.page >= 0)
        cnt, box, d = diff_box(ref, got)
        rows.append((n + 1, "비트맵" if fell else "벡터", cnt, box))
        if cnt > 50:
            triptych(ref, got, d, os.path.join(out_dir, f"{name}_{n + 1}.png"))
    if driver:
        f = os.path.join(tempfile.mkdtemp(), "drv.pdf")
        o2 = PR.PrintOptions(pages=idx, page_size=A4, paper="A4", printer=PRINTER, to_file=f, **kw)
        # 여백을 먼저 정해 넘긴다(파일로 인쇄를 준비하는 동안 윈도우 기본 프린터 여백이 섞이는 일이 있어 대조가 어긋남)
        m = o2.margins = PR.printer_margins(PR.make_printer(o2, doc))
        err = PR.send(None, doc, o2, name)
        if err:
            rows.append(("드라이버", err, 0, None))
        else:
            got_doc = fitz.open(f)
            sh2 = PR.plan(doc, o2, PR.paper_wh(o2, doc), m)
            for n, sh in enumerate(sh2):
                ref = sheet_image(doc, sh, None, color)
                pix = got_doc[n].get_pixmap(dpi=DPI)
                g = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width * 3]
                g = g.reshape(pix.height, pix.width, 3)
                h, w = min(g.shape[0], ref.shape[0]), min(g.shape[1], ref.shape[1])
                cnt, box, d = diff_box(ref[:h, :w], g[:h, :w])
                rows.append((f"드라이버 {n + 1}", f"여백 {tuple(round(v, 1) for v in m)}", cnt, box))
                if cnt > 50:
                    triptych(ref[:h, :w], g[:h, :w], d, os.path.join(out_dir, f"{name}_드라이버_{n + 1}.png"))
    print(f"== {name} ({len(doc)}쪽)")
    for r in rows:
        print("  ", *r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="*")
    ap.add_argument("--driver", action="store_true")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "인쇄잘림"))
    ap.add_argument("--fit", default="fit")
    ap.add_argument("--scan", help="이 폴더 아래 PDF 를 모두(최근 것부터 --max 개)")
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--gray", action="store_true", help="흑백 인쇄")
    a = ap.parse_args()
    QApplication.instance() or QApplication([])
    os.makedirs(a.out, exist_ok=True)
    files = list(a.pdfs or ([] if a.scan else DEFAULT))
    if a.scan:
        import glob
        found = sorted(glob.glob(os.path.join(a.scan, "**", "*.pdf"), recursive=True), key=os.path.getmtime, reverse=True)
        files += found[:a.max]
    for f in files:
        if os.path.exists(f):
            check(f, a.out, a.driver, fit=a.fit, color=not a.gray)
        else:
            print("없음:", f)


if __name__ == "__main__":
    main()

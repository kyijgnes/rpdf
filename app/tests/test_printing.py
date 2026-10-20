"""인쇄 배치 계산(plan)과 파일로 보내기 시험. 실제 프린터로는 보내지 않는다(Qt 자체 PDF 로만 씀)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QPageSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui import printing as PR  # noqa: E402

A4 = (595.0, 842.0)
NO_MARGIN = (0, 0, 0, 0)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_doc(n=8, w=595, h=842) -> fitz.Document:
    d = fitz.open()
    for i in range(n):
        p = d.new_page(width=w, height=h)
        p.draw_rect(p.rect + (20, 20, -20, -20), color=(0, 0, 1), width=4)
        p.insert_text((200, 420), f"PAGE {i + 1}", fontsize=50)
    return d


def opts(**kw) -> PR.PrintOptions:
    kw.setdefault("pages", list(range(8)))
    return PR.PrintOptions(**kw)


def target(cell: PR.Cell, doc) -> fitz.Rect:
    return (cell.src or doc[cell.page].rect) * cell.m


def test_pick_pages():
    assert PR.pick_pages(8, list(range(8)), "odd") == [0, 2, 4, 6]   # 1·3·5·7쪽
    assert PR.pick_pages(8, [1, 2, 3], "even") == [1, 3]           # 2·4쪽
    assert PR.pick_pages(8, [0, 1, 2], "all", True) == [2, 1, 0]


def test_size_fit_and_actual():
    d = make_doc()
    sh = PR.plan(d, opts(), A4, NO_MARGIN)
    assert len(sh) == 8 and all(len(s.cells) == 1 for s in sh)
    assert target(sh[0].cells[0], d) == fitz.Rect(0, 0, 595, 842)
    # 실제 크기 + 가운데 끔: 왼쪽 위에 붙고 배율 1
    sh = PR.plan(d, opts(fit="actual", center=False), A4, (20, 30, 20, 30))
    c = sh[0].cells[0]
    assert c.s == 1 and abs(target(c, d).x0 - 20) < 1e-6 and abs(target(c, d).y0 - 30) < 1e-6
    # 사용자 지정 50%: 가운데
    c = PR.plan(d, opts(fit="custom", scale=50), A4, NO_MARGIN)[0].cells[0]
    assert target(c, d) == fitz.Rect(148.75, 210.5, 446.25, 631.5)


def test_landscape_paper_rotates_page_left():
    d = make_doc()
    c = PR.plan(d, opts(orient="landscape"), (842, 595), NO_MARGIN)[0].cells[0]
    assert c.rot == 270
    t = target(c, d)
    assert abs(t.width - 842) < 0.5 and abs(t.height - 595) < 0.5
    # 쪽의 왼쪽 위 모서리는 종이의 왼쪽 아래로 간다(왼쪽으로 눕힘)
    p = fitz.Point(0, 0) * c.m
    assert abs(p.x) < 0.5 and abs(p.y - 595) < 0.5
    assert PR.plan(d, opts(auto_rotate=False), (842, 595), NO_MARGIN)[0].cells[0].rot == 0


@pytest.mark.parametrize("order, want", [
    ("h", [(0, 0), (1, 0), (0, 1), (1, 1)]),
    ("hr", [(1, 0), (0, 0), (1, 1), (0, 1)]),
    ("v", [(0, 0), (0, 1), (1, 0), (1, 1)]),
    ("vr", [(1, 0), (1, 1), (0, 0), (0, 1)]),
])
def test_multi_order(order, want):
    d = make_doc()
    sh = PR.plan(d, opts(mode="multi", nup=4, nup_order=order), A4, NO_MARGIN)
    assert len(sh) == 2
    got = []
    for c in sh[0].cells:
        t = target(c, d)
        got.append((int(t.x0 // (595 / 2)), int(t.y0 // (842 / 2))))
    assert got == want


def test_multi_two_up_grid_and_custom():
    d = make_doc()
    assert PR.nup_grid(opts(nup=2), False) == (1, 2) and PR.nup_grid(opts(nup=2), True) == (2, 1)
    assert PR.nup_grid(opts(nup=6), False) == (2, 3)
    sh = PR.plan(d, opts(mode="multi", nup=2), A4, NO_MARGIN)
    assert len(sh) == 4 and all(c.rot == 270 for c in sh[0].cells)  # 세로 종이 두 칸은 가로 칸이라 쪽을 눕힌다
    sh = PR.plan(d, opts(mode="multi", nup=0, nup_cols=3, nup_rows=1), A4, NO_MARGIN)
    assert len(sh) == 3 and len(sh[0].cells) == 3 and len(sh[2].cells) == 2


def test_booklet_order():
    d = make_doc()
    sides = lambda sh: [tuple(c.page for c in s.cells) for s in sh]  # noqa: E731
    sh = PR.plan(d, opts(mode="booklet"), (842, 595), NO_MARGIN)
    assert sides(sh) == [(7, 0), (1, 6), (5, 2), (3, 4)]
    assert sides(PR.plan(d, opts(mode="booklet", booklet_right=True), (842, 595), NO_MARGIN)) == [(0, 7), (6, 1), (2, 5), (4, 3)]
    assert sides(PR.plan(d, opts(mode="booklet", booklet_subset="front"), (842, 595), NO_MARGIN)) == [(7, 0), (5, 2)]
    assert sides(PR.plan(d, opts(mode="booklet", booklet_subset="back"), (842, 595), NO_MARGIN)) == [(1, 6), (3, 4)]
    assert sides(PR.plan(d, opts(mode="booklet", booklet_from=2, booklet_to=2), (842, 595), NO_MARGIN)) == [(5, 2), (3, 4)]
    # 6쪽이면 빈 쪽 둘이 채워진다
    sh = PR.plan(d, opts(mode="booklet", pages=list(range(6))), (842, 595), NO_MARGIN)
    assert sides(sh) == [(0,), (1,), (5, 2), (3, 4)]
    left = target(sh[2].cells[0], d)
    assert left.x1 <= 421 + 0.5  # 왼쪽 반에 들어감


def test_poster_tiles():
    d = make_doc(1)
    sh = PR.plan(d, opts(mode="poster", pages=[0], poster_scale=200), A4, NO_MARGIN)
    assert len(sh) == 4
    # 겹침 1cm 면 세로로 3×3 장이지만, 눕히면 3×2 장이라 자동 회전이 눕힌다
    sh = PR.plan(d, opts(mode="poster", pages=[0], poster_scale=200, overlap=1.0), A4, NO_MARGIN)
    assert len(sh) == 6 and sh[0].cells[0].rot == 270
    sh = PR.plan(d, opts(mode="poster", pages=[0], poster_scale=100, cut_marks=True, labels=True, doc_name="a.pdf"), A4,
                 NO_MARGIN)
    assert len(sh) == 1 and len(sh[0].marks) == 8 and "1쪽" in sh[0].label
    ov = PR.poster_overview(d, 0, opts(mode="poster", pages=[0], poster_scale=200), A4, NO_MARGIN)
    assert (ov.w, ov.h) == (1190, 1684) and len(ov.guides) == 2


def test_current_view_clip():
    d = make_doc()
    c = PR.plan(d, opts(view=(2, fitz.Rect(0, 0, 595, 300))), A4, NO_MARGIN)
    assert len(c) == 1 and c[0].cells[0].page == 2 and c[0].cells[0].src == fitz.Rect(0, 0, 595, 300)


def test_content_doc_drops_annots():
    d = make_doc(2)
    d[0].add_rect_annot(fitz.Rect(50, 50, 100, 100))
    assert PR.content_doc(d, True, True, True, [0, 1]) is d
    c = PR.content_doc(d, True, False, True, [0, 1])
    assert c is not d and len(list(c[0].annots())) == 0 and len(list(d[0].annots())) == 1
    c = PR.content_doc(d, False, True, True, [0])
    assert c[0].get_text().strip() == ""


def sizes(path):
    out = fitz.open(path)
    return [(round(p.rect.width), round(p.rect.height)) for p in out]


@pytest.mark.parametrize("kw, n, size", [
    ({}, 8, (595, 842)),
    ({"orient": "landscape"}, 8, (842, 595)),
    ({"mode": "multi", "nup": 4}, 2, (595, 842)),
    ({"mode": "booklet"}, 4, (842, 595)),
    ({"mode": "poster", "pages": [0], "poster_scale": 200}, 4, (595, 842)),
    ({"copies": 2, "pages": [0, 1]}, 4, (595, 842)),
])
def test_send_to_file(app, tmp_path, kw, n, size):
    d = make_doc()
    f = str(tmp_path / "out.pdf")
    o = opts(to_file=f, paper="A4", page_size=QPageSize(QPageSize.PageSizeId.A4), margins=NO_MARGIN, dpi=72, **kw)
    assert PR.send(None, d, o, "시험") is None
    got = sizes(f)
    assert len(got) == n and all(s == size for s in got)


def test_send_source_size(app, tmp_path):
    d = make_doc(1)
    d.new_page(width=842, height=595)
    f = str(tmp_path / "src.pdf")
    o = opts(pages=[0, 1], to_file=f, source_size=True, margins=NO_MARGIN)
    assert PR.send(None, d, o, "시험") is None
    assert sizes(f) == [(595, 842), (842, 595)]


def test_send_manual_duplex_two_files(app, tmp_path):
    d = make_doc(3)
    f = str(tmp_path / "m.pdf")
    o = opts(pages=[0, 1, 2], to_file=f, duplex="manual", margins=NO_MARGIN)
    assert PR.send(None, d, o, "시험") is None
    assert len(sizes(f)) == 2 and len(sizes(str(tmp_path / "m-뒷면.pdf"))) == 1


def test_sent_page_lands_where_planned(app, tmp_path):
    """여러 페이지(4쪽 모아 찍기) 결과에서 파란 테두리가 네 칸에 하나씩 있는지 그림으로 확인."""
    d = make_doc(4)
    f = str(tmp_path / "n.pdf")
    o = opts(pages=[0, 1, 2, 3], to_file=f, mode="multi", nup=4, margins=NO_MARGIN, page_size=QPageSize(QPageSize.PageSizeId.A4))
    assert PR.send(None, d, o, "시험") is None
    pix = fitz.open(f)[0].get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
    w, h = pix.width, pix.height
    for qx in (0, 1):
        for qy in (0, 1):
            blue = 0
            for y in range(qy * h // 2, (qy + 1) * h // 2):
                for x in range(qx * w // 2, (qx + 1) * w // 2):
                    r, g, b = pix.pixel(x, y)[:3]
                    blue += b > 150 and b - r > 50
            assert blue > 20, (qx, qy)


def test_vector_record_matches_raster(app):
    """벡터로 모은 그리기 명령을 그림으로 그리면 MuPDF 비트맵과 같아야 한다."""
    import numpy as np
    from PySide6.QtGui import QColor, QImage, QPainter, QTransform
    from app.ui import print_vector as PV
    d = make_doc(1)
    p = d[0]
    p.insert_text((100, 200), "굵은 글씨", fontname="korea", fontsize=30, render_mode=2, border_width=0.05)
    ops = PV.record(p, True, False)
    assert ops
    z = 100 / 72
    pix = p.get_pixmap(matrix=fitz.Matrix(z, z))
    img = QImage(pix.width, pix.height, QImage.Format.Format_RGB888); img.fill(QColor("white"))
    qp = QPainter(img); qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    PV.play(qp, ops, QTransform.fromScale(z, z)); qp.end()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 3]
    b = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width * 3]
    assert np.abs(a.astype(int) - b.astype(int)).mean() < 3


def test_vector_falls_back_on_transparency(app):
    d = make_doc(1)
    d[0].draw_rect(fitz.Rect(50, 50, 200, 200), color=None, fill=(1, 0, 0), fill_opacity=0.5)
    from app.ui import print_vector as PV
    assert PV.record(d[0], True, False) is None  # 비트맵으로 그리게 한다

# -*- coding: utf-8 -*-
"""주석 엔진 시험(글상자 색·삽입 기호·종류별 기본값·XFDF/FDF). 작은 PDF 를 그 자리에서 만들어 쓴다."""
from __future__ import annotations

import os
import sys
from collections import Counter

import fitz

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.engine import annots as A  # noqa: E402
from app.engine.document import Document  # noqa: E402

RED, BLUE, YELLOWISH = (1, 0, 0), (0, 0, 1), (1, 1, 0.8)


def _colors(page: fitz.Page, r: fitz.Rect) -> Counter:
    pix = page.get_pixmap(clip=r, dpi=144)
    return Counter(pix.pixel(x, y) for x in range(pix.width) for y in range(pix.height))


def _near(c: Counter, rgb, tol=40) -> int:
    return sum(n for px, n in c.items() if all(abs(a - b) <= tol for a, b in zip(px, rgb)))


def _reopen(d: Document) -> fitz.Document:
    return fitz.open("pdf", d.to_bytes())


# ── 설계.md 5절에 남았던 것 ───────────────────────────────────────────────
def test_rich_freetext_keeps_text_and_border_colors():
    """테두리색이 글자색과 다른 글상자(리치텍스트): 글자는 빨강, 테두리는 파랑으로 그린다(전에는 둘 다 검정)."""
    d = Document()
    r = fitz.Rect(100, 100, 300, 160)
    x = A.free_text(d, 0, r, "한글 글자 빨강", 16, RED, YELLOWISH, BLUE, 3)
    c = _colors(d.fitz[0], r + (-4, -4, 4, 4))
    assert _near(c, (255, 0, 0), 60) > 30       # 글자
    assert _near(c, (0, 0, 255), 60) > 100      # 테두리
    assert _near(c, (0, 0, 0), 60) < 20         # 검정이 없다
    a = A.get(d, 0, x)
    assert A.annot_colors(d, a)["border"] == BLUE
    assert A._freetext_style(d, a) == (16.0, RED)
    # 저장하고 다시 열어도 같다
    f = _reopen(d)
    c = _colors(f[0], r + (-4, -4, 4, 4))
    assert _near(c, (0, 0, 255), 60) > 100 and _near(c, (0, 0, 0), 60) < 20


def test_freetext_content_edit_keeps_rc_size_and_colors():
    """내용을 고쳐도 /RC 가 남고(한글·크기), 옮겨도 테두리 색이 그대로."""
    d = Document()
    x = A.free_text(d, 0, fitz.Rect(100, 100, 300, 160), "처음 글", 16, RED, None, BLUE, 2)
    assert d.fitz.xref_get_key(x, "RC")[0] != "null"
    x = A.update(d, 0, x, content="고친 한글\n둘째 줄")
    f = d.fitz
    assert f.xref_get_key(x, "RC")[0] != "null"
    assert "둘째 줄" in f.xref_get_key(x, "RC")[1] or "둘째 줄" in A.get(d, 0, x).info["content"]
    a = A.get(d, 0, x)
    assert a.info["content"] == "고친 한글\n둘째 줄"
    assert A._freetext_style(d, a) == (16.0, RED)
    assert A.annot_colors(d, a)["border"] == BLUE
    x = A.move_by(d, 0, x, 50, 50)
    a = A.get(d, 0, x)
    assert A.annot_colors(d, a)["border"] == BLUE and A._freetext_style(d, a) == (16.0, RED)
    # 글자 크기·색만 바꿔도 테두리는 그대로
    x = A.update(d, 0, x, fontsize=20, stroke=(0, 1, 0))
    a = A.get(d, 0, x)
    assert A._freetext_style(d, a) == (20.0, (0.0, 1.0, 0.0)) and A.annot_colors(d, a)["border"] == BLUE


def test_plain_freetext_border_color_change_turns_rich():
    """테두리가 글자색인 보통 글상자에 다른 테두리 색을 주면 리치텍스트로 바뀌어 그 색으로 그린다."""
    d = Document()
    r = fitz.Rect(100, 300, 300, 360)
    x = A.free_text(d, 0, r, "보통 글", 14, RED, None, RED, 2)
    assert not A._is_rich(d.fitz, A.get(d, 0, x))
    x = A.update(d, 0, x, border=BLUE)
    a = A.get(d, 0, x)
    assert A.annot_colors(d, a)["border"] == BLUE and A._freetext_style(d, a) == (14.0, RED)
    assert a.info["content"] == "보통 글"


def test_caret_has_real_position():
    """삽입 기호: 누른 자리에 생긴다(전에는 자리 값이 -2147483648 로 깨져 안 보였다)."""
    d = Document()
    x = A.caret(d, 0, fitz.Point(200, 300), "끼울 말")
    a = A.get(d, 0, x)
    assert 180 < a.rect.x0 < 200 < a.rect.x1 < 220 and 280 < a.rect.y0 < 300 < a.rect.y1 < 320
    assert tuple(A.annot_colors(d, a)["stroke"]) == (0.5, 0.0, 0.5)
    assert a.info["content"] == "끼울 말"
    data = A.export_annots(d)
    assert A.import_annots(Document(), data) == (1, 0)


# ── 종류별 기본값 기억 ─────────────────────────────────────────────────
def test_style_store_remembers_per_kind(tmp_path):
    from app.engine import annot_style as S
    p = str(tmp_path / "annot_styles.json")
    st = S.StyleStore(p)
    assert st.get("highlight")["color"] == S.YELLOW and st.get("rect")["width"] == 1.0
    assert st.remember("rect", {"stroke": BLUE, "width": 3, "hl_color": RED, "dashes": (3, 3)})  # 모르는 칸은 버림
    assert not st.remember("rect", {"stroke": BLUE})                                           # 그대로면 저장 안 함
    st2 = S.StyleStore(p)
    assert st2.get("rect") == {"stroke": BLUE, "fill": None, "width": 3, "opacity": 1.0}
    assert st2.get("oval")["stroke"] == RED                                                    # 다른 종류는 그대로
    st2.reset("rect")
    assert S.StyleStore(p).get("rect")["stroke"] == RED
    (tmp_path / "bad.json").write_text("{깨진", encoding="utf-8")
    assert S.StyleStore(str(tmp_path / "bad.json")).get("pencil")["stroke"] == RED


def test_style_to_viewer_props_and_key_of():
    from app.engine import annot_style as S
    props = {}
    S.to_viewer_props("pencil", {"stroke": BLUE, "width": 4, "opacity": 0.5}, props)
    assert props == {"ink_color": BLUE, "ink_width": 4, "opacity": 0.5}
    S.to_viewer_props("textbox", S.DEFAULTS["textbox"], props)
    assert props["fontsize"] == 14 and props["text_color"] == RED and props["stroke"] == RED
    d = Document()
    xs = {"rect": A.rect(d, 0, fitz.Rect(10, 10, 60, 60)), "areahl": A.area_highlight(d, 0, fitz.Rect(70, 10, 120, 60)),
          "arrow": A.line(d, 0, fitz.Point(10, 100), fitz.Point(90, 120), arrow=True),
          "line": A.line(d, 0, fitz.Point(10, 140), fitz.Point(90, 160)),
          "cloud": A.polygon(d, 0, [fitz.Point(200, 200), fitz.Point(260, 210), fitz.Point(230, 260)], cloud=True),
          "pencil": A.ink(d, 0, [[fitz.Point(300, 300), fitz.Point(340, 340)]]),
          "caret": A.caret(d, 0, fitz.Point(100, 400)), "note": A.note(d, 0, fitz.Point(20, 500), "메모"),
          "textbox": A.free_text(d, 0, fitz.Rect(300, 500, 450, 560), "글", 14, RED, None, BLUE, 1),
          "typewriter": A.free_text(d, 0, fitz.Rect(300, 600, 450, 660), "타자", 14, RED, typewriter=True),
          "callout": A.free_text(d, 0, fitz.Rect(300, 700, 450, 760), "말", 14, RED, None, RED, 1, callout=fitz.Point(260, 800)),
          "stamp": A.stamp_text(d, 0, fitz.Rect(100, 600, 200, 640), "승인")}
    for key, x in xs.items():
        assert S.key_of(d, A.get(d, 0, x)) == key, key
    s = S.style_of(d, A.get(d, 0, xs["textbox"]))
    assert s["text_color"] == RED and s["border"] == BLUE and s["fontsize"] == 14


def test_update_from_props_panel_args():
    """속성 패널이 주는 인자: 채움 없애기(()), 점선, 제목, 글상자 테두리만 바꾸기."""
    d = Document()
    x = A.rect(d, 0, fitz.Rect(10, 10, 60, 60), fill=(0, 1, 0))
    A.update(d, 0, x, stroke=BLUE, fill=(), dashes=(3, 3), subject="제목")
    a = A.get(d, 0, x)
    assert not a.colors["fill"] and tuple(a.colors["stroke"]) == BLUE
    assert tuple(a.border["dashes"]) == (3, 3) and a.info["subject"] == "제목"
    A.update(d, 0, x, dashes=())
    assert not A.get(d, 0, x).border.get("dashes")
    # 보통 글상자의 글자색만 바꾸면 테두리도 따라간다(옛 테두리 색이 남지 않음)
    s = A.stamp_text(d, 0, fitz.Rect(100, 600, 200, 640), "승인")
    A.update(d, 0, s, stroke=BLUE)
    a = A.get(d, 0, s)
    assert A._freetext_style(d, a)[1] == BLUE and A.annot_colors(d, a)["border"] == BLUE
    # 리치 글상자에 제목을 줘도 /RC 가 남는다
    t = A.free_text(d, 0, fitz.Rect(300, 500, 450, 560), "한글", 14, RED, None, BLUE, 1)
    A.update(d, 0, t, subject="검토")
    assert d.fitz.xref_get_key(t, "RC")[0] != "null" and A.annot_colors(d, A.get(d, 0, t))["border"] == BLUE


def test_props_panel_shows_kind_fields_and_remembers(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from app.engine import annot_style as S
    from app.ui.props import PropsPanel
    from app.ui.viewer import PageView
    d = Document()
    v = PageView(d)
    st = S.StyleStore(str(tmp_path / "s.json"))
    p = PropsPanel(v.props, v, st)
    applied = []
    p.applyToSel.connect(applied.append)
    vis = lambda w: not p.look.isRowVisible(w) is False  # noqa: E731
    try:
        v.set_tool("highlight")
        assert v.props["hl_color"] == S.YELLOW
        assert vis(p.color) and not p.look.isRowVisible(p.width) and not p.look.isRowVisible(p.fill)
        p._swatch((1, 0, 0))                       # 빨강 견본 → 기억
        assert st.get("highlight")["color"] == (1, 0, 0) and v.props["hl_color"] == (1, 0, 0)
        v.set_tool("rect")
        assert p.look.isRowVisible(p.width) and p.look.isRowVisible(p.fill) and not p.look.isRowVisible(p.fontsize)
        assert not p.look.isRowVisible(p.dashes)    # 점선은 고른 주석에만
        p.width.setValue(4)
        assert v.props["width"] == 4 and S.StyleStore(str(tmp_path / "s.json")).get("rect")["width"] == 4
        v.set_tool("highlight")
        assert v.props["hl_color"] == (1, 0, 0)    # 도구를 바꿨다 와도 그 종류 값
        v.set_tool("textbox")
        assert p.look.isRowVisible(p.fontsize) and p.look.isRowVisible(p.border) and v.props["fontsize"] == 14
        # 고른 주석: 칸이 그 주석 종류대로, 바꾸면 바로 적용(잠깐 뒤 한 번)
        x = A.free_text(d, 0, fitz.Rect(300, 500, 450, 560), "글", 18, BLUE, None, RED, 1)
        v.set_tool("select")
        from app.ui.viewer import Selection
        sel = Selection("annot", 0, x, fitz.Rect(300, 500, 450, 560), extra={"kind_ko": "텍스트 박스"})
        p.show_selection(sel)
        assert p.fontsize.value() == 18 and p.color.color == BLUE and p.border.color == RED
        assert p.info_box.isVisibleTo(p) and p.look.isRowVisible(p.fontsize)
        p.fontsize.setValue(20)
        p._timer.timeout.emit()
        assert applied and applied[-1]["fontsize"] == 20 and applied[-1]["border"] == RED
        assert st.get("textbox")["fontsize"] == 20     # 고친 모양이 다음 기본값
        p.show_selection(None)
        assert not p.info_box.isVisibleTo(p)
    finally:
        v.close()


# ── XFDF · FDF ─────────────────────────────────────────────────────────
def _sample_doc() -> Document:
    d = Document()
    d.fitz[0].insert_text((72, 100), "Hello world line one", fontsize=14)
    d.fitz[0].insert_text((72, 120), "second line text here", fontsize=14)
    A.text_markup(d, 0, [fitz.Rect(72, 88, 230, 104), fitz.Rect(72, 108, 230, 124)], "Highlight", content="강조 메모")
    A.text_markup(d, 0, [fitz.Rect(72, 88, 230, 104)], "Underline", color=RED)
    A.rect(d, 0, fitz.Rect(100, 200, 200, 300), width=6, author="윤성지")
    A.oval(d, 0, fitz.Rect(220, 200, 300, 260), width=1.5, fill=(0, 1, 0), opacity=0.5)
    A.line(d, 0, fitz.Point(100, 400), fitz.Point(300, 450), width=3, arrow=True)
    A.ink(d, 0, [[fitz.Point(50, 600), fitz.Point(150, 650)], [fitz.Point(60, 610), fitz.Point(70, 700)]], width=4)
    A.polygon(d, 0, [fitz.Point(400, 400), fitz.Point(500, 420), fitz.Point(450, 500)], width=2, cloud=True)
    A.polygon(d, 0, [fitz.Point(400, 600), fitz.Point(500, 620), fitz.Point(450, 700)], closed=False)
    A.free_text(d, 0, fitz.Rect(300, 500, 450, 560), "리치 글상자 & <태그>", 18, RED, YELLOWISH, BLUE, 2)
    A.free_text(d, 0, fitz.Rect(300, 600, 450, 660), "보통 글", 15, BLUE, None, BLUE, 1)
    A.free_text(d, 0, fitz.Rect(300, 700, 450, 760), "말풍선", 13, (0, 0, 0), (1, 1, 1), (0, 0, 0), 1, callout=fitz.Point(260, 800))
    A.note(d, 0, fitz.Point(20, 20), "메모", icon="Comment")
    A.caret(d, 0, fitz.Point(200, 130), "끼움")
    x = A.rect(d, 0, fitz.Rect(20, 760, 80, 800))
    A.update(d, 0, x, dashes=(3, 3))
    return d


def _sig(doc):
    out = []
    for a in doc.fitz[0].annots():
        k = a.type[1]
        if k == "Popup":
            continue
        b = a.border or {}
        cols = {n: tuple(round(c, 2) for c in v) if v else None for n, v in A.annot_colors(doc, a).items()}
        op = a.opacity
        out.append((k, [round(x) for x in a.rect], b.get("width"), b.get("clouds"), tuple(b.get("dashes") or ()),
                    a.line_ends if k == "Line" else None, A._freetext_style(doc, a) if k == "FreeText" else None,
                    len(a.vertices or []) if k != "FreeText" else None, cols, round(op if op is not None and op >= 0 else 1, 2),
                    a.info.get("content"), a.info.get("title")))
    return out


def test_xfdf_roundtrip():
    from app.engine import annot_xfdf as X
    d = _sample_doc()
    data, n, skipped = X.to_xfdf(d, "원본.pdf")
    assert n == len(_sig(d)) and skipped == 0
    assert b"<highlight" in data and b"&amp; &lt;" in data
    e = Document()
    assert X.import_xfdf(e, data) == (n, 0)
    assert _sig(d) == _sig(e)


def test_fdf_roundtrip():
    from app.engine import annot_xfdf as X
    d = _sample_doc()
    data, n, _ = X.to_fdf(d, "원본.pdf")
    assert data.startswith(b"%FDF-1.2")
    e = Document()
    assert X.import_fdf(e, data) == (n, 0)
    assert _sig(d) == _sig(e)


def test_xfdf_from_other_app():
    """다른 프로그램이 만든 XFDF(이름공간·리치텍스트 내용·모르는 종류)도 읽는다."""
    from app.engine import annot_xfdf as X
    data = '''<?xml version="1.0" encoding="UTF-8"?>
<xfdf xmlns="http://ns.adobe.com/xfdf/" xml:space="preserve"><annots>
<square page="0" rect="100,500,200,600" color="#FF0000" width="2" title="남"><contents>네모</contents></square>
<freetext page="0" rect="100,300,300,350" color="#FFFFCC" width="1">
<contents-richtext><body xmlns="http://www.w3.org/1999/xhtml"><p>첫 줄</p><p>둘째 줄</p></body></contents-richtext>
<defaultappearance>0 0 1 rg /Helv 16 Tf</defaultappearance></freetext>
<sound page="0" rect="1,1,2,2"/>
<square page="9" rect="1,1,20,20"/>
</annots></xfdf>'''.encode("utf-8")
    d = Document()
    assert X.import_xfdf(d, data) == (2, 2)
    pg = d.fitz[0]  # 쪽을 붙잡아 둔다(주석은 쪽을 약하게만 잡는다)
    got = {a.type[1]: a for a in pg.annots()}
    assert got["Square"].info["content"] == "네모" and got["Square"].info["title"] == "남"
    r = got["Square"].rect
    assert abs(r.y0 - (842 - 600)) <= 2 and abs(r.x0 - 100) <= 2   # PDF 좌표(아래가 0)를 쪽 좌표로
    ft = got["FreeText"]
    assert ft.info["content"] == "첫 줄\n둘째 줄" and A._freetext_style(d, ft) == (16.0, BLUE)


def test_annot_list_group_and_find():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from app.ui.sidebar import AnnotPanel
    d = Document()
    d.fitz.new_page()
    A.rect(d, 1, fitz.Rect(10, 10, 60, 60), author="나")
    A.note(d, 0, fitz.Point(20, 20), "숙제 확인", author="너")
    A.caret(d, 0, fitz.Point(100, 100), "끼움", author="나")
    p = AnnotPanel(d)
    heads = lambda: [p.tree.topLevelItem(i).text(0) for i in range(p.tree.topLevelItemCount())]  # noqa: E731
    assert heads() == ["1쪽", "2쪽"]
    p.group.setCurrentIndex(2)
    assert heads() == ["나", "너"] and p.tree.topLevelItem(0).childCount() == 2
    p.group.setCurrentIndex(3)
    assert sorted(heads()) == sorted(["노트", "삽입 기호", "직사각형"])
    p.find.setText("숙제")
    assert heads() == ["노트"]
    p.find.setText("없는 말")
    assert p.empty.isVisibleTo(p) and p.empty.text() == "찾은 주석 없음"

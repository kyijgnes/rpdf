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

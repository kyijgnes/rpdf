"""주석·양식·링크·텍스트/이미지 편집. 전부 Document 위에서 snapshot() 뒤에 바꾼다.

색은 (r,g,b) 0~1 튜플. 좌표는 PDF 점(pt), 쪽 좌표계(회전 반영 전 fitz 기준).
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import Sequence

import fitz

from .document import Document, _text_rotation, del_keys, korean_font_name, redact_only
from .fonts import korean_fontfile

Color = tuple[float, float, float]

KIND_NAMES = {
    "Highlight": "강조", "Underline": "밑줄", "StrikeOut": "취소선", "Squiggly": "구불구불한 선",
    "Square": "직사각형", "Circle": "타원", "Line": "선", "Polygon": "다각형", "PolyLine": "연결된 선",
    "Ink": "연필", "FreeText": "텍스트 박스", "Text": "노트", "Stamp": "스탬프", "FileAttachment": "첨부 파일",
    "Caret": "삽입 기호", "Redact": "교정 표시", "Link": "링크", "Widget": "양식 칸",
}


@dataclass
class AnnotInfo:
    page: int
    xref: int
    kind: str
    kind_ko: str
    rect: fitz.Rect
    content: str
    author: str
    color: Color | None
    modified: str


# ── 공통 ─────────────────────────────────────────────────────────
def _finish(annot: fitz.Annot, stroke: Color | None = None, fill: Color | None = None,
            width: float | None = None, opacity: float | None = None, content: str = "", author: str = ""):
    if stroke is not None or fill is not None:
        annot.set_colors(stroke=stroke, fill=fill)
    if width is not None:
        annot.set_border(width=width)
    if opacity is not None:
        annot.set_opacity(opacity)
    if content:
        annot.set_info(content=content)
    if author:
        annot.set_info(title=author)
    annot.update()
    return annot


def list_annots(doc: Document, pages: Sequence[int] | None = None) -> list[AnnotInfo]:
    out: list[AnnotInfo] = []
    rng = pages if pages is not None else range(doc.page_count)
    with doc.lock:
        for i in rng:
            for a in doc.fitz[i].annots():
                info = a.info
                kind = a.type[1]
                cols = annot_colors(doc, a)
                col = cols.get("stroke") or cols.get("fill")
                out.append(AnnotInfo(i, a.xref, kind, KIND_NAMES.get(kind, kind), fitz.Rect(a.rect),
                                     info.get("content", ""), info.get("title", ""),
                                     tuple(col) if col else None, info.get("modDate", "")))
    return out


def get(doc: Document, page: int, xref: int) -> fitz.Annot | None:
    p = doc.fitz[page]
    for a in p.annots():
        if a.xref == xref:
            # 주석은 쪽 객체를 약하게만 잡는다. 쪽이 먼저 사라지면 풀린 주석이 되어 만지는 순간 튕긴다.
            a._page = p
            return a
    return None


def delete(doc: Document, page: int, xref: int):
    doc.snapshot()
    with doc.lock:
        a = get(doc, page, xref)
        if a:
            a._page.delete_annot(a)


def delete_all(doc: Document, pages: Sequence[int] | None = None):
    doc.snapshot()
    with doc.lock:
        for i in (pages if pages is not None else range(doc.page_count)):
            p = doc.fitz[i]
            for a in list(p.annots()):
                p.delete_annot(a)


VERTEX_KINDS = ("Line", "PolyLine", "Polygon", "Ink")  # 꼭짓점으로 그리는 주석(set_rect 로는 안 옮겨짐)


def _freetext_style(doc: Document, a: fitz.Annot) -> tuple[float, Color]:
    """글상자의 지금 글자 크기·글자색(/DA). 리치텍스트 글상자는 /DS(CSS) 로 그리므로 거기서 읽는다."""
    f = doc.fitz
    da = f.xref_get_key(a.xref, "DA")[1] or ""
    m = re.search(r"([\d.]+)\s+Tf", da)
    c = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da)
    size = float(m.group(1)) if m else 11.0
    color = tuple(float(x) for x in c.groups()) if c else (0.0, 0.0, 0.0)
    # 리치텍스트 글상자는 /DS(CSS) 대로 그린다
    if _is_rich(f, a):
        ds = f.xref_get_key(a.xref, "DS")[1] or ""
        m = re.search(r"font-size\s*:\s*([\d.]+)\s*pt", ds) or re.search(r"font\s*:[^;]*?([\d.]+)\s*pt", ds)
        if m:
            size = float(m.group(1))
        c = re.search(r"(?<![\w-])color\s*:\s*#([0-9a-fA-F]{6})", ds)
        # /DS 에 색이 없으면 MuPDF 는 검정으로 그린다(/DA 의 색을 안 씀)
        color = tuple(int(c.group(1)[k:k + 2], 16) / 255 for k in (0, 2, 4)) if c else (0.0, 0.0, 0.0)
    return size, color


def _is_rich(f: fitz.Document, a: fitz.Annot) -> bool:
    return f.xref_get_key(a.xref, "RC")[0] != "null" or f.xref_get_key(a.xref, "DS")[0] != "null"


def _freetext_border(a: fitz.Annot) -> Color | None:
    """글상자 테두리 색: 모양(AP) 첫 RG. MuPDF 는 테두리를 글자색으로 그리므로 우리가 고쳐 둔 색이 거기 있다."""
    if not ((a.border or {}).get("width") or 0):
        return None
    try:
        m = re.search(rb"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+RG", a._getAP())
    except Exception:  # noqa: BLE001
        m = None
    return tuple(float(x) for x in m.groups()) if m else None


def _rc_xml(text: str) -> str:
    """글상자 리치텍스트(/RC). 줄마다 문단 하나."""
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    paras = "".join(f"<p>{esc(line)}</p>" for line in (text.split("\n") or [""]))
    return ('<?xml version="1.0"?><body xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/" xfa:APIVersion="Acrobat:8.0.0" '
            f'xfa:spec="2.4">{paras}</body>')


def _ds_css(fontsize: float, color: Color) -> str:
    hexc = "".join(f"{round(max(0, min(1, c)) * 255):02x}" for c in color)
    return f"font-family: Malgun Gothic, sans-serif; font-size: {fontsize:g}pt; color: #{hexc};"


def _ft_redraw(f: fitz.Document, a: fitz.Annot, text: str, fontsize: float, text_color: Color,
               fill: Color | None, border: Color | None, rich: bool, **kw) -> None:
    """글상자 모양을 다시 그린다. 리치텍스트면 /RC·/DS 를 먼저 쓰고(set_info 가 /RC 를 지운다),
    그린 뒤 테두리 색을 고친다(MuPDF 는 테두리를 글자색으로 그린다)."""
    if rich:
        f.xref_set_key(a.xref, "DS", fitz.get_pdf_str(_ds_css(fontsize, text_color)))
        f.xref_set_key(a.xref, "RC", fitz.get_pdf_str(_rc_xml(text)))
    a.update(fontsize=fontsize, text_color=text_color, fill_color=fill, **kw)
    if rich and border is not None and tuple(border) != tuple(text_color):
        r, g, b = border
        ap = re.sub(rb"[\d.]+\s+[\d.]+\s+[\d.]+\s+RG", f"{r:g} {g:g} {b:g} RG".encode(), a._getAP(), count=1)
        a._setAP(ap)


def annot_colors(doc: Document, a: fitz.Annot) -> dict:
    """화면에 보일 색: stroke=선·글자 색, fill=채움색, border=글상자 테두리 색.
    글상자는 PyMuPDF 가 채움색을 stroke 로 돌려주므로 바로잡는다."""
    if a.type[1] == "FreeText":
        return {"stroke": _freetext_style(doc, a)[1], "fill": a.colors.get("stroke") or a.colors.get("fill"),
                "border": _freetext_border(a)}
    return a.colors


def _recreate_moved(p: fitz.Page, a: fitz.Annot, dx: float, dy: float) -> int:
    """꼭짓점 주석을 옮긴 꼭짓점으로 새로 만들고 속성을 옮긴 뒤 옛것을 지운다. 새 xref 를 돌려준다."""
    kind, v = a.type[1], a.vertices
    sh = lambda q: (q[0] + dx, q[1] + dy)  # noqa: E731
    if kind == "Ink":
        n = p.add_ink_annot([[sh(q) for q in s] for s in v])
    elif kind == "Line":
        n = p.add_line_annot(sh(v[0]), sh(v[-1]))
        if a.line_ends:
            n.set_line_ends(*a.line_ends)
    elif kind == "Polygon":
        n = p.add_polygon_annot([sh(q) for q in v])
    else:
        n = p.add_polyline_annot([sh(q) for q in v])
    cols = a.colors
    n.set_colors(stroke=cols.get("stroke"), fill=cols.get("fill") if kind in ("Line", "Polygon") else None)
    b = a.border or {}
    n.set_border(width=b.get("width", 1), dashes=b.get("dashes") or None, clouds=b.get("clouds", 0) or 0)
    if a.opacity is not None and a.opacity >= 0:
        n.set_opacity(a.opacity)
    info = a.info
    n.set_info(content=info.get("content", ""), title=info.get("title", ""), subject=info.get("subject", ""))
    n.update()
    p.delete_annot(a)
    return n.xref


def update(doc: Document, page: int, xref: int, *, stroke: Color | None = None, fill: Color | None = None,
           width: float | None = None, opacity: float | None = None, content: str | None = None,
           author: str | None = None, rect: fitz.Rect | None = None, fontsize: float | None = None,
           text_color: Color | None = None, border: Color | None = None,
           dashes: Sequence[float] | None = None) -> int | None:
    """주석을 고친다. 꼭짓점 주석을 옮기면 새로 만들어지므로 (새) xref 를 돌려준다.

    글상자: stroke(또는 text_color)=글자색, border=테두리 색, fill=바탕색. dashes=() 는 실선."""
    doc.snapshot()
    with doc.lock:
        a = get(doc, page, xref)
        if not a:
            return None
        kind = a.type[1]
        if rect is not None:
            old = fitz.Rect(a.rect)
            if kind in VERTEX_KINDS:
                return _recreate_moved(a._page, a, rect.x0 - old.x0, rect.y0 - old.y0)
            if kind in ("Square", "Circle"):
                # a.rect 는 테두리만큼 넓혀져 나온다. 그대로 넣으면 옮길 때마다 테두리 두께만큼 커진다.
                bw = ((a.border or {}).get("width") or 0) / 2
                rect = fitz.Rect(rect.x0 + bw, rect.y0 + bw, rect.x1 - bw, rect.y1 - bw)
            a.set_rect(rect)
        f = doc.fitz
        if kind == "FreeText":
            # 고치기 전 값(set_info 가 /RC 를 지우고, 다시 그리면 테두리가 글자색이 되므로 먼저 읽어 둔다)
            fs0, tc0 = _freetext_style(doc, a)
            bc0 = _freetext_border(a)
            rich0 = _is_rich(f, a)
        if kind != "FreeText" and (stroke is not None or fill is not None):
            a.set_colors(stroke=stroke, fill=fill)
        if width is not None and kind not in ("Caret", "Text", "FileAttachment") + MARKUP_KINDS:
            a.set_border(width=width)
        if dashes is not None and kind not in ("FreeText", "Caret", "Text", "FileAttachment") + MARKUP_KINDS:
            a.set_border(width=(a.border or {}).get("width", 1), dashes=list(dashes) or None)
        if opacity is not None:
            a.set_opacity(opacity)
        if content is not None:
            a.set_info(content=content)
        if author is not None:
            a.set_info(title=author)
        if kind == "FreeText":
            # 글상자는 set_colors 를 못 쓴다. 안 준 값은 지금 값을 그대로 쓴다(안 그러면 크기 12·검정으로 돌아감).
            tc = tuple(text_color or stroke or tc0)
            bc = tuple(border) if border is not None else bc0
            rich = rich0 or (bc is not None and bc != tc)
            text = content if content is not None else a.info.get("content", "")
            _ft_redraw(f, a, text, fontsize or fs0, tc, fill, bc, rich)
        else:
            a.update()
        return a.xref


def move_by(doc: Document, page: int, xref: int, dx: float, dy: float) -> int | None:
    a = get(doc, page, xref)
    if not a:
        return None
    r = fitz.Rect(a.rect)
    return update(doc, page, xref, rect=r + (dx, dy, dx, dy))


# ── 글자 표시 주석 ────────────────────────────────────────────────
def _quads_for(page: fitz.Page, rect: fitz.Rect) -> list[fitz.Quad]:
    words = page.get_text("words", clip=rect)
    quads = []
    for w in words:
        r = fitz.Rect(w[:4]) & rect
        if r.is_empty or r.height < 1:
            continue
        quads.append(fitz.Rect(w[:4]).quad)
    return quads


def text_markup(doc: Document, page: int, rects: list[fitz.Rect], kind: str, color: Color = (1, 1, 0),
                opacity: float = 1.0, content: str = "", author: str = "") -> int | None:
    """kind: Highlight · Underline · StrikeOut · Squiggly. rects 는 글자 선택 영역(들)."""
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        quads: list[fitz.Quad] = []
        for r in rects:
            quads.extend(_quads_for(p, r))
        if not quads:
            quads = [fitz.Rect(r).quad for r in rects]
        fn = {"Highlight": p.add_highlight_annot, "Underline": p.add_underline_annot,
              "StrikeOut": p.add_strikeout_annot, "Squiggly": p.add_squiggly_annot}[kind]
        a = fn(quads)
        _finish(a, stroke=color, opacity=opacity, content=content, author=author)
        return a.xref


def area_highlight(doc: Document, page: int, rect: fitz.Rect, color: Color = (1, 1, 0), opacity: float = 0.4,
                   author: str = "") -> int:
    doc.snapshot()
    with doc.lock:
        a = doc.fitz[page].add_rect_annot(rect)
        _finish(a, stroke=color, fill=color, width=0, opacity=opacity, author=author)
        return a.xref


def caret(doc: Document, page: int, point: fitz.Point, content: str = "", author: str = "",
          color: Color = (0.5, 0, 0.5), opacity: float = 1.0) -> int:
    doc.snapshot()
    with doc.lock:
        # add_caret_annot 은 점을 받는다. 네모를 넘기면 자리 값이 깨진(-2147483648) 주석이 생긴다
        a = doc.fitz[page].add_caret_annot(fitz.Point(point))
        a.set_rect(fitz.Rect(point.x - 6, point.y - 10, point.x + 6, point.y + 2))  # 꼭짓점이 누른 자리 위
        _finish(a, stroke=color, opacity=opacity, content=content, author=author)
        return a.xref


# ── 도형 ─────────────────────────────────────────────────────────
def rect(doc: Document, page: int, r: fitz.Rect, stroke: Color = (1, 0, 0), fill: Color | None = None,
         width: float = 1.5, opacity: float = 1.0, author: str = "") -> int:
    doc.snapshot()
    with doc.lock:
        a = doc.fitz[page].add_rect_annot(r)
        _finish(a, stroke=stroke, fill=fill, width=width, opacity=opacity, author=author)
        return a.xref


def oval(doc: Document, page: int, r: fitz.Rect, stroke: Color = (1, 0, 0), fill: Color | None = None,
         width: float = 1.5, opacity: float = 1.0, author: str = "") -> int:
    doc.snapshot()
    with doc.lock:
        a = doc.fitz[page].add_circle_annot(r)
        _finish(a, stroke=stroke, fill=fill, width=width, opacity=opacity, author=author)
        return a.xref


def line(doc: Document, page: int, p1: fitz.Point, p2: fitz.Point, stroke: Color = (1, 0, 0), width: float = 1.5,
         arrow: bool = False, opacity: float = 1.0, author: str = "") -> int:
    doc.snapshot()
    with doc.lock:
        a = doc.fitz[page].add_line_annot(p1, p2)
        if arrow:
            a.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_OPEN_ARROW)
        _finish(a, stroke=stroke, fill=stroke, width=width, opacity=opacity, author=author)
        return a.xref


def polygon(doc: Document, page: int, pts: list[fitz.Point], stroke: Color = (1, 0, 0), fill: Color | None = None,
            width: float = 1.5, closed: bool = True, cloud: bool = False, opacity: float = 1.0, author: str = "") -> int:
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        a = p.add_polygon_annot(pts) if closed else p.add_polyline_annot(pts)
        if cloud:
            try:
                a.set_border(width=width, clouds=2)
            except Exception:  # noqa: BLE001
                pass
        _finish(a, stroke=stroke, fill=fill, width=width, opacity=opacity, author=author)
        return a.xref


def ink(doc: Document, page: int, strokes: list[list[fitz.Point]], stroke: Color = (0, 0, 1), width: float = 2.0,
        opacity: float = 1.0, author: str = "") -> int:
    doc.snapshot()
    with doc.lock:
        a = doc.fitz[page].add_ink_annot([[(p.x, p.y) for p in s] for s in strokes])
        _finish(a, stroke=stroke, width=width, opacity=opacity, author=author)
        return a.xref


def _seg_point_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / n))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _seg_seg_dist(a, b, c, d) -> float:
    """선분 ab 와 cd 사이 가장 가까운 거리(만나면 0)."""
    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    d1, d2, d3, d4 = cross(c, d, a), cross(c, d, b), cross(a, b, c), cross(a, b, d)
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return 0.0
    return min(_seg_point_dist(*a, *c, *d), _seg_point_dist(*b, *c, *d),
               _seg_point_dist(*c, *a, *b), _seg_point_dist(*d, *a, *b))


def erase_ink_at(doc: Document, page: int, point: fitz.Point, radius: float = 6,
                 prev: fitz.Point | None = None) -> bool:
    """지우개: 지우개가 지나간 길(prev → point)에 닿는 연필 주석을 지운다.

    꼭짓점만 보지 않고 꼭짓점 사이 선분까지 본다(빠르게 그은 연필은 꼭짓점이 듬성듬성하다)."""
    e0 = (prev.x, prev.y) if prev is not None else (point.x, point.y)
    e1 = (point.x, point.y)
    near = fitz.Rect(min(e0[0], e1[0]), min(e0[1], e1[1]), max(e0[0], e1[0]), max(e0[1], e1[1]))
    with doc.lock:
        p = doc.fitz[page]
        hit = []
        for a in p.annots(types=[fitz.PDF_ANNOT_INK]):
            reach = radius + ((a.border or {}).get("width") or 1) / 2
            if not fitz.Rect(near.x0 - reach, near.y0 - reach, near.x1 + reach, near.y1 + reach).intersects(a.rect):
                continue
            for s in a.vertices or []:
                pts = [tuple(q) for q in s]
                if not pts:
                    continue
                segs = list(zip(pts, pts[1:])) or [(pts[0], pts[0])]  # 점 하나짜리 획
                if any(_seg_seg_dist(q0, q1, e0, e1) <= reach for q0, q1 in segs):
                    hit.append(a)
                    break
        if not hit:
            return False
        doc.snapshot()
        for a in hit:
            p.delete_annot(a)
    return True


# ── 글 상자 · 노트 ────────────────────────────────────────────────
def free_text(doc: Document, page: int, r: fitz.Rect, text: str, fontsize: float = 11, text_color: Color = (0, 0, 0),
              fill: Color | None = None, border: Color | None = None, width: float = 0, opacity: float = 1.0,
              callout: fitz.Point | None = None, author: str = "", typewriter: bool = False) -> int:
    """텍스트 박스(테두리·바탕 있음) · 타자기(typewriter=True, 테두리 없음) · 말풍선(callout 점).

    PyMuPDF 는 richtext 가 아니면 테두리 색을 따로 못 준다(테두리는 글자색). 테두리 색이 글자색과
    다르면 richtext 로 만든다.
    """
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        if callout is not None:
            callout = (callout, fitz.Point((r.x0 + r.x1) / 2, r.y0))
        if typewriter:
            fill, border, width = None, None, 0
        return _add_free_text(p, r, text, fontsize, text_color, fill, border, width, opacity, callout,
                              p.rotation, author).xref  # 회전된 쪽에서도 보이는 화면에 바로 서게


def _add_free_text(p: fitz.Page, r: fitz.Rect, text: str, fontsize: float, text_color: Color, fill: Color | None,
                   border: Color | None, width: float, opacity: float, callout, rotate: int, author: str = "") -> fitz.Annot:
    """글상자 하나(free_text·주석 가져오기가 같이 씀). callout 은 말풍선 선의 꼭짓점들(없으면 None)."""
    kw = {"rotate": rotate}
    if callout:
        kw["callout"] = tuple(fitz.Point(q) for q in callout)
    text_color = tuple(text_color)
    rich = border is not None and tuple(border) != text_color
    if rich:
        a = p.add_freetext_annot(r, text, fontsize=fontsize, text_color=text_color, fill_color=fill,
                                 border_color=border, border_width=width, opacity=opacity, richtext=True,
                                 style=_ds_css(fontsize, text_color), **kw)
    else:
        a = p.add_freetext_annot(r, text, fontsize=fontsize, fontname="malgun", text_color=text_color,
                                 fill_color=fill, border_width=width if border is not None else 0,
                                 opacity=opacity, **kw)
    # 리치텍스트 글상자는 /Contents 가 비어 주석 목록·내보내기·속성 창에 내용이 안 나온다
    a.set_info(content=text, title=author or None)
    _ft_redraw(p.parent, a, text, fontsize, text_color, fill, tuple(border) if border is not None else None, rich)
    return a


def note(doc: Document, page: int, point: fitz.Point, content: str, icon: str = "Note", color: Color = (1, 0.8, 0),
         author: str = "") -> int:
    doc.snapshot()
    with doc.lock:
        a = doc.fitz[page].add_text_annot(point, content, icon=icon)
        _finish(a, stroke=color, content=content, author=author)
        return a.xref


def attachment(doc: Document, page: int, point: fitz.Point, path: str, author: str = "") -> int:
    doc.snapshot()
    with doc.lock:
        a = doc.fitz[page].add_file_annot(point, open(path, "rb").read(), os.path.basename(path),
                                          desc=os.path.basename(path), icon="PushPin")
        _finish(a, author=author)
        return a.xref


# ── 주석 내보내기 · 가져오기(JSON) ──────────────────────────────────
MARKUP_KINDS = ("Highlight", "Underline", "StrikeOut", "Squiggly")
FILL_KINDS = ("Square", "Circle", "Line", "Polygon", "PolyLine", "Redact")  # 채움색(/IC)이 있는 것


def _rd(f: fitz.Document, a: fitz.Annot) -> list[float] | None:
    """/RD: 바깥 네모(a.rect)와 실제로 그리는 안쪽 네모의 차이. 테두리·말풍선 선만큼 바깥이 넓다."""
    t, v = f.xref_get_key(a.xref, "RD")
    try:
        nums = [float(x) for x in v.strip("[] ").split()] if t == "array" else []
    except ValueError:
        return None
    return nums if len(nums) == 4 and any(nums) else None


def _inner(r: fitz.Rect, rd: Sequence[float] | None) -> fitz.Rect:
    """바깥 네모에서 /RD 를 걷은 안쪽 네모. MuPDF 는 /RD 를 PDF 좌표의 왼·아래·오른·위 차례로 쓴다(쪽 좌표의 아래=y1)."""
    r = fitz.Rect(r)
    return fitz.Rect(r.x0 + rd[0], r.y0 + rd[3], r.x1 - rd[2], r.y1 - rd[1]) if rd else r


def export_annots(doc: Document) -> list[dict]:
    """주석 전부를 JSON 에 담을 자료로(링크·양식 칸·팝업은 뺌). import_annots 가 되살린다."""
    out = []
    with doc.lock:
        f = doc.fitz
        for i in range(doc.page_count):
            p = f[i]
            for a in p.annots():
                kind = a.type[1]
                if kind in ("Link", "Widget", "Popup"):
                    continue
                e = {"page": i, "type": kind, "rect": list(a.rect), "info": a.info, "colors": annot_colors(doc, a),
                     "vertices": a.vertices if kind in VERTEX_KINDS or kind in MARKUP_KINDS else None,
                     "opacity": a.opacity, "border": a.border}
                rd = _rd(f, a)
                if rd:
                    e["rd"] = rd
                if kind == "Line" and a.line_ends:
                    e["line_ends"] = list(a.line_ends)
                if kind == "FreeText":
                    e["fontsize"] = _freetext_style(doc, a)[0]  # 있으면 colors 가 stroke=글자색·fill=바탕색(10-19 3차부터)
                    e["rotate"] = max(a.rotation, 0)
                    if f.xref_get_key(a.xref, "IT")[1] == "/FreeTextCallout":
                        e["callout"] = a.vertices
                if kind == "Text":
                    e["icon"] = (f.xref_get_key(a.xref, "Name")[1] or "/Note").lstrip("/")
                out.append(e)
    return out


def import_annots(doc: Document, data: list[dict]) -> tuple[int, int]:
    """export_annots 자료를 되살린다(되돌리기 한 걸음). (넣은 수, 못 넣은 수)."""
    doc.snapshot()
    n = skipped = 0
    with doc.lock:
        for e in data:
            try:
                ok = _import_one(doc, e)
            except Exception:  # noqa: BLE001
                ok = False
            n += ok
            skipped += not ok
    return n, skipped


def _import_one(doc: Document, e: dict) -> bool:
    page = e.get("page", -1)
    if not isinstance(page, int) or not 0 <= page < doc.page_count:
        return False
    p = doc.fitz[page]
    kind, r = e.get("type"), fitz.Rect(e["rect"])
    info, cols, b = e.get("info") or {}, e.get("colors") or {}, e.get("border") or {}
    v, rd = e.get("vertices"), e.get("rd")
    op = e.get("opacity")
    op = op if op is not None and op >= 0 else 1.0
    if kind == "FreeText":
        if "fontsize" in e:
            fs, tc, fill = e["fontsize"], cols.get("stroke") or (0, 0, 0), cols.get("fill") or None
        else:  # 10-19 2차까지 내보낸 파일: 글자 크기가 없고 colors 의 stroke 가 바탕색
            fs, tc, fill = 11, (0, 0, 0), cols.get("stroke") or None
        width = b.get("width") or 0
        box = _inner(r, rd)
        box = fitz.Rect(box.x0 + width / 2, box.y0 + width / 2, box.x1 - width / 2, box.y1 - width / 2)  # MuPDF 가 테두리 반만큼 넓혀 둔 것
        # 테두리 색이 없는 옛 파일은 글자색으로(그때는 테두리를 글자색으로 그렸다)
        bc = tuple(cols.get("border") or tc) if width else None
        a = _add_free_text(p, box, info.get("content", ""), fs, tuple(tc), fill, bc,
                           width, op, e.get("callout"), e.get("rotate", 0), info.get("title", ""))
        if info.get("subject"):  # 다시 그리면 고쳐 둔 테두리 색이 풀리므로 열쇠만 쓴다
            doc.fitz.xref_set_key(a.xref, "Subj", fitz.get_pdf_str(info["subject"]))
        return True
    if kind in MARKUP_KINDS:
        fn = {"Highlight": p.add_highlight_annot, "Underline": p.add_underline_annot,
              "StrikeOut": p.add_strikeout_annot, "Squiggly": p.add_squiggly_annot}[kind]
        quads = [fitz.Quad(*v[k:k + 4]) for k in range(0, len(v) - 3, 4)] if v and len(v[0]) == 2 \
            and not isinstance(v[0][0], (list, tuple)) else []
        a = fn(quads or r)  # 줄마다 하나씩(두 줄 강조가 두 줄을 덮는 네모 하나가 되지 않게)
    elif kind in ("Square", "Circle"):
        a = (p.add_rect_annot if kind == "Square" else p.add_circle_annot)(r)
    elif kind == "Text":
        a = p.add_text_annot(r.tl, info.get("content", ""), icon=e.get("icon") or "Note")
    elif kind == "Ink" and v:
        a = p.add_ink_annot(v if isinstance(v[0][0], (list, tuple)) else [v])
    elif kind == "Line" and v:
        a = p.add_line_annot(v[0], v[-1])
        if e.get("line_ends"):
            a.set_line_ends(*e["line_ends"])
    elif kind in ("Polygon", "PolyLine") and v:
        a = (p.add_polygon_annot if kind == "Polygon" else p.add_polyline_annot)(v)
    elif kind == "Redact":
        a = p.add_redact_annot(r)
    elif kind == "Caret":
        a = p.add_caret_annot(r.tl)
    else:
        return False
    stroke, fill = cols.get("stroke") or None, cols.get("fill") or None
    if kind not in FILL_KINDS:
        fill = None
    if stroke or fill:
        a.set_colors(stroke=stroke, fill=fill)
    if kind not in MARKUP_KINDS and kind not in ("Text", "Caret", "Redact") and b.get("width") is not None:
        kw = {"width": b["width"]}
        if b.get("dashes"):
            kw["dashes"] = list(b["dashes"])
        if (b.get("clouds") or 0) > 0:
            kw["clouds"] = b["clouds"]
        a.set_border(**kw)
    if kind in ("Square", "Circle") and rd:
        a.update()  # 새 테두리 두께로 /RD 를 먼저 맞춘다
        a.set_rect(_inner(r, rd))  # 그 /RD 만큼 다시 넓힌다(바깥 네모를 그대로 넣으면 가져올 때마다 커짐)
    elif kind == "Caret":
        a.set_rect(r)
    if op < 1:
        a.set_opacity(op)
    a.set_info(content=info.get("content", ""), title=info.get("title", ""), subject=info.get("subject", ""))
    a.update()
    return True


# ── 스탬프 · 서명 ─────────────────────────────────────────────────
STAMP_TEXTS = ["승인", "확인", "완료", "초안", "최종", "기밀", "검토 필요", "APPROVED", "DRAFT", "CONFIDENTIAL"]


def stamp_text(doc: Document, page: int, r: fitz.Rect, text: str, color: Color = (0.8, 0, 0), author: str = "") -> int:
    """글자 스탬프: 테두리 상자 + 글자(같은 색)."""
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        dr = fitz.Rect(r) * p.rotation_matrix  # 보이는 화면의 가로·세로
        fs = max(8, min(abs(dr.height) * 0.55, abs(dr.width) / max(1, len(text)) * 1.6))
        a = p.add_freetext_annot(r, text, fontsize=fs, fontname="malgun", text_color=color, border_width=2,
                                 align=fitz.TEXT_ALIGN_CENTER, rotate=p.rotation)
        a.set_info(title=author, subject="Stamp")
        a.update()
        return a.xref


def stamp_image(doc: Document, page: int, r: fitz.Rect, image_path: str, author: str = "") -> int:
    """이미지 스탬프·손글씨 서명: 그림을 쪽 내용으로 넣는다(주석이 아니라 -1 을 돌려준다)."""
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        p.insert_image(r, filename=image_path, overlay=True, keep_proportion=True, rotate=p.rotation)
    return -1


def signature_image(doc: Document, page: int, r: fitz.Rect, image_path: str) -> None:
    """서명 그림을 쪽 내용으로 넣는다(평면화된 서명)."""
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        p.insert_image(r, filename=image_path, overlay=True, keep_proportion=True, rotate=p.rotation)


# ── 측정 ─────────────────────────────────────────────────────────
def measure(points: list[fitz.Point], kind: str, scale: float = 1.0, unit: str = "cm") -> str:
    """kind: distance · perimeter · area. scale = 1pt 가 몇 unit 인가(기본 1pt=1/72 inch → cm 변환)."""
    pt_to = {"cm": 2.54 / 72, "mm": 25.4 / 72, "in": 1 / 72, "pt": 1.0}[unit] * scale
    if kind == "distance" and len(points) >= 2:
        d = math.dist(points[0], points[1]) * pt_to
        return f"{d:.2f} {unit}"
    if kind == "perimeter":
        d = sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)) * pt_to
        return f"{d:.2f} {unit}"
    if kind == "area" and len(points) >= 3:
        s = 0.0
        for i in range(len(points)):
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % len(points)]
            s += x1 * y2 - x2 * y1
        return f"{abs(s) / 2 * pt_to * pt_to:.2f} {unit}²"
    return ""


def measure_annot(doc: Document, page: int, points: list[fitz.Point], kind: str, label: str,
                  stroke: Color = (0, 0.5, 0), author: str = "") -> int:
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        if kind == "distance":
            a = p.add_line_annot(points[0], points[1])
            a.set_line_ends(fitz.PDF_ANNOT_LE_BUTT, fitz.PDF_ANNOT_LE_BUTT)
        elif kind == "perimeter":
            a = p.add_polyline_annot(points)
        else:
            a = p.add_polygon_annot(points)
        _finish(a, stroke=stroke, width=1.2, content=label, author=author)
        return a.xref


# ── 링크 ─────────────────────────────────────────────────────────
def links(doc: Document, page: int) -> list[dict]:
    with doc.lock:
        return doc.fitz[page].get_links()


def add_link(doc: Document, page: int, r: fitz.Rect, *, to_page: int | None = None, uri: str | None = None,
             file: str | None = None):
    doc.snapshot()
    with doc.lock:
        if to_page is not None:
            d = {"kind": fitz.LINK_GOTO, "from": r, "page": to_page, "to": fitz.Point(0, 0)}
        elif uri:
            d = {"kind": fitz.LINK_URI, "from": r, "uri": uri}
        elif file:
            # 역슬래시는 PDF 문자열에서 escape 로 먹혀 C:Users… 가 된다
            d = {"kind": fitz.LINK_LAUNCH, "from": r, "file": file.replace("\\", "/")}
        else:
            raise ValueError("링크 대상이 없습니다")
        doc.fitz[page].insert_link(d)


def delete_link(doc: Document, page: int, link: dict):
    doc.snapshot()
    with doc.lock:
        doc.fitz[page].delete_link(link)


# ── 교정(수정) 표시 ───────────────────────────────────────────────
def mark_redact(doc: Document, page: int, r: fitz.Rect, fill: Color = (0, 0, 0), overlay_text: str = "") -> int:
    doc.snapshot()
    with doc.lock:
        a = doc.fitz[page].add_redact_annot(r, text=overlay_text or None, fill=fill,
                                            fontname="malgun" if overlay_text else None)
        a.update()
        return a.xref


def apply_redactions(doc: Document, pages: Sequence[int] | None = None, images: bool = True):
    doc.snapshot()
    with doc.lock:
        for i in (pages if pages is not None else range(doc.page_count)):
            doc.fitz[i].apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_PIXELS if images else fitz.PDF_REDACT_IMAGE_NONE)


# ── 텍스트·이미지 편집(원문 내용) ─────────────────────────────────
def _insert_box(p: fitz.Page, r: fitz.Rect, text: str, fontsize: float, color: Color, bold: bool, align: int,
                rotate: int | None = None):
    """맑은 고딕으로 상자에 글을 넣는다. 방향은 기본이 쪽 회전(화면에 바로 섬), 넘치면 글 방향의 아래로 늘린다."""
    rot = p.rotation if rotate is None else rotate
    name = korean_font_name(p, bold)  # 굵기마다 이름을 나누고, 저장 때 줄인 글꼴은 피한다
    p.insert_font(fontname=name, fontfile=korean_fontfile(bold))
    rc = p.insert_textbox(r, text, fontsize=fontsize, fontname=name, color=color, align=align, rotate=rot)
    if rc < 0:  # 상자가 작으면 아래로 늘려 다시
        lr = fitz.Rect(r) * fitz.Matrix(rot)
        lr.normalize()
        lr.y1 += -rc + 4
        r2 = lr * fitz.Matrix(-rot)
        r2.normalize()
        p.insert_textbox(r2, text, fontsize=fontsize, fontname=name, color=color, align=align, rotate=rot)


def add_text(doc: Document, page: int, r: fitz.Rect, text: str, fontsize: float = 11, color: Color = (0, 0, 0),
             bold: bool = False, align: int = 0):
    """쪽 내용에 글자를 직접 넣는다(주석 아님)."""
    doc.snapshot()
    with doc.lock:
        _insert_box(doc.fitz[page], r, text, fontsize, color, bold, align)


def add_image(doc: Document, page: int, r: fitz.Rect, path: str, keep_proportion: bool = True):
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        p.insert_image(r, filename=path, keep_proportion=keep_proportion, overlay=True, rotate=p.rotation)


def edit_block(doc: Document, page: int, block_rect: fitz.Rect, new_text: str, fontsize: float | None = None,
               color: Color = (0, 0, 0), bold: bool = False, align: int = 0):
    """원문 글자 덩어리를 고친다: 자리를 교정(흰 칠)하고 새 글자를 같은 자리에 넣는다."""
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        if fontsize is None:
            spans = [s for b in p.get_text("dict", clip=block_rect)["blocks"] if b.get("type") == 0
                     for l in b["lines"] for s in l["spans"]]
            fontsize = spans[0]["size"] if spans else 11
            if spans and not color:
                c = spans[0]["color"]
                color = ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)
        rot = _text_rotation(p, block_rect)  # 원래 글 방향(지우기 전에)
        redact_only(p, [block_rect], fill=(1, 1, 1), images=fitz.PDF_REDACT_IMAGE_NONE)
        if new_text.strip():
            _insert_box(p, fitz.Rect(block_rect), new_text, fontsize, color, bold, align, rotate=rot)


def delete_image(doc: Document, page: int, r: fitz.Rect):
    """그 자리의 그림을 지운다(교정으로)."""
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        redact_only(p, [r], fill=None, images=fitz.PDF_REDACT_IMAGE_REMOVE, text=fitz.PDF_REDACT_TEXT_NONE)


def images_on_page(doc: Document, page: int) -> list[dict]:
    """쪽의 그림들과 자리."""
    out = []
    with doc.lock:
        p = doc.fitz[page]
        for info in p.get_image_info(xrefs=True):
            out.append({"xref": info.get("xref", 0), "rect": fitz.Rect(info["bbox"]),
                        "width": info.get("width"), "height": info.get("height")})
    return out


def replace_image(doc: Document, page: int, xref: int, path: str):
    """그 쪽의 그림만 바꾼다. 다른 쪽도 같은 그림 객체를 쓰면 새 그림 객체를 만들어 이 쪽 자원만 그것을 가리키게 한다.

    PyMuPDF 의 replace_image 는 그림 객체 자체를 덮어써서, 로고처럼 여러 쪽이 같이 쓰는 그림은 모든 쪽이 바뀐다."""
    doc.snapshot()
    with doc.lock:
        f = doc.fitz
        p = f[page]
        uses = [(im[7], im[9]) for im in p.get_images(full=True) if im[0] == xref]  # (자원 이름, 그 이름을 가진 객체·0=쪽)
        shared = any(im[0] == xref for j in range(f.page_count) if j != page for im in f[j].get_images(full=True))
        if not shared or not uses:
            p.replace_image(xref, filename=path)
            return
        new = p.insert_image(p.rect, filename=path)  # 새 그림 객체를 얻으려고 넣은 것이라 그리는 줄은 바로 비운다
        f.update_stream(p.get_contents()[-1], b" ")
        forms = {x[0]: (x[1], x[2]) for x in p.get_xobjects()}  # 폼 xref → (자원 이름, 부르는 객체·0=쪽)
        own: dict[int, int] = {}

        def holder(owner: int) -> int:
            """owner(쪽이면 0) 대신 이 쪽만 쓰는 객체. 자원 사전도 이 쪽 것으로 떼어 낸다."""
            if owner in own:
                return own[owner]
            if owner == 0:
                _own_xobjects(f, p.xref, inherit=True)
                own[0] = p.xref
                return p.xref
            nf = f.get_new_xref()  # 폼은 다른 쪽도 부를 수 있으니 사본을 떠서 이 쪽만 사본을 부르게
            f.update_object(nf, f.xref_object(owner, compressed=True))
            f.update_stream(nf, f.xref_stream(owner))
            _own_xobjects(f, nf)
            own[owner] = nf
            name, up = forms.get(owner, (None, 0))
            if name:
                f.xref_set_key(holder(up), f"Resources/XObject/{name}", f"{nf} 0 R")
            return nf

        for name, ref in uses:
            f.xref_set_key(holder(ref), f"Resources/XObject/{name}", f"{new} 0 R")
        p._image_info = None


def _own_xobjects(f: fitz.Document, xref: int, inherit: bool = False):
    """객체의 /Resources 와 그 안 /XObject 를 이 객체만의 사전으로 만든다(같이 쓰던 사전은 사본을 떠서 붙임).

    inherit=True(쪽)면 /Parent 에서 물려받은 /Resources 도 사본으로 붙인다."""
    t, v = f.xref_get_key(xref, "Resources")
    if t == "null" and inherit:
        node, seen = xref, set()
        while t == "null" and node not in seen:
            seen.add(node)
            pt, pv = f.xref_get_key(node, "Parent")
            if pt != "xref":
                break
            node = int(pv.split()[0])
            t, v = f.xref_get_key(node, "Resources")
        if t == "dict":
            f.xref_set_key(xref, "Resources", v)
    if t == "xref":
        f.xref_set_key(xref, "Resources", f.xref_object(int(v.split()[0]), compressed=True))
    elif t not in ("dict",):
        f.xref_set_key(xref, "Resources", "<<>>")
    t, v = f.xref_get_key(xref, "Resources/XObject")
    if t == "xref":
        f.xref_set_key(xref, "Resources/XObject", f.xref_object(int(v.split()[0]), compressed=True))
    elif t != "dict":
        f.xref_set_key(xref, "Resources/XObject", "<<>>")


# ── 양식 칸(위젯) ─────────────────────────────────────────────────
FIELD_TYPES = {
    "text": fitz.PDF_WIDGET_TYPE_TEXT, "checkbox": fitz.PDF_WIDGET_TYPE_CHECKBOX,
    "radio": fitz.PDF_WIDGET_TYPE_RADIOBUTTON, "combo": fitz.PDF_WIDGET_TYPE_COMBOBOX,
    "list": fitz.PDF_WIDGET_TYPE_LISTBOX, "button": fitz.PDF_WIDGET_TYPE_BUTTON,
    "signature": fitz.PDF_WIDGET_TYPE_SIGNATURE,
}
FIELD_TYPE_KO = {"text": "텍스트", "checkbox": "체크 박스", "radio": "라디오 버튼", "combo": "콤보 박스",
                 "list": "목록 박스", "button": "누름 버튼", "signature": "디지털 서명", "image": "이미지", "date": "날짜"}


def _unique_name(doc: Document, base: str) -> str:
    names = {w.field_name for i in range(doc.page_count) for w in doc.fitz[i].widgets()}
    n, name = 1, base
    while name in names:
        n += 1
        name = f"{base}{n}"
    return name


def add_field(doc: Document, page: int, r: fitz.Rect, ftype: str, name: str | None = None, value=None,
              options: list[str] | None = None, label: str = "", fontsize: float = 10,
              border: Color | None = (0.6, 0.6, 0.6), fill: Color | None = (1, 1, 1), date: bool = False) -> int:
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        base_ko = FIELD_TYPE_KO.get("date" if date else ftype, ftype)
        w = fitz.Widget()
        radio = ftype == "radio"
        # PyMuPDF 1.27 은 라디오를 바로 만들면 bad xref 로 실패하고 망가진 칸을 남긴다. 체크 박스로 만든 뒤 라디오 표시를 단다.
        w.field_type = FIELD_TYPES["checkbox" if radio else "text" if ftype in ("date", "image") else ftype]
        w.field_name = name or _unique_name(doc, base_ko)
        w.rect = r
        w.text_fontsize = fontsize
        w.text_font = "Helv"
        if border is not None:
            w.border_color = border
            w.border_width = 1
        if fill is not None:
            w.fill_color = fill
        if ftype in ("combo", "list"):
            w.choice_values = options or ["항목 1", "항목 2"]
        if ftype == "button":
            w.button_caption = label or "버튼"
        if ftype in ("checkbox", "radio"):
            w.field_value = bool(value)
        elif value is not None:
            w.field_value = value
        if date:
            w.script_format = 'AFDate_FormatEx("yyyy-mm-dd");'
            w.script_stroke = 'AFDate_KeystrokeEx("yyyy-mm-dd");'
        annot = p.add_widget(w)
        if radio:
            x = annot.xref
            doc.fitz.xref_set_key(x, "Ff", str(_RADIO_FLAGS))
            # 이름을 안 주면 이 쪽에서 마지막에 만든 라디오 묶음에 붙인다(예·아니요를 차례로 찍으면 한 묶음)
            group = name
            if not group:
                prev = [r for r in p.widgets() if r.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON and r.xref != x]
                group = max(prev, key=lambda r: r.xref).field_name if prev else w.field_name
            _radio_move(doc.fitz, x, group)
            _refresh_widget(p, x)
        return annot.xref


# ── 라디오 묶음 ─────────────────────────────────────────────────
# PDF 의 라디오 묶음 = 이름(/T)·고른 값(/V)을 가진 부모 칸 하나 + 동그라미 칸들(/Kids).
# 동그라미마다 켜짐 이름(Choice1, Choice2 …)이 달라야 다른 뷰어에서도 하나만 켜지고, 자료 내보내기에 무엇을 골랐는지 남는다.
_RADIO_FLAGS = (1 << 15) | (1 << 14)  # Radio · NoToggleToOff


def _xrefs(text: str) -> list[int]:
    return [int(x) for x in re.findall(r"(\d+)\s+0\s+R", text or "")]


def _get_refs(f: fitz.Document, xref: int, key: str) -> list[int]:
    t, v = f.xref_get_key(xref, key)
    if t == "xref":
        return _xrefs(f.xref_object(int(v.split()[0])))
    return _xrefs(v) if t == "array" else []


def _set_refs(f: fitz.Document, xref: int, key: str, xs: list[int]) -> None:
    arr = "[" + " ".join(f"{x} 0 R" for x in xs) + "]"
    t, v = f.xref_get_key(xref, key)
    if t == "xref":
        f.update_object(int(v.split()[0]), arr)
    else:
        f.xref_set_key(xref, key, arr)


def _acro_holder(f: fitz.Document) -> tuple[int, str]:
    """AcroForm/Fields 를 가진 (xref, 열쇠)."""
    cat = f.pdf_catalog()
    t, v = f.xref_get_key(cat, "AcroForm")
    return (int(v.split()[0]), "Fields") if t == "xref" else (cat, "AcroForm/Fields")


def _on_name(f: fitz.Document, x: int) -> str:
    """동그라미 칸의 켜짐 이름(AP/N 의 Off 아닌 열쇠)."""
    for ap in ("AP/N", "AP/D"):
        t, v = f.xref_get_key(x, ap)
        if t == "xref":
            v = f.xref_object(int(v.split()[0]))
        for n in re.findall(r"/([^\s/<>\[\]()]+)\s*(?:\d+\s+0\s+R|<<)", v or ""):
            if n != "Off":
                return n
    return ""


def _sync_radio(f: fitz.Document, x: int) -> None:
    """묶음의 고른 값(/V)을 켜진 동그라미의 켜짐 이름(이름 객체)으로. PyMuPDF 는 글자열로 넣는다."""
    t, v = f.xref_get_key(x, "Parent")
    if t != "xref":
        return
    par = int(v.split()[0])
    on = "/Off"
    for k in _get_refs(f, par, "Kids"):
        a = f.xref_get_key(k, "AS")[1]
        if a.startswith("/") and a != "/Off":
            on = a
    f.xref_set_key(par, "V", on)
    if f.xref_get_key(x, "V")[0] != "null" or f.xref_get_key(x, "Ff")[0] != "null":
        del_keys(f, x, ("V", "Ff"))  # 동그라미 칸에는 칸 값·깃발을 두지 않는다(부모 것을 물려받음)


def save_widget(w: fitz.Widget) -> None:
    """w.update() 대신 쓴다. PyMuPDF 는 꺼진 라디오(값 'Off')를 update 하면 켜 버리고, 묶음 값을 글자열로 넣는다."""
    radio = w.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON
    if radio and w.field_value in ("Off", "", None):
        w.field_value = False
    w.update()
    if radio:
        _sync_radio(w.parent.parent, w.xref)


def reset_widget(w: fitz.Widget) -> None:
    """칸 값 비우기. w.reset() 은 라디오 동그라미를 끄지 못한다."""
    if w.field_type in (fitz.PDF_WIDGET_TYPE_RADIOBUTTON, fitz.PDF_WIDGET_TYPE_CHECKBOX):
        w.field_value = False
        save_widget(w)
    else:
        w.reset()  # field_value = "" 는 텍스트·콤보·목록에서 무시된다


def _rename_on(f: fitz.Document, x: int, old: str, new: str) -> None:
    gone = []
    for ap in ("AP/N", "AP/D"):
        t, v = f.xref_get_key(x, f"{ap}/{old}")
        if t != "null":
            f.xref_set_key(x, f"{ap}/{new}", v)
            gone.append(f"{ap}/{old}")
    if f.xref_get_key(x, "AS")[1] == f"/{old}":
        f.xref_set_key(x, "AS", f"/{new}")
    del_keys(f, x, gone)


def _radio_parent(f: fitz.Document, x: int) -> int:
    """동그라미 칸 x 의 묶음(부모) xref. 혼자 서 있는 라디오(다른 프로그램이 만든 것)면 부모를 만들어 그 밑에 넣는다."""
    t, v = f.xref_get_key(x, "Parent")
    if t == "xref":
        return int(v.split()[0])
    name = f.xref_get_key(x, "T")[1]
    ff = f.xref_get_key(x, "Ff")[1]
    if _on_name(f, x) == "Yes":  # 체크 박스로 만든 칸
        _rename_on(f, x, "Yes", "Choice1")
    on = f.xref_get_key(x, "AS")[1]
    par = f.get_new_xref()
    f.update_object(par, f"<</FT/Btn/Ff {ff if ff.isdigit() else _RADIO_FLAGS}/T {fitz.get_pdf_str(name)}"
                         f"/V {on if on.startswith('/') else '/Off'}/Kids[{x} 0 R]>>")
    del_keys(f, x, ("T", "FT", "Ff", "V"))
    f.xref_set_key(x, "Parent", f"{par} 0 R")
    holder, key = _acro_holder(f)
    xs = _get_refs(f, holder, key)
    _set_refs(f, holder, key, [par if k == x else k for k in xs] if x in xs else xs + [par])
    return par


def _radio_move(f: fitz.Document, x: int, group: str) -> None:
    """동그라미 칸 x 를 이름이 group 인 묶음으로 옮긴다(없으면 새 묶음). 켜짐 이름은 묶음 안에서 겹치지 않게."""
    holder, key = _acro_holder(f)
    t, v = f.xref_get_key(x, "Parent")
    if t == "xref":  # 옛 묶음에서 빼기
        old = int(v.split()[0])
        if f.xref_get_key(old, "T")[1] == group:
            return
        kids = [k for k in _get_refs(f, old, "Kids") if k != x]
        _set_refs(f, old, "Kids", kids)
        if not kids:
            _set_refs(f, holder, key, [k for k in _get_refs(f, holder, key) if k != old])
        elif f.xref_get_key(old, "V")[1] == f"/{_on_name(f, x)}":
            f.xref_set_key(old, "V", "/Off")
    par = None
    for pno in range(f.page_count):
        pg = f[pno]
        for w in pg.widgets():
            if w.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON and w.xref != x and w.field_name == group:
                par = _radio_parent(f, w.xref)
                break
        if par:
            break
    if par is None:
        par = f.get_new_xref()
        f.update_object(par, f"<</FT/Btn/Ff {_RADIO_FLAGS}/T {fitz.get_pdf_str(group)}/V/Off/Kids[]>>")
        _set_refs(f, holder, key, _get_refs(f, holder, key) + [par])
    kids = _get_refs(f, par, "Kids")
    used = {_on_name(f, k) for k in kids}
    _set_refs(f, holder, key, [k for k in _get_refs(f, holder, key) if k != x])
    del_keys(f, x, ("T", "FT", "Ff", "V"))
    f.xref_set_key(x, "Parent", f"{par} 0 R")
    _set_refs(f, par, "Kids", kids + [x])
    on = _on_name(f, x)
    if on in used or on in ("", "Yes"):
        n = 1
        while f"Choice{n}" in used:
            n += 1
        _rename_on(f, x, on or "Yes", f"Choice{n}")
    f.xref_set_key(x, "AS", "/Off")


def _refresh_widget(page: fitz.Page, x: int) -> None:
    """구조를 바꾼 칸의 모양을 새로 그린다(라디오는 동그라미로)."""
    for w in page.widgets():
        if w.xref == x:
            save_widget(w)
            return


def rename_field(doc: Document, page: int, xref: int, name: str) -> None:
    """칸 이름 바꾸기. 라디오는 이름이 곧 묶음이라, 같은 이름의 묶음으로 옮겨 간다."""
    with doc.lock:
        p = doc.fitz[page]
        w = next((w for w in p.widgets() if w.xref == xref), None)
        if w is None or not name or name == w.field_name:
            return
        if w.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
            _radio_move(doc.fitz, xref, name)
            _refresh_widget(p, xref)
        else:
            w.field_name = name
            save_widget(w)


def fields(doc: Document) -> list[dict]:
    out = []
    with doc.lock:
        for i in range(doc.page_count):
            for w in doc.fitz[i].widgets():
                out.append({"page": i, "xref": w.xref, "name": w.field_name, "type": w.field_type_string,
                            "value": w.field_value, "rect": fitz.Rect(w.rect), "options": w.choice_values or []})
    return out


def set_field_value(doc: Document, page: int, xref: int, value):
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        for w in p.widgets():
            if w.xref == xref:
                w.field_value = value
                save_widget(w)
                return


def delete_field(doc: Document, page: int, xref: int):
    doc.snapshot()
    with doc.lock:
        p = doc.fitz[page]
        for w in p.widgets():
            if w.xref == xref:
                f = doc.fitz
                t, v = f.xref_get_key(xref, "Parent")
                p.delete_widget(w)
                if t == "xref":  # 라디오 묶음에 남은 빈자리도 걷는다
                    par = int(v.split()[0])
                    kids = [k for k in _get_refs(f, par, "Kids") if k != xref]
                    _set_refs(f, par, "Kids", kids)
                    if not kids:
                        holder, key = _acro_holder(f)
                        _set_refs(f, holder, key, [k for k in _get_refs(f, holder, key) if k != par])
                return


def reset_fields(doc: Document):
    doc.snapshot()
    with doc.lock:
        for i in range(doc.page_count):
            for w in doc.fitz[i].widgets():
                reset_widget(w)


def align_fields(doc: Document, items: list[tuple[int, int]], how: str):
    """items=(page,xref) 들을 맞춘다. how: left right top bottom hcenter vcenter page_h page_v page_both"""
    if not items:
        return
    doc.snapshot()
    with doc.lock:
        ws = []
        held = {}  # 쪽 객체를 붙잡아 둔다(놓치면 칸이 풀려 update 가 「Annot is not bound to a page」 로 멈춘다)
        for pg, xref in items:
            p = held.setdefault(pg, doc.fitz[pg])
            for w in p.widgets():
                if w.xref == xref:
                    ws.append((pg, w))
        if not ws:
            return
        rects = [fitz.Rect(w.rect) for _, w in ws]
        for (pg, w), r in zip(ws, rects):
            page_r = doc.fitz[pg].rect
            nr = fitz.Rect(r)
            if how == "left":
                nr.x0, nr.x1 = min(x.x0 for x in rects), min(x.x0 for x in rects) + r.width
            elif how == "right":
                nr.x1 = max(x.x1 for x in rects); nr.x0 = nr.x1 - r.width
            elif how == "top":
                nr.y0 = min(x.y0 for x in rects); nr.y1 = nr.y0 + r.height
            elif how == "bottom":
                nr.y1 = max(x.y1 for x in rects); nr.y0 = nr.y1 - r.height
            elif how == "hcenter":
                c = sum((x.x0 + x.x1) / 2 for x in rects) / len(rects)
                nr.x0, nr.x1 = c - r.width / 2, c + r.width / 2
            elif how == "vcenter":
                c = sum((x.y0 + x.y1) / 2 for x in rects) / len(rects)
                nr.y0, nr.y1 = c - r.height / 2, c + r.height / 2
            elif how in ("page_h", "page_both"):
                c = page_r.width / 2
                nr.x0, nr.x1 = c - r.width / 2, c + r.width / 2
            if how in ("page_v", "page_both"):
                c = page_r.height / 2
                nr.y0, nr.y1 = c - r.height / 2, c + r.height / 2
            w.rect = nr
            save_widget(w)


def recognize_fields(doc: Document, pages: Sequence[int] | None = None) -> int:
    """양식 인식(간단판): 글자 뒤에 오는 긴 밑줄·빈 네모를 찾아 텍스트 칸을 만든다."""
    made = 0
    doc.snapshot()
    with doc.lock:
        for i in (pages if pages is not None else range(doc.page_count)):
            p = doc.fitz[i]
            existing = [fitz.Rect(w.rect) for w in p.widgets()]
            for d in p.get_drawings():
                r = fitz.Rect(d["rect"])
                is_line = r.height <= 2 and r.width >= 40
                is_box = 8 <= r.height <= 40 and r.width >= 40 and d.get("fill") in (None, (1, 1, 1))
                if not (is_line or is_box):
                    continue
                fr = fitz.Rect(r.x0, r.y0 - 14, r.x1, r.y1) if is_line else r
                if any(fr.intersects(e) for e in existing):
                    continue
                if p.get_text("text", clip=fr).strip():
                    continue
                w = fitz.Widget()
                w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                w.field_name = _unique_name(doc, "텍스트")
                w.rect = fr
                w.text_fontsize = 10
                w.border_width = 0
                p.add_widget(w)
                existing.append(fr)
                made += 1
    return made

"""주석 종류별 기본 모양(색·두께·불투명도·글자 크기)을 마지막에 쓴 값으로 기억한다.

일반적인 PDF 편집기는 종류마다 Annots.ini 에 한 칸씩 두고 「마지막에 고친 모양을 기본값으로」가 기본 켬이다.
우리는 설정 폴더의 annot_styles.json 한 벌에 도구 이름(highlight·rect·textbox …)마다 한 칸.
settings.json 은 창이 통째로 다시 쓰므로 따로 둔다.
"""
from __future__ import annotations

import json
import os

import fitz

from .annots import Color, MARKUP_KINDS, _freetext_border, _freetext_style, annot_colors  # noqa: F401
from .document import Document

YELLOW = (1.0, 238 / 255, 54 / 255)   # 강조색 #FFEE36
RED = (1.0, 0.0, 0.0)
PURPLE = (0.5, 0.0, 0.5)

# 기본값(기능명세/주석.md 「주석 객체와 종류별 기본값」). 선 굵기 1·불투명도 100%·채움 없음이 공통.
_SHAPE = {"stroke": RED, "fill": None, "width": 1.0, "opacity": 1.0}
_LINE = {"stroke": RED, "width": 1.0, "opacity": 1.0}
_TEXT = {"text_color": RED, "fontsize": 14.0, "opacity": 1.0}
DEFAULTS: dict[str, dict] = {
    "highlight": {"color": YELLOW, "opacity": 1.0},
    "underline": {"color": RED, "opacity": 1.0},
    "strike": {"color": RED, "opacity": 1.0},
    "squiggly": {"color": RED, "opacity": 1.0},
    "caret": {"color": PURPLE, "opacity": 1.0},
    "areahl": {"color": YELLOW, "opacity": 0.3},   # 일반적인 PDF 편집기는 채움 알파 76(약 30%)
    "rect": dict(_SHAPE), "oval": dict(_SHAPE), "polygon": dict(_SHAPE), "cloud": dict(_SHAPE),
    "line": dict(_LINE), "arrow": dict(_LINE), "polyline": dict(_LINE),
    "pencil": {"stroke": RED, "width": 1.0, "opacity": 1.0},
    "note": {"color": (1.0, 1.0, 0.0), "opacity": 1.0},
    "textbox": dict(_TEXT, fill=None, border=RED, width=1.0),
    "callout": dict(_TEXT, fill=None, border=RED, width=1.0),
    "typewriter": dict(_TEXT),
    "stamp": {"stroke": (0.8, 0.0, 0.0)},
}

# 속성 패널이 그 종류에 보일 칸(차례 그대로). 고른 주석에만 보이는 칸은 SELECTED_ONLY.
FIELDS: dict[str, tuple[str, ...]] = {k: tuple(v) for k, v in DEFAULTS.items()}
for _k in ("rect", "oval", "polygon", "cloud", "line", "arrow", "polyline"):
    FIELDS[_k] += ("dashes",)
SELECTED_ONLY = ("dashes",)

# 테두리 모양(속성 패널 목록에서 구름 둘은 다각형의 「클라우드」 도구로 따로 있어 뺌)
DASHES = {"실선": (), "점선 2·2": (2, 2), "점선 3·3": (3, 3), "점선 4·4": (4, 4),
          "점선 4·3·2·4": (4, 3, 2, 4), "점선 4·3·1·6·3·3": (4, 3, 1, 6, 3, 3), "점선 8·4·4·4": (8, 4, 4, 4)}

# 도구 → 이름(속성 패널 맨 위)
TOOL_NAMES = {
    "highlight": "강조", "underline": "밑줄", "strike": "취소선", "squiggly": "구불구불한 선", "caret": "삽입 기호",
    "areahl": "영역 강조", "rect": "직사각형", "oval": "타원", "polygon": "다각형", "cloud": "클라우드",
    "line": "선", "arrow": "화살표", "polyline": "연결된 선", "pencil": "연필", "note": "노트",
    "textbox": "텍스트 박스", "callout": "텍스트 말풍선", "typewriter": "타자기", "stamp": "스탬프",
}


def _tup(v):
    return tuple(v) if isinstance(v, (list, tuple)) else v


def to_viewer_props(key: str, style: dict, props: dict) -> None:
    """한 종류의 기본값을 뷰어 도구 속성(viewer.props)에 얹는다. 뷰어·창은 이 칸들로 주석을 만든다."""
    s = {k: _tup(v) for k, v in style.items()}
    if "opacity" in s:
        props["opacity"] = s["opacity"]
    if key == "pencil":
        props["ink_color"], props["ink_width"] = s["stroke"], s["width"]
    elif key == "caret":
        props["caret_color"] = s["color"]
    elif "color" in s:  # 강조·밑줄·영역 강조·노트
        props["hl_color"] = s["color"]
    elif key in ("textbox", "callout", "typewriter"):
        props["fontsize"], props["text_color"] = s["fontsize"], s["text_color"]
        props["fill"] = s.get("fill")
        props["stroke"] = s.get("border")   # 글상자 대화상자는 stroke 를 테두리색으로 읽는다
        props["width"] = s.get("width", 0)
    else:
        for k in ("stroke", "fill", "width"):
            if k in s:
                props[k] = s[k]


def key_of(doc: Document, a: fitz.Annot) -> str | None:
    """이미 있는 주석이 어느 도구의 것인가(그 종류의 기본값으로 기억할 칸). 모르면 None."""
    f, kind = doc.fitz, a.type[1]
    if kind in MARKUP_KINDS:
        return {"Highlight": "highlight", "Underline": "underline", "StrikeOut": "strike", "Squiggly": "squiggly"}[kind]
    if kind == "Square":
        c = a.colors
        if not ((a.border or {}).get("width") or 0) and c.get("fill") and c.get("fill") == c.get("stroke"):
            return "areahl"
        return "rect"
    if kind == "Polygon":
        return "cloud" if (a.border or {}).get("clouds", 0) > 0 else "polygon"
    if kind == "Line":
        return "arrow" if a.line_ends and a.line_ends[1] == fitz.PDF_ANNOT_LE_OPEN_ARROW else "line"
    if kind == "FreeText":
        if (a.info.get("subject") or "") == "Stamp":
            return "stamp"
        if f.xref_get_key(a.xref, "IT")[1] == "/FreeTextCallout":
            return "callout"
        if not ((a.border or {}).get("width") or 0) and not annot_colors(doc, a).get("fill"):
            return "typewriter"
        return "textbox"
    return {"Circle": "oval", "PolyLine": "polyline", "Ink": "pencil", "Text": "note", "Caret": "caret"}.get(kind)


def style_of(doc: Document, a: fitz.Annot, key: str | None = None) -> dict:
    """이미 있는 주석의 지금 모양을 그 종류의 칸 이름으로(속성 패널에 보일 값)."""
    key = key or key_of(doc, a)
    cols = annot_colors(doc, a)
    op = a.opacity
    s = {"opacity": 1.0 if op is None or op < 0 else round(op, 2)}
    b = a.border or {}
    if key in ("textbox", "callout", "typewriter", "stamp"):
        fs, tc = _freetext_style(doc, a)
        s.update(fontsize=fs, text_color=tc, stroke=tc, fill=_tup(cols.get("fill")) or None,
                 border=_freetext_border(a), width=b.get("width") or 0)
        return s
    stroke = _tup(cols.get("stroke")) or None
    s.update(color=stroke, stroke=stroke, fill=_tup(cols.get("fill")) or None, width=b.get("width", 1) or 0,
             dashes=tuple(b.get("dashes") or ()))
    return s


class StyleStore:
    """annot_styles.json 읽고 쓰기. 파일이 없거나 칸이 없으면 DEFAULTS."""

    def __init__(self, path: str | None):
        self.path = path
        self.data: dict[str, dict] = {}
        try:
            with open(path, encoding="utf-8") as fp:
                raw = json.load(fp)
            if isinstance(raw, dict):
                self.data = {k: v for k, v in raw.items() if k in DEFAULTS and isinstance(v, dict)}
        except (OSError, ValueError, TypeError):
            pass

    def get(self, key: str) -> dict:
        out = dict(DEFAULTS.get(key, {}))
        for k, v in self.data.get(key, {}).items():
            if k in out:
                out[k] = _tup(v)
        return out

    def remember(self, key: str | None, values: dict) -> bool:
        """그 종류에 쓰는 칸만 골라 기억한다. 바뀐 게 있으면 저장하고 True."""
        if key not in DEFAULTS:
            return False
        cur = self.get(key)
        new = dict(cur)
        for k, v in values.items():
            if k in cur:
                new[k] = _tup(v)
        if new == cur:
            return False
        self.data[key] = new
        self.save()
        return True

    def reset(self, key: str) -> None:
        self.data.pop(key, None)
        self.save()

    def save(self) -> None:
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump(self.data, fp, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass


def default_path() -> str:
    from ..appinfo import APP_ID
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_ID, "annot_styles.json")


_store: StyleStore | None = None


def store() -> StyleStore:
    """앱 전체가 같이 쓰는 한 벌(탭이 여럿이어도 같은 기본값)."""
    global _store
    if _store is None:
        _store = StyleStore(default_path())
    return _store

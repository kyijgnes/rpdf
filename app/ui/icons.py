"""아이콘: 윈도우 11 내장 Segoe Fluent Icons 글자를 그려 QIcon 으로. 그림 파일 없음.

이름 → 글자 코드. 모르는 이름은 첫 글자를 네모에 그린다.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QIconEngine, QPainter, QPen, QPixmap

from . import theme

GLYPH = {
    # 파일·공통
    "open": 0xE8E5, "save": 0xE74E, "saveas": 0xE792, "print": 0xE749, "undo": 0xE7A7, "redo": 0xE7A6,
    "mail": 0xE715, "share": 0xE72D, "new": 0xE8A5, "folder": 0xE8B7, "recent": 0xE81C, "star": 0xE734,
    "close": 0xE711, "menu": 0xE700, "more": 0xE712, "settings": 0xE713, "info": 0xE946, "help": 0xE897,
    "back": 0xE72B, "forward": 0xE72A, "down": 0xE70D, "up": 0xE70E, "right": 0xE76C, "left": 0xE76B,
    "first": 0xE892, "last": 0xE893, "prev": 0xE76B, "next": 0xE76C, "refresh": 0xE72C, "search": 0xE721,
    "check": 0xE73E, "add": 0xE710, "remove": 0xE738, "delete": 0xE74D, "copy": 0xE8C8, "paste": 0xE77F,
    "cut": 0xE8C6, "clipboard": 0xF0E3, "export": 0xEDE1, "import": 0xE8B5, "pin": 0xE718, "cloud": 0xE753,
    # 보기
    "zoomin": 0xE8A3, "zoomout": 0xE71F, "fitpage": 0xE9A6, "fitwidth": 0xE9A6, "actual": 0xE799,
    "fullscreen": 0xE740, "single": 0xE7C3, "continuous": 0xE8A4, "facing": 0xE736, "tile": 0xE8A9,
    "read": 0xE8FD, "rotate": 0xE7AD, "rotateleft": 0xE7A7, "rotateright": 0xE7A6, "grid": 0xF0E2,
    "hand": 0xE7C9, "select": 0xE8B0, "snapshot": 0xE722, "ruler": 0xED5E, "eye": 0xE7B3, "dark": 0xE708,
    # 왼쪽 막대
    "thumbs": 0xE7C3, "bookmark": 0xE8A4, "comments": 0xE90A, "attach": 0xE723, "layers": 0xE81E,
    "fields": 0xE8E9, "signature": 0xEE56, "props": 0xE90F,
    # 주석
    "highlight": 0xE7E6, "underline": 0xE8DC, "strike": 0xEDE0, "squiggly": 0xE8DD, "areahl": 0xEF20,
    "caret": 0xE78B, "rect": 0xE739, "oval": 0xEA3A, "line": 0xE8EC, "arrow": 0xE8E2, "polygon": 0xE8F1,
    "polyline": 0xEE97, "cloudshape": 0xE753, "note": 0xE70B, "typewriter": 0xE8D2, "textbox": 0xE8A1,
    "callout": 0xE8F2, "pencil": 0xEE56, "eraser": 0xED60, "stamp": 0xE8B6, "measure": 0xED5E,
    "sign": 0xEE56, "createnote": 0xE70B,
    # 편집
    "edit": 0xE70F, "addtext": 0xE8D2, "addimage": 0xE8B9, "link": 0xE71B, "watermark": 0xE7B5,
    "background": 0xE771, "headerfooter": 0xE8E4, "bates": 0xE8EF, "crop": 0xE7A8, "resize": 0xE740,
    # 변환
    "convert": 0xE8AB, "word": 0xE8A5, "excel": 0xE9D5, "ppt": 0xE7F8, "image": 0xE8B9, "text": 0xE8D2,
    "hwp": 0xE8A5, "html": 0xE774, "epub": 0xE736, "rtf": 0xE8A5, "pdfa": 0xE72E, "batch": 0xE9D5, "create": 0xE8A5,
    # 구성
    "extract": 0xEDE1, "split": 0xE8C7, "insert": 0xE710, "replace": 0xE895, "pagebox": 0xE740, "label": 0xE8EC,
    "blank": 0xE7C3, "frompdf": 0xE8E5, "duplicate": 0xE8C8,
    # 도구
    "ocr": 0xE8D2, "ocrarea": 0xE8B0, "merge": 0xE8F1, "compare": 0xE8A4, "compress": 0xE73F, "flatten": 0xE8A4,
    "translate": 0xE775, "table": 0xF0E2, "scan": 0xE8FE,
    # 양식
    "ftext": 0xE8D2, "fcheck": 0xE73A, "fradio": 0xECCA, "fcombo": 0xE70D, "flist": 0xE8FD, "fbutton": 0xE7C4,
    "fimage": 0xE8B9, "fsign": 0xEE56, "fdate": 0xE787, "align": 0xE8E4, "recognize": 0xE8B0, "calc": 0xE8EF,
    "preview": 0xE7B3, "clear": 0xE74D,
    # 보안
    "lock": 0xE72E, "unlock": 0xE785, "redact": 0xE8B0, "redactapply": 0xE73E, "redactsearch": 0xE721,
    "hidden": 0xED1A, "cert": 0xEB95, "validate": 0xE73E, "clearsig": 0xE74D,
}

_FONT_NAME = None
_cache: dict[tuple, QIcon] = {}


def _font_name() -> str:
    global _FONT_NAME
    if _FONT_NAME is None:
        fams = set(QFontDatabase.families())
        for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI Symbol"):
            if f in fams:
                _FONT_NAME = f
                break
        else:
            _FONT_NAME = "Segoe UI Symbol"
    return _FONT_NAME


def _draw(p: QPainter, rect: QRectF, name: str, col: QColor):
    """글자 아이콘 하나를 rect 에 그린다(장치 픽셀로 그려 고해상도 화면에서도 또렷하게)."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    size = min(rect.width(), rect.height())
    code = GLYPH.get(name)
    if code:
        f = QFont(_font_name())
        f.setPixelSize(max(1, round(size * 0.82)))
        p.setFont(f)
        p.setPen(col)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, chr(code))
    else:
        p.setPen(QPen(col, max(1.0, size / 14)))
        p.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), 3, 3)
        f = QFont(theme.FONT)
        f.setPixelSize(max(1, round(size * 0.55)))
        f.setBold(True)
        p.setFont(f)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, (name[:1] or "?").upper())


class _GlyphEngine(QIconEngine):
    """그릴 때마다 지금 테마 색을 쓴다: 보통은 글자색, 꺼진 단추는 흐린 색, 켜진(눌린) 단추는 강조 빨강.
    전에는 밝은 테마 검정으로 미리 그려 두어 「어두운 화면」 에서 아이콘이 거의 안 보였다."""

    def __init__(self, name: str, color: str | None):
        super().__init__()
        self.name, self.color = name, color

    def _color(self, mode, state) -> QColor:
        if mode == QIcon.Mode.Disabled:
            return QColor(theme.CUR["TEXT_DIM"])
        if self.color:
            return QColor(self.color)
        if state == QIcon.State.On:
            return QColor(theme.ACCENT)
        return QColor(theme.CUR["TEXT"])

    def paint(self, painter, rect, mode, state):
        painter.save()
        _draw(painter, QRectF(rect), self.name, self._color(mode, state))
        painter.restore()

    def scaledPixmap(self, size, mode, state, scale):
        pm = QPixmap(QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale))))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        _draw(p, QRectF(0, 0, pm.width(), pm.height()), self.name, self._color(mode, state))
        p.end()
        pm.setDevicePixelRatio(scale)
        return pm

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, 1.0)

    def clone(self):
        e = _GlyphEngine(self.name, self.color)
        _engines.append(e)
        return e


_engines: list[_GlyphEngine] = []  # 파이썬 쪽 엔진을 붙잡아 둔다(놓치면 Qt 가 부를 때 튕김)


def pixmap(name: str, size: int = 18, color: str | None = None) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    _draw(p, QRectF(0, 0, size, size), name, QColor(color or theme.CUR["TEXT"]))
    p.end()
    return pm


def icon(name: str, size: int = 18, color: str | None = None) -> QIcon:
    key = (name, size, color)
    if key not in _cache:
        e = _GlyphEngine(name, color)
        _engines.append(e)
        _cache[key] = QIcon(e)
    return _cache[key]


def icon_size(n: int = 18) -> QSize:
    return QSize(n, n)

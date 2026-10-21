"""인쇄: 알PDF 인쇄 창과 같은 배치·항목의 인쇄 창(PrintDialog)과 실제로 그려 보내는 일(send).

창은 세 칸이다. 왼쪽(프린터·인쇄 설정·방향·페이지 범위), 가운데 고급 설정(내용 인쇄·홀짝·역순·인쇄 모드 탭
크기/포스터/여러 페이지/소책자), 오른쪽 미리보기와 쪽 넘기기. 「고급 설정 숨기기」 로 가운데 칸을 접는다.

종이 한 장에 무엇을 어디에 그릴지는 plan() 한 곳에서 정하고(Sheet·Cell), 미리보기와 보내기가 같은 계산을 쓴다.
보내기는 칸마다 쪽을 선·면·글자 윤곽(벡터, print_vector)으로 그린다. 벡터로 못 옮기는 쪽(투명도 등)과
「이미지로 인쇄」 만 그림(프린터 해상도, 최대 600dpi, 또는 고른 dpi)으로 떠서 그린다.
그리는 동안 진행 막대와 [그만두기] 를 보이고, 프린터를 못 열면 한국어로 알린다. 일괄 인쇄도 send 로 보낸다
(윈도우 「인쇄」 동작은 PDF 기본 앱에 따라 등록돼 있지 않아 늘 실패했다).
"""
from __future__ import annotations

import math
import os
from contextlib import nullcontext
from dataclasses import dataclass, field

import fitz
from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPageLayout, QPageSize, QPainter, QPen, QPixmap, QTransform
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QProgressDialog, QPushButton, QRadioButton,
                               QSpinBox, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from . import icons, print_vector as PV, theme

FITS = [("fit", "맞춤"), ("actual", "실제 크기"), ("custom", "사용자 지정 배율")]
SUBSETS = [("all", "모든 페이지"), ("odd", "홀수 페이지"), ("even", "짝수 페이지")]
DUPLEX = [("none", "단일면", QPrinter.DuplexMode.DuplexNone),
          ("long", "긴 가장자리에 양면 플립", QPrinter.DuplexMode.DuplexLongSide),
          ("short", "짧은 가장자리에 양면 플립", QPrinter.DuplexMode.DuplexShortSide),
          ("manual", "수동으로 양면 프린트", QPrinter.DuplexMode.DuplexNone)]
DPIS = [72, 96, 144, 150, 300, 400, 600]
MODES = [("size", "크기"), ("poster", "포스터"), ("multi", "여러 페이지"), ("booklet", "소책자")]
NUPS = [(2, "2"), (4, "4"), (6, "6"), (9, "9"), (16, "16"), (0, "사용자 지정...")]
NUP_GRID = {2: (1, 2), 4: (2, 2), 6: (2, 3), 9: (3, 3), 16: (4, 4)}  # 세로 종이의 (열, 행). 가로 종이는 맞바꾼다
ORDERS = [("h", "가로"), ("hr", "가로 역순"), ("v", "세로"), ("vr", "세로 역순")]
BOOKLET_SUBSETS = [("both", "양면"), ("front", "앞면"), ("back", "뒷면")]
MANUAL_TIP = "앞면 인쇄가 끝났습니다. 나온 종이를 뒤집어 용지함에 다시 넣고 [확인] 을 누르면 뒷면을 인쇄합니다."
CM = 72 / 2.54
MAX_DPI = 600  # 그 이상은 글자가 더 좋아지지 않고 그림만 커진다


@dataclass
class PrintOptions:
    printer: str = ""
    pages: list[int] = field(default_factory=list)  # 0부터, 보낼 차례대로(홀짝·역순 반영)
    copies: int = 1
    collate: bool = True
    mode: str = "size"           # size(크기) · poster · multi(여러 페이지) · booklet(소책자)
    fit: str = "fit"             # fit(맞춤) · actual(실제 크기) · custom(사용자 지정 배율)
    scale: int = 100             # 사용자 지정 배율(%)
    auto_rotate: bool = True
    center: bool = True
    orient: str = "auto"         # portrait · landscape · auto(첫 쪽 모양 따라, 일괄 인쇄)
    paper: str = "A4"            # QPageSize 이름(다음에 열 때 고를 이름)
    page_size: object = None     # 프린터가 알려 준 QPageSize 그대로(드라이버 고유 용지도 맞게). 없으면 paper 이름으로 찾음
    source_size: bool = False    # 소스 파일의 페이지 크기: 쪽마다 그 쪽 크기 종이
    duplex: str = "none"         # none · long · short · manual
    color: bool = True           # False = 흑백 인쇄
    content: bool = True         # 내용 인쇄: 문서
    annots: bool = True          # 내용 인쇄: 주석
    forms: bool = True           # 내용 인쇄: 양식
    as_image: bool = False       # 이미지로 인쇄(고른 dpi 로 떠서 보냄)
    dpi: int = 300
    view: tuple | None = None    # 최근 보기: (쪽, fitz.Rect 쪽에서 보이던 곳)
    poster_scale: int = 100      # 타일 스케일(%)
    overlap: float = 0.0         # 겹침(cm)
    cut_marks: bool = False
    labels: bool = False
    nup: int = 2                 # 시트 당 페이지(0 = 사용자 지정)
    nup_cols: int = 2
    nup_rows: int = 2
    nup_order: str = "h"
    booklet_subset: str = "both"
    booklet_from: int = 1        # 시작 시트(1부터)
    booklet_to: int = 0          # 끝 시트(0 = 끝까지)
    booklet_right: bool = False  # 우철(오른쪽 넘김)
    margins: tuple | None = None  # 인쇄 영역 바깥(pt: 왼·위·오른·아래). 없으면 프린터 기본
    doc_name: str = ""
    to_file: str = ""            # 시험용: 이 경로로 PDF 를 쓴다(프린터 이름 없으면 Qt 자체 PDF)


# ── 계산 ─────────────────────────────────────────────────────────
def pick_pages(total: int, base: list[int], subset: str = "all", reverse: bool = False) -> list[int]:
    """고른 쪽들에서 홀수·짝수 페이지만 남기고 차례를 정한다(손으로 양면 인쇄할 때 쓰는 고르기)."""
    pages = [i for i in base if 0 <= i < total]
    if subset == "odd":
        pages = [i for i in pages if i % 2 == 0]
    elif subset == "even":
        pages = [i for i in pages if i % 2 == 1]
    return pages[::-1] if reverse else pages


def fit_in(w: float, h: float, box: fitz.Rect, fit: str = "fit", scale: float = 1.0, auto_rotate: bool = True,
           center: bool = True):
    """w×h(pt) 를 box 에 놓는 법: (돌릴 각도 0·270, 배율, 놓일 자리 Rect)."""
    rot = 0
    if auto_rotate and abs(w - h) > 1 and (w > h) != (box.width > box.height):
        rot, w, h = 270, h, w  # 알PDF 처럼 왼쪽으로 눕힌다(글 윗머리가 왼쪽)
    s = min(box.width / w, box.height / h) if fit == "fit" else scale if fit == "custom" else 1.0
    tw, th = w * s, h * s
    x = box.x0 + (box.width - tw) / 2 if center else box.x0
    y = box.y0 + (box.height - th) / 2 if center else box.y0
    return rot, s, fitz.Rect(x, y, x + tw, y + th)


def paper_orientation(doc: fitz.Document, pages: list[int], orient: str) -> QPageLayout.Orientation:
    if orient == "landscape":
        return QPageLayout.Orientation.Landscape
    if orient == "portrait" or not pages:
        return QPageLayout.Orientation.Portrait
    r = doc[pages[0]].rect  # 자동: 첫 쪽 모양을 따르고, 모양이 다른 쪽은 돌려 앉힌다
    return QPageLayout.Orientation.Landscape if r.width > r.height else QPageLayout.Orientation.Portrait


@dataclass
class Cell:
    """종이 위에 쪽 하나(또는 그 일부)를 그리는 자리."""
    page: int
    m: fitz.Matrix          # 쪽(page.rect 좌표) → 종이(pt)
    s: float                # 배율(그림 해상도 정할 때)
    rot: int                # 더 돌리는 각도(0·270)
    clip: fitz.Rect         # 종이에서 이 쪽이 보일 수 있는 곳
    src: fitz.Rect | None = None  # 쪽에서 쓸 곳(최근 보기). None 이면 쪽 전체


@dataclass
class Sheet:
    w: float
    h: float
    cells: list[Cell] = field(default_factory=list)
    marks: list[tuple] = field(default_factory=list)   # 실선(컷 마크): (x0, y0, x1, y1)
    guides: list[tuple] = field(default_factory=list)  # 점선(미리보기의 타일 경계)
    label: str = ""
    label_at: tuple = (0.0, 0.0)


def _cell(doc: fitz.Document, i: int, box: fitz.Rect, fit="fit", scale=1.0, auto_rotate=True, center=True,
          src: fitz.Rect | None = None, clip: fitz.Rect | None = None) -> Cell:
    r = fitz.Rect(src) if src is not None else doc[i].rect
    rot, s, tgt = fit_in(r.width, r.height, box, fit, scale, auto_rotate, center)
    m = fitz.Matrix(rot)
    rr = r * m
    m = m * fitz.Matrix(1, 0, 0, 1, -rr.x0, -rr.y0) * fitz.Matrix(s, s) * fitz.Matrix(1, 0, 0, 1, tgt.x0, tgt.y0)
    c = fitz.Rect(clip if clip is not None else box)
    if src is not None:
        c &= tgt
    return Cell(i, m, s, rot, c, src)


def _box(w: float, h: float, margins) -> fitz.Rect:
    ml, mt, mr, mb = margins or (0, 0, 0, 0)
    return fitz.Rect(ml, mt, max(ml + 10, w - mr), max(mt + 10, h - mb))


def nup_grid(opts: PrintOptions, landscape: bool) -> tuple[int, int]:
    if opts.nup in NUP_GRID:
        c, r = NUP_GRID[opts.nup]
        return (r, c) if landscape else (c, r)
    return max(1, opts.nup_cols), max(1, opts.nup_rows)


def booklet_sheets(n_pages: int) -> int:
    return max(1, math.ceil(n_pages / 4)) if n_pages else 0


def _poster(doc: fitz.Document, i: int, opts: PrintOptions, box: fitz.Rect):
    """포스터 한 쪽: (돌림, 배율, 열, 행, 겹침 pt, 포스터 안 쪽 자리 x·y, 타일 폭·높이)."""
    aw, ah = box.width, box.height
    o = max(0.0, min(opts.overlap * CM, min(aw, ah) * 0.5))
    S = max(1, opts.poster_scale) / 100
    r = doc[i].rect

    def tiles(pw, ph):
        cols = 1 if pw <= aw + 0.01 else math.ceil((pw - o) / (aw - o) - 1e-6)
        rows = 1 if ph <= ah + 0.01 else math.ceil((ph - o) / (ah - o) - 1e-6)
        return cols, rows

    rot, (pw, ph) = 0, (r.width * S, r.height * S)
    cols, rows = tiles(pw, ph)
    c2, r2 = tiles(ph, pw)  # 돌리면 장 수가 줄어드는가
    if c2 * r2 < cols * rows:
        rot, pw, ph, cols, rows = 270, ph, pw, c2, r2
    tw, th = cols * aw - (cols - 1) * o, rows * ah - (rows - 1) * o
    ox = (tw - pw) / 2 if opts.center else 0.0
    oy = (th - ph) / 2 if opts.center else 0.0
    return rot, S, cols, rows, o, ox, oy, aw, ah


def _poster_matrix(doc, i, rot, S, x, y) -> fitz.Matrix:
    m = fitz.Matrix(rot)
    rr = doc[i].rect * m
    return m * fitz.Matrix(1, 0, 0, 1, -rr.x0, -rr.y0) * fitz.Matrix(S, S) * fitz.Matrix(1, 0, 0, 1, x, y)


def paper_wh(opts: PrintOptions, doc: fitz.Document) -> tuple[float, float]:
    ps = opts.page_size if isinstance(opts.page_size, QPageSize) else _page_size(opts.paper)
    sz = ps.size(QPageSize.Unit.Point)
    w, h = sorted((sz.width(), sz.height()))
    if opts.mode == "booklet":
        return h, w
    land = paper_orientation(doc, opts.pages, opts.orient) == QPageLayout.Orientation.Landscape
    return (h, w) if land else (w, h)


def plan(doc: fitz.Document, opts: PrintOptions, paper: tuple[float, float], margins) -> list[Sheet]:
    """opts 대로 인쇄할 종이 면 목록. 미리보기와 보내기가 같이 쓴다."""
    pw, ph = paper
    pages = [i for i in opts.pages if 0 <= i < len(doc)]
    if opts.view is not None:  # 최근 보기: 보이던 곳 한 군데를 크기 탭 설정으로
        i, r = opts.view
        box = _box(pw, ph, margins)
        mode_fit = opts.fit if opts.mode == "size" else "fit"
        return [Sheet(pw, ph, [_cell(doc, i, box, mode_fit, opts.scale / 100, opts.auto_rotate, opts.center, src=r)])]
    out: list[Sheet] = []
    if opts.mode == "poster":
        box = _box(pw, ph, margins)
        for i in pages:
            rot, S, cols, rows, o, ox, oy, aw, ah = _poster(doc, i, opts, box)
            for rr in range(rows):
                for cc in range(cols):
                    x0, y0 = cc * (aw - o), rr * (ah - o)
                    m = _poster_matrix(doc, i, rot, S, box.x0 + ox - x0, box.y0 + oy - y0)
                    sh = Sheet(pw, ph, [Cell(i, m, S, rot, fitz.Rect(box))])
                    if opts.cut_marks:
                        L = min(14.0, box.width / 6, box.height / 6)
                        for (x, y, dx, dy) in ((box.x0, box.y0, 1, 1), (box.x1, box.y0, -1, 1),
                                               (box.x0, box.y1, 1, -1), (box.x1, box.y1, -1, -1)):
                            sh.marks += [(x, y, x + dx * L, y), (x, y, x, y + dy * L)]
                    if opts.labels:
                        name = f"{opts.doc_name}  " if opts.doc_name else ""
                        sh.label = f"{name}{i + 1}쪽 ({rr + 1}, {cc + 1})"
                        sh.label_at = (box.x0 + 4, box.y1 - 4)
                    out.append(sh)
        return out
    if opts.mode == "multi":
        box = _box(pw, ph, margins)
        cols, rows = nup_grid(opts, pw > ph)
        n = cols * rows
        cw, chh = box.width / cols, box.height / rows
        for k0 in range(0, len(pages), n):
            sh = Sheet(pw, ph)
            for k, i in enumerate(pages[k0:k0 + n]):
                if opts.nup_order in ("h", "hr"):
                    r, c = divmod(k, cols)
                else:
                    c, r = divmod(k, rows)
                if opts.nup_order in ("hr", "vr"):
                    c = cols - 1 - c
                cb = fitz.Rect(box.x0 + c * cw, box.y0 + r * chh, box.x0 + (c + 1) * cw, box.y0 + (r + 1) * chh)
                sh.cells.append(_cell(doc, i, cb, "fit", 1.0, opts.auto_rotate, opts.center))
            out.append(sh)
        return out
    if opts.mode == "booklet":
        box = _box(pw, ph, margins)
        seq = pages + [-1] * (-len(pages) % 4)
        n4, total = len(seq), booklet_sheets(len(pages))
        if not total:
            return []
        a = max(1, min(opts.booklet_from, total))
        b = total if opts.booklet_to <= 0 else max(a, min(opts.booklet_to, total))
        mid = pw / 2
        halves = (fitz.Rect(box.x0, box.y0, min(mid, box.x1), box.y1), fitz.Rect(max(mid, box.x0), box.y0, box.x1, box.y1))
        for s in range(a - 1, b):
            sides = []
            if opts.booklet_subset in ("both", "front"):
                sides.append((seq[n4 - 1 - 2 * s], seq[2 * s]))
            if opts.booklet_subset in ("both", "back"):
                sides.append((seq[2 * s + 1], seq[n4 - 2 - 2 * s]))
            for left, right in sides:
                if opts.booklet_right:
                    left, right = right, left
                sh = Sheet(pw, ph)
                for i, hb in ((left, halves[0]), (right, halves[1])):
                    if i >= 0:
                        sh.cells.append(_cell(doc, i, hb, "fit", 1.0, opts.auto_rotate, opts.center))
                out.append(sh)
        return out
    for i in pages:  # 크기
        if opts.source_size:
            r = doc[i].rect
            w, h = r.width, r.height
        else:
            w, h = pw, ph
        box = _box(w, h, margins)
        out.append(Sheet(w, h, [_cell(doc, i, box, opts.fit, opts.scale / 100, opts.auto_rotate, opts.center)]))
    return out


def poster_overview(doc: fitz.Document, i: int, opts: PrintOptions, paper, margins) -> Sheet:
    """미리보기용: 포스터 한 장 전체 위에 타일 경계를 점선으로."""
    box = _box(paper[0], paper[1], margins)
    rot, S, cols, rows, o, ox, oy, aw, ah = _poster(doc, i, opts, box)
    tw, th = cols * aw - (cols - 1) * o, rows * ah - (rows - 1) * o
    sh = Sheet(tw, th, [Cell(i, _poster_matrix(doc, i, rot, S, ox, oy), S, rot, fitz.Rect(0, 0, tw, th))])
    for c in range(1, cols):
        for x in {c * (aw - o), c * (aw - o) + o}:
            sh.guides.append((x, 0, x, th))
    for r in range(1, rows):
        for y in {r * (ah - o), r * (ah - o) + o}:
            sh.guides.append((0, y, tw, y))
    return sh


def content_doc(doc: fitz.Document, content: bool, annots: bool, forms: bool, pages, lock=None) -> fitz.Document:
    """내용 인쇄에서 뺀 것(문서·주석·양식)을 지운 사본. 다 켜져 있으면 원본 그대로."""
    if (content and annots and forms) or not doc.is_pdf:
        return doc
    with lock if lock is not None else nullcontext():
        c = fitz.open("pdf", doc.tobytes())
    for i in sorted(set(pages)):
        if not 0 <= i < len(c):
            continue
        p = c[i]
        if not annots:
            for x in [a.xref for a in p.annots()]:
                a = p.load_annot(x)
                if a is not None:
                    p.delete_annot(a)
        if not forms:
            for w in list(p.widgets()):
                p.delete_widget(w)
        if not content:
            for x in p.get_contents():
                c.update_stream(x, b" ")
    return c


def _cell_image(doc: fitz.Document, cell: Cell, dpi: float, color: bool, annots: bool, lock=None):
    """칸에서 실제로 보이는 부분만 그림으로: (그림, 종이 위 자리 Rect) 또는 None."""
    page = doc[cell.page]
    src = (cell.src or page.rect) & page.rect
    vis = (src * cell.m) & cell.clip
    if vis.is_empty or vis.width < 0.01 or vis.height < 0.01:
        return None
    region = (vis * ~cell.m) & src
    if region.is_empty:
        return None
    zoom = max(0.02, cell.s * dpi / 72)
    with lock if lock is not None else nullcontext():
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom).prerotate(cell.rot), clip=region, annots=annots,
                              colorspace=fitz.csRGB if color else fitz.csGRAY)
    fmt = QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_Grayscale8
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
    return img, region * cell.m


class VectorPages:
    """보내기에서 쪽마다 벡터 그리기 명령을 한 번만 모아 둔다(여러 부·포스터 타일이 같은 쪽을 다시 씀).
    벡터로 못 옮기는 쪽은 None 으로 적어 두고 비트맵으로 그린다."""

    def __init__(self, doc: fitz.Document, color: bool, annots: bool, lock=None):
        self.doc, self.gray, self.annots, self.lock = doc, not color, annots, lock
        self.glyphs = PV.Glyphs()
        self.pages: dict[int, list | None] = {}

    def get(self, i: int):
        if i not in self.pages:
            if len(self.pages) > 8:  # 메모리: 최근 몇 쪽만
                self.pages.pop(next(iter(self.pages)))
            self.pages[i] = PV.record(self.doc[i], self.annots, self.gray, self.glyphs, self.lock)
        return self.pages[i]


def _cell_vector(p: QPainter, doc: fitz.Document, cell: Cell, ops: list, origin: QPointF, k: float):
    page = doc[cell.page]
    src = (cell.src or page.rect) & page.rect
    vis = (src * cell.m) & cell.clip
    if vis.is_empty or vis.width < 0.01 or vis.height < 0.01:
        return
    m = cell.m  # 그리기 명령은 page.rect 와 같은 좌표(fz_run_page 를 단위 행렬로 돌림)
    to_dev = (QTransform(m.a, m.b, m.c, m.d, m.e, m.f) * QTransform.fromScale(k, k)
              * QTransform.fromTranslate(origin.x(), origin.y()))
    p.save()
    p.setClipRect(QRectF(origin.x() + vis.x0 * k, origin.y() + vis.y0 * k, vis.width * k, vis.height * k))
    PV.play(p, ops, to_dev)
    p.restore()


def draw_sheet(p: QPainter, sheet: Sheet, doc: fitz.Document, origin: QPointF, k: float, dpi: float, color: bool,
               annots: bool, lock=None, cache: dict | None = None, key=None, vector: VectorPages | None = None):
    """종이 한 면을 p 에 그린다. origin 은 종이 왼쪽 위(장치 좌표), k 는 pt → 장치 점.
    vector 가 있으면 쪽을 선·면으로 그리고(인쇄), 벡터로 못 옮기는 쪽만 dpi 비트맵으로 그린다."""
    for n, cell in enumerate(sheet.cells):
        if cell.page < 0:
            continue
        if vector is not None:
            ops = vector.get(cell.page)
            if ops is not None:
                _cell_vector(p, doc, cell, ops, origin, k)
                continue
        ck = (key, n, round(dpi, 1))
        got = cache.get(ck) if cache is not None else None
        if got is None:
            got = _cell_image(doc, cell, dpi, color, annots, lock)
            if cache is not None:
                cache[ck] = got
        if got is None:
            continue
        img, r = got
        p.drawImage(QRectF(origin.x() + r.x0 * k, origin.y() + r.y0 * k, r.width * k, r.height * k), img)
    if sheet.marks:
        p.setPen(QPen(QColor("#000000"), max(1.0, 0.5 * k)))
        for x0, y0, x1, y1 in sheet.marks:
            p.drawLine(QPointF(origin.x() + x0 * k, origin.y() + y0 * k), QPointF(origin.x() + x1 * k, origin.y() + y1 * k))
    if sheet.label:
        f = QFont(theme.FONT); f.setPixelSize(max(1, round(7 * k)))
        p.setFont(f); p.setPen(QColor("#000000"))
        p.drawText(QPointF(origin.x() + sheet.label_at[0] * k, origin.y() + sheet.label_at[1] * k), sheet.label)


# ── 보내기 ───────────────────────────────────────────────────────
def _layout_for(w: float, h: float, ps: QPageSize | None = None) -> tuple[QPageSize, QPageLayout.Orientation]:
    if ps is None:
        a, b = sorted((w, h))
        ps = QPageSize(QSizeF(a, b), QPageSize.Unit.Point, "", QPageSize.SizeMatchPolicy.FuzzyMatch)
    return ps, QPageLayout.Orientation.Landscape if w > h + 0.5 else QPageLayout.Orientation.Portrait


def make_printer(opts: PrintOptions, doc: fitz.Document, to_file: str = "") -> QPrinter:
    # 이름으로 바로 연다(빈 QPrinter 는 기본 프린터 드라이버부터 열어 0.3~0.5초를 더 쓴다)
    info = QPrinterInfo.printerInfo(opts.printer) if opts.printer else None
    p = QPrinter(info, QPrinter.PrinterMode.HighResolution) if info is not None and not info.isNull() \
        else QPrinter(QPrinter.PrinterMode.HighResolution)
    out = to_file or opts.to_file
    if out and not opts.printer:
        p.setOutputFormat(QPrinter.OutputFormat.PdfFormat)  # Qt 자체 PDF
        p.setOutputFileName(out)
    elif out:
        # 윈도우 드라이버로 「파일로 인쇄」(시험: Microsoft Print to PDF 가 창 없이 씀). 이름이 .pdf 면 Qt 가 자체 PDF 로
        # 바꾸므로 드라이버 출력으로 되돌린다. 되돌리면 기본 프린터로 바뀌니 이름을 맨 나중에 넣고, 다르면 멈춘다(종이가 나옴)
        p.setOutputFileName(out)
        p.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
        p.setPrinterName(opts.printer)
        same = os.path.normcase(os.path.abspath(p.outputFileName())) == os.path.normcase(os.path.abspath(out))
        if p.printerName() != opts.printer or not same:
            raise RuntimeError(f"파일로 인쇄를 준비하지 못했습니다: {p.printerName()}")
    else:
        p.setPrinterName(opts.printer)
    p.setPageSize(opts.page_size if isinstance(opts.page_size, QPageSize) else _page_size(opts.paper))
    w, h = paper_wh(opts, doc)
    p.setPageOrientation(QPageLayout.Orientation.Landscape if w > h else QPageLayout.Orientation.Portrait)
    p.setColorMode(QPrinter.ColorMode.Color if opts.color else QPrinter.ColorMode.GrayScale)
    duplex = opts.duplex
    if opts.mode == "poster" or duplex == "manual":
        duplex = "none"
    elif opts.mode == "booklet":
        duplex = "short" if opts.booklet_subset == "both" else "none"  # 가로로 눕힌 종이는 짧은 쪽으로 넘겨야 접힌다
    p.setDuplex(next((m for k, _, m in DUPLEX if k == duplex), QPrinter.DuplexMode.DuplexNone))
    return p


def printer_margins(p: QPrinter) -> tuple:
    m = p.pageLayout().margins(QPageLayout.Unit.Point)
    return m.left(), m.top(), m.right(), m.bottom()


def send(parent, doc: fitz.Document, opts: PrintOptions, name: str, lock=None) -> str | None:
    """opts 대로 인쇄한다. 잘 보냈으면 None, 못 보냈으면 까닭(한국어), 그만뒀으면 「그만둠」."""
    if not opts.pages and opts.view is None:
        return "인쇄할 쪽이 없습니다"
    if opts.printer and opts.printer not in QPrinterInfo.availablePrinterNames():
        return f"프린터를 찾지 못했습니다: {opts.printer}"
    if not opts.doc_name:
        opts.doc_name = name
    probe = make_printer(opts, doc)
    margins = opts.margins if opts.margins is not None else printer_margins(probe)
    sheets = plan(doc, opts, paper_wh(opts, doc), margins)
    if not sheets:
        return "인쇄할 쪽이 없습니다"
    cdoc = content_doc(doc, opts.content, opts.annots, opts.forms, opts.pages if opts.view is None else [opts.view[0]], lock)
    own_lock = None if cdoc is not doc else lock
    passes = [sheets]
    if opts.duplex == "manual" and opts.mode in ("size", "multi") and len(sheets) > 1:
        passes = [sheets[0::2], sheets[1::2]]
    try:
        for n, part in enumerate(passes):
            out = ""
            if n and opts.to_file:
                base, ext = os.path.splitext(opts.to_file)
                out = f"{base}-뒷면{ext}"
            if n and parent is not None:
                QMessageBox.information(parent, "인쇄", MANUAL_TIP)
            err = _job(parent, cdoc, opts, part, name, own_lock, probe if n == 0 else make_printer(opts, doc, out))
            if err:
                return err
    finally:
        if cdoc is not doc:
            cdoc.close()
    return None


def progress_dialog(parent, total: int) -> QProgressDialog:
    """보내는 동안 띄우는 진행 창(「n / 총장 보내는 중」·막대·[그만두기])."""
    bar = QProgressDialog("인쇄 준비 중", "그만두기", 0, total, parent)
    # 막대가 6px(theme)라 가운데 퍼센트 글자가 위아래로 잘린다. 「n / 총장」 글이 이미 있어 퍼센트는 뺀다
    line = QProgressBar(bar); line.setTextVisible(False); bar.setBar(line)
    bar.setRange(0, total)  # 새 막대는 0~100 이라 다시 맞춘다
    bar.setWindowTitle("인쇄"); bar.setWindowModality(Qt.WindowModality.WindowModal); bar.setMinimumDuration(400)
    bar.setMinimumWidth(320)
    return bar


def _job(parent, doc: fitz.Document, opts: PrintOptions, sheets: list[Sheet], name: str, lock, printer: QPrinter):
    printer.setDocName(name)
    printer.setFullPage(True)  # 종이 왼쪽 위가 (0,0). 인쇄 영역은 plan 이 margins 로 이미 비켜 둠
    ps = opts.page_size if isinstance(opts.page_size, QPageSize) else _page_size(opts.paper)
    # 드라이버가 여러 부를 못 받으면 면을 늘려 보낸다
    copies = max(1, opts.copies)
    if copies > 1 and printer.supportsMultipleCopies():
        printer.setCopyCount(copies); printer.setCollateCopies(opts.collate)
        seq = list(sheets)
    elif opts.collate:
        seq = list(sheets) * copies
    else:
        seq = [s for s in sheets for _ in range(copies)]

    def apply_size(sh: Sheet):
        size, orient = _layout_for(sh.w, sh.h, None if opts.source_size and opts.mode == "size" else ps)
        printer.setPageLayout(QPageLayout(size, orient, QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point))

    if opts.source_size and opts.mode == "size":
        apply_size(seq[0])
    painter = QPainter()
    if not painter.begin(printer):
        return "프린터를 열지 못했습니다(꺼져 있거나 연결이 끊겼는지 확인)"
    bar = None
    if parent is not None:
        bar = progress_dialog(parent, len(seq))
    dpi = opts.dpi if opts.as_image else min(printer.resolution(), MAX_DPI)
    # 「이미지로 인쇄」 가 아니면 선·면으로 보낸다(스풀이 작아 빠르고 글자가 프린터 해상도 그대로)
    vector = None if opts.as_image else VectorPages(doc, opts.color, opts.annots or opts.forms, lock)
    try:
        for n, sh in enumerate(seq):
            if bar is not None:
                bar.setValue(n); bar.setLabelText(f"{n + 1} / {len(seq)}장 보내는 중")
                QApplication.processEvents()
                if bar.wasCanceled():
                    printer.abort()
                    return "그만둠"
            if n:
                if opts.source_size and opts.mode == "size":
                    apply_size(sh)
                printer.newPage()
            paper = printer.paperRect(QPrinter.Unit.DevicePixel)
            k = paper.width() / max(1.0, sh.w)
            draw_sheet(painter, sh, doc, QPointF(0, 0), k, dpi, opts.color, opts.annots or opts.forms, lock, vector=vector)
    finally:
        painter.end()
        if bar is not None:
            bar.setValue(len(seq)); bar.close()
    return None


_STD_SIZES: dict[str, QPageSize] = {}


def _page_size(name: str) -> QPageSize:
    """표준 용지 이름 → QPageSize. 모르는 이름은 A4."""
    if not _STD_SIZES:
        for sid in QPageSize.PageSizeId:
            if sid != QPageSize.PageSizeId.Custom:
                ps = QPageSize(sid)
                if ps.isValid():
                    _STD_SIZES.setdefault(ps.name(), ps)
    return _STD_SIZES.get(name) or QPageSize(QPageSize.PageSizeId.A4)


def paper_label(ps: QPageSize) -> str:
    """「A4 21 x 29.7 cm」 꼴."""
    sz = ps.size(QPageSize.Unit.Millimeter)
    a, b = sorted((sz.width(), sz.height()))
    return f"{ps.name()} {a / 10:g} x {b / 10:g} cm"


def printer_properties(hwnd: int, name: str) -> bool:
    """프린터 드라이버의 「속성」 창을 띄우고, 확인을 누르면 그 설정을 이 사용자의 기본값으로 둔다(Qt 가 다음 인쇄 때 읽음)."""
    import ctypes
    from ctypes import wintypes
    try:
        ws = ctypes.WinDLL("winspool.drv")
    except OSError:
        return False
    ws.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    ws.OpenPrinterW.restype = wintypes.BOOL
    ws.DocumentPropertiesW.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                       wintypes.DWORD]
    ws.DocumentPropertiesW.restype = wintypes.LONG
    ws.SetPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    ws.SetPrinterW.restype = wintypes.BOOL
    ws.ClosePrinter.argtypes = [wintypes.HANDLE]
    h = wintypes.HANDLE()
    if not ws.OpenPrinterW(name, ctypes.byref(h), None):
        return False
    try:
        size = ws.DocumentPropertiesW(hwnd, h, name, None, None, 0)
        if size <= 0:
            return False
        cur, new = ctypes.create_string_buffer(size), ctypes.create_string_buffer(size)
        if ws.DocumentPropertiesW(hwnd, h, name, cur, None, 2) < 0:  # DM_OUT_BUFFER
            return False
        if ws.DocumentPropertiesW(hwnd, h, name, new, cur, 2 | 4 | 8) != 1:  # OUT·IN_PROMPT·IN_BUFFER → IDOK
            return False
        info9 = ctypes.c_void_p(ctypes.addressof(new))  # PRINTER_INFO_9 { DEVMODEW* }
        return bool(ws.SetPrinterW(h, 9, ctypes.byref(info9), 0))
    finally:
        ws.ClosePrinter(h)


# ── 미리보기 ─────────────────────────────────────────────────────
class Preview(QWidget):
    """종이 한 면을 그린다(보내기와 같은 plan·draw_sheet)."""

    def __init__(self, doc: fitz.Document, lock=None, parent=None):
        super().__init__(parent)
        self.doc, self.lock = doc, lock
        self.setMinimumSize(300, 340)
        self.sheet: Sheet | None = None
        self.color, self.annots = True, True
        self._key = None
        self._cache: dict = {}

    def set_sheet(self, sheet: Sheet | None, doc: fitz.Document, color: bool, annots: bool, key):
        if key != self._key or doc is not self.doc:
            self._cache = {}
        self.sheet, self.doc, self.color, self.annots, self._key = sheet, doc, color, annots, key
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        sh = self.sheet
        if sh is None:
            p.end(); return
        pad = 6
        k = min((self.width() - 2 * pad) / sh.w, (self.height() - 2 * pad) / sh.h)
        pw, ph = sh.w * k, sh.h * k
        paper = QRectF((self.width() - pw) / 2, (self.height() - ph) / 2, pw, ph)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 22)); p.drawRect(paper.adjusted(-1, -1, 1, 2))
        p.setBrush(QColor("#FFFFFF")); p.drawRect(paper)
        p.save(); p.setClipRect(paper)
        dpr = self.devicePixelRatioF()
        draw_sheet(p, sh, self.doc, paper.topLeft(), k, k * 72 * dpr, self.color, self.annots, self.lock,
                   self._cache, self._key)
        if sh.guides:
            p.setPen(QPen(QColor("#555555"), 1, Qt.PenStyle.DotLine))
            for x0, y0, x1, y1 in sh.guides:
                p.drawLine(QPointF(paper.x() + x0 * k, paper.y() + y0 * k), QPointF(paper.x() + x1 * k, paper.y() + y1 * k))
        p.restore()
        p.end()


def _page_icon(landscape: bool, color: str) -> QIcon:
    """방향 단추: 줄 그어진 종이 한 장(세로·가로)."""
    s = 2
    pm = QPixmap(18 * s, 18 * s); pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(s, s)
    p.setPen(QPen(QColor(color), 1.2))
    r = QRectF(2.5, 4.5, 13, 9) if landscape else QRectF(4.5, 2.5, 9, 13)
    p.drawRoundedRect(r, 1.5, 1.5)
    for n in range(3):
        y = r.y() + 3 + n * (r.height() - 5) / 2.6
        p.drawLine(QPointF(r.x() + 2.5, y), QPointF(r.right() - 2.5, y))
    p.end()
    pm.setDevicePixelRatio(s)
    return QIcon(pm)


# ── 인쇄 창 ──────────────────────────────────────────────────────
class PrintDialog(QDialog):
    COL_W = 268  # 왼쪽·가운데 칸 폭(알PDF 와 같은 크기: 창 안쪽 1061×637)

    def __init__(self, parent, doc: fitz.Document, current: int, remember: dict | None = None, lock=None,
                 view: tuple | None = None, name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("인쇄")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setObjectName("printdlg")
        self.doc, self.lock, self.current, self.view, self.name = doc, lock, current, view, name
        r = dict(remember or {})
        self._remember = r
        n = len(doc)

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        root.addLayout(body, 1)

        # ── 왼쪽 칸 ──
        left = self._column("printcol"); lv = left.layout()
        self._head(lv, "프린터", first=True)
        prow = QHBoxLayout(); prow.setSpacing(6)
        self.printer = QComboBox(); self.printer.setMinimumWidth(60)
        names = QPrinterInfo.availablePrinterNames()
        self.printer.addItems(names)
        want = r.get("printer") if r.get("printer") in names else QPrinterInfo.defaultPrinterName()
        if want in names:
            self.printer.setCurrentText(want)
        self.props_btn = QToolButton(); self.props_btn.setObjectName("printprops"); self.props_btn.setIcon(icons.icon("settings", 14))
        self.props_btn.clicked.connect(self._printer_props)
        prow.addWidget(self.printer, 1); prow.addWidget(self.props_btn)
        lv.addLayout(prow)
        self.gray = QCheckBox("흑백 인쇄"); self.gray.setChecked(not r.get("color", True)); lv.addWidget(self.gray)

        self._head(lv, "인쇄 설정")
        self.duplex = QComboBox(); lv.addWidget(self.duplex)
        self.paper = QComboBox(); lv.addWidget(self.paper)
        self.source_size = QCheckBox("소스 파일의 페이지 크기"); self.source_size.setChecked(r.get("source_size", False))
        lv.addWidget(self.source_size)
        crow = QHBoxLayout(); crow.setSpacing(6)
        cic = QLabel(); cic.setPixmap(icons.icon("copy", 16).pixmap(16, 16)); crow.addWidget(cic)
        self.copies = QSpinBox(); self.copies.setRange(1, 999); self.copies.setFixedWidth(64); crow.addWidget(self.copies)
        crow.addStretch(); lv.addLayout(crow)
        irow = QHBoxLayout(); irow.setSpacing(6)
        self.as_image = QCheckBox("이미지로 인쇄"); self.as_image.setChecked(r.get("as_image", False))
        self.dpi = QComboBox()
        for d in DPIS:
            self.dpi.addItem(f"{d}dpi", d)
        self.dpi.setCurrentIndex(max(0, self.dpi.findData(r.get("dpi", 300))))
        self.dpi.setFixedWidth(82)
        irow.addWidget(self.as_image); irow.addWidget(self.dpi); irow.addStretch(); lv.addLayout(irow)

        self._head(lv, "방향")
        orow = QHBoxLayout(); orow.setSpacing(4)
        self.orient_group = QButtonGroup(self)
        self.portrait_btn, self.landscape_btn = QToolButton(), QToolButton()
        for b, land in ((self.portrait_btn, False), (self.landscape_btn, True)):
            b.setObjectName("orient"); b.setCheckable(True); b.setIcon(_page_icon(land, theme.CUR["TEXT"]))
            b.setFixedSize(26, 24); self.orient_group.addButton(b); orow.addWidget(b)
        orow.addStretch(); lv.addLayout(orow)
        land = n and doc[min(current, n - 1)].rect.width > doc[min(current, n - 1)].rect.height
        (self.landscape_btn if land else self.portrait_btn).setChecked(True)

        self._head(lv, "페이지 범위")
        self.r_cur = QRadioButton("현재 페이지"); self.r_view = QRadioButton("최근 보기")
        self.r_all = QRadioButton("모든 페이지"); self.r_custom = QRadioButton("사용자 정의")
        self.r_all.setChecked(True)
        self.r_view.setEnabled(view is not None)
        for b in (self.r_cur, self.r_view, self.r_all):
            lv.addWidget(b)
        rrow = QHBoxLayout(); rrow.setSpacing(6)
        self.range_edit = QLineEdit(f"1-{n}" if n > 1 else "1"); self.range_edit.setPlaceholderText("예: 1,3,5,7-10")
        self.range_edit.setFixedWidth(74)
        rrow.addWidget(self.r_custom); rrow.addWidget(self.range_edit); rrow.addWidget(QLabel(f"/{n}")); rrow.addStretch()
        lv.addLayout(rrow)
        lv.addStretch()
        lrow = QHBoxLayout(); lrow.addStretch()
        self.adv_link = QPushButton(""); self.adv_link.setObjectName("printlink"); self.adv_link.setFlat(True); self.adv_link.setAutoDefault(False)
        self.adv_link.setCursor(Qt.CursorShape.PointingHandCursor); self.adv_link.clicked.connect(self._toggle_advanced)
        self.adv_link.setMinimumWidth(self.adv_link.fontMetrics().horizontalAdvance("고급 설정 숨기기") + 12)
        lrow.addWidget(self.adv_link); lv.addLayout(lrow)
        body.addWidget(left)

        # ── 가운데 칸(고급 설정) ──
        mid = self._column("printcol"); mv = mid.layout()
        self.mid = mid
        self._head(mv, "내용 인쇄", first=True)
        self.c_doc = QCheckBox("문서"); self.c_annot = QCheckBox("주석"); self.c_form = QCheckBox("양식")
        for b, key in ((self.c_doc, "content"), (self.c_annot, "annots"), (self.c_form, "forms")):
            b.setChecked(r.get(key, True)); mv.addWidget(b)
        self._head(mv, "페이지 범위")
        self.subset = QComboBox()
        for k, label in SUBSETS:
            self.subset.addItem(label, k)
        mv.addWidget(self.subset)
        self.reverse = QCheckBox("페이지 역순"); mv.addWidget(self.reverse)
        self._head(mv, "인쇄 모드")
        tabs = QWidget(); tabs.setObjectName("printtabs"); th = QHBoxLayout(tabs); th.setContentsMargins(0, 0, 0, 0); th.setSpacing(0)
        self.mode_group = QButtonGroup(self)
        self.mode_btns: dict[str, QToolButton] = {}
        for k, label in MODES:
            b = QToolButton(); b.setObjectName("printtab"); b.setText(label); b.setCheckable(True)
            b.setMinimumWidth(b.fontMetrics().horizontalAdvance(label) + 16)
            self.mode_group.addButton(b); self.mode_btns[k] = b; th.addWidget(b)
        th.addStretch()
        mv.addWidget(tabs)
        self.stack = QStackedWidget()
        mv.addWidget(self.stack)
        self._rot_boxes: list[QCheckBox] = []
        self._center_boxes: list[QCheckBox] = []

        # 크기
        pg, v = self._page()
        self.fit_btns: dict[str, QRadioButton] = {}
        for k, label in FITS:
            b = QRadioButton(label); self.fit_btns[k] = b; v.addWidget(b)
        self.fit_btns.get(r.get("fit", "fit"), self.fit_btns["fit"]).setChecked(True)
        self.scale = QSpinBox(); self.scale.setRange(1, 1000); self.scale.setValue(int(r.get("scale", 100))); v.addWidget(self.scale)
        self._common_checks(v)
        # 포스터
        pg, v = self._page()
        v.addWidget(QLabel("타일 스케일"))
        self.poster_scale = QSpinBox(); self.poster_scale.setRange(10, 1000); self.poster_scale.setValue(100); v.addWidget(self.poster_scale)
        v.addWidget(QLabel("겹침"))
        self.overlap = QDoubleSpinBox(); self.overlap.setRange(0, 10); self.overlap.setDecimals(1); self.overlap.setSingleStep(0.5)
        self.overlap.setSuffix(" (cm)"); v.addWidget(self.overlap)
        self.cut_marks = QCheckBox("컷 마크"); self.labels = QCheckBox("레이블")
        v.addWidget(self.cut_marks); v.addWidget(self.labels)
        prot = QCheckBox("자동 회전"); prot.setChecked(True); prot.setEnabled(False); v.addWidget(prot)
        self._common_checks(v, rotate=False)
        # 여러 페이지
        pg, v = self._page()
        v.addWidget(QLabel("시트 당 페이지"))
        nrow = QHBoxLayout(); nrow.setSpacing(6)
        self.nup = QComboBox()
        for k, label in NUPS:
            self.nup.addItem(label, k)
        self.nup.setFixedWidth(76)
        self.nup_cols = QSpinBox(); self.nup_cols.setRange(1, 10); self.nup_rows = QSpinBox(); self.nup_rows.setRange(1, 10)
        nrow.addWidget(self.nup); nrow.addWidget(self.nup_cols, 1); nrow.addWidget(QLabel("X")); nrow.addWidget(self.nup_rows, 1)
        v.addLayout(nrow)
        v.addWidget(QLabel("페이지 순서"))
        self.nup_order = QComboBox()
        for k, label in ORDERS:
            self.nup_order.addItem(label, k)
        v.addWidget(self.nup_order)
        self._common_checks(v)
        # 소책자
        pg, v = self._page()
        v.addWidget(QLabel("소책자 서브셋"))
        self.booklet_subset = QComboBox()
        for k, label in BOOKLET_SUBSETS:
            self.booklet_subset.addItem(label, k)
        v.addWidget(self.booklet_subset)
        v.addWidget(QLabel("시작 시트"))
        brow = QHBoxLayout(); brow.setSpacing(6)
        self.b_from = QSpinBox(); self.b_to = QSpinBox()
        for sb in (self.b_from, self.b_to):
            sb.setRange(1, 1)
        brow.addWidget(self.b_from, 1); brow.addWidget(QLabel("~")); brow.addWidget(self.b_to, 1)
        v.addLayout(brow)
        self.b_left = QRadioButton("좌"); self.b_right = QRadioButton("우"); self.b_left.setChecked(True)
        bg = QButtonGroup(self); bg.addButton(self.b_left); bg.addButton(self.b_right)
        v.addWidget(self.b_left); v.addWidget(self.b_right)
        self._common_checks(v)
        for b in self._rot_boxes:
            b.setChecked(r.get("auto_rotate", True))
        for b in self._center_boxes:
            b.setChecked(r.get("center", True))
        mv.addStretch()
        body.addWidget(mid)

        # ── 오른쪽: 미리보기 ──
        right = QWidget(); right.setObjectName("printpreview"); right.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rv = QVBoxLayout(right); rv.setContentsMargins(16, 10, 16, 12); rv.setSpacing(8)
        fname = QLabel(name or "문서"); fname.setObjectName("printfile"); fname.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rv.addWidget(fname)
        self.preview = Preview(doc, lock); rv.addWidget(self.preview, 1)
        nav = QFrame(); nav.setObjectName("printnav"); nh = QHBoxLayout(nav); nh.setContentsMargins(6, 3, 6, 3); nh.setSpacing(2)
        self.first_btn, self.prev_btn, self.next_btn, self.last_btn = (QToolButton() for _ in range(4))
        for b, t in ((self.first_btn, "«"), (self.prev_btn, "‹"), (self.next_btn, "›"), (self.last_btn, "»")):
            b.setObjectName("printstep"); b.setText(t); b.setFixedSize(24, 24)
        self.pos = QLineEdit("1"); self.pos.setObjectName("printpos"); self.pos.setFixedWidth(34)
        self.pos.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.count = QLabel("/1"); self.count.setObjectName("dim")
        nh.addWidget(self.first_btn); nh.addWidget(self.prev_btn); nh.addSpacing(10); nh.addWidget(self.pos); nh.addWidget(self.count)
        nh.addSpacing(10); nh.addWidget(self.next_btn); nh.addWidget(self.last_btn)
        navrow = QHBoxLayout(); navrow.addStretch(); navrow.addWidget(nav); navrow.addStretch()
        rv.addLayout(navrow)
        body.addWidget(right, 1)

        # ── 아래 단추 줄 ──
        bottom = QWidget(); bottom.setObjectName("printbottom"); bottom.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bh = QHBoxLayout(bottom); bh.setContentsMargins(20, 16, 16, 16); bh.setSpacing(16)
        self.err = QLabel(""); self.err.setStyleSheet(f"color:{theme.ACCENT};"); bh.addWidget(self.err, 1)
        self.ok = QPushButton("인쇄"); self.ok.setObjectName("accent"); self.ok.setDefault(True); self.ok.setFixedSize(88, 32); self.ok.clicked.connect(self._accept)
        cancel = QPushButton("취소"); cancel.setAutoDefault(False); cancel.setFixedSize(88, 32); cancel.clicked.connect(self.reject)
        bh.addWidget(self.ok); bh.addWidget(cancel)
        root.addWidget(bottom)

        # ── 처음 값·연결 ──
        self._idx = 0
        self._sheets: list[Sheet] = []
        self._pages: list[int] = []
        self._cdoc_key, self._cdoc = None, doc
        self._advanced = bool(r.get("advanced", True))
        self.mode_btns["size"].setChecked(True); self.stack.setCurrentIndex(0)
        self._printer_changed()
        self.printer.currentTextChanged.connect(self._printer_changed)
        for w in (self.duplex, self.paper, self.dpi, self.subset, self.nup, self.nup_order, self.booklet_subset):
            w.currentIndexChanged.connect(self._refresh)
        for w in (self.gray, self.source_size, self.as_image, self.c_doc, self.c_annot, self.c_form, self.reverse,
                  self.cut_marks, self.labels, self.b_left, self.r_cur, self.r_view, self.r_all, self.r_custom,
                  *self.fit_btns.values()):
            w.toggled.connect(self._refresh)
        for w in (self.copies, self.scale, self.poster_scale, self.overlap, self.nup_cols, self.nup_rows, self.b_from, self.b_to):
            w.valueChanged.connect(self._refresh)
        self.orient_group.buttonToggled.connect(lambda *_: self._refresh())
        self.mode_group.buttonToggled.connect(self._mode_changed)
        self.range_edit.textEdited.connect(lambda: self.r_custom.setChecked(True))
        self.range_edit.textChanged.connect(self._refresh)
        self.first_btn.clicked.connect(lambda: self._go(0)); self.last_btn.clicked.connect(lambda: self._go(10 ** 9))
        self.prev_btn.clicked.connect(lambda: self._go(self._idx - 1)); self.next_btn.clicked.connect(lambda: self._go(self._idx + 1))
        self.pos.editingFinished.connect(self._pos_entered)
        self._set_advanced(self._advanced, adjust=False)
        self.resize(self.COL_W * (2 if self._advanced else 1) + 525, 637)
        self._refresh()

    # ── 짓는 도우미 ──
    def _column(self, name: str) -> QWidget:
        w = QWidget(); w.setObjectName(name); w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        w.setFixedWidth(self.COL_W)
        v = QVBoxLayout(w); v.setContentsMargins(24, 18, 18, 14); v.setSpacing(8)
        return w

    def _head(self, lay, text: str, first: bool = False):
        if not first:
            lay.addSpacing(18)
        h = QLabel(text); h.setObjectName("printhead"); lay.addWidget(h)
        lay.addSpacing(4)

    def _page(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 6, 0, 0); v.setSpacing(7)
        self.stack.addWidget(w)
        return w, v

    def _common_checks(self, v, rotate: bool = True):
        if rotate:
            b = QCheckBox("자동 회전"); v.addWidget(b); self._rot_boxes.append(b)
            b.toggled.connect(lambda on: self._sync(self._rot_boxes, on))
        c = QCheckBox("자동 가운데 맞춤"); v.addWidget(c); self._center_boxes.append(c)
        c.toggled.connect(lambda on: self._sync(self._center_boxes, on))
        v.addStretch()

    def _sync(self, boxes: list[QCheckBox], on: bool):
        for b in boxes:
            if b.isChecked() != on:
                b.blockSignals(True); b.setChecked(on); b.blockSignals(False)
        self._refresh()

    # ── 고급 설정 접기 ──
    def _toggle_advanced(self):
        self._set_advanced(not self._advanced)

    def _set_advanced(self, on: bool, adjust: bool = True):
        self._advanced = on
        self.adv_link.setText("고급 설정 숨기기" if on else "고급 설정 표시")
        if adjust and self.mid.isVisible() != on and not self.isMaximized():
            g = self.geometry()
            dw = self.COL_W if on else -self.COL_W
            self.mid.setVisible(on)
            self.layout().activate()  # 줄어든 최소 폭을 먼저 알려야 창이 좁아진다
            self.setGeometry(g.x() - dw // 2, g.y(), g.width() + dw, g.height())
        else:
            self.mid.setVisible(on)

    def _mode_changed(self, btn, checked):
        if not checked:
            return
        keys = [k for k, _ in MODES]
        self.stack.setCurrentIndex(keys.index(self._mode()))
        self._idx = 0
        self._refresh()

    def _mode(self) -> str:
        return next((k for k, b in self.mode_btns.items() if b.isChecked()), "size")

    # ── 프린터 ──
    def _printer_props(self):
        name = self.printer.currentText()
        if not name:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            QApplication.processEvents()
            ok = printer_properties(int(self.winId()), name)
        finally:
            QApplication.restoreOverrideCursor()
        if ok:  # 드라이버에서 바꾼 용지·양면·색을 이 창에도
            pr = QPrinter(QPrinterInfo.printerInfo(name), QPrinter.PrinterMode.HighResolution)
            label = self._label_of(pr.pageLayout().pageSize())
            if label:
                self.paper.setCurrentText(label)
            dmap = {QPrinter.DuplexMode.DuplexLongSide: "long", QPrinter.DuplexMode.DuplexShortSide: "short",
                    QPrinter.DuplexMode.DuplexAuto: "long"}
            self.duplex.setCurrentIndex(max(0, self.duplex.findData(dmap.get(pr.duplex(), "none"))))
            self.gray.setChecked(pr.colorMode() == QPrinter.ColorMode.GrayScale)
            self._refresh()

    def _label_of(self, ps: QPageSize) -> str | None:
        for label, s in self._sizes.items():
            if s.name() == ps.name():
                return label
        return None

    # 프린터가 바뀌면 그 프린터가 받는 용지·양면·색으로 다시 채운다
    def _printer_changed(self, *_):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = QPrinterInfo.printerInfo(self.printer.currentText())
            self._info = info
            sizes = info.supportedPageSizes() or [_page_size("A4")]
            self._sizes = {paper_label(s): s for s in sizes}
            # 처음 열 때는 문서 첫 쪽과 같은 크기의 용지(B4 위클리면 B4)가 있으면 그것, 없으면 지난번 용지, 그다음 프린터 기본
            cur = self._sizes.get(self.paper.currentText())
            want = cur.name() if cur else (self._doc_paper() or self._remember.get("paper") or info.defaultPageSize().name())
            labels = list(self._sizes)
            pick = next((lb for lb, s in self._sizes.items() if s.name() == want), None) \
                or next((lb for lb, s in self._sizes.items() if s.name() == info.defaultPageSize().name()), labels[0])
            self.paper.blockSignals(True); self.paper.clear(); self.paper.addItems(labels)
            self.paper.setCurrentText(pick); self.paper.blockSignals(False)
            dmodes = set(info.supportedDuplexModes())
            want_dup = self.duplex.currentData() or self._remember.get("duplex", "none")
            self.duplex.blockSignals(True); self.duplex.clear()
            for k, label, m in DUPLEX:
                if k in ("none", "manual") or m in dmodes:
                    self.duplex.addItem(label, k)
            self.duplex.setCurrentIndex(max(0, self.duplex.findData(want_dup))); self.duplex.blockSignals(False)
            cmodes = set(info.supportedColorModes())
            can_color = QPrinter.ColorMode.Color in cmodes or not cmodes
            self.gray.setEnabled(can_color)
            if not can_color:
                self.gray.setChecked(True)
            pr = QPrinter(info, QPrinter.PrinterMode.HighResolution)
            self._margins = printer_margins(pr)  # 인쇄 영역(종이 여백)은 그 프린터의 기본 여백으로
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh()

    def _doc_paper(self) -> str | None:
        if not len(self.doc):
            return None
        r = self.doc[0].rect
        a, b = sorted((r.width, r.height))
        for s in self._sizes.values():
            sz = s.size(QPageSize.Unit.Point)
            x, y = sorted((sz.width(), sz.height()))
            if abs(x - a) < 4 and abs(y - b) < 4:
                return s.name()
        return None

    def _paper_size(self) -> QPageSize:
        return getattr(self, "_sizes", {}).get(self.paper.currentText()) or _page_size("A4")

    # ── 상태 ──
    def _base_pages(self) -> list[int]:
        n = len(self.doc)
        if self.r_cur.isChecked():
            return [min(self.current, n - 1)] if n else []
        if self.r_view.isChecked() and self.view is not None:
            return [self.view[0]]
        if self.r_custom.isChecked():
            from ..engine import pages as P
            return P.parse_range(self.range_edit.text(), n)  # 잘못되면 ValueError
        return list(range(n))

    def _refresh(self, *_):
        if not hasattr(self, "_margins"):
            return
        self.err.setText("")
        mode = self._mode()
        view = self.r_view.isChecked() and self.view is not None
        # 켜고 끄기
        self.range_edit.setEnabled(self.r_custom.isChecked())
        self.subset.setEnabled(not view)
        for k in ("multi", "booklet"):
            self.mode_btns[k].setEnabled(not view)
        if view and mode in ("multi", "booklet"):
            self.mode_btns["size"].setChecked(True)
            return
        self.duplex.setEnabled(mode not in ("poster", "booklet"))
        self.source_size.setEnabled(mode == "size" and not view)
        src = self.source_size.isChecked() and self.source_size.isEnabled()
        self.paper.setEnabled(not src)
        self.portrait_btn.setEnabled(not src and mode != "booklet"); self.landscape_btn.setEnabled(not src and mode != "booklet")
        self.dpi.setEnabled(self.as_image.isChecked())
        self.scale.setEnabled(self.fit_btns["custom"].isChecked())
        custom_nup = self.nup.currentData() == 0
        if not custom_nup:
            c, r = nup_grid(PrintOptions(nup=self.nup.currentData()), self.landscape_btn.isChecked())
            for sb, val in ((self.nup_cols, c), (self.nup_rows, r)):
                sb.blockSignals(True); sb.setValue(val); sb.blockSignals(False)
        self.nup_cols.setEnabled(custom_nup); self.nup_rows.setEnabled(custom_nup)
        # 쪽 고르기
        try:
            self._pages = pick_pages(len(self.doc), self._base_pages(), "all" if view else (self.subset.currentData() or "all"),
                                     self.reverse.isChecked())
        except ValueError as e:
            self._pages = []
            self.err.setText(str(e))
        total = booklet_sheets(len(self._pages))
        for sb in (self.b_from, self.b_to):
            sb.blockSignals(True)
        at_end = self.b_to.value() >= self.b_to.maximum()
        self.b_from.setRange(1, max(1, total)); self.b_to.setRange(1, max(1, total))
        if at_end:
            self.b_to.setValue(max(1, total))
        for sb in (self.b_from, self.b_to):
            sb.blockSignals(False)
        opts = self.options()
        paper = paper_wh(opts, self.doc)
        if mode == "poster" and not view:
            self._sheets = [poster_overview(self.doc, i, opts, paper, self._margins) for i in self._pages]
        else:
            self._sheets = plan(self.doc, opts, paper, self._margins) if (self._pages or view) else []
        if not self._sheets and not self.err.text():
            self.err.setText("인쇄할 쪽이 없습니다" if not self._pages else "")
        self.ok.setEnabled(bool(self._sheets))
        n = len(self._sheets)
        self._idx = max(0, min(self._idx, n - 1))
        # 내용 인쇄에서 뺀 것은 사본으로
        key = (opts.content, opts.annots, opts.forms)
        if key != self._cdoc_key:
            if self._cdoc is not self.doc:
                self._cdoc.close()
            self._cdoc = content_doc(self.doc, *key, range(len(self.doc)), self.lock)
            self._cdoc_key = key
        sheet = self._sheets[self._idx] if n else None
        pkey = (mode, self._idx, key, opts.color, repr(paper), opts.fit, opts.scale, opts.auto_rotate, opts.center,
                opts.source_size, opts.nup_cols, opts.nup_rows, opts.nup_order, opts.booklet_right, opts.booklet_subset,
                opts.poster_scale, opts.overlap, tuple(self._pages[:64]), len(self._pages), view)
        self.preview.set_sheet(sheet, self._cdoc, opts.color, opts.annots or opts.forms, pkey)
        self.preview.lock = self.lock if self._cdoc is self.doc else None
        self.pos.setText(str(self._idx + 1 if n else 0)); self.count.setText(f"/{n}")
        for b in (self.first_btn, self.prev_btn):
            b.setEnabled(self._idx > 0)
        for b in (self.next_btn, self.last_btn):
            b.setEnabled(self._idx < n - 1)

    def _go(self, i: int):
        self._idx = max(0, min(len(self._sheets) - 1, i))
        self._refresh()

    def _pos_entered(self):
        try:
            self._go(int(self.pos.text()) - 1)
        except ValueError:
            self._refresh()

    def _accept(self):
        if self._sheets:
            self.accept()

    def done(self, r):
        if self._cdoc is not self.doc:
            self._cdoc.close(); self._cdoc = self.doc
        super().done(r)

    def options(self) -> PrintOptions:
        view = self.view if (self.r_view.isChecked() and self.view is not None) else None
        return PrintOptions(
            printer=self.printer.currentText(), pages=list(self._pages), copies=self.copies.value(),
            mode=self._mode(), fit=next((k for k, b in self.fit_btns.items() if b.isChecked()), "fit"),
            scale=self.scale.value(), auto_rotate=self._rot_boxes[0].isChecked(), center=self._center_boxes[0].isChecked(),
            orient="landscape" if self.landscape_btn.isChecked() else "portrait",
            paper=self._paper_size().name(), page_size=self._paper_size(),
            source_size=self.source_size.isChecked() and self.source_size.isEnabled(),
            duplex=self.duplex.currentData() or "none", color=not self.gray.isChecked(),
            content=self.c_doc.isChecked(), annots=self.c_annot.isChecked(), forms=self.c_form.isChecked(),
            as_image=self.as_image.isChecked(), dpi=self.dpi.currentData() or 300, view=view,
            poster_scale=self.poster_scale.value(), overlap=self.overlap.value(), cut_marks=self.cut_marks.isChecked(),
            labels=self.labels.isChecked(), nup=self.nup.currentData() or 0, nup_cols=self.nup_cols.value(),
            nup_rows=self.nup_rows.value(), nup_order=self.nup_order.currentData() or "h",
            booklet_subset=self.booklet_subset.currentData() or "both", booklet_from=self.b_from.value(),
            booklet_to=self.b_to.value(), booklet_right=self.b_right.isChecked(),
            margins=getattr(self, "_margins", None), doc_name=self.name)

    def remember(self) -> dict:
        """다음에 열 때 그대로 쓸 설정(쪽 범위·매수·인쇄 모드는 뺀다)."""
        o = self.options()
        return {"printer": o.printer, "paper": o.paper, "duplex": o.duplex, "color": o.color, "source_size": o.source_size,
                "as_image": o.as_image, "dpi": o.dpi, "content": o.content, "annots": o.annots, "forms": o.forms,
                "fit": o.fit, "scale": o.scale, "auto_rotate": o.auto_rotate, "center": o.center, "advanced": self._advanced}

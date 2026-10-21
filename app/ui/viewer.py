"""가운데 문서 보기: 쪽 그림(따로 도는 일꾼이 그림)·확대·보기 방식·도구(손·선택·주석·편집·양식).

좌표: 화면 → 쪽(회전 반영된 fitz page.rect 좌표) → 회전 전 좌표(주석·글자가 쓰는 좌표).
"""
from __future__ import annotations

import bisect
import math
import queue
import threading
import time
from dataclasses import dataclass, field

import fitz
from PySide6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QImage, QKeyEvent, QMouseEvent, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF, QWheelEvent)
from PySide6.QtWidgets import (QApplication, QGraphicsItem, QGraphicsScene, QGraphicsView, QInputDialog, QMenu,
                               QStyleOptionGraphicsItem, QWidget)

from ..engine import annots as A
from ..engine.document import Document
from . import theme

GAP = 12  # 쪽 사이 간격(px)
MARGIN = 20

TOOLS_MARKUP = {"highlight": "Highlight", "underline": "Underline", "strike": "StrikeOut", "squiggly": "Squiggly"}
TOOLS_SHAPE = {"rect", "oval", "line", "arrow", "polygon", "polyline", "cloud", "areahl", "redact", "link", "crop",
               "addtext", "addimage", "textbox", "callout", "typewriter", "stamp", "signature", "snapshot", "ocrarea",
               "ftext", "fcheck", "fradio", "fcombo", "flist", "fbutton", "fimage", "fsign", "fdate",
               "m_distance", "m_perimeter", "m_area"}


def _qimage(pix: fitz.Pixmap) -> QImage:
    fmt = QImage.Format.Format_RGBA8888 if pix.alpha else QImage.Format.Format_RGB888
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
    return img.copy()  # samples 버퍼와 떼어 둔다


class RenderWorker(QThread):
    done = Signal(int, float, QImage, int)  # page, zoom, image, generation

    def __init__(self, doc: Document):
        super().__init__()
        self.doc = doc
        self.q: "queue.LifoQueue[tuple]" = queue.LifoQueue()
        self._stop = False
        self.gen = 0
        self.annots = True  # 주석 보이기(보기 설정)
        self.big_image: dict[int, bool] = {}   # 쪽마다: 100만 화소 넘는 그림이 있나(띠로 나누면 덜 멈추는 쪽). 문서가 바뀌면 비움

    def request(self, page: int, zoom: float):
        self.q.put((page, zoom, self.gen))

    def invalidate(self, content: bool = False):
        """content=True: 문서 내용이 바뀌었다(쪽마다 알아 둔 것도 버린다)."""
        self.gen += 1
        if content:
            self.big_image = {}
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def stop(self):
        self._stop = True
        self.q.put((-1, 0, 0))
        self.wait(2000)

    BAND_MS = 16   # 한 쪽이 이보다 오래 걸릴 것 같으면 띠로 나눠 그린다(그동안 화면이 멈추지 않게)
    BAND_EACH = 6  # 띠 하나에 들일 시간(ms)

    def run(self):
        ms_per_mp = None   # 이 문서에서 100만 화소 그리는 데 든 시간(최근 쪽들 평균). 스캔본은 15~20, 글자 PDF 는 2~8
        while not self._stop:
            page, zoom, gen = self.q.get()
            if page < 0 or self._stop:
                break
            if gen != self.gen:
                continue
            try:
                big_image = self.big_image
                with self.doc.lock:
                    pg = self.doc.fitz[page]
                    r = pg.rect
                    if page not in big_image:   # 쪽 자원의 그림 목록만 본다(0.1~1ms)
                        big_image[page] = any(w * h > 1e6 for _, _, w, h, *_ in pg.get_images())
                    del pg
                mp = r.width * r.height * zoom * zoom / 1e6
                est = (ms_per_mp or 0) * mp
                t0 = time.perf_counter()
                # 글자·선만 있는 쪽은 띠마다 다시 그려 오히려 느리다. 큰 그림이 든 쪽만(그림 풀기는 한 번이고 띠마다 제 몫만 그림)
                if est > self.BAND_MS and big_image[page]:
                    pix = self.doc.render_bands(page, zoom, math.ceil(est / self.BAND_EACH), annots=self.annots,
                                                cancel=lambda g=gen: g != self.gen or self._stop)
                    if pix is None:
                        continue
                else:
                    pix = self.doc.render(page, zoom, annots=self.annots)
                ms = (time.perf_counter() - t0) * 1000 / max(mp, 0.05)
                ms_per_mp = ms if ms_per_mp is None else ms_per_mp * 0.6 + ms * 0.4
                img = _qimage(pix)
            except Exception:  # noqa: BLE001
                continue
            if gen == self.gen:
                self.done.emit(page, zoom, img, gen)


class PageItem(QGraphicsItem):
    def __init__(self, view: "PageView", index: int):
        super().__init__()
        self.view = view
        self.index = index
        self.pm: QPixmap | None = None
        self.pm_zoom = 0.0
        self.w = self.h = 0.0
        self.setAcceptHoverEvents(False)

    def set_size(self, w: float, h: float):
        self.prepareGeometryChange()
        self.w, self.h = w, h

    def boundingRect(self) -> QRectF:
        # 그림자까지 넣어야 다시 그릴 때 그림자 자리가 지워지지 않는다(쪽 자리는 page_rect)
        return QRectF(-6, -4, self.w + 13, self.h + 14)

    def page_rect(self) -> QRectF:
        return QRectF(0, 0, self.w, self.h)

    def paint(self, p: QPainter, opt: QStyleOptionGraphicsItem, widget: QWidget | None = None):
        r = self.page_rect()
        # 부드러운 그림자: 바깥으로 갈수록 옅은 테를 겹쳐 종이가 바탕에서 떠 보이게(한 겹 그림자는 밋밋했다)
        for k, a in ((6, 6), (4, 10), (2, 16), (1, 22)):
            p.fillRect(r.adjusted(-k + 1, -k + 3, k + 1, k + 3), QColor(0, 0, 0, a))
        p.fillRect(r, Qt.GlobalColor.white)
        if self.pm is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.pm_zoom != self.view.zoom)
            p.drawPixmap(r, self.pm, QRectF(self.pm.rect()))
        else:
            self.view.need_render(self.index)
        self.view.paint_overlay(p, self.index)


@dataclass
class Selection:
    """지금 고른 것: 글자(words) · 주석(annot) · 양식 칸(widget) · 글자 덩어리(block) · 그림(image)."""
    kind: str = ""
    page: int = -1
    xref: int = -1
    rect: fitz.Rect | None = None  # 회전 전 좌표
    words: list[tuple] = field(default_factory=list)
    text: str = ""
    extra: dict = field(default_factory=dict)


class PageView(QGraphicsView):
    pageChanged = Signal(int)
    zoomChanged = Signal(float)
    docChanged = Signal()
    selectionChanged = Signal(object)  # Selection | None
    status = Signal(str)
    toolDone = Signal(str)  # 도구 하나 쓰고 나서(스탬프 등은 계속 쓰기)
    requestDialog = Signal(str, object)  # 화면에 대화상자를 부탁(종류, 자료)
    toolChanged = Signal(str)  # 속성 패널이 그 도구의 기억해 둔 모양을 얹는다

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setBackgroundBrush(QBrush(QColor(theme.CANVAS)))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

        self.closed = False
        self.zoom = 1.0
        self.zoom_mode = "fit_width"  # fixed / fit_width / fit_page / fit_height
        self.layout_mode = "continuous"  # single / continuous / facing / facing_continuous
        self.current = 0
        self.items: list[PageItem] = []
        self.tool = "hand"
        self.edit_mode = False      # 텍스트·이미지 편집(원문)
        self.form_mode = False      # 양식 칸 만들기·편집
        self.read_mode = False
        self.show_annots = True
        self.rotation_cache: dict[int, int] = {}
        self.words_cache: dict[int, list[tuple]] = {}
        self.blocks_cache: dict[int, list[dict]] = {}  # 편집 모드 글자 덩어리(문서가 바뀌면 비움)

        # 도구 속성(오른쪽 패널이 바꿈)
        self.props = {"stroke": (1, 0, 0), "fill": None, "width": 1.5, "opacity": 1.0,
                      "hl_color": (1, 1, 0), "text_color": (0, 0, 0), "fontsize": 11, "ink_color": (0.1, 0.1, 0.9),
                      "ink_width": 2.0, "author": "", "stamp_text": "승인", "stamp_image": "", "redact_fill": (0, 0, 0),
                      "measure_unit": "cm", "measure_scale": 1.0, "field_type": "text", "image_path": "",
                      "link_target": {}}

        self.sel: Selection | None = None
        self._drag_start: QPointF | None = None  # 화면(뷰포트) 좌표
        self._drag_page = -1
        self._drag_rect: QRectF | None = None    # 장면 좌표
        self._ink: list[QPointF] = []
        self._poly: list[QPointF] = []           # 다각형·연결선·측정 진행 중(장면 좌표)
        self._poly_page = -1
        self._panning = False
        self._pan_last = QPointF()
        self._pan_start = QPointF()
        self._moving_annot = False
        self._move_last: fitz.Point | None = None
        self._erase_last: tuple[int, fitz.Point] | None = None  # 지우개가 지난 자리(쪽, 쪽 좌표)
        self._hover_block: fitz.Rect | None = None
        self.search_hits: list[tuple[int, list[fitz.Rect]]] = []  # (쪽, 줄마다 네모)
        self.search_current = -1
        self._back: list[tuple[int, float, int]] = []   # 이전 보기 자리(view_pos)
        self._fwd: list[tuple[int, float, int]] = []
        self._space_tool = ""   # Space 를 누르는 동안 손 도구로 바꾸기 전의 도구
        self._rects: list[fitz.Rect] = []   # 쪽 크기(rebuild 때 한 번 읽는다)
        self._tops: list[float] = []        # 보이는 쪽의 위 끝(장면 y, 차례대로). 보이는 쪽 찾기용
        self._shown: list[int] = []         # 그 쪽 번호
        self._held: set[int] = set()        # 그림을 들고 있는 쪽

        self.worker = RenderWorker(doc)
        self.worker.annots = self.show_annots
        self.worker.done.connect(self._rendered)
        self.worker.start()
        self._pending: set[int] = set()
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._apply_fit)
        self.rebuild()

    @property
    def show_annots(self) -> bool:
        return self._show_annots

    @show_annots.setter
    def show_annots(self, on: bool):
        self._show_annots = on
        if hasattr(self, "worker"):
            self.worker.annots = on

    # ── 배치 ──────────────────────────────────────────────────
    def close(self):
        # 닫은 뒤에도 창 맞춤 타이머·singleShot 이 돌아 닫힌 문서를 읽다 「document closed」 가 났다
        self.closed = True
        self._fit_timer.stop()
        self.worker.stop()

    def page_rect_pt(self, i: int) -> fitz.Rect:
        """쪽 크기(회전 반영). 확대할 때마다 쪽마다 fitz 에 물으면 959쪽 문서에서 한 번에 15ms 가 들어 rebuild 때 읽어 둔다."""
        if i < len(self._rects):
            return self._rects[i]
        return self.doc.fitz[i].rect

    def rebuild(self, mapping: list[int | None] | None = None, dirty=()):
        """쪽 수·크기가 바뀌었을 때 전부 다시 놓는다. mapping[새 쪽] = 옛 쪽 이면 그 그림을 옮겨 쓴다
        (dirty 에 든 새 쪽은 다시 그림). 회전·삭제·순서 바꾸기에서 안 바뀐 쪽까지 다시 그리지 않게."""
        old = {it.index: (it.pm, it.pm_zoom) for it in self.items if it.pm is not None} if mapping is not None else {}
        self.scene_.clear()
        self.items = []
        self.words_cache.clear(); self.blocks_cache.clear()
        self.rotation_cache.clear()
        n = self.doc.page_count
        with self.doc.lock:
            self._rects = [fitz.Rect(self.doc.fitz[i].rect) for i in range(n)]
        self._held = set()
        for i in range(n):
            it = PageItem(self, i)
            if mapping is not None and i < len(mapping) and i not in dirty and mapping[i] in old:
                it.pm, it.pm_zoom = old[mapping[i]]
                self._held.add(i)
            self.scene_.addItem(it)
            self.items.append(it)
        self.worker.invalidate(content=True)
        self._pending.clear()  # 버린 부탁이 남아 있으면 그 쪽을 다시 부탁하지 못해 흰 쪽으로 남는다
        self.relayout()
        self.current = min(self.current, n - 1)

    def visible_pages_for_layout(self) -> list[int]:
        n = self.doc.page_count
        if self.layout_mode == "single":
            return [self.current]
        if self.layout_mode == "facing":
            a = self.current - (self.current % 2)
            return [i for i in (a, a + 1) if i < n]
        return list(range(n))

    def relayout(self):
        z = self.zoom
        y = MARGIN
        maxw = 0
        pages = self.visible_pages_for_layout()
        on = set(pages)   # 목록에 「in」 을 쓰면 959쪽에서 쪽 수의 제곱만큼 돈다
        for it in self.items:
            it.setVisible(it.index in on)
        facing = self.layout_mode.startswith("facing")
        if not facing:
            for i in pages:
                it = self.items[i]
                r = self.page_rect_pt(i)
                it.set_size(r.width * z, r.height * z)
                it.setPos(0, y)
                maxw = max(maxw, r.width * z)
                y += r.height * z + GAP
            for i in pages:  # 가운데 맞춤
                it = self.items[i]
                it.setPos((maxw - it.w) / 2 + MARGIN, it.pos().y())
            self.scene_.setSceneRect(0, 0, maxw + 2 * MARGIN, y + MARGIN)
        else:
            rows = [pages[k:k + 2] for k in range(0, len(pages), 2)]
            for row in rows:
                x = MARGIN
                rh = 0
                for i in row:
                    it = self.items[i]
                    r = self.page_rect_pt(i)
                    it.set_size(r.width * z, r.height * z)
                    it.setPos(x, y)
                    x += r.width * z + GAP
                    rh = max(rh, r.height * z)
                maxw = max(maxw, x - GAP + MARGIN)
                y += rh + GAP
            self.scene_.setSceneRect(0, 0, maxw, y + MARGIN)
        # 보이는 쪽 찾기용: 위 끝이 차례대로 늘어나는 목록(두 쪽 보기는 한 줄 두 쪽이 같은 값). 옛 그림은 늘려 보여 주다가 새 그림이 오면 바꾼다
        self._shown = list(pages)
        self._tops = [self.items[i].pos().y() for i in pages]
        self.viewport().update()
        QTimer.singleShot(0, self._request_visible)

    def set_layout_mode(self, mode: str):
        self.layout_mode = mode
        self.relayout()
        self.goto(self.current)

    # ── 확대 ──────────────────────────────────────────────────
    def set_zoom(self, z: float, anchor: QPointF | None = None):
        z = max(0.1, min(8.0, z))
        if abs(z - self.zoom) < 1e-4:
            return
        old = self.zoom
        # 닻: 뷰포트 가운데(또는 마우스) 가 가리키던 장면 점을 유지
        vp = anchor if anchor is not None else QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        scene_pt = self.mapToScene(vp.toPoint())
        self.zoom = z
        self.worker.invalidate()
        self._pending.clear()
        self.relayout()
        ratio = z / old
        new_pt = QPointF(scene_pt.x() * ratio, scene_pt.y() * ratio)
        self.centerOn(new_pt + (QPointF(self.viewport().width() / 2, self.viewport().height() / 2) - vp))
        self.zoomChanged.emit(z)

    # 확대·축소 단추가 건너는 배율(알PDF 단계표에서 10~800% 만). Ctrl+휠은 1.1배씩 부드럽게
    STEPS = (0.10, 0.15, 0.25, 1 / 3, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 3.00, 4.00, 6.00, 8.00)

    def zoom_in(self):
        self.zoom_mode = "fixed"
        self.set_zoom(next((s for s in self.STEPS if s > self.zoom * 1.001), self.STEPS[-1]))

    def zoom_out(self):
        self.zoom_mode = "fixed"
        self.set_zoom(next((s for s in reversed(self.STEPS) if s < self.zoom * 0.999), self.STEPS[0]))

    def set_zoom_mode(self, mode: str):
        self.zoom_mode = mode
        self._apply_fit()

    def _apply_fit(self):
        if self.closed or self.zoom_mode == "fixed" or not self.items:
            return
        i = max(0, min(self.current, len(self.items) - 1))
        r = self.page_rect_pt(i)
        vw = self.viewport().width() - 2 * MARGIN - 4
        vh = self.viewport().height() - 2 * MARGIN - 4
        if self.layout_mode.startswith("facing"):
            vw = (vw - GAP) / 2
        if self.zoom_mode == "fit_width":
            z = vw / r.width
        elif self.zoom_mode == "fit_height":
            z = vh / r.height
        elif self.zoom_mode == "actual":
            z = self.logicalDpiX() / 72.0
        else:
            z = min(vw / r.width, vh / r.height)
        self.set_zoom(z)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_timer.start(80)

    # ── 그리기 요청 ────────────────────────────────────────────
    def need_render(self, i: int):
        if i in self._pending:
            return
        self._pending.add(i)
        self.worker.request(i, self.zoom)

    def _request_visible(self):
        if self.closed:
            return
        vis = self.visible_pages()
        for i in vis:
            it = self.items[i]
            if it.pm is None or it.pm_zoom != self.zoom:
                self.need_render(i)
        self._evict(vis)

    KEEP_NEAR = 3              # 보이는 쪽 앞뒤로 그림을 남겨 둘 쪽 수
    KEEP_BYTES = 300 * 2**20   # 남겨 둔 그림이 이보다 많으면 먼 쪽부터 버린다

    def _evict(self, vis: list[int]):
        """화면에서 먼 쪽 그림을 버린다. 안 버리면 끝까지 훑을 때 쪽 수만큼 쌓였다(126쪽 1GB, 10-20 측정).
        다시 보이면 paint 가 그리기를 부탁한다."""
        if not vis:
            return
        lo, hi = vis[0], vis[-1]
        held = []
        for i in list(self._held):   # 그림을 든 쪽만 본다(모든 쪽을 훑지 않게)
            it = self.items[i] if i < len(self.items) else None
            if it is None or it.pm is None:
                self._held.discard(i)
                continue
            d = lo - it.index if it.index < lo else it.index - hi if it.index > hi else 0
            if d > self.KEEP_NEAR:
                it.pm = None
            else:
                held.append((d, it))
        total = sum(it.pm.width() * it.pm.height() * 4 for _, it in held)
        for d, it in sorted(held, key=lambda x: -x[0]):
            if total <= self.KEEP_BYTES or d == 0:
                break
            total -= it.pm.width() * it.pm.height() * 4
            it.pm = None

    def _rendered(self, page: int, zoom: float, img: QImage, gen: int):
        self._pending.discard(page)
        if gen != self.worker.gen or page >= len(self.items):
            return
        it = self.items[page]
        it.pm = QPixmap.fromImage(img)
        it.pm_zoom = zoom
        self._held.add(page)
        it.update()

    def refresh_pages(self, pages: list[int] | None = None, structural: bool = False,
                      mapping: list[int | None] | None = None):
        """문서가 바뀐 뒤 다시 그린다. structural=True 면 쪽 수·크기도 바뀐 것(mapping 은 rebuild 를 볼 것)."""
        self.words_cache.clear(); self.blocks_cache.clear()
        if structural:
            self.rebuild(mapping, set(pages or ()))
        else:
            self.worker.invalidate(content=True)
            self._pending.clear()
            for it in self.items:
                if pages is None or it.index in pages:
                    it.pm = None
                    it.update()
        self.docChanged.emit()
        QTimer.singleShot(0, self._request_visible)

    def _candidates(self, vr: QRectF) -> list[int]:
        """화면 높이 vr 에 걸칠 수 있는 쪽만(위 끝 목록을 반으로 나눠 찾는다). 스크롤할 때마다 모든 쪽을 훑으면 959쪽에서 몇 ms 씩 들었다."""
        if len(self._tops) != len(self._shown):
            return [it.index for it in self.items if it.isVisible()]
        # 쪽은 위아래로 겹치지 않으니 화면 위 끝보다 위에서 시작한 쪽은 마지막 줄(두 쪽 보기면 둘)만 걸칠 수 있다
        lo = max(0, bisect.bisect_right(self._tops, vr.top()) - 2)
        hi = bisect.bisect_right(self._tops, vr.bottom())
        return self._shown[lo:hi]

    def visible_pages(self) -> list[int]:
        vr = self.mapToScene(self.viewport().rect()).boundingRect()
        out = []
        for i in self._candidates(vr):
            it = self.items[i]
            if it.isVisible() and it.sceneBoundingRect().intersects(vr):
                out.append(i)
        return out

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._update_current()
        QTimer.singleShot(0, self._request_visible)

    def _update_current(self):
        vr = self.mapToScene(self.viewport().rect()).boundingRect()
        best, best_area = self.current, -1.0
        mid = vr.center().y()
        for i in self._candidates(vr):
            it = self.items[i]
            if not it.isVisible():
                continue
            r = it.mapRectToScene(it.page_rect())
            if r.top() <= mid <= r.bottom():
                best = it.index
                break
            inter = r.intersected(vr)
            a = inter.width() * inter.height()
            if a > best_area:
                best_area, best = a, it.index
        if best != self.current:
            self.current = best
            self.pageChanged.emit(best)

    # ── 이동 ──────────────────────────────────────────────────
    HISTORY = 50  # 이전 보기로 돌아갈 수 있는 자리 수

    def goto(self, i: int, y_pt: float | None = None, remember: bool = True):
        """i 쪽으로(y_pt 를 주면 그 높이가 위에서 조금 아래에 오게). 다른 쪽으로 건너뛰면 떠나는 자리를 「이전 보기」 에 남긴다."""
        if self.closed:
            return
        i = max(0, min(i, self.doc.page_count - 1))
        if remember and i != self.current and self.items:
            self._push_history(self._back)
            self._fwd.clear()
        if self.layout_mode in ("single", "facing") and i not in self.visible_pages_for_layout():
            self.current = i
            self.relayout()
        it = self.items[i]
        y = it.pos().y() - 8
        if y_pt is not None:
            y = it.pos().y() + y_pt * self.zoom - 40
        self.verticalScrollBar().setValue(int(y))
        if self.current != i:
            self.current = i
            self.pageChanged.emit(i)
        QTimer.singleShot(0, self._request_visible)

    def next_page(self):
        step = 2 if self.layout_mode.startswith("facing") else 1
        self.goto(self.current + step, remember=False)

    def prev_page(self):
        step = 2 if self.layout_mode.startswith("facing") else 1
        self.goto(self.current - step, remember=False)

    def view_pos(self) -> tuple[int, float, int]:
        """지금 보는 자리: (쪽, 화면 맨 위가 그 쪽 위에서 몇 pt 아래인가, 가로 스크롤 값)."""
        if not self.items:
            return 0, 0.0, 0
        i = max(0, min(self.current, len(self.items) - 1))
        y = (self.verticalScrollBar().value() - self.items[i].pos().y()) / (self.zoom or 1)
        return i, round(y, 1), self.horizontalScrollBar().value()

    def set_view_pos(self, i: int, y_pt: float, x: int = 0):
        """view_pos 로 잰 자리로 그대로 돌아간다(이전 보기·다시 열 때)."""
        if self.closed or not self.items:
            return
        i = max(0, min(int(i), len(self.items) - 1))
        if self.layout_mode in ("single", "facing") and i not in self.visible_pages_for_layout():
            self.current = i
            self.relayout()
        self.verticalScrollBar().setValue(int(self.items[i].pos().y() + y_pt * self.zoom))
        self.horizontalScrollBar().setValue(int(x))
        if self.current != i:
            self.current = i
            self.pageChanged.emit(i)
        QTimer.singleShot(0, self._request_visible)

    def _push_history(self, stack: list):
        stack.append(self.view_pos())
        del stack[:-self.HISTORY]

    def back(self):
        """이전 보기(Alt+←): 건너뛰기 전에 보던 자리로."""
        if self._back:
            self._push_history(self._fwd)
            self.set_view_pos(*self._back.pop())

    def forward(self):
        if self._fwd:
            self._push_history(self._back)
            self.set_view_pos(*self._fwd.pop())

    # ── 좌표 ──────────────────────────────────────────────────
    def page_at(self, scene_pt: QPointF) -> int:
        for i in self._candidates(QRectF(scene_pt.x(), scene_pt.y(), 1, 1)):
            it = self.items[i]
            if it.isVisible() and it.mapRectToScene(it.page_rect()).contains(scene_pt):
                return it.index
        return -1

    def to_page(self, i: int, scene_pt: QPointF) -> fitz.Point:
        """장면 좌표 → 회전 전 쪽 좌표."""
        it = self.items[i]
        lp = scene_pt - it.pos()
        p = fitz.Point(lp.x() / self.zoom, lp.y() / self.zoom)
        return p * self.doc.fitz[i].derotation_matrix

    def from_page_rect(self, i: int, r: fitz.Rect) -> QRectF:
        """회전 전 쪽 좌표 → 장면 좌표 QRectF."""
        it = self.items[i]
        rr = fitz.Rect(r) * self.doc.fitz[i].rotation_matrix
        rr.normalize()
        return QRectF(it.pos().x() + rr.x0 * self.zoom, it.pos().y() + rr.y0 * self.zoom,
                      rr.width * self.zoom, rr.height * self.zoom)

    def from_page_point(self, i: int, p: fitz.Point) -> QPointF:
        it = self.items[i]
        q = fitz.Point(p) * self.doc.fitz[i].rotation_matrix
        return QPointF(it.pos().x() + q.x * self.zoom, it.pos().y() + q.y * self.zoom)

    def _scene_rect_to_page(self, i: int, r: QRectF) -> fitz.Rect:
        a = self.to_page(i, r.topLeft())
        b = self.to_page(i, r.bottomRight())
        out = fitz.Rect(a, b)
        out.normalize()
        return out

    def words(self, i: int) -> list[tuple]:
        if i not in self.words_cache:
            self.words_cache[i] = self.doc.words(i)
        return self.words_cache[i]

    def blocks(self, i: int) -> list[dict]:
        """편집 모드에서 마우스가 움직일 때마다·다시 그릴 때마다 쓰여 쪽마다 한 번만 읽는다."""
        if i not in self.blocks_cache:
            self.blocks_cache[i] = self.doc.text_blocks(i)
        return self.blocks_cache[i]

    # ── 도구 ──────────────────────────────────────────────────
    def set_tool(self, tool: str):
        self.tool = tool
        self._poly.clear()
        self._ink.clear()
        self._drag_rect = None
        self._space_tool = ""
        self._apply_cursor()
        self.viewport().update()

    def _apply_cursor(self):
        tool = self.tool
        cur = {"hand": Qt.CursorShape.OpenHandCursor, "select": Qt.CursorShape.IBeamCursor}.get(tool)
        if cur is None:
            cur = Qt.CursorShape.CrossCursor if tool in TOOLS_SHAPE or tool in TOOLS_MARKUP or tool in (
                "pencil", "eraser", "note", "caret", "attach") else Qt.CursorShape.ArrowCursor
        self.viewport().setCursor(QCursor(cur))
        self.viewport().update()
        self.toolChanged.emit(tool)

    def set_edit_mode(self, on: bool):
        self.edit_mode = on
        if on:
            self.form_mode = False
            self.set_tool("edit")
        else:
            self.set_tool("hand")
        self.clear_selection()

    def set_form_mode(self, on: bool):
        self.form_mode = on
        if on:
            self.edit_mode = False
            self.set_tool("form")
        else:
            self.set_tool("hand")
        self.clear_selection()

    def clear_selection(self):
        if self.sel is not None:
            self.sel = None
            self.selectionChanged.emit(None)
            self.viewport().update()

    # ── 마우스 ────────────────────────────────────────────────
    def wheelEvent(self, e: QWheelEvent):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_mode = "fixed"
            f = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
            self.set_zoom(self.zoom * f, QPointF(e.position()))
            e.accept()
            return
        if self.layout_mode in ("single", "facing"):
            sb = self.verticalScrollBar()
            at_bottom = sb.value() >= sb.maximum()
            at_top = sb.value() <= sb.minimum()
            if e.angleDelta().y() < 0 and at_bottom:
                self.next_page(); e.accept(); return
            if e.angleDelta().y() > 0 and at_top:
                self.prev_page(); e.accept(); return
        super().wheelEvent(e)

    def mousePressEvent(self, e: QMouseEvent):
        sp = self.mapToScene(e.position().toPoint())
        i = self.page_at(sp)
        if e.button() == Qt.MouseButton.MiddleButton or (self.tool == "hand" and e.button() == Qt.MouseButton.LeftButton):
            self._panning = True
            self._pan_last = e.position()
            self._pan_start = e.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            if self.tool == "hand" and i >= 0:
                self._try_select_annot(i, sp, e)
            return
        if e.button() == Qt.MouseButton.RightButton:
            self._context_menu(e, i, sp)
            return
        if e.button() != Qt.MouseButton.LeftButton or i < 0:
            return
        self._drag_start = e.position()
        self._drag_page = i
        t = self.tool
        if t in ("select", "edit", "form"):
            if self._try_select_annot(i, sp, e):
                return
            if t == "edit":
                if self._select_block_or_image(i, sp):
                    return
            self._drag_start_scene = sp
            self._drag_end_scene = sp
            if t == "form":
                self._drag_rect = QRectF(sp, sp)
                return
            self._drag_rect = QRectF(sp, sp)
            self.clear_selection()
        elif t in TOOLS_MARKUP or t in TOOLS_SHAPE:
            if t in ("polygon", "polyline", "cloud", "m_perimeter", "m_area"):
                if self._poly and self._poly_page != i:
                    self._poly.clear()
                self._poly.append(sp)
                self._poly_page = i
                self.viewport().update()
                return
            self._drag_rect = QRectF(sp, sp)
            self._drag_start_scene = sp
            self._drag_end_scene = sp
        elif t == "pencil":
            self._ink = [sp]
        elif t == "eraser":
            pt = self.to_page(i, sp)
            self._erase_last = (i, pt)
            if A.erase_ink_at(self.doc, i, pt, radius=6 / self.zoom):
                self.refresh_pages([i])
        elif t in ("note", "caret", "attach"):
            pt = self.to_page(i, sp)
            self.requestDialog.emit(t, {"page": i, "point": pt})
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._panning:
            d = e.position() - self._pan_last
            self._pan_last = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        sp = self.mapToScene(e.position().toPoint())
        if self._moving_annot and self.sel and self.sel.kind in ("annot", "widget"):
            i = self.sel.page
            pt = self.to_page(i, sp)
            if self._move_last is not None:
                dx, dy = pt.x - self._move_last.x, pt.y - self._move_last.y
                self.sel.rect = self.sel.rect + (dx, dy, dx, dy)
                self.viewport().update()
            self._move_last = pt
            return
        if self._drag_rect is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self._drag_rect = QRectF(self._drag_rect.topLeft(), sp).normalized() if self._drag_start_scene is None                 else QRectF(self._drag_start_scene, sp).normalized()
            self._drag_end_scene = sp
            self.viewport().update()
            return
        if self.tool == "pencil" and self._ink and e.buttons() & Qt.MouseButton.LeftButton:
            self._ink.append(sp)
            self.viewport().update()
            return
        if self.tool == "eraser" and e.buttons() & Qt.MouseButton.LeftButton:
            i = self.page_at(sp)
            if i >= 0:
                # 지난 자리부터 지금 자리까지 지나간 길 전체로 지운다(빠르게 끌면 움직임 사이가 듬성듬성하다)
                pt = self.to_page(i, sp)
                prev = self._erase_last[1] if self._erase_last and self._erase_last[0] == i else None
                self._erase_last = (i, pt)
                if A.erase_ink_at(self.doc, i, pt, radius=6 / self.zoom, prev=prev):
                    self.refresh_pages([i])
            return
        if self._poly:
            self.viewport().update()
        if self.edit_mode and self.tool == "edit":
            i = self.page_at(sp)
            hb = None
            if i >= 0:
                pt = self.to_page(i, sp)
                for b in self.blocks(i):
                    if fitz.Rect(b["bbox"]).contains(pt):
                        hb = (i, fitz.Rect(b["bbox"]))
                        break
            if hb != self._hover_block:
                self._hover_block = hb
                self.viewport().update()
        # 손 도구에서 링크 위면 손가락
        if self.tool == "hand":
            i = self.page_at(sp)
            over = False
            if i >= 0:
                pt = self.to_page(i, sp)
                for l in self.doc.fitz[i].get_links():
                    if fitz.Rect(l["from"]).contains(pt):
                        over = True
                        break
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.OpenHandCursor)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if self._panning:
            self._panning = False
            if self.tool == "hand":
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
                sp = self.mapToScene(e.position().toPoint())
                # 끌어서 넘기다 링크 위에서 놓은 것은 누른 것이 아니다
                if (e.position() - self._pan_start).manhattanLength() < 4:
                    self._follow_link(sp)
            return
        if self._moving_annot:
            self._moving_annot = False
            if self.sel and self.sel.rect is not None:
                self._commit_move()
            return
        sp = self.mapToScene(e.position().toPoint())
        i = self._drag_page
        t = self.tool
        if self._drag_rect is not None and i >= 0:
            r = self._drag_rect
            self._drag_rect = None
            small = r.width() < 3 and r.height() < 3
            pr = self._scene_rect_to_page(i, r)
            if t in ("select", "edit"):
                self._select_words(i, pr, click=small, scene_pt=sp)
            elif t == "form":
                if not small:
                    self._make_field(i, pr)
            elif t in TOOLS_MARKUP:
                if small:
                    # 한 번 눌렀으면 그 낱말 하나
                    pt = self.to_page(i, sp)
                    pr = next((fitz.Rect(w[:4]) for w in self.words(i) if fitz.Rect(w[:4]).contains(pt)), None)
                if pr is not None:
                    A.text_markup(self.doc, i, [pr], TOOLS_MARKUP[t], color=self.props["hl_color"],
                                  opacity=self.props["opacity"], author=self.props["author"])
                    self.refresh_pages([i])
            elif not small:
                self._shape_done(i, pr, r)
            self.viewport().update()
        elif t == "pencil" and len(self._ink) > 1 and i >= 0:
            pts = [self.to_page(i, p) for p in self._ink]
            self._ink = []
            A.ink(self.doc, i, [pts], stroke=self.props["ink_color"], width=self.props["ink_width"],
                  opacity=self.props["opacity"], author=self.props["author"])
            self.refresh_pages([i])
        self._drag_start = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        sp = self.mapToScene(e.position().toPoint())
        i = self.page_at(sp)
        if i < 0:
            return
        if self._poly and self.tool in ("polygon", "polyline", "cloud", "m_perimeter", "m_area"):
            self._finish_poly()
            return
        if self.sel and self.sel.kind == "annot" and self.sel.rect and self.sel.rect.contains(self.to_page(i, sp)):
            self.requestDialog.emit("annot_props", self.sel)
            return
        if self.sel and self.sel.kind == "widget":
            self.requestDialog.emit("field_props", self.sel)
            return
        if self.edit_mode and self.sel and self.sel.kind == "block":
            self.requestDialog.emit("edit_block", self.sel)
            return
        if self.tool in ("hand", "select"):
            # 양식 칸 값 넣기(읽기 모드에서도)
            pt = self.to_page(i, sp)
            for w in self.doc.fitz[i].widgets():
                if fitz.Rect(w.rect).contains(pt):
                    self.requestDialog.emit("fill_field", {"page": i, "xref": w.xref, "widget": w})
                    return
            # 낱말 하나 고르기
            for w in self.words(i):
                if fitz.Rect(w[:4]).contains(pt):
                    self._select_words(i, fitz.Rect(w[:4]), click=False, scene_pt=sp)
                    return

    def keyPressEvent(self, e: QKeyEvent):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self._poly.clear(); self._drag_rect = None; self.clear_selection(); self.viewport().update()
            if self.tool not in ("hand", "select", "edit", "form"):
                self.toolDone.emit("escape")
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._poly:
            self._finish_poly(); return
        if k == Qt.Key.Key_Delete and self.sel:
            self.delete_selection(); return
        if k == Qt.Key.Key_Space and not e.isAutoRepeat() and self.tool != "hand" and not self._space_tool:
            # 누르는 동안만 손 도구(알PDF 와 같음). 떼면 하던 도구로
            self._space_tool = self.tool
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor); self.tool = "hand"
            return
        if k == Qt.Key.Key_Space:
            return
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if k in (Qt.Key.Key_Home,):
            self.goto(0); return
        if k in (Qt.Key.Key_End,):
            self.goto(self.doc.page_count - 1); return
        # 다음 쪽: PageDown · Ctrl+↓ · Enter (한 쪽·두 쪽 보기는 → 도), 이전 쪽: PageUp · Ctrl+↑ · Shift+Enter (←)
        enter = k in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if (k == Qt.Key.Key_PageDown or (ctrl and k == Qt.Key.Key_Down) or (enter and not shift)
                or (k == Qt.Key.Key_Right and self.layout_mode in ("single", "facing"))):
            self.next_page(); return
        if (k == Qt.Key.Key_PageUp or (ctrl and k == Qt.Key.Key_Up) or (enter and shift)
                or (k == Qt.Key.Key_Left and self.layout_mode in ("single", "facing"))):
            self.prev_page(); return
        if e.matches(e.StandardKey.Copy):
            self.copy_selection(); return
        if e.matches(e.StandardKey.SelectAll) and self.tool in ("select", "hand"):
            i = self.current
            ws = self.words(i)
            if ws:
                r = fitz.Rect(ws[0][:4])
                for w in ws:
                    r |= fitz.Rect(w[:4])
                self._select_words(i, r, click=False, scene_pt=None)
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat() and self._space_tool:
            tool, self._space_tool = self._space_tool, ""
            self._panning = False
            self.tool = tool; self._apply_cursor()   # set_tool 은 그리던 다각형을 지운다
            return
        super().keyReleaseEvent(e)

    # ── 고르기 ────────────────────────────────────────────────
    def _try_select_annot(self, i: int, sp: QPointF, e: QMouseEvent) -> bool:
        pt = self.to_page(i, sp)
        if self.show_annots and not self.form_mode and not self.edit_mode and self.tool in ("select", "hand"):
            for a in self.doc.fitz[i].annots():
                if a.type[1] in ("Link", "Widget", "Popup"):
                    continue
                if fitz.Rect(a.rect).contains(pt):
                    self.sel = Selection("annot", i, a.xref, fitz.Rect(a.rect), text=a.info.get("content", ""),
                                         extra={"kind": a.type[1], "kind_ko": A.KIND_NAMES.get(a.type[1], a.type[1]),
                                                "colors": A.annot_colors(self.doc, a), "opacity": a.opacity,
                                                "width": (a.border or {}).get("width", 1)})
                    self.selectionChanged.emit(self.sel)
                    if self.tool == "select":
                        self._moving_annot = True
                        self._move_last = pt
                    self.viewport().update()
                    return True
        if self.form_mode:
            for w in self.doc.fitz[i].widgets():
                if fitz.Rect(w.rect).contains(pt):
                    self.sel = Selection("widget", i, w.xref, fitz.Rect(w.rect), text=w.field_name,
                                         extra={"type": w.field_type_string, "value": w.field_value})
                    self.selectionChanged.emit(self.sel)
                    self._moving_annot = True
                    self._move_last = pt
                    self.viewport().update()
                    return True
        return False

    def _select_block_or_image(self, i: int, sp: QPointF) -> bool:
        pt = self.to_page(i, sp)
        for b in self.blocks(i):
            if fitz.Rect(b["bbox"]).contains(pt):
                if b.get("type") == 0:
                    text = "\n".join("".join(s["text"] for s in l["spans"]) for l in b["lines"])
                    span = b["lines"][0]["spans"][0]
                    self.sel = Selection("block", i, -1, fitz.Rect(b["bbox"]), text=text,
                                         extra={"fontsize": span["size"], "font": span["font"],
                                                "bold": bool(span["flags"] & 16)})
                else:
                    self.sel = Selection("image", i, -1, fitz.Rect(b["bbox"]), extra={"xref": 0})
                    for im in A.images_on_page(self.doc, i):
                        if im["rect"].intersects(fitz.Rect(b["bbox"])):
                            self.sel.extra["xref"] = im["xref"]
                            break
                self.selectionChanged.emit(self.sel)
                self.viewport().update()
                return True
        return False

    def _select_words(self, i: int, pr: fitz.Rect, click: bool, scene_pt: QPointF | None):
        ws = [w for w in self.words(i) if fitz.Rect(w[:4]).intersects(pr)] if not click else []
        if not ws:
            self.clear_selection()
            return
        ws.sort(key=lambda w: (w[5], w[6], w[7]))
        lines: list[str] = []
        cur_line, cur_key = [], None
        for w in ws:
            key = (w[5], w[6])
            if key != cur_key and cur_line:
                lines.append(" ".join(cur_line)); cur_line = []
            cur_key = key
            cur_line.append(w[4])
        if cur_line:
            lines.append(" ".join(cur_line))
        r = fitz.Rect(ws[0][:4])
        for w in ws:
            r |= fitz.Rect(w[:4])
        self.sel = Selection("words", i, -1, r, words=ws, text="\n".join(lines))
        self.selectionChanged.emit(self.sel)
        self.viewport().update()

    def selected_text(self) -> str:
        return self.sel.text if self.sel and self.sel.kind == "words" else ""

    def copy_selection(self):
        t = self.selected_text()
        if t:
            QApplication.clipboard().setText(t)
            self.status.emit("글자를 복사했습니다")

    def delete_selection(self):
        s = self.sel
        if not s:
            return
        if s.kind == "annot":
            A.delete(self.doc, s.page, s.xref)
        elif s.kind == "widget":
            A.delete_field(self.doc, s.page, s.xref)
        elif s.kind == "block":
            A.edit_block(self.doc, s.page, s.rect, "")
        elif s.kind == "image":
            A.delete_image(self.doc, s.page, s.rect)
        else:
            return
        self.clear_selection()
        self.refresh_pages([s.page])

    def _commit_move(self):
        s = self.sel
        if not s or s.rect is None:
            return
        if s.kind == "annot":
            a = A.get(self.doc, s.page, s.xref)
            if a is not None:
                old = fitz.Rect(a.rect)
                if abs(old.x0 - s.rect.x0) > 0.01 or abs(old.y0 - s.rect.y0) > 0.01:
                    new = A.update(self.doc, s.page, s.xref, rect=s.rect)
                    if new:
                        s.xref = new  # 선·연필·다각형은 옮기면 새로 만들어진다
                    self.refresh_pages([s.page])
        elif s.kind == "widget":
            self.doc.snapshot()
            for w in self.doc.fitz[s.page].widgets():
                if w.xref == s.xref:
                    w.rect = s.rect
                    A.save_widget(w)
            self.refresh_pages([s.page])
        self._move_last = None

    def _follow_link(self, sp: QPointF):
        i = self.page_at(sp)
        if i < 0:
            return
        pt = self.to_page(i, sp)
        for l in self.doc.fitz[i].get_links():
            if fitz.Rect(l["from"]).contains(pt):
                if l["kind"] == fitz.LINK_GOTO:
                    self.goto(l.get("page", 0))
                elif l["kind"] == fitz.LINK_URI:
                    self.requestDialog.emit("open_uri", l.get("uri", ""))
                elif l["kind"] == fitz.LINK_LAUNCH:
                    self.requestDialog.emit("open_file", l.get("file", ""))
                return

    # ── 도형 끝 ───────────────────────────────────────────────
    def _shape_done(self, i: int, pr: fitz.Rect, scene_r: QRectF):
        t = self.tool
        P = self.props
        d = self.doc
        a, b = self.to_page(i, scene_r.topLeft()), self.to_page(i, scene_r.bottomRight())
        if t == "rect":
            A.rect(d, i, pr, P["stroke"], P["fill"], P["width"], P["opacity"], P["author"])
        elif t == "oval":
            A.oval(d, i, pr, P["stroke"], P["fill"], P["width"], P["opacity"], P["author"])
        elif t in ("line", "arrow", "m_distance"):
            # 실제 끌기 방향대로 선을 긋는다
            s0 = self.to_page(i, self._drag_start_scene or scene_r.topLeft())
            s1 = self.to_page(i, self._drag_end_scene or scene_r.bottomRight())
            if t == "m_distance":
                label = A.measure([s0, s1], "distance", P["measure_scale"], P["measure_unit"])
                A.measure_annot(d, i, [s0, s1], "distance", label, author=P["author"])
                self.status.emit(f"거리 {label}")
            else:
                A.line(d, i, s0, s1, P["stroke"], P["width"], arrow=(t == "arrow"), opacity=P["opacity"],
                       author=P["author"])
        elif t == "areahl":
            A.area_highlight(d, i, pr, P["hl_color"], P["opacity"], P["author"])
        elif t == "redact":
            A.mark_redact(d, i, pr, P["redact_fill"])
        elif t == "textbox":
            self.requestDialog.emit("textbox", {"page": i, "rect": pr, "kind": "textbox"}); return
        elif t == "callout":
            self.requestDialog.emit("textbox", {"page": i, "rect": pr, "kind": "callout"}); return
        elif t == "typewriter":
            self.requestDialog.emit("textbox", {"page": i, "rect": pr, "kind": "typewriter"}); return
        elif t == "addtext":
            self.requestDialog.emit("addtext", {"page": i, "rect": pr}); return
        elif t == "addimage":
            self.requestDialog.emit("addimage", {"page": i, "rect": pr}); return
        elif t == "stamp":
            if P.get("stamp_image"):
                A.stamp_image(d, i, pr, P["stamp_image"], P["author"])
            else:
                A.stamp_text(d, i, pr, P["stamp_text"], P["stroke"], P["author"])
        elif t == "signature":
            self.requestDialog.emit("signature", {"page": i, "rect": pr}); return
        elif t == "link":
            self.requestDialog.emit("link", {"page": i, "rect": pr}); return
        elif t == "crop":
            self.requestDialog.emit("crop", {"page": i, "rect": pr}); return
        elif t == "snapshot":
            self.snapshot_to_clipboard(i, pr); return
        elif t == "ocrarea":
            self.requestDialog.emit("ocrarea", {"page": i, "rect": pr}); return
        elif t.startswith("f"):
            self._make_field(i, pr); return
        else:
            return
        self.refresh_pages([i])
        self.toolDone.emit(t)

    _drag_start_scene: QPointF | None = None
    _drag_end_scene: QPointF | None = None

    def _make_field(self, i: int, pr: fitz.Rect):
        t = self.tool if self.tool.startswith("f") and self.tool != "form" else "f" + self.props["field_type"]
        kind = {"ftext": "text", "fcheck": "checkbox", "fradio": "radio", "fcombo": "combo", "flist": "list",
                "fbutton": "button", "fimage": "image", "fsign": "signature", "fdate": "text"}.get(t, "text")
        if kind in ("checkbox", "radio"):
            s = max(10, min(pr.width, pr.height))
            pr = fitz.Rect(pr.x0, pr.y0, pr.x0 + s, pr.y0 + s)
        if pr.height < 8:
            pr.y1 = pr.y0 + 18
        A.add_field(self.doc, i, pr, kind, date=(t == "fdate"), label="버튼" if kind == "button" else "")
        self.refresh_pages([i])
        self.toolDone.emit(t)

    def _finish_poly(self):
        if len(self._poly) < 2:
            self._poly.clear(); return
        i = self._poly_page
        pts = [self.to_page(i, p) for p in self._poly]
        self._poly.clear()
        P = self.props
        t = self.tool
        if t in ("polygon", "cloud"):
            if len(pts) >= 3:
                A.polygon(self.doc, i, pts, P["stroke"], P["fill"], P["width"], closed=True, cloud=(t == "cloud"),
                          opacity=P["opacity"], author=P["author"])
        elif t == "polyline":
            A.polygon(self.doc, i, pts, P["stroke"], None, P["width"], closed=False, opacity=P["opacity"],
                      author=P["author"])
        elif t == "m_perimeter":
            label = A.measure(pts, "perimeter", P["measure_scale"], P["measure_unit"])
            A.measure_annot(self.doc, i, pts, "perimeter", label, author=P["author"])
            self.status.emit(f"둘레 {label}")
        elif t == "m_area" and len(pts) >= 3:
            label = A.measure(pts, "area", P["measure_scale"], P["measure_unit"])
            A.measure_annot(self.doc, i, pts, "area", label, author=P["author"])
            self.status.emit(f"영역 {label}")
        self.refresh_pages([i])
        self.toolDone.emit(t)

    def snapshot_to_clipboard(self, i: int, pr: fitz.Rect):
        pix = self.doc.render(i, max(2.0, self.zoom), clip=pr)
        QApplication.clipboard().setImage(_qimage(pix))
        self.status.emit("화면을 클립보드에 복사했습니다")
        self.toolDone.emit("snapshot")

    # ── 오른쪽 클릭 ───────────────────────────────────────────
    def _context_menu(self, e: QMouseEvent, i: int, sp: QPointF):
        m = QMenu(self)
        act = lambda key: self.requestDialog.emit("action", key)  # noqa: E731  창의 동작(on_action)을 부탁
        if self.sel and self.sel.kind == "words":
            s = self.sel
            m.addAction("복사", self.copy_selection)
            m.addSeparator()
            m.addAction("강조", lambda: self._markup_sel("Highlight"))
            m.addAction("밑줄", lambda: self._markup_sel("Underline"))
            m.addAction("취소선", lambda: self._markup_sel("StrikeOut"))
            m.addAction("구불구불한 선", lambda: self._markup_sel("Squiggly"))
            m.addSeparator()
            m.addAction("북마크 추가", lambda: self.requestDialog.emit("bookmark_text", {"page": s.page, "text": s.text}))
            m.addAction("이 글자 검색", lambda: self.requestDialog.emit("search_text", " ".join(s.text.split())[:200]))
            m.addSeparator()
            m.addAction("교정 표시", lambda: self._redact_sel())
        elif self.sel and self.sel.kind in ("annot", "widget"):
            m.addAction("속성", lambda: self.requestDialog.emit("annot_props" if self.sel.kind == "annot" else "field_props", self.sel))
            m.addAction("삭제", self.delete_selection)
        elif self.sel and self.sel.kind == "block":
            m.addAction("글자 고치기", lambda: self.requestDialog.emit("edit_block", self.sel))
            m.addAction("삭제", self.delete_selection)
        elif self.sel and self.sel.kind == "image":
            m.addAction("이미지 바꾸기", lambda: self.requestDialog.emit("replace_image", self.sel))
            m.addAction("이미지 저장", lambda: self.requestDialog.emit("save_image", self.sel))
            m.addAction("삭제", self.delete_selection)
        else:
            m.addAction("모두 선택", lambda: self.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)))
            if i >= 0:
                m.addAction("이 쪽에 메모", lambda: self.requestDialog.emit("note", {"page": i, "point": self.to_page(i, sp)}))
                m.addAction("북마크 추가", lambda: self.requestDialog.emit("bookmark_text", {"page": i, "text": ""}))
            m.addSeparator()
            m.addAction("확대", lambda: act("zoomin")); m.addAction("축소", lambda: act("zoomout"))
            m.addSeparator()
            m.addAction("첫 페이지", lambda: act("first")).setEnabled(self.current > 0)
            m.addAction("마지막 페이지", lambda: act("last")).setEnabled(self.current < self.doc.page_count - 1)
            m.addAction("이전 보기", self.back).setEnabled(bool(self._back))
            m.addAction("다음 보기", self.forward).setEnabled(bool(self._fwd))
            if i >= 0:
                m.addSeparator()
                m.addAction("왼쪽 회전", lambda: self.requestDialog.emit("rotate", {"pages": [i], "deg": -90}))
                m.addAction("오른쪽 회전", lambda: self.requestDialog.emit("rotate", {"pages": [i], "deg": 90}))
                m.addAction("이 쪽 삭제", lambda: self.requestDialog.emit("delete_pages", {"pages": [i]}))
            m.addSeparator()
            m.addAction("인쇄", lambda: act("print")); m.addAction("문서 속성", lambda: act("properties"))
            if self.window().isFullScreen():
                m.addAction("전체 화면 끝내기", lambda: act("fullscreen"))
        m.exec(e.globalPosition().toPoint())

    def _markup_sel(self, kind: str):
        if self.sel and self.sel.kind == "words":
            A.text_markup(self.doc, self.sel.page, [fitz.Rect(w[:4]) for w in self.sel.words], kind,
                          color=self.props["hl_color"], author=self.props["author"])
            pg = self.sel.page
            self.clear_selection()
            self.refresh_pages([pg])

    def _redact_sel(self):
        if self.sel and self.sel.kind == "words":
            pg = self.sel.page
            for w in self.sel.words:
                A.mark_redact(self.doc, pg, fitz.Rect(w[:4]), self.props["redact_fill"])
            self.clear_selection()
            self.refresh_pages([pg])

    # ── 덧그리기 ──────────────────────────────────────────────
    def paint_overlay(self, p: QPainter, i: int):
        """PageItem 안에서 부른다(아이템 좌표 = 장면 좌표 - pos)."""
        it = self.items[i]
        off = -it.pos()
        p.save()
        p.translate(off)
        accent = QColor(theme.ACCENT)
        # 검색 결과
        for (pg, rs) in self.search_hits:
            if pg == i:
                for r in (rs if isinstance(rs, list) else [rs]):
                    p.fillRect(self.from_page_rect(i, r), QColor(255, 200, 0, 90))
        if 0 <= self.search_current < len(self.search_hits) and self.search_hits[self.search_current][0] == i:
            rs = self.search_hits[self.search_current][1]
            p.setPen(QPen(QColor(230, 120, 0), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for r in (rs if isinstance(rs, list) else [rs]):
                p.drawRect(self.from_page_rect(i, r))
        # 편집 모드: 글자 덩어리 상자
        if self.edit_mode:
            p.setPen(QPen(QColor(120, 120, 220, 160), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for b in self.blocks(i):
                p.drawRect(self.from_page_rect(i, fitz.Rect(b["bbox"])))
            if self._hover_block and self._hover_block[0] == i:
                p.setPen(QPen(accent, 1.5))
                p.drawRect(self.from_page_rect(i, self._hover_block[1]))
        # 양식 모드: 칸 상자
        if self.form_mode:
            p.setPen(QPen(QColor(60, 140, 240, 200), 1, Qt.PenStyle.DashLine))
            p.setBrush(QColor(60, 140, 240, 25))
            for w in self.doc.fitz[i].widgets():
                p.drawRect(self.from_page_rect(i, fitz.Rect(w.rect)))
        # 고른 것
        s = self.sel
        if s and s.page == i:
            if s.kind == "words":
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(50, 120, 240, 80))
                for w in s.words:
                    p.drawRect(self.from_page_rect(i, fitz.Rect(w[:4])))
            elif s.rect is not None:
                rr = self.from_page_rect(i, s.rect)
                p.setPen(QPen(accent, 1.5, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(rr)
                p.setBrush(QBrush(Qt.GlobalColor.white))
                p.setPen(QPen(accent, 1))
                for c in (rr.topLeft(), rr.topRight(), rr.bottomLeft(), rr.bottomRight()):
                    p.drawRect(QRectF(c.x() - 3, c.y() - 3, 6, 6))
        # 진행 중 끌기
        if self._drag_rect is not None and self._drag_page == i:
            r = self._drag_rect
            t = self.tool
            if t in ("select", "edit", "form") or t in TOOLS_MARKUP:
                p.setPen(QPen(QColor(50, 120, 240), 1, Qt.PenStyle.DashLine))
                p.setBrush(QColor(50, 120, 240, 30))
                p.drawRect(r)
            elif t in ("line", "arrow", "m_distance"):
                p.setPen(QPen(self._qcolor(self.props["stroke"]), self.props["width"] * self.zoom))
                a = self._drag_start_scene or r.topLeft()
                b = self._drag_end_scene or r.bottomRight()
                p.drawLine(a, b)
            elif t == "oval":
                p.setPen(QPen(self._qcolor(self.props["stroke"]), self.props["width"] * self.zoom))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(r)
            else:
                p.setPen(QPen(accent, 1, Qt.PenStyle.DashLine))
                p.setBrush(QColor(232, 56, 61, 25) if t != "redact" else QColor(0, 0, 0, 120))
                p.drawRect(r)
        if self._ink and self._drag_page == i:
            p.setPen(QPen(self._qcolor(self.props["ink_color"]), self.props["ink_width"] * self.zoom,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            path = QPainterPath(self._ink[0])
            for q in self._ink[1:]:
                path.lineTo(q)
            p.drawPath(path)
        if self._poly and self._poly_page == i:
            p.setPen(QPen(self._qcolor(self.props["stroke"]), max(1.0, self.props["width"] * self.zoom)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            poly = QPolygonF(self._poly)
            p.drawPolyline(poly)
            cur = self.mapToScene(self.viewport().mapFromGlobal(QCursor.pos()))
            p.setPen(QPen(QColor(120, 120, 120), 1, Qt.PenStyle.DashLine))
            p.drawLine(self._poly[-1], cur)
            for q in self._poly:
                p.setBrush(Qt.GlobalColor.white)
                p.drawEllipse(q, 3, 3)
        p.restore()

    @staticmethod
    def _qcolor(c) -> QColor:
        if c is None:
            return QColor(0, 0, 0, 0)
        return QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255))


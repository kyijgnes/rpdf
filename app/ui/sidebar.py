"""왼쪽 패널: 썸네일 · 북마크 · 주석 목록 · 첨부 파일 · 검색 · 레이어 · (양식 칸 · 서명)."""
from __future__ import annotations

import queue
import time

import fitz
from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
                               QStyle, QStyledItemDelegate, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..engine import annots as A
from ..engine import pages as P
from ..engine.document import Bookmark, Document
from . import icons, theme


def panel_head(title: str, buttons=()) -> QWidget:
    """패널 머리: 제목 + 오른쪽 작은 단추들. 패널마다 높이·여백·밑줄이 달랐던 것을 한 모양으로."""
    w = QWidget(); w.setObjectName("panelhead"); w.setFixedHeight(32)
    w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    hl = QHBoxLayout(w); hl.setContentsMargins(10, 0, 4, 0); hl.setSpacing(0)
    t = QLabel(title); t.setObjectName("paneltitle"); hl.addWidget(t); hl.addStretch()
    for name, tip, fn in buttons:
        b = QToolButton(); b.setObjectName("quick"); b.setIcon(icons.icon(name, 16)); b.setToolTip(tip)
        b.clicked.connect(fn); hl.addWidget(b)
    return w


def group_card(title: str):
    """옅은 회색 패널 위의 흰 카드 하나: 제목 + 칸 목록. (카드, 칸 목록 QFormLayout) 을 돌려준다."""
    from PySide6.QtWidgets import QFormLayout, QFrame
    box = QFrame(); box.setObjectName("group")
    v = QVBoxLayout(box); v.setContentsMargins(10, 7, 10, 8); v.setSpacing(5)
    t = QLabel(title); t.setObjectName("grouptitle"); v.addWidget(t)
    f = QFormLayout(); f.setHorizontalSpacing(8); f.setVerticalSpacing(5); f.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    f.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    v.addLayout(f)
    return box, f


def _tidy_tree(tree: QTreeWidget, stretch: int):
    """좁은 패널에서 가로 스크롤이 생기지 않게: 한 칸은 늘이고 나머지는 내용만큼, 넘치면 … 로 줄임."""
    h = tree.header()
    h.setStretchLastSection(False)
    for k in range(tree.columnCount()):
        h.setSectionResizeMode(k, QHeaderView.ResizeMode.Stretch if k == stretch else QHeaderView.ResizeMode.ResizeToContents)
    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    tree.setTextElideMode(Qt.TextElideMode.ElideRight)
    tree.setIndentation(14)


class ThumbWorker(QThread):
    """부탁받은 쪽만 그리는 일꾼(나중에 부탁한 것부터). PyMuPDF 는 그리는 동안 GIL 을 놓지 않아
    전 쪽을 한꺼번에 그리면 화면이 그만큼 멈춘다(959쪽 열기 3.6초, 10-20 측정). 그래서 보이는 칸만 부탁받는다."""
    done = Signal(int, QImage, int)  # 쪽, 그림, 세대

    def __init__(self, doc: Document, width: int, dpr: float = 1.0):
        super().__init__()
        self.doc = doc
        self.width = int(width * dpr)
        self.dpr = dpr
        self.q: "queue.LifoQueue[tuple[int, int]]" = queue.LifoQueue()
        self.gen = 0
        self._stop = False

    def request(self, i: int):
        self.q.put((i, self.gen))

    def drop_queue(self):
        """아직 안 그린 부탁을 버린다(화면을 옮겨 안 보이게 된 칸)."""
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                return

    def stop(self):
        self._stop = True
        self.drop_queue()
        self.q.put((-1, -1))
        self.wait(2000)

    def run(self):
        while not self._stop:
            i, gen = self.q.get()
            if i < 0 or self._stop:
                break
            if gen != self.gen:
                continue
            try:
                w, _ = self.doc.page_size(i)
                pix = self.doc.render(i, self.width / max(1, w))
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
                img.setDevicePixelRatio(self.dpr)
                self.done.emit(i, img, gen)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.002)  # 한 장마다 GIL 을 놓아 화면이 숨 쉬게


class LazyThumbs:
    """PageGrid 의 썸네일을 보이는 칸(과 그 아래 한 화면)만 그려 채운다. 숨은 목록은 그리지 않는다."""
    AHEAD = 1.0  # 보이는 칸 아래로 화면 몇 개만큼 미리

    def __init__(self, grid: "PageGrid", doc: Document):
        self.grid, self.doc = grid, doc
        self.worker: ThumbWorker | None = None
        self.have: set[int] = set()      # 다 그린 쪽
        self.asked: set[int] = set()     # 부탁해 둔 쪽
        self.timer = QTimer(grid); self.timer.setSingleShot(True); self.timer.timeout.connect(self._ask)
        grid.verticalScrollBar().valueChanged.connect(self.kick)
        grid.shown.connect(self.kick)

    def pixmaps(self) -> dict[int, QPixmap]:
        """다 그린 썸네일(쪽 → 그림). 쪽 구조가 바뀔 때 안 바뀐 쪽 그림을 옮겨 쓰려고."""
        out = {}
        for k in range(self.grid.count()):   # 끌어 옮긴 직후엔 칸 차례가 쪽 차례와 다르다: 칸에 적힌 쪽으로 찾는다
            it = self.grid.item(k)
            p = it.data(Qt.ItemDataRole.UserRole)
            if p in self.have:
                out[p] = it.data(ThumbDelegate.PIX)
        return out

    def start(self, width: int, dpr: float, keep: dict[int, QPixmap] | None = None):
        """keep: 새 쪽 → 옮겨 쓸 그림(그 쪽은 다시 그리지 않는다)."""
        self.stop()
        self.have.clear(); self.asked.clear()
        for p, pm in (keep or {}).items():
            if p < self.grid.count():
                self.grid.item(p).setData(ThumbDelegate.PIX, pm)
                self.have.add(p)
        self.worker = ThumbWorker(self.doc, width, dpr)
        self.worker.done.connect(self._done)
        self.worker.start()
        self.kick()

    def stop(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker = None

    def forget(self, pages=None):
        """이 쪽들은 다시 그린다(옛 그림은 새 그림이 올 때까지 둔다)."""
        if self.worker is None:
            return
        # 그리던 그림은 옛 문서 것이라 버린다(세대를 올림). 부탁해 둔 것도 다시 부탁한다
        self.worker.gen += 1; self.worker.drop_queue(); self.asked.clear()
        if pages is None:
            self.have.clear()
        else:
            self.have.difference_update(pages)
        self.kick()

    def busy(self) -> bool:
        return bool(self.asked - self.have)

    def kick(self, *_):
        self.timer.start(30)

    def _visible_rows(self) -> list[int]:
        g = self.grid
        vp = g.viewport().rect()
        vp.setBottom(int(vp.bottom() + vp.height() * self.AHEAD))
        first = g.indexAt(vp.topLeft() + QPoint(4, 4)).row()
        rows = []
        for k in range(max(0, first), g.count()):
            r = g.visualItemRect(g.item(k))
            if r.top() > vp.bottom():
                break
            if r.intersects(vp):
                rows.append(k)
        return rows

    def _ask(self):
        if self.worker is None or not self.grid.isVisible():
            return
        self.worker.drop_queue()
        self.asked &= self.have           # 버린 부탁은 다시 부탁할 수 있게
        want = [self.grid.item(k).data(Qt.ItemDataRole.UserRole) for k in self._visible_rows()]
        for p in reversed(want):          # 나중에 부탁한 것부터 그리니 위 칸이 먼저 나온다
            if p not in self.have and p not in self.asked:
                self.asked.add(p)
                self.worker.request(p)

    def _done(self, i: int, img: QImage, gen: int):
        if self.worker is None or gen != self.worker.gen:
            return
        self.have.add(i)
        if i < self.grid.count():
            it = self.grid.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == i:
                it.setData(ThumbDelegate.PIX, QPixmap.fromImage(img))


class ThumbDelegate(QStyledItemDelegate):
    """썸네일을 QIcon 크기 맞춤 없이 저장한 그림 그대로 그린다(고해상도 화면에서 작아지는 문제 피함)."""
    PIX = Qt.ItemDataRole.UserRole + 1

    def paint(self, p, opt, idx):
        r = opt.rect
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme.CUR  # 어두운 화면에서도 맞는 색
        if selected:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(c["SELECT_BG"]))
            p.drawRoundedRect(QRectF(r).adjusted(2, 1, -2, -1), 6, 6)
        pm = idx.data(self.PIX)
        label = idx.data(Qt.ItemDataRole.DisplayRole) or ""
        top = r.top() + 4
        if isinstance(pm, QPixmap) and not pm.isNull():
            w = pm.width() / pm.devicePixelRatio(); h = pm.height() / pm.devicePixelRatio()
            x = r.left() + (r.width() - w) / 2
            p.fillRect(QRectF(x + 1, top + 2, w, h), QColor(0, 0, 0, 22))
            p.drawPixmap(QRectF(x, top, w, h), pm, QRectF(pm.rect()))
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.setPen(QPen(QColor(theme.ACCENT) if selected else QColor(c["FIELD_LINE"]), 2 if selected else 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(x, top, w, h))
        f = p.font(); f.setBold(selected); p.setFont(f)
        p.setPen(QColor(theme.ACCENT) if selected else QColor(c["TEXT_DIM"]))
        p.drawText(QRectF(r.left(), r.bottom() - 19, r.width(), 18), Qt.AlignmentFlag.AlignCenter, str(label))
        p.restore()

    def sizeHint(self, opt, idx):
        return idx.data(Qt.ItemDataRole.SizeHintRole) or QSize(100, 140)


class PageGrid(QListWidget):
    """쪽 썸네일 격자. 끌어 놓아 순서를 바꾸면 reordered(새 순서) 를 한 번 낸다.
    IconMode 는 Qt 가 놓을 자리를 받지 않아 끌어도 아무 일이 없다(10-19 진짜 끌기로 확인).
    그래서 ListMode 를 왼→오 흐름·줄바꿈으로 격자처럼 쓴다."""
    reordered = Signal(list)
    shown = Signal()  # 보이게 됐거나 크기가 바뀜(그릴 칸이 달라짐)

    def showEvent(self, e):
        super().showEvent(e)
        self.shown.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.shown.emit()

    def __init__(self, spacing: int, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.ListMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)  # 보기 방식을 정하면 끌기가 꺼지므로 그 뒤에
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSpacing(spacing)
        self.setItemDelegate(ThumbDelegate(self))
        self._pending = False
        self.model().rowsMoved.connect(self._moved)

    def _moved(self, *_):
        # 여러 장을 끌면 한 장마다 rowsMoved 가 온다. 놓기가 다 끝난 뒤 한 번만 알린다.
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self._emit)

    def _emit(self):
        self._pending = False
        order = [self.item(k).data(Qt.ItemDataRole.UserRole) for k in range(self.count())]
        if order != list(range(len(order))):
            self.reordered.emit(order)


def kept_thumbs(lazy: "LazyThumbs", mapping: list[int | None] | None, dirty=()) -> dict[int, QPixmap]:
    """mapping[새 쪽] = 옛 쪽 으로 옮겨 쓸 썸네일. dirty 에 든 새 쪽은 빼고(다시 그림)."""
    if mapping is None:
        return {}
    old = lazy.pixmaps()
    return {k: old[o] for k, o in enumerate(mapping) if o in old and k not in dirty}


def fill_grid(grid: PageGrid, doc: Document, thumb_w: int, pad_w: int, pad_h: int):
    """쪽마다 빈 흰 칸을 놓는다(그림은 LazyThumbs 가 보이는 칸부터 채움)."""
    grid.setUpdatesEnabled(False)
    grid.clear()
    labels = P.labels(doc)
    blank: dict[int, QPixmap] = {}   # 쪽 크기가 같으면 빈 그림 하나를 같이 쓴다
    for i in range(doc.page_count):
        w, hh = doc.page_size(i)
        h = int(thumb_w * hh / max(1, w))
        if h not in blank:
            pm = QPixmap(thumb_w, h); pm.fill(Qt.GlobalColor.white); blank[h] = pm
        it = QListWidgetItem(labels[i])
        it.setData(Qt.ItemDataRole.UserRole, i)
        it.setData(ThumbDelegate.PIX, blank[h])
        it.setSizeHint(QSize(thumb_w + pad_w, h + pad_h))
        grid.addItem(it)
    grid.setUpdatesEnabled(True)


class ThumbnailPanel(QWidget):
    """썸네일: 눌러 이동, 끌어 순서 바꾸기, 오른쪽 클릭 메뉴."""
    pageClicked = Signal(int)
    reordered = Signal(list)       # 새 순서
    pagesAction = Signal(str, list)  # 'rotate_left' 'rotate_right' 'delete' 'extract' 'insert_blank' 'insert_pdf' 'duplicate'

    def __init__(self, doc: Document, thumb_w: int = 150, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.thumb_w = thumb_w
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(panel_head("썸네일", (("zoomout", "작게", lambda: self.set_width(max(70, self.thumb_w - 30))),
                                            ("zoomin", "크게", lambda: self.set_width(min(260, self.thumb_w + 30))))))
        self.list = PageGrid(3)
        self.list.itemClicked.connect(lambda it: self.pageClicked.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.list.reordered.connect(self.reordered)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list)
        self.thumbs = LazyThumbs(self.list, doc)
        self.list.viewport().installEventFilter(self)
        self.reload()

    def set_width(self, w: int):
        self.thumb_w = w
        self.reload()

    def selected_pages(self) -> list[int]:
        return sorted(it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems())

    def reload(self, mapping: list[int | None] | None = None, dirty=()):
        keep = kept_thumbs(self.thumbs, mapping, dirty)
        fill_grid(self.list, self.doc, self.thumb_w, 12, 27)
        self._fit_items()
        self.thumbs.start(self.thumb_w, self.devicePixelRatioF(), keep)

    def _fit_items(self):
        """한 줄에 한 장만 들어가면 칸을 패널 폭만큼 넓혀 썸네일이 가운데 오게(왼쪽에 붙고 오른쪽이 비던 것)."""
        each = self.thumb_w + 12
        room = self.list.viewport().width() - 2 * self.list.spacing() - 1
        w = room if each <= room < 2 * each + 2 * self.list.spacing() else each
        for k in range(self.list.count()):
            it = self.list.item(k)
            if it.sizeHint().width() != w:
                it.setSizeHint(QSize(w, it.sizeHint().height()))

    def eventFilter(self, obj, e):
        if obj is self.list.viewport() and e.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._fit_items)
        return super().eventFilter(obj, e)

    def refresh_pages(self, pages: list[int] | None):
        self.thumbs.forget(pages)

    def set_current(self, i: int):
        if 0 <= i < self.list.count():
            self.list.blockSignals(True)
            self.list.setCurrentRow(i)
            self.list.scrollToItem(self.list.item(i))
            self.list.blockSignals(False)

    def _menu(self, pos):
        pages = self.selected_pages() or ([self.list.currentRow()] if self.list.currentRow() >= 0 else [])
        if not pages:
            return
        m = QMenu(self)
        for label, key in (("왼쪽 회전", "rotate_left"), ("오른쪽 회전", "rotate_right"), (None, None),
                           ("빈 페이지 끼우기", "insert_blank"), ("PDF 에서 끼우기", "insert_pdf"), ("복제", "duplicate"),
                           (None, None), ("내보내기", "extract"), ("삭제", "delete")):
            if label is None:
                m.addSeparator()
            else:
                m.addAction(label, lambda k=key: self.pagesAction.emit(k, pages))
        m.exec(self.list.mapToGlobal(pos))

    def close(self):
        self.thumbs.stop()


class BookmarkPanel(QWidget):
    gotoPage = Signal(int, object)  # 쪽, 쪽 안 높이(pt) 또는 None
    changed = Signal()
    DEST = Qt.ItemDataRole.UserRole + 1  # 쪽 안 자리(get_toc 넷째 칸)

    def __init__(self, doc: Document, get_current_page, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.get_current_page = get_current_page
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(panel_head("북마크", (("add", "북마크 추가", self.add),)))
        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True); _tidy_tree(self.tree, 0)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.model().rowsMoved.connect(lambda *_: self._save())
        self.tree.itemChanged.connect(lambda *_: self._save())
        lay.addWidget(self.tree)
        self.reload()

    def reload(self):
        # 문서가 바뀔 때마다 불린다. 여기서 신호를 다시 이으면 이름 하나 바꿀 때 저장이 그 횟수만큼 돈다.
        self.tree.blockSignals(True)
        self.tree.clear()

        def add(parent, nodes: list[Bookmark]):
            for b in nodes:
                it = QTreeWidgetItem([b.title])
                it.setData(0, Qt.ItemDataRole.UserRole, b.page)
                it.setData(0, self.DEST, b.dest)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
                (parent.addChild if isinstance(parent, QTreeWidgetItem) else self.tree.addTopLevelItem)(it)
                add(it, b.children)
        add(self.tree, self.doc.bookmarks())
        self.tree.expandAll()
        self.tree.blockSignals(False)

    def _clicked(self, it, _):
        pg = it.data(0, Qt.ItemDataRole.UserRole)
        if pg is not None and pg >= 0:
            self.gotoPage.emit(pg, self.doc.bookmark_y(Bookmark(1, "", pg, dest=it.data(0, self.DEST))))

    def _collect(self) -> list[Bookmark]:
        def walk(parent) -> list[Bookmark]:
            out = []
            n = parent.childCount() if isinstance(parent, QTreeWidgetItem) else parent.topLevelItemCount()
            for k in range(n):
                it = parent.child(k) if isinstance(parent, QTreeWidgetItem) else parent.topLevelItem(k)
                b = Bookmark(1, it.text(0), it.data(0, Qt.ItemDataRole.UserRole) or 0, dest=it.data(0, self.DEST))
                b.children = walk(it)
                out.append(b)
            return out
        return walk(self.tree)

    def _save(self):
        self.doc.set_bookmarks(self._collect())
        self.changed.emit()

    def rename_current(self):
        it = self.tree.currentItem()
        if it:
            self.tree.editItem(it, 0)

    def add(self, title: str = "", page: int | None = None):
        """지금 쪽(또는 page)에 북마크. title 을 주면(고른 글자) 그것을 이름 칸에 미리 넣는다."""
        pg = self.get_current_page() if page is None else page
        title = title if isinstance(title, str) else ""   # 단추·메뉴 신호는 checked(bool) 를 넘긴다
        title, ok = QInputDialog.getText(self, "북마크 추가", "이름", text=(title.strip()[:255] or f"{pg + 1}쪽"))
        if not ok or not title.strip():
            return
        it = QTreeWidgetItem([title.strip()])
        it.setData(0, Qt.ItemDataRole.UserRole, pg)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
        cur = self.tree.currentItem()
        if cur and cur.parent():
            cur.parent().insertChild(cur.parent().indexOfChild(cur) + 1, it)
        elif cur:
            self.tree.insertTopLevelItem(self.tree.indexOfTopLevelItem(cur) + 1, it)
        else:
            self.tree.addTopLevelItem(it)
        self._save()

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        m = QMenu(self)
        m.addAction("북마크 추가", self.add)
        if it:
            m.addAction("이름 바꾸기", lambda: self.tree.editItem(it, 0))
            m.addAction("지금 쪽으로 자리 바꾸기", lambda: self._repoint(it))
            m.addAction("아래 북마크 추가(하위)", lambda: self._add_child(it))
            m.addSeparator()
            m.addAction("삭제", lambda: (((it.parent() or self.tree.invisibleRootItem()).removeChild(it)), self._save()))
        m.exec(self.tree.mapToGlobal(pos))

    def _repoint(self, it: QTreeWidgetItem):
        self.tree.blockSignals(True)
        it.setData(0, self.DEST, None)  # 옛 쪽 안 자리는 버리고 새 쪽 맨 위로
        self.tree.blockSignals(False)
        it.setData(0, Qt.ItemDataRole.UserRole, self.get_current_page())  # itemChanged 가 저장

    def _add_child(self, parent: QTreeWidgetItem):
        pg = self.get_current_page()
        title, ok = QInputDialog.getText(self, "하위 북마크", "이름", text=f"{pg + 1}쪽")
        if ok and title.strip():
            it = QTreeWidgetItem([title.strip()]); it.setData(0, Qt.ItemDataRole.UserRole, pg)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
            parent.addChild(it); parent.setExpanded(True); self._save()


class AnnotPanel(QWidget):
    gotoAnnot = Signal(int, object)  # page, rect
    changed = Signal()
    importExport = Signal(str)

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(panel_head("주석", tuple((name, tip, lambda _=False, k=key: self._action(k)) for name, tip, key in (
            ("import", "주석 가져오기", "import"), ("export", "주석 내보내기", "export"), ("delete", "모두 삭제", "delete_all")))))
        box = QWidget(); bl = QVBoxLayout(box); bl.setContentsMargins(8, 6, 8, 6); bl.setSpacing(4)
        row = QHBoxLayout(); row.setSpacing(4)
        self.filter = QComboBox(); self.filter.addItems(["전체"] + sorted(set(A.KIND_NAMES.values())))
        self.filter.currentIndexChanged.connect(self.reload)
        # 묶는 기준(주석 목록: 쪽·날짜·작성자·종류). 저장하지 않고 늘 쪽순으로 연다
        self.group = QComboBox(); self.group.addItems(["쪽순", "날짜순", "작성자순", "종류순"])
        self.group.currentIndexChanged.connect(self.reload)
        row.addWidget(self.filter, 1); row.addWidget(self.group, 1); bl.addLayout(row)
        self.find = QLineEdit(); self.find.setPlaceholderText("내용·작성자 찾기"); self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self.reload)
        bl.addWidget(self.find); lay.addWidget(box)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["종류", "내용", "작성자"]); _tidy_tree(self.tree, 1)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemDoubleClicked.connect(lambda it, _c: (d := it.data(0, Qt.ItemDataRole.UserRole)) and self._edit(d))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.tree)
        self.empty = QLabel(""); self.empty.setObjectName("dim"); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.hide(); lay.addWidget(self.empty)
        self.reload()

    @staticmethod
    def _day(mod: str) -> str:
        s = (mod or "").removeprefix("D:")
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 and s[:8].isdigit() else "날짜 없음"

    def reload(self):
        self.tree.clear()
        want = self.filter.currentText()
        q = self.find.text().strip().lower()
        how = self.group.currentIndex()
        rows = []
        for a in A.list_annots(self.doc):
            if a.kind in ("Link", "Widget", "Popup"):
                continue
            if want != "전체" and a.kind_ko != want:
                continue
            if q and q not in (a.content or "").lower() and q not in (a.author or "").lower():
                continue
            head = (f"{a.page + 1}쪽", self._day(a.modified), a.author or "작성자 없음", a.kind_ko)[how]
            key = (a.page, "", a.author or "￿", a.kind_ko)[how]
            if how == 1:
                key = "" if head == "날짜 없음" else head
            rows.append((key, head, a))
        # 날짜는 새것부터, 나머지는 오름차순. 같은 묶음 안은 문서 차례(쪽 → 쪽 안 차례)
        rows.sort(key=lambda r: r[0], reverse=(how == 1))
        groups: dict[str, QTreeWidgetItem] = {}
        for _key, head, a in rows:
            if head not in groups:
                pit = QTreeWidgetItem([head, "", ""])
                pit.setFlags(pit.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.tree.addTopLevelItem(pit)
                groups[head] = pit
            it = QTreeWidgetItem([a.kind_ko, a.content, a.author])
            if how != 0:
                it.setText(0, f"{a.page + 1}쪽 {a.kind_ko}" if how != 3 else f"{a.page + 1}쪽")
            it.setData(0, Qt.ItemDataRole.UserRole, (a.page, a.xref, a.rect))
            groups[head].addChild(it)
        self.tree.expandAll()
        self.empty.setText("찾은 주석 없음" if (q or want != "전체") else "주석 없음")
        self.empty.setVisible(not rows)
        self.tree.setVisible(bool(rows))

    def _clicked(self, it, _):
        d = it.data(0, Qt.ItemDataRole.UserRole)
        if d:
            self.gotoAnnot.emit(d[0], d[2])

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        d = it.data(0, Qt.ItemDataRole.UserRole) if it else None
        m = QMenu(self)
        if d:
            m.addAction("내용 고치기", lambda: self._edit(d))
            m.addAction("삭제", lambda: (A.delete(self.doc, d[0], d[1]), self.reload(), self.changed.emit()))
        m.exec(self.tree.mapToGlobal(pos))

    def _edit(self, d):
        a = A.get(self.doc, d[0], d[1])
        if not a:
            return
        text, ok = QInputDialog.getMultiLineText(self, "주석 내용", "내용", a.info.get("content", ""))
        if ok:
            A.update(self.doc, d[0], d[1], content=text)
            self.reload(); self.changed.emit()

    def _action(self, key: str):
        if key == "delete_all":
            if QMessageBox.question(self, "주석 모두 삭제", "이 문서의 주석을 전부 지울까요?") == QMessageBox.StandardButton.Yes:
                A.delete_all(self.doc); self.reload(); self.changed.emit()
        else:
            self.importExport.emit(key)


class AttachmentPanel(QWidget):
    changed = Signal()

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(panel_head("첨부 파일", (("add", "첨부 파일 추가", self.add),)))
        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(lambda it: self.save(it.text()))
        lay.addWidget(self.list)
        self.reload()

    def reload(self):
        self.list.clear()
        for a in self.doc.attachments():
            desc = a["desc"] if a["desc"] and a["desc"] not in (a["filename"], a["name"]) else ""
            self.list.addItem(f"{a['filename']}  ({a['size'] / 1024:.0f} KB)" + (f" · {desc}" if desc else ""))
            it = self.list.item(self.list.count() - 1)
            it.setData(Qt.ItemDataRole.UserRole, a["name"])
            it.setData(Qt.ItemDataRole.UserRole + 1, a["filename"])

    def add(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "첨부할 파일")
        for p in paths:
            self.doc.add_attachment(p)
        if paths:
            self.reload(); self.changed.emit()

    def save(self, _):
        it = self.list.currentItem()
        if not it:
            return
        name = it.data(Qt.ItemDataRole.UserRole)
        out, _ = QFileDialog.getSaveFileName(self, "첨부 파일 저장", it.data(Qt.ItemDataRole.UserRole + 1) or name)
        if out:
            open(out, "wb").write(self.doc.get_attachment(name))

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        m = QMenu(self)
        m.addAction("첨부 파일 추가", self.add)
        if it:
            m.addAction("저장", lambda: self.save(None))
            m.addAction("삭제", lambda: (self.doc.remove_attachment(it.data(Qt.ItemDataRole.UserRole)), self.reload(), self.changed.emit()))
        m.exec(self.list.mapToGlobal(pos))


class SearchPanel(QWidget):
    hitsChanged = Signal(list, int)   # [(page, [rect…])], current
    replaced = Signal(object)         # 바꾼 쪽 목록(None 이면 여러 쪽)

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.hits = []       # [(쪽, [줄마다 네모])]
        self.results = []    # SearchHit
        self.current = -1
        self._gen = 0                      # 찾기를 새로 하면 옛 일꾼 결과는 버린다
        self._workers: list[QThread] = []
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(panel_head("검색"))
        lay = QVBoxLayout(); lay.setContentsMargins(8, 8, 8, 6); lay.setSpacing(6); outer.addLayout(lay)
        row = QHBoxLayout()
        self.edit = QLineEdit(); self.edit.setPlaceholderText("찾을 글자"); self.edit.returnPressed.connect(self.run)
        row.addWidget(self.edit)
        b = QToolButton(); b.setObjectName("quick"); b.setIcon(icons.icon("search", 16)); b.clicked.connect(self.run); row.addWidget(b)
        bp = QToolButton(); bp.setObjectName("quick"); bp.setIcon(icons.icon("up", 16)); bp.clicked.connect(lambda: self.step(-1))
        bn = QToolButton(); bn.setObjectName("quick"); bn.setIcon(icons.icon("down", 16)); bn.clicked.connect(lambda: self.step(1))
        row.setSpacing(0); row.addSpacing(4); row.addWidget(bp); row.addWidget(bn)
        lay.addLayout(row)
        opts = QHBoxLayout()
        self.case = QCheckBox("대소문자"); self.whole = QCheckBox("낱말 전체")
        self.count = QLabel(""); self.count.setObjectName("dim")
        opts.addWidget(self.case); opts.addWidget(self.whole); opts.addStretch(); opts.addWidget(self.count)
        lay.addLayout(opts)
        # 바꾸기
        self.repl = QLineEdit(); self.repl.setPlaceholderText("바꿀 글자"); self.repl.returnPressed.connect(self.replace_one)
        lay.addWidget(self.repl)
        rrow = QHBoxLayout()
        rb1 = QPushButton("바꾸기"); rb1.clicked.connect(self.replace_one); rrow.addWidget(rb1)
        rb = QPushButton("모두 바꾸기"); rb.clicked.connect(self.replace_all); rrow.addWidget(rb)
        lay.addLayout(rrow)
        self._quiet = False   # 내가 바꾼 것이라 doc_changed 로 다시 찾지 않음
        self.jump = True      # hitsChanged 를 받는 쪽이 지금 결과로 옮겨 갈지
        self.list = QListWidget(); self.list.itemClicked.connect(self._pick)
        self.list.setUniformItemSizes(True)  # 한 줄 글이라 칸 높이가 같다. 안 두면 결과 300건에 칸 재기만 0.24초
        # 고른 줄로 저절로 굴리면 결과마다 목록 전체 칸을 다시 재어 0.13초(298건이면 1.3초) 멈췄다. 보이게 하는 것은 step 이 한 줄만
        self.list.setAutoScroll(False)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        outer.addWidget(self.list)

    def focus(self):
        self.edit.setFocus(); self.edit.selectAll()

    def focus_replace(self):
        """검색 및 바꾸기(Ctrl+T): 찾을 글자가 있으면 바꿀 글자 칸으로."""
        (self.repl if self.edit.text() else self.edit).setFocus()

    BG_PAGES = 60  # 이보다 큰 문서는 일꾼에서 찾는다(959쪽은 글자 뽑기만 0.9초)

    def run(self, sync: bool = False):
        self._search(sync=sync)

    def _args(self):
        return self.edit.text(), self.case.isChecked(), self.whole.isChecked()

    def _search(self, sync: bool = False, near: tuple | None = None, jump: bool = True):
        """전부 다시 찾는다. near=(쪽, y, x) 를 주면 그 자리 다음 결과를 지금 결과로(문서가 바뀌어 다시 찾을 때 자리를 지킨다)."""
        q, case, whole = self._args()
        self.list.clear()
        self.hits = []; self.results = []
        self._gen += 1
        if not q:
            self.count.setText(""); self.hitsChanged.emit([], -1); return
        if sync or self.doc.page_count <= self.BG_PAGES:
            self._show(self.doc.search(q, case=case, whole_word=whole), near, jump)
            return
        self.count.setText("찾는 중")
        w = _SearchWorker(self.doc, q, case, whole)
        w.found.connect(lambda res, g=self._gen: self._show(res, near, jump) if g == self._gen else None)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(w)
        w.start()

    def _show(self, res, near: tuple | None = None, jump: bool = True):
        """jump=False 면 강조만 고치고 보기는 그 자리에 둔다(문서를 고쳐 다시 찾았을 때)."""
        self.jump = jump
        self.results = res
        self.hits = [(h.page, h.all_rects()) for h in res]
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        for h in res:
            self.list.addItem(f"{h.page + 1}쪽   {h.context[:60]}")
        self.list.setUpdatesEnabled(True)
        self.current = self._index_after(near) if near else (0 if self.hits else -1)
        if self.hits:
            self.list.setCurrentRow(self.current)
            self.list.scrollToItem(self.list.item(self.current))
        self._count()
        self.hitsChanged.emit(self.hits, self.current)

    def _count(self):
        """「3/12」: 지금 결과 / 모두. 없으면 「없음」."""
        self.count.setText(f"{self.current + 1}/{len(self.hits)}" if self.hits else ("없음" if self.edit.text() else ""))

    def _index_after(self, near: tuple) -> int:
        """near=(쪽, y, x) 자리이거나 그 뒤에 오는 첫 결과(끝을 넘으면 처음)."""
        if not self.results:
            return -1
        pg, y, x = near
        for k, h in enumerate(self.results):
            r = h.rect
            if h.page > pg or (h.page == pg and (r.y0 > y + 2 or (abs(r.y0 - y) <= 2 and r.x0 >= x - 1))):
                return k
        return 0

    def step(self, d: int):
        if not self.hits:
            return
        self.current = (self.current + d) % len(self.hits)
        self.list.setCurrentRow(self.current)
        self.list.scrollToItem(self.list.item(self.current))
        self._count()
        self.jump = True
        self.hitsChanged.emit(self.hits, self.current)

    def _pick(self, it):
        self.current = self.list.row(it)
        self.jump = True
        self._count()
        self.hitsChanged.emit(self.hits, self.current)

    def _splice(self, pages: set[int], near: tuple | None = None, jump: bool = True):
        """그 쪽만 다시 찾아 결과에 끼운다(한 쪽 4ms 안팎. 959쪽 전체를 다시 찾으면 1초)."""
        q, case, whole = self._args()
        cur = self.results[self.current] if 0 <= self.current < len(self.results) else None
        new = self.doc.search(q, pages=sorted(pages), case=case, whole_word=whole) if q else []
        res = sorted([h for h in self.results if h.page not in pages] + new, key=lambda h: h.page)   # 쪽 안 차례는 그대로
        if near is None and cur is not None:
            near = (cur.page, cur.rect.y0, cur.rect.x0)
        self._show(res, near, jump)

    def doc_changed(self, pages: list[int] | None, structural: bool = False):
        """문서가 바뀌었다: 찾아 둔 결과의 자리가 틀릴 수 있어 다시 찾는다(바뀐 쪽만, 쪽 구조가 바뀌면 전부)."""
        if self._quiet or not self.edit.text():
            return
        cur = self.results[self.current] if 0 <= self.current < len(self.results) else None
        near = (cur.page, cur.rect.y0, cur.rect.x0) if cur else None
        if structural or pages is None:
            self._search(near=near, jump=False)
        else:
            self._splice(set(pages), near, jump=False)

    def replace_one(self):
        """지금 결과 하나를 바꾸고 다음 결과로(「바꾸기」). 아직 안 찾았으면 이번에는 찾기만."""
        if not self.hits:
            self.run(); return
        if not (0 <= self.current < len(self.results)):
            return
        h = self.results[self.current]
        self.doc.replace_text([h], self.repl.text())
        self._quiet = True
        try:
            self.replaced.emit([h.page])
        finally:
            self._quiet = False
        # 바꾼 글자 뒤부터(바꾼 글자에 찾는 말이 또 들어 있어도 같은 자리를 다시 고르지 않게)
        self._splice({h.page}, (h.page, h.rect.y0, h.rect.x1 - 1))

    def replace_all(self):
        if not self.hits:
            self.run(sync=True)
        if not self.hits:
            return
        n = self.doc.replace_text(self.results, self.repl.text())
        QMessageBox.information(self, "바꾸기", f"{n}곳을 바꿨습니다")
        self._quiet = True
        try:
            self.replaced.emit(sorted({h.page for h in self.results}))
        finally:
            self._quiet = False
        self.run()

    def close(self):
        self._gen += 1
        for w in list(self._workers):
            w.wait(3000)


class _SearchWorker(QThread):
    found = Signal(object)

    def __init__(self, doc: Document, q: str, case: bool, whole: bool):
        super().__init__()
        self.doc, self.args = doc, (q, case, whole)

    def run(self):
        last = [time.perf_counter()]

        def breathe(*_):
            # 그냥 두면 처음 찾을 때 이 스레드가 GIL 을 끝까지 쥐어 화면이 0.8초 멈췄다(959쪽).
            # 20ms 마다 1ms 씩 놓아 준다(쪽마다 놓으면 찾는 시간이 두 배)
            if time.perf_counter() - last[0] > 0.02:
                time.sleep(0.001)
                last[0] = time.perf_counter()
        try:
            res = self.doc.search(self.args[0], case=self.args[1], whole_word=self.args[2], progress=breathe)
        except Exception:  # noqa: BLE001  찾는 사이 문서가 닫혔다
            return
        self.found.emit(res)


class LayerPanel(QWidget):
    changed = Signal()  # 보기만 바뀜(문서는 그대로)

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(panel_head("레이어"))
        self.list = QListWidget(); self.list.itemChanged.connect(self._toggle)
        lay.addWidget(self.list)
        self.empty = QLabel("이 문서에는 레이어가 없습니다"); self.empty.setObjectName("dim")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter); lay.addWidget(self.empty)
        self.reload()

    def reload(self):
        self.list.blockSignals(True)
        self.list.clear()
        layers = self.doc.layers()
        self.empty.setVisible(not layers)
        for l in layers:
            it = QListWidgetItem("    " * l["depth"] + l["name"])
            if not l["locked"]:
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if l["on"] else Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, l["number"])
            self.list.addItem(it)
        self.list.blockSignals(False)

    def _toggle(self, it):
        self.doc.set_layer(it.data(Qt.ItemDataRole.UserRole), it.checkState() == Qt.CheckState.Checked)
        self.changed.emit()
        self.reload()  # 묶음(라디오) 레이어는 하나를 켜면 다른 것이 꺼진다


class FieldPanel(QWidget):
    """양식 칸 목록(오른쪽 패널용)."""
    gotoField = Signal(int, object)
    changed = Signal()

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(panel_head("양식 칸"))
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["이름", "종류", "값"]); _tidy_tree(self.tree, 0)
        self.tree.itemClicked.connect(lambda it, _: self.gotoField.emit(*it.data(0, Qt.ItemDataRole.UserRole)) if it.data(0, Qt.ItemDataRole.UserRole) else None)
        lay.addWidget(self.tree)
        self.reload()

    def reload(self):
        self.tree.clear()
        for f in A.fields(self.doc):
            it = QTreeWidgetItem([f["name"], A.FIELD_TYPE_KO.get(f["type"].lower().replace("button", "button"), f["type"]), "꺼짐" if str(f["value"]) == "Off" else str(f["value"] or "")])
            it.setData(0, Qt.ItemDataRole.UserRole, (f["page"], f["rect"]))
            self.tree.addTopLevelItem(it)

"""왼쪽 패널: 썸네일 · 북마크 · 주석 목록 · 첨부 파일 · 검색 · 레이어 · (양식 칸 · 서명)."""
from __future__ import annotations

import fitz
from PySide6.QtCore import QRectF, QSize, Qt, QThread, QTimer, Signal
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
    w = QWidget(); w.setObjectName("panelhead"); w.setFixedHeight(36)
    w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    hl = QHBoxLayout(w); hl.setContentsMargins(12, 0, 6, 0); hl.setSpacing(2)
    t = QLabel(title); t.setObjectName("paneltitle"); hl.addWidget(t); hl.addStretch()
    for name, tip, fn in buttons:
        b = QToolButton(); b.setObjectName("quick"); b.setIcon(icons.icon(name, 16)); b.setToolTip(tip)
        b.clicked.connect(fn); hl.addWidget(b)
    return w


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
    done = Signal(int, QImage)

    def __init__(self, doc: Document, width: int, dpr: float = 1.0):
        super().__init__()
        self.doc = doc
        self.width = int(width * dpr)
        self.dpr = dpr
        self.todo: list[int] = []
        self._stop = False

    def run(self):
        while not self._stop and self.todo:
            i = self.todo.pop(0)
            try:
                r = self.doc.fitz[i].rect
                z = self.width / max(1, r.width)
                pix = self.doc.render(i, z)
                fmt = QImage.Format.Format_RGB888
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
                img.setDevicePixelRatio(self.dpr)
                self.done.emit(i, img)
            except Exception:  # noqa: BLE001
                pass


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
        top = r.top() + 6
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
        p.drawText(QRectF(r.left(), r.bottom() - 22, r.width(), 20), Qt.AlignmentFlag.AlignCenter, str(label))
        p.restore()

    def sizeHint(self, opt, idx):
        return idx.data(Qt.ItemDataRole.SizeHintRole) or QSize(100, 140)


class PageGrid(QListWidget):
    """쪽 썸네일 격자. 끌어 놓아 순서를 바꾸면 reordered(새 순서) 를 한 번 낸다.
    IconMode 는 Qt 가 놓을 자리를 받지 않아 끌어도 아무 일이 없다(10-19 진짜 끌기로 확인).
    그래서 ListMode 를 왼→오 흐름·줄바꿈으로 격자처럼 쓴다."""
    reordered = Signal(list)

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


class ThumbnailPanel(QWidget):
    """썸네일: 눌러 이동, 끌어 순서 바꾸기, 오른쪽 클릭 메뉴."""
    pageClicked = Signal(int)
    reordered = Signal(list)       # 새 순서
    pagesAction = Signal(str, list)  # 'rotate_left' 'rotate_right' 'delete' 'extract' 'insert_blank' 'insert_pdf' 'duplicate'

    def __init__(self, doc: Document, thumb_w: int = 120, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.thumb_w = thumb_w
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(panel_head("썸네일", (("zoomout", "작게", lambda: self.set_width(max(70, self.thumb_w - 30))),
                                            ("zoomin", "크게", lambda: self.set_width(min(260, self.thumb_w + 30))))))
        self.list = PageGrid(8)
        self.list.itemClicked.connect(lambda it: self.pageClicked.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.list.reordered.connect(self.reordered)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list)
        self.worker: ThumbWorker | None = None
        self.reload()

    def set_width(self, w: int):
        self.thumb_w = w
        self.reload()

    def selected_pages(self) -> list[int]:
        return sorted(it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems())

    def reload(self):
        if self.worker and self.worker.isRunning():
            self.worker._stop = True
            self.worker.wait(1000)
        self.list.clear()
        labels = P.labels(self.doc)
        for i in range(self.doc.page_count):
            r = self.doc.fitz[i].rect
            h = int(self.thumb_w * r.height / max(1, r.width))
            pm = QPixmap(self.thumb_w, h); pm.fill(Qt.GlobalColor.white)
            it = QListWidgetItem(labels[i])
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setData(ThumbDelegate.PIX, pm)
            it.setSizeHint(QSize(self.thumb_w + 16, h + 34))
            self.list.addItem(it)
        self.worker = ThumbWorker(self.doc, self.thumb_w, self.devicePixelRatioF())
        self.worker.todo = list(range(self.doc.page_count))
        self.worker.done.connect(self._thumb)
        self.worker.start()

    def refresh_pages(self, pages: list[int] | None):
        if self.worker and self.worker.isRunning():
            self.worker.todo.extend(pages or range(self.doc.page_count))
        else:
            self.worker = ThumbWorker(self.doc, self.thumb_w, self.devicePixelRatioF())
            self.worker.todo = list(pages or range(self.doc.page_count))
            self.worker.done.connect(self._thumb)
            self.worker.start()

    def _thumb(self, i: int, img: QImage):
        if i < self.list.count():
            self.list.item(i).setData(ThumbDelegate.PIX, QPixmap.fromImage(img))

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
        if self.worker and self.worker.isRunning():
            self.worker._stop = True
            self.worker.wait(1000)


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

    def add(self):
        pg = self.get_current_page()
        title, ok = QInputDialog.getText(self, "북마크 추가", "이름", text=f"{pg + 1}쪽")
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
        box = QWidget(); bl = QVBoxLayout(box); bl.setContentsMargins(8, 8, 8, 6)
        self.filter = QComboBox(); self.filter.addItems(["전체"] + sorted(set(A.KIND_NAMES.values())))
        self.filter.currentIndexChanged.connect(self.reload)
        bl.addWidget(self.filter); lay.addWidget(box)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["종류", "내용", "작성자"]); _tidy_tree(self.tree, 1)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.tree)
        self.reload()

    def reload(self):
        self.tree.clear()
        want = self.filter.currentText()
        by_page: dict[int, QTreeWidgetItem] = {}
        for a in A.list_annots(self.doc):
            if a.kind in ("Link", "Widget", "Popup"):
                continue
            if want != "전체" and a.kind_ko != want:
                continue
            if a.page not in by_page:
                pit = QTreeWidgetItem([f"{a.page + 1}쪽", "", ""])
                pit.setFlags(pit.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.tree.addTopLevelItem(pit)
                by_page[a.page] = pit
            it = QTreeWidgetItem([a.kind_ko, a.content, a.author])
            it.setData(0, Qt.ItemDataRole.UserRole, (a.page, a.xref, a.rect))
            by_page[a.page].addChild(it)
        self.tree.expandAll()

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
    replaced = Signal()

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.hits = []       # [(쪽, [줄마다 네모])]
        self.results = []    # SearchHit
        self.current = -1
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(panel_head("검색"))
        lay = QVBoxLayout(); lay.setContentsMargins(10, 10, 10, 8); lay.setSpacing(8); outer.addLayout(lay)
        row = QHBoxLayout()
        self.edit = QLineEdit(); self.edit.setPlaceholderText("찾을 글자"); self.edit.returnPressed.connect(self.run)
        row.addWidget(self.edit)
        b = QToolButton(); b.setObjectName("quick"); b.setIcon(icons.icon("search", 16)); b.clicked.connect(self.run); row.addWidget(b)
        lay.addLayout(row)
        opts = QHBoxLayout()
        self.case = QCheckBox("대소문자"); self.whole = QCheckBox("낱말 전체")
        opts.addWidget(self.case); opts.addWidget(self.whole); opts.addStretch()
        lay.addLayout(opts)
        nav = QHBoxLayout()
        self.count = QLabel(""); self.count.setObjectName("dim")
        bp = QToolButton(); bp.setObjectName("quick"); bp.setIcon(icons.icon("up", 16)); bp.clicked.connect(lambda: self.step(-1))
        bn = QToolButton(); bn.setObjectName("quick"); bn.setIcon(icons.icon("down", 16)); bn.clicked.connect(lambda: self.step(1))
        nav.addWidget(self.count); nav.addStretch(); nav.addWidget(bp); nav.addWidget(bn)
        lay.addLayout(nav)
        # 바꾸기
        rrow = QHBoxLayout()
        self.repl = QLineEdit(); self.repl.setPlaceholderText("바꿀 글자")
        rrow.addWidget(self.repl)
        rb = QPushButton("모두 바꾸기"); rb.clicked.connect(self.replace_all); rrow.addWidget(rb)
        lay.addLayout(rrow)
        self.list = QListWidget(); self.list.itemClicked.connect(self._pick)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        outer.addWidget(self.list)

    def focus(self):
        self.edit.setFocus(); self.edit.selectAll()

    def run(self):
        q = self.edit.text()
        self.list.clear()
        self.hits = []
        if not q:
            self.count.setText(""); self.hitsChanged.emit([], -1); return
        res = self.doc.search(q, case=self.case.isChecked(), whole_word=self.whole.isChecked())
        self.results = res
        self.hits = [(h.page, h.all_rects()) for h in res]
        for h in res:
            ctx = self.doc.text_in_rect(h.page, fitz.Rect(h.rect.x0 - 80, h.rect.y0 - 2, h.rect.x1 + 80, h.rect.y1 + 2))
            self.list.addItem(f"{h.page + 1}쪽   {ctx.strip().replace(chr(10), ' ')[:60]}")
        self.current = 0 if self.hits else -1
        self.count.setText(f"{len(self.hits)}개" if self.hits else "없음")
        if self.hits:
            self.list.setCurrentRow(0)
        self.hitsChanged.emit(self.hits, self.current)

    def step(self, d: int):
        if not self.hits:
            return
        self.current = (self.current + d) % len(self.hits)
        self.list.setCurrentRow(self.current)
        self.hitsChanged.emit(self.hits, self.current)

    def _pick(self, it):
        self.current = self.list.row(it)
        self.hitsChanged.emit(self.hits, self.current)

    def replace_all(self):
        if not self.hits:
            self.run()
        if not self.hits:
            return
        n = self.doc.replace_text(self.results, self.repl.text())
        QMessageBox.information(self, "바꾸기", f"{n}곳을 바꿨습니다")
        self.replaced.emit()
        self.run()


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
            it = QTreeWidgetItem([f["name"], A.FIELD_TYPE_KO.get(f["type"].lower().replace("button", "button"), f["type"]), str(f["value"] or "")])
            it.setData(0, Qt.ItemDataRole.UserRole, (f["page"], f["rect"]))
            self.tree.addTopLevelItem(it)

"""「구성」 탭: 쪽 썸네일 격자. 끌어 순서 바꾸기, 여러 장 골라 회전·삭제·내보내기·끼우기."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QListWidgetItem, QMenu, QVBoxLayout, QWidget

from ..engine import pages as P
from ..engine.document import Document
from .sidebar import PageGrid, ThumbDelegate, ThumbWorker


class OrganizeView(QWidget):
    reordered = Signal(list)
    pagesAction = Signal(str, list)
    openPage = Signal(int)

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.thumb_w = 150
        lay = QVBoxLayout(self); lay.setContentsMargins(16, 16, 16, 16)
        self.list = PageGrid(14)
        self.list.setStyleSheet("QListWidget{background: transparent;}")
        self.list.reordered.connect(self.reordered)
        self.list.itemDoubleClicked.connect(lambda it: self.openPage.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list)
        self.worker: ThumbWorker | None = None
        self.reload()

    def set_width(self, w: int):
        self.thumb_w = max(80, min(400, w))
        self.reload()

    def selected_pages(self) -> list[int]:
        return sorted(it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems())

    def select_pages(self, pages: list[int]):
        self.list.clearSelection()
        for k in range(self.list.count()):
            it = self.list.item(k)
            if it.data(Qt.ItemDataRole.UserRole) in pages:
                it.setSelected(True)

    def reload(self):
        if self.worker and self.worker.isRunning():
            self.worker._stop = True; self.worker.wait(1000)
        self.list.clear()
        labels = P.labels(self.doc)
        for i in range(self.doc.page_count):
            r = self.doc.fitz[i].rect
            h = int(self.thumb_w * r.height / max(1, r.width))
            pm = QPixmap(self.thumb_w, h); pm.fill(Qt.GlobalColor.white)
            it = QListWidgetItem(labels[i])
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setData(ThumbDelegate.PIX, pm)
            it.setSizeHint(QSize(self.thumb_w + 20, h + 40))
            self.list.addItem(it)
        self.worker = ThumbWorker(self.doc, self.thumb_w, self.devicePixelRatioF())
        self.worker.todo = list(range(self.doc.page_count))
        self.worker.done.connect(self._thumb)
        self.worker.start()

    def _thumb(self, i: int, img: QImage):
        if i < self.list.count():
            self.list.item(i).setData(ThumbDelegate.PIX, QPixmap.fromImage(img))

    def _menu(self, pos):
        pages = self.selected_pages()
        m = QMenu(self)
        for label, key in (("왼쪽 회전", "rotate_left"), ("오른쪽 회전", "rotate_right"), (None, None),
                           ("빈 페이지 끼우기", "insert_blank"), ("PDF 에서 끼우기", "insert_pdf"), ("바꾸기", "replace"),
                           ("복제", "duplicate"), (None, None), ("내보내기", "extract"), ("자르기", "crop"),
                           ("크기", "resize"), ("삭제", "delete")):
            if label is None:
                m.addSeparator()
            else:
                a = m.addAction(label, lambda k=key: self.pagesAction.emit(k, pages))
                a.setEnabled(bool(pages) or key in ("insert_blank", "insert_pdf"))
        m.exec(self.list.mapToGlobal(pos))

    def close(self):
        if self.worker and self.worker.isRunning():
            self.worker._stop = True; self.worker.wait(1000)

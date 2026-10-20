"""「구성」 탭: 쪽 썸네일 격자. 끌어 순서 바꾸기, 여러 장 골라 회전·삭제·내보내기·끼우기."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from ..engine.document import Document
from .sidebar import LazyThumbs, PageGrid, fill_grid


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
        self.thumbs = LazyThumbs(self.list, doc)
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
        fill_grid(self.list, self.doc, self.thumb_w, 20, 40)
        self.thumbs.start(self.thumb_w, self.devicePixelRatioF())

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
        self.thumbs.stop()

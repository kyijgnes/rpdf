"""시작 화면: 왼쪽 [PDF 열기]·최근 파일·즐겨찾기·최근 폴더, 오른쪽 빠른 도구 카드 + 최근 파일 표."""
from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
                               QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from . import icons, theme

QUICK_TOOLS = [
    ("edit", "편집", "파일에서 텍스트와 이미지를 편집합니다."),
    ("convert", "PDF 변환", "PDF를 Word, Excel, PPT 등으로 변환합니다."),
    ("ocr", "OCR PDF", "스캔한 문서를 검색·편집할 수 있게 합니다."),
    ("merge", "PDF 병합", "여러 파일을 하나의 PDF로 합칩니다."),
    ("batch", "PDF 일괄 작업", "일괄 변환, 생성, 인쇄, OCR PDF 등"),
    ("create", "PDF 생성", "이미지·오피스·한글 파일을 PDF 로 만듭니다."),
    ("compress", "PDF 압축", "파일 크기를 줄입니다."),
    ("protect", "암호화", "열기·권한 암호를 겁니다."),
]


def _ago(ts: float) -> str:
    d = time.time() - ts
    if d < 86400 and time.localtime(ts).tm_yday == time.localtime().tm_yday:
        return "오늘"
    if d < 7 * 86400:
        return "지난 주" if d > 86400 else "어제"
    return "이전"


def _stat(path: str) -> tuple[bool, float, int, bool]:
    """(있나, 수정 시각, 크기, 폴더인가). 닿지 않는 공유폴더(\\\\192.168…)는 여기서 몇 초씩 걸린다."""
    try:
        st = os.stat(path)
    except OSError:
        return False, 0.0, 0, False
    return True, st.st_mtime, st.st_size, os.path.isdir(path)


class _Stats(QObject):
    """최근 파일이 있는지·크기를 일꾼 스레드에서 본다. 닿지 않는 공유폴더 경로 하나가 화면 스레드를
    8초씩 붙잡아 켤 때·마지막 탭을 닫을 때 「응답 없음」이 났다(10-29)."""
    got = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.known: dict[str, tuple] = {}
        self._pending: set[str] = set()
        self.got.connect(self._got)

    def ask(self, path: str):
        if path in self._pending:   # 아직 답을 기다리는 경로(닿지 않는 곳)는 또 묻지 않는다
            return
        self._pending.add(path)
        threading.Thread(target=lambda: self.got.emit(path, _stat(path)), daemon=True).start()

    def _got(self, path: str, st: tuple):
        self._pending.discard(path)
        self.known[path] = st


class ToolCard(QFrame):
    clicked = Signal(str)

    def __init__(self, key: str, title: str, desc: str):
        super().__init__()
        self.key = key
        self.setObjectName("card")
        self.setFixedSize(200, 76)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self); lay.setContentsMargins(12, 10, 10, 10)
        col = QVBoxLayout(); col.setSpacing(2)
        t = QLabel(title); t.setStyleSheet("font-weight:bold")
        d = QLabel(desc); d.setObjectName("dim"); d.setWordWrap(True); d.setStyleSheet(f"color:{theme.TEXT_DIM}; font-size:8pt")
        col.addWidget(t); col.addWidget(d); col.addStretch()
        lay.addLayout(col, 1)
        ic = QLabel(); ic.setPixmap(icons.pixmap(key, 28, theme.ACCENT)); ic.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        lay.addWidget(ic)

    def mousePressEvent(self, e):
        self.clicked.emit(self.key)


class CardRow(QWidget):
    """빠른 도구 카드 한 줄. 폭이 모자라면 뒤 카드부터 [더보기] 메뉴로 넘긴다(카드 다섯 장이 창 최소 폭을 1275px 로 묶던 것)."""
    tool = Signal(str)
    GAP = 10

    def __init__(self, shown: int = 5):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)  # 줄일 수 있는 데까지=카드 한 장+더보기
        self.setFixedHeight(76)
        self.cards = []
        for key, title, desc in QUICK_TOOLS[:shown]:
            c = ToolCard(key, title, desc); c.setParent(self); c.clicked.connect(self.tool.emit); self.cards.append(c)
        self.more = QToolButton(self); self.more.setObjectName("quick"); self.more.setIcon(icons.icon("more", 18)); self.more.setToolTip("더보기")
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.more); self.more.setMenu(self.menu)
        self.fit()

    def minimumSizeHint(self) -> QSize:
        return QSize(self.cards[0].width() + self.GAP + self.more.sizeHint().width(), 76)

    def sizeHint(self) -> QSize:
        return QSize(len(self.cards) * (self.cards[0].width() + self.GAP) + self.more.sizeHint().width(), 76)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    def fit(self):
        cw = self.cards[0].width()
        mw = self.more.sizeHint().width()
        n = max(1, min(len(self.cards), (self.width() - mw) // (cw + self.GAP)))
        x = 0
        for k, c in enumerate(self.cards):
            c.setVisible(k < n)
            if k < n:
                c.move(x, 0); x += cw + self.GAP
        self.more.move(x, 0)
        self.menu.clear()
        for key, title, _ in QUICK_TOOLS[n:]:
            self.menu.addAction(title, lambda k=key: self.tool.emit(k))


class StartPage(QWidget):
    openFile = Signal()
    openPath = Signal(str)
    tool = Signal(str)
    newBlank = Signal()
    recentChanged = Signal()

    def __init__(self, recent: list[dict], favorites: list[str], parent=None):
        super().__init__(parent)
        self.recent = recent
        self.favorites = favorites
        self.mode = "recent"
        self.setObjectName("central")
        root = QHBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        # 왼쪽
        left = QWidget(); left.setObjectName("sidepanel"); left.setFixedWidth(150)
        ll = QVBoxLayout(left); ll.setContentsMargins(12, 16, 12, 12); ll.setSpacing(6)
        row = QHBoxLayout()
        ob = QPushButton("PDF 열기"); ob.setObjectName("accent"); ob.clicked.connect(self.openFile.emit); row.addWidget(ob, 1)
        nb = QToolButton(); nb.setObjectName("quick"); nb.setIcon(icons.icon("add", 16)); nb.setToolTip("빈 PDF")
        nb.clicked.connect(self.newBlank.emit); row.addWidget(nb)
        ll.addLayout(row); ll.addSpacing(18)
        self.navbtns = {}
        for key, name, label in (("recent", "recent", "최근 파일"), ("fav", "star", "즐겨찾기 파일"), ("folder", "folder", "최근 폴더")):
            b = QToolButton(); b.setObjectName("nav"); b.setIcon(icons.icon(name, 16)); b.setText(label)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); b.setCheckable(True); b.setAutoExclusive(True)
            b.setStyleSheet("QToolButton#nav{border-left:none; padding:6px; text-align:left}")
            b.clicked.connect(lambda _, k=key: self.set_mode(k)); ll.addWidget(b); self.navbtns[key] = b
        self.navbtns["recent"].setChecked(True)
        ll.addStretch()
        root.addWidget(left)
        # 오른쪽
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(24, 20, 24, 16); rl.setSpacing(10)
        h = QLabel("빠른 도구"); h.setStyleSheet("font-size:13pt; font-weight:bold"); rl.addWidget(h)
        self.cards = CardRow(); self.cards.tool.connect(self.tool.emit)
        rl.addWidget(self.cards)
        hr = QHBoxLayout()
        self.title = QLabel("최근 파일"); self.title.setStyleSheet("font-size:13pt; font-weight:bold"); hr.addWidget(self.title); hr.addStretch()
        self.search = QLineEdit(); self.search.setPlaceholderText("검색"); self.search.setFixedWidth(180); self.search.textChanged.connect(self.reload)
        hr.addWidget(self.search)
        clr = QToolButton(); clr.setObjectName("quick"); clr.setIcon(icons.icon("delete", 16)); clr.setToolTip("목록 비우기"); clr.clicked.connect(self.clear_list)
        hr.addWidget(clr)
        rl.addLayout(hr)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["이름", "마지막 수정 시간", "크기"])
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeaderItem(2).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)  # 크기 숫자와 같은 쪽
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed); self.table.setColumnWidth(1, 160)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed); self.table.setColumnWidth(2, 100)
        self.table.verticalHeader().hide(); self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        rl.addWidget(self.table)
        root.addWidget(right, 1)
        self.stats = _Stats(self)
        self.stats.got.connect(self._stat_got)
        self.reload()

    def set_mode(self, m: str):
        self.mode = m
        self.title.setText({"recent": "최근 파일", "fav": "즐겨찾기 파일", "folder": "최근 폴더"}[m])
        self.reload()

    def _rows(self) -> list[dict]:
        """디스크는 건드리지 않는다(있는지·크기는 _Stats 가 뒤에서 본다)."""
        q = self.search.text().strip().lower()
        if self.mode == "folder":
            seen, out = set(), []
            for r in self.recent:
                d = os.path.dirname(r["path"])
                if d not in seen:
                    seen.add(d); out.append({"path": d, "time": r.get("time", 0), "dir": True})
            rows = out
        elif self.mode == "fav":
            rows = [{"path": p, "time": 0} for p in self.favorites]
        else:
            rows = list(self.recent)
        return [r for r in rows if q in os.path.basename(r["path"]).lower()]

    def reload(self):
        rows = self._rows()
        self.table.setRowCount(len(rows))
        for n, r in enumerate(rows):
            name = QTableWidgetItem(os.path.basename(r["path"]) or r["path"])
            name.setIcon(icons.icon("folder" if r.get("dir") else "thumbs", 16, theme.ACCENT))
            name.setData(Qt.ItemDataRole.UserRole, r["path"])
            name.setData(Qt.ItemDataRole.UserRole + 1, bool(r.get("dir")))
            name.setData(Qt.ItemDataRole.UserRole + 2, r.get("time", 0))
            self.table.setItem(n, 0, name)
            self._fill(n)
            self.stats.ask(r["path"])

    def _fill(self, n: int):
        """n 번째 줄의 시간·크기 칸. 아직 못 본 경로는 최근 파일에 적어 둔 시각으로 두고 크기는 비운다."""
        it0 = self.table.item(n, 0)
        path, is_dir, t = it0.data(Qt.ItemDataRole.UserRole), it0.data(Qt.ItemDataRole.UserRole + 1), it0.data(Qt.ItemDataRole.UserRole + 2)
        st = self.stats.known.get(path)
        size = ""
        if st is None:
            when = _ago(t) if t else ""
        elif not st[0]:
            when = "파일 없음"
        else:
            when = _ago(st[1])
            if not is_dir:
                b = st[2]; size = f"{b / 1024:.1f} KB" if b < 1024 * 1024 else f"{b / 1024 / 1024:.1f} MB"
        self.table.setItem(n, 1, QTableWidgetItem(when))
        it = QTableWidgetItem(size); it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(n, 2, it)
        self.table.setRowHidden(n, bool(is_dir and st is not None and not (st[0] and st[3])))   # 최근 폴더는 없는 폴더를 뺀다

    def _stat_got(self, path: str, _st):
        for n in range(self.table.rowCount()):
            if self.table.item(n, 0).data(Qt.ItemDataRole.UserRole) == path:
                self._fill(n)

    def _open_row(self, row, _):
        it = self.table.item(row, 0)
        p = it.data(Qt.ItemDataRole.UserRole)
        if it.data(Qt.ItemDataRole.UserRole + 1):
            os.startfile(p)
        else:
            self.openPath.emit(p)

    def _menu(self, pos):
        it = self.table.itemAt(pos)
        if not it:
            return
        p = self.table.item(it.row(), 0).data(Qt.ItemDataRole.UserRole)
        is_dir = self.table.item(it.row(), 0).data(Qt.ItemDataRole.UserRole + 1)
        m = QMenu(self)
        m.addAction("열기", lambda: self._open_row(it.row(), 0))
        m.addAction("폴더 열기", lambda: os.startfile(p if is_dir else os.path.dirname(p)))
        if p in self.favorites:
            m.addAction("즐겨찾기에서 빼기", lambda: (self.favorites.remove(p), self.reload(), self.recentChanged.emit()))
        else:
            m.addAction("즐겨찾기에 넣기", lambda: (self.favorites.append(p), self.reload(), self.recentChanged.emit()))
        m.addAction("목록에서 빼기", lambda: (self._remove(p), self.reload(), self.recentChanged.emit()))
        m.exec(self.table.mapToGlobal(pos))

    def _remove(self, p: str):
        self.recent[:] = [r for r in self.recent if r["path"] != p]

    def clear_list(self):
        if self.mode == "fav":
            self.favorites.clear()
        else:
            self.recent.clear()
        self.reload(); self.recentChanged.emit()

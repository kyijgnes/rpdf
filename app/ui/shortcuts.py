"""단축키 표 · 사용자가 바꾼 키 · 환경 설정의 단축키 칸.

기본 키는 일반적인 PDF 편집기의 단축키 배치를 따르고, PDF메트리에만 있던 키는 뒤에 덧붙였다.
설정 파일(settings.json)에는 기본값과 다른 동작만 `hotkeys: {동작: ["Ctrl+W", …]}` 로 둔다. 빈 목록이면 키 없음.
화살표·Home·End·Enter·Space 처럼 문서 보기 안에서만 듣는 키는 뷰어(keyPressEvent)가 맡아 여기 없다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QKeySequenceEdit, QLabel, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme

MAX_KEYS = 3  # 한 동작에 키 조합 셋까지

# (동작, 묶음, 이름, 기본 키)
TABLE: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("open", "파일", "열기", ("Ctrl+O",)),
    ("save", "파일", "저장", ("Ctrl+S",)),
    ("saveas", "파일", "다른 이름으로 저장", ("Ctrl+Shift+S",)),
    ("print", "파일", "인쇄", ("Ctrl+P",)),
    ("close", "파일", "지금 문서 닫기", ("Ctrl+W", "Ctrl+F4")),
    ("properties", "파일", "문서 속성", ("Ctrl+D",)),
    ("preferences", "파일", "환경 설정", ("Ctrl+K",)),
    ("create_files", "파일", "파일에서 PDF 생성", ("Ctrl+N",)),
    ("create_blank", "파일", "빈 PDF", ("Ctrl+Shift+N",)),
    ("undo", "파일", "실행 취소", ("Ctrl+Z",)),
    ("redo", "파일", "다시 실행", ("Ctrl+Y", "Ctrl+Shift+Z")),
    ("next_tab", "탭", "다음 문서", ("Ctrl+Tab",)),
    ("prev_tab", "탭", "이전 문서", ("Ctrl+Shift+Tab",)),
    ("search", "검색", "검색 패널", ("Ctrl+F",)),
    ("search_replace", "검색", "검색 및 바꾸기", ("Ctrl+T",)),
    ("search_next", "검색", "다음 검색 결과", ("F3",)),
    ("search_prev", "검색", "이전 검색 결과", ("Shift+F3",)),
    ("zoom_actual", "확대", "실제 크기", ("Ctrl+1",)),
    ("zoom_width", "확대", "창 너비에 맞추기", ("Ctrl+2",)),
    ("zoom_height", "확대", "창 높이에 맞추기", ("Ctrl+3",)),
    ("zoom_page", "확대", "창 크기에 맞추기", ("Ctrl+0",)),
    ("zoomin", "확대", "확대", ("Ctrl+=",)),   # Ctrl++ 는 큰 키판에서 Ctrl+Shift+= (오른쪽 회전)와 같은 키. 숫자 키판 + 는 뷰어가 받는다
    ("zoomout", "확대", "축소", ("Ctrl+-",)),
    ("layout_continuous", "보기", "한 페이지 연속", ("Ctrl+4",)),
    ("layout_single", "보기", "한 페이지씩", ("Ctrl+5",)),
    ("layout_facing", "보기", "두 페이지", ("Ctrl+6",)),
    ("layout_facing_continuous", "보기", "두 페이지 연속", ("Ctrl+7",)),
    ("fullscreen", "보기", "전체 화면", ("F11", "Ctrl+L")),
    ("read_mode", "보기", "읽기 모드", ("Ctrl+R",)),
    ("tile_h", "보기", "가로로 나란히", ("Ctrl+Shift+K",)),
    ("tile_v", "보기", "세로로 나란히", ("Ctrl+Shift+L",)),
    ("goto", "이동", "쪽으로 이동", ("Ctrl+G",)),
    ("prev_view", "이동", "이전 보기", ("Alt+Left",)),
    ("next_view", "이동", "다음 보기", ("Alt+Right",)),
    ("side_left", "막대", "왼쪽 막대 보이기·숨기기", ("F4",)),
    ("side_right", "막대", "속성 막대 보이기·숨기기", ("Shift+F4",)),
    ("thumbs", "막대", "썸네일 패널", ("Ctrl+Shift+2",)),
    ("bookmark", "막대", "북마크 패널", ("Ctrl+Shift+3",)),
    ("comments", "막대", "주석 목록 패널", ("Ctrl+Shift+4",)),
    ("attach", "막대", "첨부 파일 패널", ("Ctrl+Shift+5",)),
    ("search_panel", "막대", "검색 패널 펼치기", ("Ctrl+Shift+6",)),
    ("ribbon_next", "리본", "다음 리본 탭", ("F6",)),
    ("ribbon_prev", "리본", "이전 리본 탭", ("Shift+F6",)),
    ("ribbon_fold", "리본", "리본 접기·펴기", ("F8",)),
    ("tool_hand", "모드", "손 도구", ("Alt+3",)),
    ("tool_select", "모드", "선택 도구", ("Alt+6",)),
    ("edit_all_toggle", "모드", "모두 편집", ("Ctrl+E",)),
    ("highlight", "주석", "강조", ("Shift+Alt+1",)),
    ("note", "주석", "노트", ("Shift+Alt+2",)),
    ("textbox", "주석", "텍스트 박스", ("Shift+Alt+3",)),
    ("typewriter", "주석", "타자기", ("Shift+Alt+4",)),
    ("callout", "주석", "텍스트 말풍선", ("Shift+Alt+5",)),
    ("line", "주석", "선", ("Shift+Alt+6",)),
    ("arrow", "주석", "화살표", ("Shift+Alt+7",)),
    ("oval", "주석", "타원", ("Shift+Alt+8",)),
    ("rect", "주석", "직사각형", ("Shift+Alt+9",)),
    ("pencil", "주석", "연필", ("Shift+Alt+P",)),
    ("eraser", "주석", "지우개", ("Shift+Alt+E",)),
    ("underline", "주석", "밑줄", ("Ctrl+U",)),
    ("strike", "주석", "취소선", ("Ctrl+Q",)),
    ("insert_pdf", "쪽", "파일에서 쪽 삽입", ("Ctrl+Shift+I",)),
    ("insert_blank", "쪽", "빈 쪽 삽입", ("Ctrl+Shift+T",)),
    ("delete_pages", "쪽", "쪽 삭제", ("Ctrl+Shift+D",)),
    ("rotate_left", "쪽", "왼쪽으로 회전", ("Ctrl+Shift+-",)),
    ("rotate_right", "쪽", "오른쪽으로 회전", ("Ctrl+Shift+=",)),
    ("bookmark_add", "북마크", "북마크 추가", ("Ctrl+B",)),
    ("bookmark_rename", "북마크", "고른 북마크 이름 바꾸기", ("F2",)),
    ("snapshot_tool", "도구", "스크린샷", ("Ctrl+F1", "Ctrl+Shift+C")),
    ("batch", "도구", "일괄 처리", ("Ctrl+F8",)),
    ("print_batch", "도구", "일괄 인쇄", ("Ctrl+F2",)),
    ("help", "공통", "도움말", ("F1",)),
]
NAMES = {k: name for k, _, name, _ in TABLE}
DEFAULTS = {k: list(keys) for k, _, _, keys in TABLE}


def norm(seq: str) -> str:
    """키 글자를 Qt 표기 하나로 맞춘다(「ctrl+shift+s」 와 「Ctrl+Shift+S」 를 같은 키로)."""
    return QKeySequence(seq).toString(QKeySequence.SequenceFormat.PortableText)


# Shift 를 눌러야 나오는 글자 → (Shift 없이 누르는 키). 「Ctrl++」 는 손으로는 Ctrl+Shift+= 라 둘을 같은 키로 본다
_SHIFTED = {"+": "=", "_": "-", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8",
            "(": "9", ")": "0", ":": ";", "<": ",", ">": ".", "?": "/", '"': "'", "{": "[", "}": "]", "|": "\\", "~": "`"}


def physical(seq: str) -> str:
    """손으로 누르는 키로 맞춘 글자(겹침 검사용). 「Ctrl++」 → 「Ctrl+Shift+=」."""
    s = norm(seq)
    if not s:
        return s
    head, _, ch = (s[:-2], "+", "+") if s.endswith("++") else s.rpartition("+")
    if ch in _SHIFTED:
        mods = [m for m in head.split("+") if m]
        if "Shift" not in mods:
            mods.append("Shift")
        return norm("+".join(mods + [_SHIFTED[ch]]))
    return s


def current(overrides: dict | None) -> dict[str, list[str]]:
    """동작마다 지금 쓰는 키(바꾼 것이 있으면 그것)."""
    out = {k: list(v) for k, v in DEFAULTS.items()}
    for k, v in (overrides or {}).items():
        if k in out and isinstance(v, list):
            out[k] = [norm(s) for s in v if isinstance(s, str) and norm(s)][:MAX_KEYS]
    return out


def diff(keys: dict[str, list[str]]) -> dict[str, list[str]]:
    """설정 파일에 남길 것: 기본값과 다른 동작만."""
    return {k: v for k, v in keys.items() if [norm(s) for s in v] != [norm(s) for s in DEFAULTS.get(k, [])]}


def clashes(keys: dict[str, list[str]]) -> dict[str, set[str]]:
    """같은 키를 둘 이상의 동작이 쓰면 {키: 동작들}. 겹친 키는 Qt 가 어느 쪽도 부르지 않는다."""
    who: dict[str, set[str]] = {}
    for k, seqs in keys.items():
        for s in seqs:
            who.setdefault(physical(s), set()).add(k)
    return {s: ks for s, ks in who.items() if len(ks) > 1}


def label(keys: dict[str, list[str]], action: str) -> str:
    """메뉴 옆에 붙일 키 글자(첫 키만). 키가 없으면 빈 글자."""
    seqs = keys.get(action) or []
    return QKeySequence(seqs[0]).toString(QKeySequence.SequenceFormat.NativeText) if seqs else ""



def _no_hint(e: QKeySequenceEdit):
    """빈 칸의 Qt 기본 안내 글(영어 「Press shortcut」)을 뺀다. Qt 가 키를 넣거나 지울 때마다 다시 넣어서 그때마다 부른다."""
    for le in e.findChildren(QLineEdit):
        le.setPlaceholderText("")

class ShortcutEditor(QWidget):
    """환경 설정 「단축키」 칸: 동작마다 키 셋. 칸을 누르고 키를 누르면 바뀐다. 겹친 키는 그 줄을 빨갛게."""

    def __init__(self, overrides: dict | None, parent=None):
        super().__init__(parent)
        self.keys = current(overrides)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 6, 0, 0)
        top = QHBoxLayout()
        self.filter = QLineEdit(); self.filter.setPlaceholderText("동작이나 키로 찾기")
        self.filter.textChanged.connect(self._filter); top.addWidget(self.filter, 1)
        self.clash_label = QLabel(""); self.clash_label.setObjectName("dim"); top.addWidget(self.clash_label)
        reset = QPushButton("모두 기본값으로"); reset.clicked.connect(self.reset); top.addWidget(reset)
        lay.addLayout(top)
        self.table = QTableWidget(len(TABLE), 2 + MAX_KEYS)
        self.table.setHorizontalHeaderLabels(["묶음", "동작"] + [f"키 {n + 1}" for n in range(MAX_KEYS)])
        self.table.verticalHeader().hide()
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in range(2, 2 + MAX_KEYS):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed); self.table.setColumnWidth(c, 118)
        self.edits: dict[str, list[QKeySequenceEdit]] = {}
        for row, (k, group, name, _) in enumerate(TABLE):
            self.table.setItem(row, 0, QTableWidgetItem(group))
            self.table.setItem(row, 1, QTableWidgetItem(name))
            eds = []
            for n in range(MAX_KEYS):
                e = QKeySequenceEdit(); e.setMaximumSequenceLength(1); e.setClearButtonEnabled(True)
                e.editingFinished.connect(lambda k=k: self._edited(k))
                e.keySequenceChanged.connect(lambda _s, k=k: self._edited(k))
                e.keySequenceChanged.connect(lambda _s, e=e: _no_hint(e))
                self.table.setCellWidget(row, 2 + n, e); eds.append(e)
            self.edits[k] = eds
        self.table.setMinimumSize(560, 360)
        lay.addWidget(self.table, 1)
        self._fill()

    def _fill(self):
        for k, eds in self.edits.items():
            seqs = self.keys.get(k, [])
            for n, e in enumerate(eds):
                e.blockSignals(True)
                e.setKeySequence(QKeySequence(seqs[n]) if n < len(seqs) else QKeySequence())
                e.blockSignals(False)
                _no_hint(e)
        self._mark()

    def _edited(self, k: str):
        seqs = []
        for e in self.edits[k]:
            s = e.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            if s and s not in seqs:
                seqs.append(s)
        self.keys[k] = seqs
        self._mark()

    def _mark(self):
        bad = clashes(self.keys)
        hit = {a for ks in bad.values() for a in ks}
        red = QColor(theme.ACCENT)
        for row, (k, _, _, _) in enumerate(TABLE):
            for c in (0, 1):
                it = self.table.item(row, c)
                it.setForeground(red if k in hit else self.palette().text().color())
        self.clash_label.setText(f"겹친 키 {len(bad)}개 · " + ", ".join(sorted(bad))[:60] if bad else "")

    def _filter(self, text: str):
        q = text.strip().lower()
        for row, (k, group, name, _) in enumerate(TABLE):
            keys = " ".join(self.keys.get(k, [])).lower()
            self.table.setRowHidden(row, bool(q) and q not in (group + " " + name).lower() and q not in keys)

    def reset(self):
        self.keys = current(None)
        self._fill()

    def values(self) -> dict[str, list[str]]:
        return diff(self.keys)

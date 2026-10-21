"""리본: 윗줄(파일 · 빠른 단추 · 탭 · 검색칸) + 아랫줄(그 탭의 단추들, 가운데 정렬).

단추 정의는 TABS 자료로. kind: action(누르면 한 번) · tool(켜짐 유지, 뷰어 도구) · toggle(켜고 끄기) · menu(메뉴).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont, QFontMetrics
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QMenu, QSizePolicy,
                               QSpinBox, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from . import icons, theme

# (key, icon, label, kind, menu_items)  menu_items: [(key, label)] 또는 None. label 이 "|" 면 구분선.
SEP = ("|",)
TABS: list[tuple[str, str, list]] = [
    ("home", "홈", [
        ("zoomout", "zoomout", "", "action", None), ("zoomin", "zoomin", "", "action", None), SEP,
        ("hand", "hand", "", "tool", None), ("select", "select", "", "tool", None), SEP,
        ("edit_all", "edit", "모두 편집", "toggle", None), ("addtext", "addtext", "텍스트 추가", "tool", None), SEP,
        ("ocr", "ocr", "OCR", "action", None), ("crop", "crop", "자르기", "tool", None), SEP,
        ("search", "search", "검색", "action", None),
        ("home_more", "more", "더보기", "menu", [("snapshot", "스크린샷"), ("m_distance", "측정: 거리"), ("print", "인쇄"),
                                                 ("properties", "파일 속성")]),
    ]),
    ("edit", "편집", [
        ("edit_all", "edit", "모두 편집", "toggle", None), ("addtext", "addtext", "텍스트 추가", "tool", None),
        ("addimage", "addimage", "이미지 추가", "tool", None),
        ("link", "link", "링크 추가", "tool", None), SEP,
        ("watermark", "watermark", "워터마크", "action", [("watermark", "추가"), ("watermark_update", "업데이트"), ("watermark_remove", "삭제")]),
        ("background", "background", "배경화면", "action", [("background", "추가"), ("background_update", "업데이트"), ("background_remove", "삭제")]),
        ("headerfooter", "headerfooter", "머리글 & 바닥글", "action", [("headerfooter", "추가"), ("headerfooter_update", "업데이트"), ("headerfooter_remove", "삭제")]),
        ("pagenumber", "bates", "쪽 번호", "action", [("pagenumber", "추가"), ("pagenumber_update", "업데이트"), ("pagenumber_remove", "삭제")]),
        ("edit_more", "more", "더보기", "menu", [("bates", "베이츠 번호 추가"), ("bates_update", "베이츠 번호 업데이트"), ("bates_remove", "베이츠 번호 삭제"), ("pagelabel", "페이지 레이블"),
                                                 ("replace_image", "이미지 바꾸기(고른 것)"), ("delete_sel", "고른 것 삭제")]),
    ]),
    ("comment", "주석", [
        ("pencil", "pencil", "연필", "tool", None), ("eraser", "eraser", "지우개", "tool", None), SEP,
        ("highlight", "highlight", "강조", "tool", [("highlight", "강조"), ("areahl", "영역 강조")]),
        ("underline", "underline", "밑줄", "tool", [("underline", "밑줄"), ("strike", "취소선"), ("squiggly", "구불구불한 선"), ("caret", "삽입 기호")]),
        SEP,
        ("typewriter", "typewriter", "타자기", "tool", [("typewriter", "타자기"), ("textbox", "텍스트 박스"), ("callout", "텍스트 말풍선")]),
        ("note", "note", "노트", "tool", None), SEP,
        ("rect", "rect", "직사각형", "tool", [("rect", "직사각형"), ("oval", "타원"), ("line", "선"), ("arrow", "화살표"), ("polygon", "다각형"),
                                      ("polyline", "연결된 선"), ("cloud", "클라우드")]),
        ("stamp", "stamp", "스탬프", "tool", [("stamp_pick", "스탬프 고르기"), ("stamp_image", "이미지 스탬프 만들기")]),
        ("signature", "signature", "서명", "tool", None), ("attach", "attach", "첨부 파일", "tool", None),
        ("measure", "measure", "거리 측정", "tool", [("m_distance", "거리"), ("m_perimeter", "둘레"), ("m_area", "영역")]), SEP,
        ("show_annots", "eye", "주석 보이기", "toggle", None),
    ]),
    ("convert", "변환", [
        ("create", "create", "PDF 생성", "menu", [("create_files", "파일에서 생성"), ("create_blank", "빈 PDF"),
                                                 ("create_clipboard", "클립보드에서 가져오기"), ("create_scan", "스캐너에서 생성")]), SEP,
        ("to_hwpx", "hwp", "HWP로 변환", "action", None), ("to_docx", "word", "Word로 변환", "action", None),
        ("to_xlsx", "excel", "Excel로 변환", "action", None), ("to_pptx", "ppt", "PowerPoint로 변환", "action", None),
        ("to_png", "image", "이미지로 변환", "action", None), ("to_txt", "text", "텍스트로 변환", "action", None),
        ("convert_more", "more", "더보기", "menu", [("to_html", "HTML로"), ("to_rtf", "RTF로"), ("to_epub", "EPUB로"), ("to_pdfa", "PDF/A로"),
                                                    ("convert_settings", "설정 변환")]), SEP,
        ("batch", "batch", "일괄 변환", "action", None),
    ]),
    ("view", "보기", [
        ("zoomout", "zoomout", "", "action", None), ("zoomin", "zoomin", "", "action", None), SEP,
        ("zoom_menu", "actual", "확대 방식", "menu", [("zoom_actual", "실제 페이지 크기에 맞추기"), ("zoom_width", "창 너비에 맞추기"),
                                             ("zoom_height", "창 높이에 맞추기"), ("zoom_page", "창 크기에 맞추기")]),
        ("layout_menu", "continuous", "보기 방식", "menu", [("layout_single", "한 페이지씩 보기"), ("layout_continuous", "스크롤 활성화 상태로 페이지 보기"),
                                                   ("layout_facing", "양 옆으로 두페이지 보기"), ("layout_facing_continuous", "스크롤 활성화 상태로 양 옆으로 보기")]),
        ("canvas_menu", "background", "바탕색", "menu", [("canvas_gray", "회색 바탕"), ("canvas_white", "흰 바탕"), ("canvas_dark", "어두운 바탕"), ("canvas_sepia", "세피아")]), SEP,
        ("read_mode", "read", "읽기 모드", "toggle", None),
        ("rotate_view", "rotate", "회전시켜 보기", "menu", [("rotate_view_cw", "시계 방향"), ("rotate_view_ccw", "반시계 방향")]), SEP,
        ("auto_bookmark", "bookmark", "자동 북마크", "action", None),
        ("grid", "grid", "눈금자와 격자", "menu", [("toggle_grid", "격자 보이기·숨기기"), ("toggle_ruler", "눈금자 보이기·숨기기")]),
        ("tile", "tile", "타일", "menu", [("tile_h", "가로 제목"), ("tile_v", "세로 제목")]), SEP,
        ("fullscreen", "fullscreen", "전체 화면", "action", None), ("dark", "dark", "어두운 화면", "toggle", None),
    ]),
    ("page", "구성", [
        ("thumb_out", "zoomout", "", "action", None), ("thumb_in", "zoomin", "", "action", None), SEP,
        ("rotate_left", "rotateleft", "", "action", None), ("rotate_right", "rotateright", "", "action", None),
        ("delete_pages", "delete", "", "action", None), SEP,
        ("extract", "extract", "추출", "action", None),
        ("split", "split", "분할", "action", None),
        ("insert", "insert", "삽입", "menu", [("insert_blank", "빈 페이지"), ("insert_pdf", "PDF에서"), ("insert_images", "이미지에서")]), SEP,
        ("crop_pages", "crop", "자르기", "action", None), ("rotate_pages", "rotate", "회전", "action", None),
        ("resize", "resize", "크기", "action", None),
        ("page_more", "more", "더보기", "menu", [("split_page", "페이지 분할(칸으로 나누기)"), ("replace", "바꾸기"), ("duplicate", "복제"), ("pagebox", "페이지 박스"),
                                                 ("pagelabel", "페이지 레이블"), ("delete_blank", "빈 페이지 삭제"), ("reverse", "순서 뒤집기")]),
    ]),
    ("tools", "도구", [
        ("ocr", "ocr", "OCR", "action", None), ("ocrarea", "ocrarea", "영역 OCR", "tool", None), SEP,
        ("merge", "merge", "PDF 병합", "action", None), ("compare", "compare", "PDF 비교", "action", None), SEP,
        ("compress", "compress", "PDF 압축", "action", None), ("flatten", "flatten", "평면화", "action", None), SEP,
        ("batch", "batch", "일괄 편집", "action", None),
        ("tools_more", "more", "더보기", "menu", [("deskew", "기울기 보정"), ("table", "표 인식"), ("snapshot", "스크린샷"),
                                                  ("extract_data", "데이터 추출"), ("print", "인쇄")]),
    ]),
    ("form", "양식", [
        ("form_edit", "edit", "양식 편집", "toggle", None), SEP,
        ("ftext", "ftext", "텍스트 칸", "tool", None), ("fcheck", "fcheck", "체크 박스", "tool", None), ("fradio", "fradio", "라디오 버튼", "tool", None),
        ("fcombo", "fcombo", "콤보 박스", "tool", None), ("flist", "flist", "목록 박스", "tool", None), ("fbutton", "fbutton", "누름 버튼", "tool", None),
        ("fimage", "fimage", "이미지 칸", "tool", None), ("fsign", "fsign", "서명 칸", "tool", None), ("fdate", "fdate", "날짜 칸", "tool", None), SEP,
        ("recognize", "recognize", "양식 인식", "action", None), ("form_export", "export", "데이터 추출", "action", None),
        ("form_more", "more", "더보기", "menu", [("form_import", "데이터 가져오기"), ("form_reset", "기본값으로 되돌리기"),
                                                 ("form_set_default", "지금 값을 기본값으로"), ("form_preview", "미리보기"),
                                                 ("align_left", "정렬: 왼쪽"), ("align_right", "정렬: 오른쪽"), ("align_top", "정렬: 위"),
                                                 ("align_bottom", "정렬: 아래"), ("align_hcenter", "정렬: 가로 가운데"), ("align_vcenter", "정렬: 세로 가운데"),
                                                 ("align_dist_h", "정렬: 가로로 같은 간격"), ("align_dist_v", "정렬: 세로로 같은 간격"),
                                                 ("align_page_both", "페이지 가운데")]),
    ]),
    ("protect", "보안", [
        ("encrypt", "lock", "암호화", "action", None), ("decrypt", "unlock", "암호 풀기", "action", None), SEP,
        ("redact", "redact", "교정 표시", "tool", None), ("redact_search", "redactsearch", "검색 & 교정", "action", None),
        ("redact_apply", "redactapply", "교정 적용", "action", None), ("hidden", "hidden", "숨겨진 데이터 삭제", "action", None), SEP,
        ("digital_sign", "cert", "디지털 서명", "action", None),
        ("sign_manage", "signature", "서명 관리", "menu", [("sign_new", "서명 이미지 등록"), ("sign_apply", "서명 넣기"), ("sign_clear", "등록한 서명 지우기")]),
    ]),
]

LABELS = {k: lbl for _, _, items in TABS for it in items if it != SEP for k, lbl in [(it[0], it[2])]}
LABELS.update({"hand": "손", "select": "선택", "zoomin": "확대", "zoomout": "축소", "pencil": "연필", "eraser": "지우개",
               "highlight": "강조", "underline": "밑줄", "typewriter": "타자기", "note": "노트", "rect": "직사각형", "stamp": "스탬프",
               "signature": "서명", "attach": "첨부 파일", "measure": "측정", "show_annots": "주석 보이기", "zoom_menu": "확대 방식",
               "layout_menu": "보기 방식", "canvas_menu": "바탕색", "thumb_out": "썸네일 축소", "thumb_in": "썸네일 확대",
               "rotate_left": "왼쪽 회전", "rotate_right": "오른쪽 회전", "delete_pages": "페이지 삭제", "ftext": "텍스트 칸",
               "fcheck": "체크 박스", "fradio": "라디오 버튼", "fcombo": "콤보 박스", "flist": "목록 박스", "fbutton": "누름 버튼",
               "fimage": "이미지", "fsign": "디지털 서명 칸", "fdate": "날짜 칸", "areahl": "영역 강조", "strike": "취소선",
               "squiggly": "구불구불한 선", "caret": "삽입 기호", "textbox": "텍스트 박스", "callout": "텍스트 말풍선", "oval": "타원",
               "line": "선", "arrow": "화살표", "polygon": "다각형", "polyline": "연결된 선", "cloud": "클라우드",
               "m_distance": "거리 측정", "m_perimeter": "둘레 측정", "m_area": "넓이 측정", "crop": "자르기", "link": "링크", "redact": "교정 표시",
               "ocrarea": "영역 OCR", "addtext": "텍스트 추가", "addimage": "이미지 추가", "snapshot": "스크린샷"})

# 메뉴 항목 중 뷰어 도구가 되는 것
TOOL_KEYS = {"hand", "select", "addtext", "addimage", "link", "crop", "pencil", "eraser", "highlight", "areahl", "underline",
             "strike", "squiggly", "caret", "typewriter", "textbox", "callout", "note", "rect", "oval", "line", "arrow",
             "polygon", "polyline", "cloud", "stamp", "signature", "attach", "m_distance", "m_perimeter", "m_area",
             "ocrarea", "redact", "snapshot", "ftext", "fcheck", "fradio", "fcombo", "flist", "fbutton", "fimage", "fsign", "fdate"}


class Ribbon(QWidget):
    action = Signal(str)          # action·menu 항목
    tool = Signal(str)            # 뷰어 도구 바뀜
    toggled = Signal(str, bool)   # toggle 단추
    tabChanged = Signal(str)
    searchRequested = Signal(str)
    fileMenu = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ribbon")
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        # 윗줄
        top = QWidget(); top.setObjectName("ribbonbar"); tl = QHBoxLayout(top); tl.setContentsMargins(6, 3, 10, 0); tl.setSpacing(2)
        fb = QToolButton(); fb.setObjectName("filetab"); fb.setText("파일"); fb.clicked.connect(self.fileMenu.emit); tl.addWidget(fb)
        self.quick: dict[str, QToolButton] = {}
        for key, name, tip in (("save", "save", "저장"), ("print", "print", "인쇄"), ("undo", "undo", "실행 취소"),
                               ("redo", "redo", "다시 실행"), ("mail", "mail", "메일로 보내기")):
            b = QToolButton(); b.setObjectName("quick"); b.setIcon(icons.icon(name, 16)); b.setToolTip(tip)
            b.clicked.connect(lambda _, k=key: self.action.emit(k)); tl.addWidget(b); self.quick[key] = b
        qm = QToolButton(); qm.setObjectName("quick"); qm.setIcon(icons.icon("down", 14)); qm.setToolTip("빠른 실행 단추")
        menu = QMenu(qm)
        for key, label in (("saveas", "다른 이름으로 저장"), ("properties", "파일 속성"), ("preferences", "환경 설정")):
            menu.addAction(label, lambda k=key: self.action.emit(k))
        qm.setMenu(menu); qm.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup); tl.addWidget(qm)
        tl.addStretch(1)
        self.tabbtns: dict[str, QToolButton] = {}
        grp = QButtonGroup(self); grp.setExclusive(True)
        for key, label, _ in TABS:
            b = QToolButton(); b.setObjectName("ribbontab"); b.setText(label); b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self.set_tab(k)); grp.addButton(b); tl.addWidget(b); self.tabbtns[key] = b
            bf = QFont(theme.FONT); bf.setPointSizeF(theme.FONT_PT); bf.setBold(True)  # 고른 탭이 굵어져도 폭이 그대로이게
            b.setFixedWidth(QFontMetrics(bf).horizontalAdvance(label) + 24)
        tl.addStretch(1)
        self.search = QLineEdit(); self.search.setPlaceholderText("검색 (Ctrl+F)")
        self.search.setMinimumWidth(70); self.search.setMaximumWidth(150)  # 창이 좁으면 검색칸부터 줄인다(화면 반쪽 960px)
        self.search.returnPressed.connect(lambda: self.searchRequested.emit(self.search.text()))
        tl.addWidget(self.search)
        lay.addWidget(top)
        # 아랫줄
        self.stack = QStackedWidget(); self.stack.setObjectName("ribbonrow"); self.stack.setFixedHeight(40)
        self.pages: dict[str, QWidget] = {}
        self.buttons: dict[str, list[QToolButton]] = {}
        self.toolgroup: dict[str, list[QToolButton]] = {}
        for key, _, items in TABS:
            w = self._build(items)
            self.pages[key] = w; self.stack.addWidget(w)
        lay.addWidget(self.stack)
        # 리본 아래 옅은 그림자: 리본과 문서 자리가 한 판으로 붙어 밋밋하던 것을 층으로 나눈다
        shade = QWidget(); shade.setObjectName("ribbonshadow"); shade.setFixedHeight(4)
        shade.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True); lay.addWidget(shade)
        self._widths: dict[str, tuple[int, int, list[QToolButton]]] = {}
        self.current_tab = "home"
        self.set_tab("home")

    # 창이 좁으면 단추 이름을 접고(아이콘만) 넓으면 편다. 이름을 늘 다 보이면 창을 1300px 아래로 못 줄였다.
    def _measure(self):
        for key, w in self.pages.items():
            btns = [b for b in w.findChildren(QToolButton) if b.text()]
            lay = w.layout()
            for b in btns:
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            lay.invalidate(); compact = lay.minimumSize().width()
            for b in btns:
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            lay.invalidate(); full = lay.minimumSize().width()
            self._widths[key] = (compact, full, btns)
            w.setMinimumWidth(compact)
        self._fit()

    def _fit(self):
        avail = self.stack.width()
        for compact, full, btns in self._widths.values():
            style = Qt.ToolButtonStyle.ToolButtonTextBesideIcon if avail >= full else Qt.ToolButtonStyle.ToolButtonIconOnly
            for b in btns:
                if b.toolButtonStyle() != style:
                    b.setToolButtonStyle(style)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._widths:
            self._measure()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._widths:
            self._fit()

    def _build(self, items) -> QWidget:
        w = QWidget(); hl = QHBoxLayout(w); hl.setContentsMargins(8, 3, 8, 4); hl.setSpacing(2)
        hl.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)  # 최소 폭은 _measure 가 정한다(아이콘만일 때 폭)
        hl.addStretch(1)
        for it in items:
            if it == SEP:
                f = QFrame(); f.setObjectName("vsep"); f.setFrameShape(QFrame.Shape.VLine); f.setFixedHeight(18); hl.addWidget(f)
                continue
            key, icon, label, kind, menu_items = it
            b = QToolButton(); b.setObjectName("rb"); b.setIcon(icons.icon(icon, 16)); b.setIconSize(icons.icon_size(16))
            b.setToolTip(LABELS.get(key, label))
            if label:
                b.setText(label); b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setProperty("key", key); b.setProperty("kind", kind)
            if kind in ("tool", "toggle"):
                b.setCheckable(True)
            if menu_items:
                m = QMenu(b)
                for mk, ml in menu_items:
                    m.addAction(ml, lambda k=mk, btn=b: self._menu_pick(k, btn))
                b.setMenu(m)
                b.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup if kind == "tool" else QToolButton.ToolButtonPopupMode.InstantPopup)
                # 화살표 자리를 QSS 가 단추 모양마다 맞춘다(split: 눌러 쓰고 옆 화살표로 고름, drop: 눌러서 메뉴)
                b.setProperty("split" if kind == "tool" else "drop", True)
            if kind == "tool":
                b.setProperty("toolkey", menu_items[0][0] if menu_items else key)
                b.clicked.connect(lambda checked, btn=b: self._tool_clicked(btn, checked))
            elif kind == "toggle":
                b.clicked.connect(lambda checked, k=key: self.toggled.emit(k, checked))
            elif kind == "action":
                b.clicked.connect(lambda _, k=key: self.action.emit(k))
            self.buttons.setdefault(key, []).append(b)
            hl.addWidget(b)
        hl.addStretch(1)
        return w

    def _menu_pick(self, key: str, btn: QToolButton):
        if key in TOOL_KEYS and btn.property("kind") == "tool":
            btn.setProperty("toolkey", key)
            btn.setToolTip(LABELS.get(key, key))
            if btn.text():
                btn.setText(LABELS.get(key, btn.text()))
            btn.setChecked(True)
            self.tool.emit(key)
        else:
            self.action.emit(key)

    def _tool_clicked(self, btn: QToolButton, checked: bool):
        key = btn.property("toolkey")
        if checked:
            self.tool.emit(key)
        else:
            self.tool.emit("hand")

    def set_tab(self, key: str):
        self.current_tab = key
        self.tabbtns[key].setChecked(True)
        self.stack.setCurrentWidget(self.pages[key])
        self.tabChanged.emit(key)

    def reflect_tool(self, tool: str):
        """뷰어 도구가 바뀌면 단추 켜짐을 맞춘다."""
        for key, btns in self.buttons.items():
            for b in btns:
                if b.property("kind") != "tool":
                    continue
                b.setChecked(b.property("toolkey") == tool or (key == tool))

    def set_toggle(self, key: str, on: bool):
        for b in self.buttons.get(key, []):
            b.blockSignals(True); b.setChecked(on); b.blockSignals(False)

    def set_enabled_all(self, on: bool):
        for btns in self.buttons.values():
            for b in btns:
                b.setEnabled(on)
        for k, b in self.quick.items():
            if k != "mail":
                b.setEnabled(on)
        self.search.setEnabled(on)

    def set_enabled(self, key: str, on: bool):
        for b in self.buttons.get(key, []):
            b.setEnabled(on)
        if key in self.quick:
            self.quick[key].setEnabled(on)

"""색·여백·글꼴 한 곳. 알PDF 기본 스킨(흰 바탕·옅은 회색 띠·빨간 강조) 을 따른다.

화살표(⌄)·체크 표시는 Qt 기본 그림(테마마다 모양이 달라 하늘색 네모가 섞임) 대신 여기서 같은 굵기로 그려 쓴다.
"""
from __future__ import annotations

import os
import tempfile

ACCENT = "#E8383D"        # 알PDF 빨강
ACCENT_DARK = "#C9272C"
BG = "#FFFFFF"
BAR = "#F4F5F7"           # 리본 단추 줄·상태줄·세로 막대 바탕
BAR_LINE = "#E3E3E6"
CANVAS = "#EDEEF0"        # 문서 뒤 회색
TEXT = "#222326"
TEXT_DIM = "#8A8C91"
HOVER = "#F0F0F2"
PRESSED = "#E6E6E9"
SELECT_BG = "#FDECEC"
FONT = "Malgun Gothic"

LIGHT = {"BG": BG, "BAR": BAR, "BAR_LINE": BAR_LINE, "CANVAS": CANVAS, "TEXT": TEXT, "TEXT_DIM": TEXT_DIM,
         "HOVER": HOVER, "PRESSED": PRESSED, "SELECT_BG": SELECT_BG, "FIELD": "#FFFFFF", "FIELD_LINE": "#D9DADE",
         "SCROLL": "#CDCED2", "SCROLL_HOVER": "#AEB0B5", "WARN_BG": "#FDEBEC", "WARN_LINE": "#F5C9CB",
         # 층 나누기: 맨 위 탭 줄은 진하게, 패널 바탕은 옅은 회색, 그 위에 흰 카드
         "TITLEBAR": "#E9EAED", "PANEL": "#F6F7F9", "CARD": "#FFFFFF", "CARD_LINE": "#E3E4E8", "SHADE": "rgba(0,0,0,0.07)"}
DARK = {"BG": "#1F2023", "BAR": "#26272B", "BAR_LINE": "#35363B", "CANVAS": "#141517", "TEXT": "#E6E6E8",
        "TEXT_DIM": "#8E9095", "HOVER": "#2E2F33", "PRESSED": "#393A3F", "SELECT_BG": "#3A2426", "FIELD": "#2A2B2F",
        "FIELD_LINE": "#45464C", "SCROLL": "#4A4B51", "SCROLL_HOVER": "#62636A", "WARN_BG": "#3A2426", "WARN_LINE": "#5A3033",
        "TITLEBAR": "#17181A", "PANEL": "#1B1C1F", "CARD": "#25262A", "CARD_LINE": "#34353A", "SHADE": "rgba(0,0,0,0.35)"}

CUR: dict = dict(LIGHT)  # 지금 테마. 아이콘이 그릴 때 여기 색을 쓴다(qss() 가 바꿈)


def _images(c: dict, dark: bool) -> dict[str, str]:
    """화살표·체크 그림을 1배·2배로 그려 임시 폴더에 둔다. QSS 는 url 의 @2x 를 고해상도 화면에서 알아서 쓴다."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

    folder = os.path.join(tempfile.gettempdir(), "pdfeditor_qss")
    os.makedirs(folder, exist_ok=True)
    shapes = {  # 이름: (가로, 세로, 선 색, 점들[0~1], 굵기)
        "down": (10, 6, c["TEXT_DIM"], [(0.1, 0.15), (0.5, 0.85), (0.9, 0.15)], 1.3),
        "up": (10, 6, c["TEXT_DIM"], [(0.1, 0.85), (0.5, 0.15), (0.9, 0.85)], 1.3),
        "check": (10, 8, "#FFFFFF", [(0.08, 0.5), (0.38, 0.85), (0.92, 0.12)], 1.6),
        "dot": (8, 8, "#FFFFFF", None, 0),
    }
    out = {}
    for name, (w, h, col, pts, lw) in shapes.items():
        base = os.path.join(folder, f"{'dark' if dark else 'light'}_{name}")
        for scale, suffix in ((1, ""), (2, "@2x")):
            pm = QPixmap(w * scale, h * scale)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            if pts:
                p.setPen(QPen(QColor(col), lw * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                path = QPainterPath(QPointF(pts[0][0] * w * scale, pts[0][1] * h * scale))
                for x, y in pts[1:]:
                    path.lineTo(x * w * scale, y * h * scale)
                p.drawPath(path)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(col))
                p.drawEllipse(QPointF(w * scale / 2, h * scale / 2), w * scale * 0.22, h * scale * 0.22)
            p.end()
            pm.save(base + suffix + ".png")
        out[name] = (base + ".png").replace("\\", "/")
    return out


def qss(dark: bool = False) -> str:
    c = dict(DARK if dark else LIGHT)
    c.update(ACCENT=ACCENT, ACCENT_DARK=ACCENT_DARK, FONT=FONT)
    CUR.clear(); CUR.update(c)
    try:
        img = _images(c, dark)
    except Exception:  # noqa: BLE001  (그림을 못 만들면 Qt 기본 화살표로)
        img = {}
    down, up, check, dot = (f'url("{img[k]}")' if k in img else "none" for k in ("down", "up", "check", "dot"))
    return f"""
    * {{ font-family: "{c['FONT']}"; font-size: 9pt; color: {c['TEXT']}; }}
    QMainWindow, QDialog, QWidget#central {{ background: {c['BG']}; }}
    QWidget#titlebar {{ background: {c['TITLEBAR']}; border-bottom: 1px solid {c['BAR_LINE']}; }}
    QWidget#ribbon {{ background: {c['BG']}; }}
    QStackedWidget#ribbonrow {{ background: {c['BAR']}; border-top: 1px solid {c['BAR_LINE']}; border-bottom: 1px solid {c['BAR_LINE']}; }}
    QWidget#ribbonshadow {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {c['SHADE']}, stop:1 rgba(0,0,0,0)); }}
    QWidget#ribbonbar {{ background: {c['BG']}; }}
    QWidget#statusbar {{ background: {c['BAR']}; border-top: 1px solid {c['BAR_LINE']}; }}
    QWidget#statusbar QLabel {{ color: {c['TEXT_DIM']}; }}
    QWidget#navstrip, QWidget#rightstrip {{ background: {c['BAR']}; }}
    QWidget#navstrip {{ border-right: 1px solid {c['BAR_LINE']}; }}
    QWidget#rightstrip {{ border-left: 1px solid {c['BAR_LINE']}; }}
    QWidget#sidepanel {{ background: {c['PANEL']}; border-right: 1px solid {c['BAR_LINE']}; }}
    QWidget#sidepanel QListWidget, QWidget#sidepanel QTreeWidget, QWidget#sidepanel QHeaderView,
    QWidget#sidepanel QHeaderView::section {{ background: {c['PANEL']}; }}
    QWidget#proppanel {{ background: {c['PANEL']}; border-left: 1px solid {c['BAR_LINE']}; }}
    QFrame#group {{ background: {c['CARD']}; border: 1px solid {c['CARD_LINE']}; border-radius: 8px; }}
    QFrame#group QLabel {{ background: transparent; }}
    QLabel#grouptitle {{ font-weight: bold; color: {c['TEXT']}; padding: 0 0 2px 0; }}
    /* 인쇄 창: 설정 두 칸 · 회색 미리보기 · 아래 단추 줄 */
    QWidget#printcol {{ background: {c['PANEL']}; border-right: 1px solid {c['BAR_LINE']}; }}
    QLabel#printhead {{ font-weight: bold; }}
    QWidget#printpreview {{ background: {c['CANVAS']}; }}
    QLabel#printfile {{ font-size: 8pt; }}
    QFrame#printnav {{ background: {c['BG']}; border: 1px solid {c['BAR_LINE']}; border-radius: 4px; }}
    QDialog#printdlg QLineEdit#printpos {{ border: none; padding: 0; background: transparent; min-height: 0; }}
    QWidget#printbottom {{ background: {c['PANEL']}; border-top: 1px solid {c['BAR_LINE']}; }}
    QDialog#printdlg QComboBox, QDialog#printdlg QSpinBox, QDialog#printdlg QDoubleSpinBox, QDialog#printdlg QLineEdit {{
        min-height: 16px; padding-top: 2px; padding-bottom: 2px; }}
    QDialog#printdlg QComboBox:disabled, QDialog#printdlg QSpinBox:disabled, QDialog#printdlg QDoubleSpinBox:disabled,
    QDialog#printdlg QLineEdit:disabled {{ background: {c['HOVER']}; border-color: {c['BAR_LINE']}; }}
    QToolButton#printstep {{ border: none; background: transparent; color: {c['TEXT_DIM']}; font-size: 12pt; padding: 0; }}
    QToolButton#printstep:hover {{ color: {c['ACCENT']}; }}
    QToolButton#printstep:disabled {{ color: {c['FIELD_LINE']}; }}
    QPushButton#printlink {{ border: none; background: transparent; color: {c['ACCENT']}; padding: 2px 0; min-height: 0; }}
    QPushButton#printlink:hover {{ color: {c['ACCENT_DARK']}; text-decoration: underline; }}
    QWidget#printtabs {{ border-bottom: 1px solid {c['BAR_LINE']}; }}
    QToolButton#printtab {{ border: none; border-bottom: 2px solid transparent; padding: 4px 6px; background: transparent;
        font-weight: bold; }}
    QToolButton#printtab:hover {{ color: {c['ACCENT']}; }}
    QToolButton#printtab:checked {{ color: {c['ACCENT']}; border-bottom: 2px solid {c['ACCENT']}; }}
    QToolButton#printtab:disabled {{ color: {c['TEXT_DIM']}; }}
    QToolButton#orient {{ border: 1px solid transparent; border-radius: 3px; background: transparent; }}
    QToolButton#orient:hover {{ background: {c['HOVER']}; }}
    QToolButton#orient:checked {{ background: {c['PRESSED']}; border-color: {c['FIELD_LINE']}; }}
    QToolButton#printprops {{ border: 1px solid {c['FIELD_LINE']}; border-radius: 11px; background: {c['FIELD']};
        min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px; padding: 0; }}
    QToolButton#printprops:hover {{ border-color: {c['ACCENT']}; }}

    /* 패널 머리(썸네일·북마크·주석…): 높이·글자·밑줄을 한 모양으로 */
    QWidget#panelhead {{ background: {c['BG']}; border-bottom: 1px solid {c['BAR_LINE']}; }}
    QWidget#panelshadow {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {c['SHADE']}, stop:1 rgba(0,0,0,0)); }}
    QLabel#paneltitle {{ font-weight: bold; padding: 0; }}
    QLabel#section {{ color: {c['TEXT_DIM']}; font-size: 8pt; padding: 8px 0 2px 0; }}

    /* 리본 탭: 고른 탭을 굵게 하면 글자 폭이 달라져 줄이 출렁인다. 색과 밑줄로만 */
    QToolButton#ribbontab {{ background: transparent; border: none; border-bottom: 2px solid transparent;
        padding: 7px 12px 5px 12px; color: {c['TEXT']}; }}
    QToolButton#ribbontab:hover {{ color: {c['ACCENT']}; }}
    QToolButton#ribbontab:checked {{ color: {c['ACCENT']}; border-bottom: 2px solid {c['ACCENT']}; }}
    QToolButton#ribbontab:disabled {{ color: {c['TEXT_DIM']}; }}
    QToolButton#filetab {{ background: transparent; border: none; padding: 7px 12px 5px 10px; }}
    QToolButton#filetab:hover {{ color: {c['ACCENT']}; }}

    /* 리본 단추 */
    QToolButton#rb {{ background: transparent; border: none; border-radius: 4px; padding: 4px 8px; }}
    QToolButton#rb:hover {{ background: {c['HOVER']}; }}
    QToolButton#rb:pressed {{ background: {c['PRESSED']}; }}
    QToolButton#rb:checked {{ background: {c['SELECT_BG']}; color: {c['ACCENT']}; }}
    QToolButton#rb:disabled {{ color: {c['TEXT_DIM']}; }}
    QToolButton#rb[drop="true"] {{ padding-right: 18px; }}
    QToolButton#rb::menu-indicator {{ image: {down}; subcontrol-origin: padding; subcontrol-position: right center;
        right: 6px; width: 10px; height: 6px; }}
    QToolButton#rb[split="true"] {{ padding-right: 20px; }}
    QToolButton#rb::menu-button {{ border: none; background: transparent; width: 16px;
        border-top-right-radius: 4px; border-bottom-right-radius: 4px; }}
    QToolButton#rb::menu-button:hover {{ background: {c['PRESSED']}; }}
    QToolButton#rb::menu-arrow {{ image: {down}; width: 10px; height: 6px; }}
    QToolButton#quick {{ background: transparent; border: none; padding: 4px; border-radius: 4px; }}
    QToolButton#quick:hover {{ background: {c['HOVER']}; }}
    QToolButton#quick:pressed {{ background: {c['PRESSED']}; }}
    QToolButton#quick:checked {{ background: {c['SELECT_BG']}; }}
    QToolButton#quick:disabled {{ color: {c['TEXT_DIM']}; }}
    QToolButton#quick::menu-indicator {{ image: none; width: 0; }}
    QFrame#vsep {{ color: {c['BAR_LINE']}; margin: 0 4px; }}

    /* 왼쪽·오른쪽 세로 막대 */
    QToolButton#nav {{ background: transparent; border: none; border-left: 2px solid transparent; padding: 8px 6px; }}
    QToolButton#nav:hover {{ background: {c['HOVER']}; }}
    QToolButton#nav:checked {{ background: {c['BG']}; border-left: 2px solid {c['ACCENT']}; }}

    /* 문서 탭 */
    QTabBar#doctabs::tab {{ background: transparent; border: none; border-top: 2px solid transparent;
        padding: 6px 10px 6px 12px; min-width: 120px; max-width: 220px; color: {c['TEXT_DIM']}; }}
    QTabBar#doctabs::tab:selected {{ background: {c['BG']}; border-top: 2px solid {c['ACCENT']}; color: {c['TEXT']}; }}
    QTabBar#doctabs::tab:hover:!selected {{ background: {c['HOVER']}; }}
    QTabBar#doctabs::close-button {{ subcontrol-position: right; }}

    /* 단추·입력칸 */
    QPushButton {{ background: {c['FIELD']}; border: 1px solid {c['FIELD_LINE']}; border-radius: 4px; padding: 5px 14px;
        min-height: 16px; }}
    QPushButton:hover {{ background: {c['HOVER']}; }}
    QPushButton:pressed {{ background: {c['PRESSED']}; }}
    QPushButton:default, QPushButton#accent {{ background: {c['ACCENT']}; color: white; border-color: {c['ACCENT']}; }}
    QPushButton:default:hover, QPushButton#accent:hover {{ background: {c['ACCENT_DARK']}; border-color: {c['ACCENT_DARK']}; }}
    QPushButton:disabled {{ color: {c['TEXT_DIM']}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
        background: {c['FIELD']}; border: 1px solid {c['FIELD_LINE']}; border-radius: 4px; padding: 3px 6px;
        min-height: 18px; selection-background-color: {c['ACCENT']}; selection-color: white; }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {c['SCROLL_HOVER']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border-color: {c['ACCENT']}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {c['TEXT_DIM']}; }}
    QComboBox {{ padding-right: 18px; }}
    QComboBox QLineEdit {{ border: none; padding: 0; margin: 0; background: transparent; min-height: 0; }}
    QComboBox::drop-down {{ border: none; width: 18px; subcontrol-origin: padding; subcontrol-position: right center; }}
    QComboBox::down-arrow {{ image: {down}; width: 10px; height: 6px; }}
    QComboBox QAbstractItemView {{ background: {c['BG']}; border: 1px solid {c['BAR_LINE']}; padding: 2px;
        selection-background-color: {c['HOVER']}; selection-color: {c['TEXT']}; outline: none; }}
    QAbstractSpinBox {{ padding-right: 18px; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ border: none; background: transparent; width: 16px; }}
    QAbstractSpinBox::up-button {{ subcontrol-position: top right; margin-top: 2px; }}
    QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 2px; }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {c['HOVER']}; border-radius: 3px; }}
    QAbstractSpinBox::up-arrow {{ image: {up}; width: 8px; height: 5px; }}
    QAbstractSpinBox::down-arrow {{ image: {down}; width: 8px; height: 5px; }}
    QCheckBox, QRadioButton {{ spacing: 6px; background: transparent; }}
    QCheckBox::indicator, QRadioButton::indicator, QListView::indicator, QTreeView::indicator {{
        width: 14px; height: 14px; border: 1px solid {c['FIELD_LINE']}; background: {c['FIELD']}; }}
    QCheckBox::indicator, QListView::indicator, QTreeView::indicator {{ border-radius: 3px; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {c['ACCENT']}; }}
    QCheckBox::indicator:checked, QListView::indicator:checked, QTreeView::indicator:checked {{
        background: {c['ACCENT']}; border-color: {c['ACCENT']}; image: {check}; }}
    QRadioButton::indicator:checked {{ background: {c['ACCENT']}; border-color: {c['ACCENT']}; image: {dot}; }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ background: {c['HOVER']}; }}
    QCheckBox::indicator:checked:disabled {{ background: {c['TEXT_DIM']}; border-color: {c['TEXT_DIM']}; image: {check}; }}
    QRadioButton::indicator:checked:disabled {{ background: {c['TEXT_DIM']}; border-color: {c['TEXT_DIM']}; image: {dot}; }}

    /* 목록 */
    QListWidget, QTreeWidget, QTreeView, QListView, QTableWidget {{ background: {c['BG']}; border: none;
        selection-background-color: {c['SELECT_BG']}; selection-color: {c['TEXT']}; outline: none; }}
    QListWidget::item, QTreeWidget::item {{ padding: 3px 2px; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: {c['SELECT_BG']}; color: {c['TEXT']}; }}
    QListWidget::item:hover:!selected, QTreeWidget::item:hover:!selected {{ background: {c['HOVER']}; }}
    QHeaderView {{ background: {c['BG']}; border: none; }}
    QHeaderView::section {{ background: {c['BG']}; color: {c['TEXT_DIM']}; border: none;
        border-bottom: 1px solid {c['BAR_LINE']}; padding: 4px 6px; }}

    /* 스크롤바: 가늘게, 바탕 없이 */
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['SCROLL']}; border-radius: 2px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['SCROLL_HOVER']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c['SCROLL']}; border-radius: 2px; min-width: 30px; }}
    QScrollBar::handle:horizontal:hover {{ background: {c['SCROLL_HOVER']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QAbstractScrollArea::corner {{ background: transparent; }}

    /* 메뉴 */
    QMenu {{ background: {c['BG']}; border: 1px solid {c['BAR_LINE']}; border-radius: 6px; padding: 5px; }}
    QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {c['HOVER']}; }}
    QMenu::item:disabled {{ color: {c['TEXT_DIM']}; }}
    QMenu::separator {{ height: 1px; background: {c['BAR_LINE']}; margin: 5px 8px; }}
    QMenu::right-arrow {{ image: none; }}

    /* 그 밖 */
    QSlider::groove:horizontal {{ height: 3px; background: {c['BAR_LINE']}; border-radius: 1px; }}
    QSlider::sub-page:horizontal {{ background: {c['ACCENT']}; border-radius: 1px; }}
    QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -5px 0; background: {c['ACCENT']}; border-radius: 6px; }}
    QSlider::handle:horizontal:hover {{ background: {c['ACCENT_DARK']}; }}
    QToolTip {{ background: {c['BG']}; color: {c['TEXT']}; border: 1px solid {c['BAR_LINE']}; padding: 4px 6px; }}
    QGroupBox {{ border: 1px solid {c['BAR_LINE']}; border-radius: 6px; margin-top: 12px; padding: 10px 8px 6px 8px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c['TEXT_DIM']}; }}
    QTabWidget::pane {{ border: 1px solid {c['BAR_LINE']}; border-radius: 6px; top: -1px; }}
    QTabWidget QTabBar::tab {{ background: transparent; border: none; border-bottom: 2px solid transparent;
        padding: 6px 12px; color: {c['TEXT_DIM']}; }}
    QTabWidget QTabBar::tab:selected {{ color: {c['ACCENT']}; border-bottom: 2px solid {c['ACCENT']}; }}
    QProgressBar {{ border: none; border-radius: 3px; background: {c['BAR_LINE']}; text-align: center; max-height: 6px; }}
    QProgressBar::chunk {{ background: {c['ACCENT']}; border-radius: 3px; }}
    QLabel#dim {{ color: {c['TEXT_DIM']}; }}
    QLabel#warn {{ background: {c['WARN_BG']}; color: {c['ACCENT_DARK']}; padding: 6px 12px; border-bottom: 1px solid {c['WARN_LINE']}; }}
    QFrame#card {{ background: {c['BG']}; border: 1px solid {c['BAR_LINE']}; border-radius: 6px; }}
    QFrame#card:hover {{ border-color: {c['ACCENT']}; }}
    """

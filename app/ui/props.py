"""오른쪽 속성 패널: 고른 주석의 모양·정보, 또는 지금 도구의 기본 모양.

알PDF 처럼 그 종류에 맞는 칸만 보이고, 고른 주석은 바꾸는 즉시 적용한다.
바꾼 모양은 그 종류의 기본값으로 기억한다(engine/annot_style, 「마지막에 고친 모양을 기본값으로」).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QToolButton, QVBoxLayout, QWidget)

from ..engine import annot_style as S
from ..engine import annots as A
from .dialogs import ColorButton, from_rgb01
from .sidebar import group_card, panel_head

# 알PDF 속성 패널 색 견본 여섯: 노랑·빨강·주황·파랑·초록·보라
SWATCHES = [(1, 238 / 255, 54 / 255), (1, 0, 0), (1, 154 / 255, 0), (49 / 255, 131 / 255, 1), (0, 253 / 255, 0),
            (194 / 255, 76 / 255, 1)]
_TEXT_KEYS = ("textbox", "callout", "typewriter")
_MEASURE = ("m_distance", "m_perimeter", "m_area")


def _pdf_date(s: str) -> str:
    """D:20261021142000+09'00' → 2026-10-21 14:20."""
    s = (s or "").removeprefix("D:")
    if len(s) < 12 or not s[:12].isdigit():
        return ""
    return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}"


class PropsPanel(QWidget):
    changed = Signal(dict)       # 도구 기본 속성 바뀜
    applyToSel = Signal(dict)    # 고른 주석에 적용(A.update 인자)
    deleteSel = Signal()

    def __init__(self, props: dict, viewer=None, store: S.StyleStore | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("proppanel")
        self.setFixedWidth(260)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.props = props
        self.viewer = viewer
        self.store = store or S.store()
        self.key: str | None = None     # 지금 보이는 종류(도구 이름)
        self.sel = None                  # 고른 주석(없으면 도구 기본값)
        self._loading = False
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(300)
        self._timer.timeout.connect(self._apply_style)

        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(panel_head("속성"))
        # 옅은 회색 바탕 위에 쓰임새별 흰 카드. 창이 낮으면 스크롤
        body = QWidget(); body.setObjectName("propbody")
        lay = QVBoxLayout(body); lay.setContentsMargins(8, 6, 8, 8); lay.setSpacing(6)
        scroll = QScrollArea(); scroll.setWidget(body); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QWidget#propbody { background: transparent; }")
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll, 1)
        self.kind = QLabel(""); self.kind.setObjectName("dim"); self.kind.setWordWrap(True); lay.addWidget(self.kind)

        self.look_box, f = group_card("모양"); lay.addWidget(self.look_box); self.look = f
        sw = QWidget(); sl = QHBoxLayout(sw); sl.setContentsMargins(0, 0, 0, 0); sl.setSpacing(4)
        for c in SWATCHES:
            b = QToolButton(); b.setFixedSize(20, 20)
            b.setStyleSheet(f"QToolButton{{border:1px solid rgba(0,0,0,40); border-radius:3px; background:{from_rgb01(c).name()};}}")
            b.clicked.connect(lambda _=False, c=c: self._swatch(c)); sl.addWidget(b)
        sl.addStretch()
        self.swatches = sw; f.addRow("", sw)
        self.color = ColorButton((1, 0, 0)); f.addRow("색", self.color)
        self.border = ColorButton((1, 0, 0), allow_none=True); f.addRow("테두리색", self.border)
        self.fill = ColorButton(None, allow_none=True); f.addRow("채움색", self.fill)
        self.width = QDoubleSpinBox(); self.width.setRange(0, 12); self.width.setSingleStep(0.5); self.width.setDecimals(1)
        f.addRow("두께", self.width)
        self.dashes = QComboBox(); self.dashes.addItems(list(S.DASHES)); f.addRow("선 모양", self.dashes)
        op = QWidget(); ol = QHBoxLayout(op); ol.setContentsMargins(0, 0, 0, 0); ol.setSpacing(6)
        self.opacity = QSlider(Qt.Orientation.Horizontal); self.opacity.setRange(5, 100)
        self.op_label = QLabel("100%"); self.op_label.setMinimumWidth(34)
        ol.addWidget(self.opacity, 1); ol.addWidget(self.op_label)
        self.op_row = op; f.addRow("불투명도", op)
        self.fontsize = QDoubleSpinBox(); self.fontsize.setRange(5, 200); self.fontsize.setDecimals(1); f.addRow("글자 크기", self.fontsize)
        self.stamp_text = QComboBox(); self.stamp_text.setEditable(True); self.stamp_text.addItems(A.STAMP_TEXTS)
        self.stamp_text.setCurrentText(props.get("stamp_text", "승인")); f.addRow("스탬프 글자", self.stamp_text)
        self.unit = QComboBox(); self.unit.addItems(["cm", "mm", "in", "pt"]); self.unit.setCurrentText(props.get("measure_unit", "cm"))
        f.addRow("측정 단위", self.unit)
        self.reset_btn = QPushButton("처음 값으로"); self.reset_btn.clicked.connect(self._reset); lay.addWidget(self.reset_btn)

        self.info_box, f = group_card("정보"); lay.addWidget(self.info_box)
        self.author = QLineEdit(); f.addRow("작성자", self.author)
        self.subject = QLineEdit(); f.addRow("제목", self.subject)
        self.dates = QLabel(""); self.dates.setObjectName("dim"); f.addRow("", self.dates)
        self.content = QPlainTextEdit(); self.content.setPlaceholderText("주석 내용"); self.content.setMaximumHeight(80)
        f.addRow(self.content)
        self.apply_btn = QPushButton("내용·작성자 적용"); self.apply_btn.setObjectName("accent")
        self.apply_btn.clicked.connect(self._apply_info); lay.addWidget(self.apply_btn)
        self.del_btn = QPushButton("고른 주석 삭제"); self.del_btn.clicked.connect(self.deleteSel.emit); lay.addWidget(self.del_btn)
        lay.addStretch()
        self._align_labels(body)

        for w in (self.color, self.border, self.fill):
            w.clicked.connect(self._edited)
        self.width.valueChanged.connect(self._edited); self.fontsize.valueChanged.connect(self._edited)
        self.dashes.currentIndexChanged.connect(self._edited)
        self.opacity.valueChanged.connect(self._opacity_moved); self.opacity.sliderReleased.connect(self._edited)
        self.stamp_text.currentTextChanged.connect(self._extra); self.unit.currentTextChanged.connect(self._extra)
        if viewer is not None and hasattr(viewer, "toolChanged"):
            viewer.toolChanged.connect(self.tool_selected)
        self.show_selection(None)

    @staticmethod
    def _align_labels(body: QWidget):
        """카드마다 이름 칸 폭이 달라 입력칸이 들쭉날쭉하던 것을 가장 긴 이름에 맞춘다."""
        labels = [f.labelForField(f.itemAt(i, QFormLayout.ItemRole.FieldRole).widget())
                  for f in body.findChildren(QFormLayout) for i in range(f.rowCount())
                  if f.itemAt(i, QFormLayout.ItemRole.FieldRole)]
        labels = [l for l in labels if l is not None]
        w = max((l.sizeHint().width() for l in labels), default=0)
        for l in labels:
            l.setMinimumWidth(w)

    # ── 무엇을 보이나 ─────────────────────────────────────────
    def _tool(self) -> str:
        return getattr(self.viewer, "tool", "") if self.viewer is not None else ""

    def _tool_key(self) -> str | None:
        """지금 도구가 기본값을 가진 주석 도구면 그 이름. 측정 도구는 「m_…」 그대로."""
        t = self._tool()
        return t if t in S.DEFAULTS or t in _MEASURE else None

    def _fields(self) -> tuple[str, ...]:
        if self.key in _MEASURE:
            return ("unit",)
        fs = S.FIELDS.get(self.key, ())
        if self.sel is None:
            fs = tuple(x for x in fs if x not in S.SELECTED_ONLY)
        if self.key == "stamp":
            fs = ("stroke", "stamp_text") if self.sel is None else ("stroke", "opacity")
        return fs

    def show_selection(self, sel):
        annot = sel is not None and sel.kind == "annot"
        tool_key = self._tool_key()
        self.del_btn.setVisible(sel is not None and sel.kind in ("annot", "widget", "block", "image"))
        if annot and tool_key is None:
            self.sel = sel
            a = self._annot()
            self.key = S.key_of(self.viewer.doc, a) if a is not None else None
            style = S.style_of(self.viewer.doc, a, self.key) if a is not None else {}
            name = S.TOOL_NAMES.get(self.key) or sel.extra.get("kind_ko", "주석")
            self.kind.setText(f"{name} · 고른 주석")
            self._load(style)
            self._load_info(a)
        else:
            self.sel = None
            self.key = tool_key
            if tool_key:
                name = S.TOOL_NAMES.get(tool_key) or {"m_distance": "거리 측정", "m_perimeter": "둘레 측정",
                                                      "m_area": "영역 측정"}[tool_key]
                self.kind.setText(f"{name} · 새로 만들 때 쓰는 값")
                self._load(self.store.get(tool_key) if tool_key in S.DEFAULTS else {})
            else:
                self.kind.setText({"words": "글자 선택", "widget": "양식 칸", "block": "글자 덩어리", "image": "이미지"}.get(
                    getattr(sel, "kind", ""), "고른 것 없음"))
        self._layout_rows()

    def _layout_rows(self):
        fs = self._fields()
        main = next((x for x in ("color", "stroke", "text_color") if x in fs), None)
        rows = {self.swatches: main is not None, self.color: main is not None, self.border: "border" in fs,
                self.fill: "fill" in fs, self.width: "width" in fs, self.dashes: "dashes" in fs,
                self.op_row: "opacity" in fs, self.fontsize: "fontsize" in fs, self.stamp_text: "stamp_text" in fs,
                self.unit: "unit" in fs}
        for w, on in rows.items():
            self.look.setRowVisible(w, on)
        if main:
            self.look.labelForField(self.color).setText({"color": "색", "stroke": "선 색", "text_color": "글자색"}[main])
        if self.key in _TEXT_KEYS:
            self.look.labelForField(self.width).setText("테두리 두께")
            self.look.labelForField(self.fill).setText("바탕색")
        else:
            self.look.labelForField(self.width).setText("두께")
            self.look.labelForField(self.fill).setText("채움색")
        self.look_box.setVisible(any(rows.values()))
        self.reset_btn.setVisible(self.sel is None and self.key in S.DEFAULTS)
        self.info_box.setVisible(self.sel is not None)
        self.apply_btn.setVisible(self.sel is not None)

    def _annot(self):
        if self.sel is None or self.viewer is None:
            return None
        try:
            return A.get(self.viewer.doc, self.sel.page, self.sel.xref)
        except Exception:  # noqa: BLE001
            return None

    def _load(self, s: dict):
        self._loading = True
        try:
            main = s.get("color") or s.get("text_color") or s.get("stroke")
            self.color.color = tuple(main) if main else (1, 0, 0); self.color._paint()
            self.border.color = tuple(s["border"]) if s.get("border") else None; self.border._paint()
            self.fill.color = tuple(s["fill"]) if s.get("fill") else None; self.fill._paint()
            self.width.setValue(float(s.get("width", 1) or 0))
            d = tuple(s.get("dashes") or ())
            self.dashes.setCurrentIndex(next((i for i, v in enumerate(S.DASHES.values()) if v == d), 0))
            op = s.get("opacity", 1.0)
            self.opacity.setValue(int(round((1.0 if op is None or op < 0 else op) * 100)))
            self.op_label.setText(f"{self.opacity.value()}%")
            self.fontsize.setValue(float(s.get("fontsize", 14)))
        finally:
            self._loading = False

    def _load_info(self, a):
        info = a.info if a is not None else {}
        self.author.setText(info.get("title", ""))
        self.subject.setText(info.get("subject", ""))
        self.content.setPlainText(info.get("content", "") if a is not None else (self.sel.text or ""))
        made, mod = _pdf_date(info.get("creationDate", "")), _pdf_date(info.get("modDate", ""))
        self.dates.setText(" · ".join(x for x in (f"만듦 {made}" if made else "", f"고침 {mod}" if mod else "") if x))
        self.dates.setVisible(bool(made or mod))

    # ── 바꿀 때 ───────────────────────────────────────────────
    def _values(self) -> dict:
        """보이는 칸의 값을 그 종류의 칸 이름으로."""
        fs = self._fields()
        v: dict = {}
        c = self.color.color
        for k in ("color", "stroke", "text_color"):
            if k in fs:
                v[k] = c
        if "border" in fs:
            v["border"] = self.border.color
        if "fill" in fs:
            v["fill"] = self.fill.color
        if "width" in fs:
            v["width"] = self.width.value()
        if "dashes" in fs:
            v["dashes"] = S.DASHES[self.dashes.currentText()]
        if "opacity" in fs:
            v["opacity"] = self.opacity.value() / 100
        if "fontsize" in fs:
            v["fontsize"] = self.fontsize.value()
        return v

    def _swatch(self, c):
        self.color.color = tuple(c); self.color._paint()
        self._edited()

    def _opacity_moved(self, *_):
        self.op_label.setText(f"{self.opacity.value()}%")
        if not self.opacity.isSliderDown():  # 끄는 동안은 놓을 때 한 번만(되돌리기가 한 걸음씩 쌓이지 않게)
            self._edited()

    def _edited(self, *_):
        if self._loading or self.key is None:
            return
        if self.sel is not None:
            self._timer.start()
            return
        if self.key in S.DEFAULTS:
            self.store.remember(self.key, self._values())
            self._push_tool()

    def _push_tool(self):
        S.to_viewer_props(self.key, self.store.get(self.key), self.props)
        self.changed.emit(dict(self.props))

    def _extra(self, *_):
        self.props["stamp_text"] = self.stamp_text.currentText()
        self.props["measure_unit"] = self.unit.currentText()
        self.changed.emit(dict(self.props))

    def _reset(self):
        if self.key in S.DEFAULTS:
            self.store.reset(self.key)
            self._load(self.store.get(self.key))
            self._push_tool()

    def _apply_style(self):
        """고른 주석에 바로 적용하고, 그 종류의 기본값으로도 기억한다."""
        if self.sel is None:
            return
        v = self._values()
        d: dict = {"opacity": v.get("opacity")}
        main = v.get("color", v.get("stroke", v.get("text_color")))
        if main is not None:
            d["stroke"] = main
        if "fill" in v:
            d["fill"] = v["fill"] if v["fill"] is not None else ()
        if self.key == "areahl":
            d["fill"] = main
        for k in ("width", "fontsize", "border", "dashes"):
            if k in v:
                d[k] = v[k]
        self.applyToSel.emit(d)
        self.store.remember(self.key, v)

    def _apply_info(self):
        if self.sel is None:
            return
        self.applyToSel.emit({"content": self.content.toPlainText(), "author": self.author.text(),
                              "subject": self.subject.text()})

    # ── 창이 부름 ─────────────────────────────────────────────
    def tool_selected(self, tool: str):
        """도구를 고르면 그 종류의 기억해 둔 값을 뷰어 도구 속성에 얹는다."""
        if tool in S.DEFAULTS:
            S.to_viewer_props(tool, self.store.get(tool), self.props)
        self.show_selection(None if (tool in S.DEFAULTS or tool in _MEASURE) else self.sel)

    def remember(self, key: str, values: dict):
        """대화상자로 만든 주석(글상자 등)의 값을 그 종류의 기본값으로."""
        if self.store.remember(key, {k: v for k, v in values.items() if v is not None or k in ("fill", "border")}):
            S.to_viewer_props(key, self.store.get(key), self.props)

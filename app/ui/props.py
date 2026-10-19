"""오른쪽 속성 패널: 고른 주석의 색·두께·불투명도·내용, 또는 지금 도구의 기본 속성."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from ..engine import annots as A
from .dialogs import ColorButton
from .sidebar import group_card, panel_head


class PropsPanel(QWidget):
    changed = Signal(dict)       # 도구 기본 속성 바뀜
    applyToSel = Signal(dict)    # 고른 주석에 적용
    deleteSel = Signal()

    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("proppanel")
        self.setFixedWidth(260)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.props = props
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(panel_head("속성"))
        # 옅은 회색 바탕 위에 쓰임새별 흰 카드. 창이 낮으면 스크롤
        body = QWidget(); body.setObjectName("propbody")
        lay = QVBoxLayout(body); lay.setContentsMargins(8, 10, 8, 12); lay.setSpacing(10)
        scroll = QScrollArea(); scroll.setWidget(body); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QWidget#propbody { background: transparent; }")
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll, 1)
        self.kind = QLabel(""); self.kind.setObjectName("dim"); lay.addWidget(self.kind)

        box, f = group_card("선·채움"); lay.addWidget(box)
        self.stroke = ColorButton(props["stroke"], allow_none=True); f.addRow("선·글자 색", self.stroke)
        self.fill = ColorButton(props["fill"], allow_none=True); f.addRow("채움색", self.fill)
        self.width = QDoubleSpinBox(); self.width.setRange(0, 30); self.width.setValue(props["width"]); f.addRow("두께", self.width)
        self.opacity = QSlider(Qt.Orientation.Horizontal); self.opacity.setRange(5, 100); self.opacity.setValue(int(props["opacity"] * 100))
        f.addRow("불투명도", self.opacity)
        box, f = group_card("강조·글자"); lay.addWidget(box)
        self.hl = ColorButton(props["hl_color"]); f.addRow("강조색", self.hl)
        self.fontsize = QDoubleSpinBox(); self.fontsize.setRange(4, 200); self.fontsize.setValue(props["fontsize"]); f.addRow("글자 크기", self.fontsize)
        box, f = group_card("연필"); lay.addWidget(box)
        self.ink_color = ColorButton(props["ink_color"]); f.addRow("색", self.ink_color)
        self.ink_width = QDoubleSpinBox(); self.ink_width.setRange(0.5, 30); self.ink_width.setValue(props["ink_width"]); f.addRow("두께", self.ink_width)
        box, f = group_card("스탬프·측정"); lay.addWidget(box)
        self.stamp_text = QComboBox(); self.stamp_text.setEditable(True); self.stamp_text.addItems(A.STAMP_TEXTS)
        self.stamp_text.setCurrentText(props["stamp_text"]); f.addRow("스탬프 글자", self.stamp_text)
        self.unit = QComboBox(); self.unit.addItems(["cm", "mm", "in", "pt"]); self.unit.setCurrentText(props["measure_unit"]); f.addRow("측정 단위", self.unit)
        self.content = QPlainTextEdit(); self.content.setPlaceholderText("주석 내용"); self.content.setMaximumHeight(80); lay.addWidget(self.content)
        self.apply_btn = QPushButton("고른 주석에 적용"); self.apply_btn.setObjectName("accent")
        self.apply_btn.clicked.connect(self._apply); lay.addWidget(self.apply_btn)
        self.del_btn = QPushButton("고른 주석 삭제"); self.del_btn.clicked.connect(self.deleteSel.emit); lay.addWidget(self.del_btn)
        lay.addStretch()
        for w, sig in ((self.stroke, "clicked"), (self.fill, "clicked"), (self.hl, "clicked"), (self.ink_color, "clicked")):
            getattr(w, sig).connect(self._emit)
        self.width.valueChanged.connect(self._emit); self.opacity.valueChanged.connect(self._emit)
        self.fontsize.valueChanged.connect(self._emit); self.ink_width.valueChanged.connect(self._emit)
        self.stamp_text.currentTextChanged.connect(self._emit); self.unit.currentTextChanged.connect(self._emit)
        self.show_selection(None)

    def _emit(self, *_):
        d = {"stroke": self.stroke.color, "fill": self.fill.color, "hl_color": self.hl.color or (1, 1, 0),
             "width": self.width.value(), "opacity": self.opacity.value() / 100, "fontsize": self.fontsize.value(),
             "ink_width": self.ink_width.value(), "ink_color": self.ink_color.color or (0, 0, 1),
             "stamp_text": self.stamp_text.currentText(), "measure_unit": self.unit.currentText()}
        self.props.update(d)
        self.changed.emit(d)

    def show_selection(self, sel):
        has = sel is not None and sel.kind == "annot"
        self.apply_btn.setVisible(has); self.del_btn.setVisible(sel is not None and sel.kind in ("annot", "widget", "block", "image"))
        self.content.setVisible(has)
        if has:
            self.kind.setText(sel.extra.get("kind_ko", ""))
            cols = sel.extra.get("colors", {})
            self.stroke.color = tuple(cols["stroke"]) if cols.get("stroke") else None; self.stroke._paint()
            self.fill.color = tuple(cols["fill"]) if cols.get("fill") else None; self.fill._paint()
            self.width.blockSignals(True); self.width.setValue(float(sel.extra.get("width", 1) or 0)); self.width.blockSignals(False)
            op = sel.extra.get("opacity", 1.0); op = 1.0 if op is None or op < 0 else op
            self.opacity.blockSignals(True); self.opacity.setValue(int(op * 100)); self.opacity.blockSignals(False)
            self.content.setPlainText(sel.text or "")
        else:
            self.kind.setText("도구 기본값" if sel is None else {"words": "글자 선택", "widget": "양식 칸", "block": "글자 덩어리", "image": "이미지"}.get(sel.kind, ""))

    def _apply(self):
        self.applyToSel.emit({"stroke": self.stroke.color, "fill": self.fill.color, "width": self.width.value(),
                              "opacity": self.opacity.value() / 100, "content": self.content.toPlainText()})

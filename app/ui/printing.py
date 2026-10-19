"""인쇄: 미리보기가 있는 인쇄 창(PrintDialog)과 실제로 그려 보내는 일(send).

윈도우 기본 인쇄 창(QPrintDialog)은 앱과 모양이 다르고 크기 맞춤·홀짝·거꾸로·미리보기가 없어 앱 모양으로 짓는다.
보내기는 쪽을 프린터 해상도(최대 600dpi) 그림으로 떠서 그린다. 그리는 동안 진행 막대와 [그만두기] 를 보이고,
프린터를 못 열면 한국어로 알린다. 일괄 인쇄도 여기 send 로 보낸다(윈도우 「인쇄」 동작은 PDF 기본 앱에 따라
등록돼 있지 않아 늘 실패했다).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import fitz
from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPen, QPixmap
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QProgressDialog, QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import icons, theme

FITS = [("fit", "용지에 맞추기"), ("shrink", "큰 쪽만 줄이기"), ("actual", "실제 크기")]
ORIENTS = [("auto", "쪽 모양 따라"), ("portrait", "세로"), ("landscape", "가로")]
SUBSETS = [("all", "모든 쪽"), ("odd", "홀수 번째 쪽만"), ("even", "짝수 번째 쪽만")]
DUPLEX = [("none", "단면", QPrinter.DuplexMode.DuplexNone), ("long", "양면(긴 쪽 넘김)", QPrinter.DuplexMode.DuplexLongSide),
          ("short", "양면(짧은 쪽 넘김)", QPrinter.DuplexMode.DuplexShortSide)]
MAX_DPI = 600  # 그 이상은 글자가 더 좋아지지 않고 그림만 커진다


@dataclass
class PrintOptions:
    printer: str = ""
    pages: list[int] = field(default_factory=list)  # 0부터, 보낼 차례대로(홀짝·거꾸로 반영)
    copies: int = 1
    collate: bool = True
    fit: str = "fit"
    orient: str = "auto"
    paper: str = "A4"            # QPageSize 이름(다음에 열 때 고를 이름)
    page_size: object = None     # 프린터가 알려 준 QPageSize 그대로(드라이버 고유 용지도 맞게). 없으면 paper 이름으로 찾음
    duplex: str = "none"
    color: bool = True
    annots: bool = True
    to_file: str = ""            # 시험용: 이 경로로 PDF 를 쓴다(Qt 자체 PDF 출력)


# ── 계산 ─────────────────────────────────────────────────────────
def pick_pages(total: int, base: list[int], subset: str = "all", reverse: bool = False) -> list[int]:
    """고른 쪽들에서 홀수·짝수 번째만 남기고 차례를 정한다(손으로 양면 인쇄할 때 쓰는 고르기)."""
    pages = [i for i in base if 0 <= i < total]
    if subset == "odd":
        pages = pages[0::2]
    elif subset == "even":
        pages = pages[1::2]
    return pages[::-1] if reverse else pages


def placement(page_w: float, page_h: float, area_w: float, area_h: float, fit: str, auto_rotate: bool):
    """쪽(pt)을 인쇄 영역(pt)에 놓는 법: (돌릴 각도 0·90, 배율)."""
    rot = 0
    if auto_rotate and abs(page_w - page_h) > 1 and (page_w > page_h) != (area_w > area_h):
        rot = 90
        page_w, page_h = page_h, page_w
    s_fit = min(area_w / page_w, area_h / page_h)
    s = s_fit if fit == "fit" else min(1.0, s_fit) if fit == "shrink" else 1.0
    return rot, s


def paper_orientation(doc: fitz.Document, pages: list[int], orient: str) -> QPageLayout.Orientation:
    if orient == "landscape":
        return QPageLayout.Orientation.Landscape
    if orient == "portrait" or not pages:
        return QPageLayout.Orientation.Portrait
    r = doc[pages[0]].rect  # 자동: 첫 쪽 모양을 따르고, 모양이 다른 쪽은 돌려 앉힌다
    return QPageLayout.Orientation.Landscape if r.width > r.height else QPageLayout.Orientation.Portrait


def _page_image(doc: fitz.Document, i: int, zoom: float, rot: int, color: bool, annots: bool, lock=None) -> QImage:
    def grab():
        return doc[i].get_pixmap(matrix=fitz.Matrix(zoom, zoom).prerotate(rot), annots=annots,
                                 colorspace=fitz.csRGB if color else fitz.csGRAY)
    if lock is not None:
        with lock:
            pix = grab()
    else:
        pix = grab()
    fmt = QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_Grayscale8
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


# ── 보내기 ───────────────────────────────────────────────────────
def make_printer(opts: PrintOptions, doc: fitz.Document) -> QPrinter:
    p = QPrinter(QPrinter.PrinterMode.HighResolution)
    if opts.to_file and not opts.printer:
        p.setOutputFormat(QPrinter.OutputFormat.PdfFormat)  # Qt 자체 PDF
        p.setOutputFileName(opts.to_file)
    else:
        p.setPrinterName(opts.printer)
        if opts.to_file:
            p.setOutputFileName(opts.to_file)  # 윈도우 드라이버로 「파일로 인쇄」(시험: Microsoft Print to PDF 가 창 없이 씀)
    p.setPageSize(opts.page_size if isinstance(opts.page_size, QPageSize) else _page_size(opts.paper))
    p.setPageOrientation(paper_orientation(doc, opts.pages, opts.orient))
    p.setColorMode(QPrinter.ColorMode.Color if opts.color else QPrinter.ColorMode.GrayScale)
    p.setDuplex(next((m for k, _, m in DUPLEX if k == opts.duplex), QPrinter.DuplexMode.DuplexNone))
    return p


def send(parent, doc: fitz.Document, opts: PrintOptions, name: str, lock=None) -> str | None:
    """opts 대로 인쇄한다. 잘 보냈으면 None, 못 보냈으면 까닭(한국어), 그만뒀으면 「그만둠」."""
    if not opts.pages:
        return "인쇄할 쪽이 없습니다"
    if opts.printer and opts.printer not in QPrinterInfo.availablePrinterNames():
        return f"프린터를 찾지 못했습니다: {opts.printer}"
    printer = make_printer(opts, doc)
    printer.setDocName(name)
    # 드라이버가 여러 부를 못 받으면 쪽을 늘려 보낸다
    copies = max(1, opts.copies)
    if copies > 1 and printer.supportsMultipleCopies():
        printer.setCopyCount(copies); printer.setCollateCopies(opts.collate)
        seq = list(opts.pages)
    elif opts.collate:
        seq = list(opts.pages) * copies
    else:
        seq = [i for i in opts.pages for _ in range(copies)]
    painter = QPainter()
    if not painter.begin(printer):
        return "프린터를 열지 못했습니다(꺼져 있거나 연결이 끊겼는지 확인)"
    bar = None
    if parent is not None:
        bar = QProgressDialog("인쇄 준비 중", "그만두기", 0, len(seq), parent)
        bar.setWindowTitle("인쇄"); bar.setWindowModality(Qt.WindowModality.WindowModal); bar.setMinimumDuration(400)
        bar.setMinimumWidth(320)
    res = min(printer.resolution(), MAX_DPI)
    try:
        for n, i in enumerate(seq):
            if bar is not None:
                bar.setValue(n); bar.setLabelText(f"{n + 1} / {len(seq)}쪽 보내는 중")
                QApplication.processEvents()
                if bar.wasCanceled():
                    printer.abort()
                    return "그만둠"
            if n:
                printer.newPage()
            dev = printer.pageRect(QPrinter.Unit.DevicePixel)          # 인쇄 영역(장치 점)
            area = printer.pageRect(QPrinter.Unit.Point)               # 같은 영역(pt)
            pr = doc[i].rect
            rot, s = placement(pr.width, pr.height, area.width(), area.height(), opts.fit, opts.orient == "auto")
            img = _page_image(doc, i, s * res / 72, rot, opts.color, opts.annots, lock)
            w_pt, h_pt = (pr.height, pr.width) if rot else (pr.width, pr.height)
            k = dev.width() / area.width()                             # pt → 장치 점
            tw, th = w_pt * s * k, h_pt * s * k
            painter.drawImage(QRectF((dev.width() - tw) / 2, (dev.height() - th) / 2, tw, th), img)
    finally:
        painter.end()
        if bar is not None:
            bar.setValue(len(seq)); bar.close()
    return None


_STD_SIZES: dict[str, QPageSize] = {}


def _page_size(name: str) -> QPageSize:
    """표준 용지 이름 → QPageSize. 모르는 이름은 A4."""
    if not _STD_SIZES:
        for sid in QPageSize.PageSizeId:
            if sid != QPageSize.PageSizeId.Custom:
                ps = QPageSize(sid)
                if ps.isValid():
                    _STD_SIZES.setdefault(ps.name(), ps)
    return _STD_SIZES.get(name) or QPageSize(QPageSize.PageSizeId.A4)


# ── 미리보기 ─────────────────────────────────────────────────────
class Preview(QWidget):
    """종이 위에 쪽이 어떻게 앉는지 그린다(인쇄 영역·배율·돌림·흑백·주석까지 보내기와 같은 계산)."""

    def __init__(self, doc: fitz.Document, lock=None, parent=None):
        super().__init__(parent)
        self.doc, self.lock = doc, lock
        self.setMinimumSize(360, 440)
        self.page = -1
        self.paper = QSizeF(595, 842)      # pt
        self.area = QRectF(0, 0, 595, 842)  # 인쇄 영역(pt, 종이 기준)
        self.fit, self.auto, self.color, self.annots = "fit", True, True, True
        self._cache: dict[tuple, QImage] = {}

    def set_state(self, page: int, paper: QSizeF, area: QRectF, fit: str, auto: bool, color: bool, annots: bool):
        self.page, self.paper, self.area = page, paper, area
        self.fit, self.auto, self.color, self.annots = fit, auto, color, annots
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(theme.CUR["CANVAS"]))
        pad = 24
        k = min((self.width() - 2 * pad) / self.paper.width(), (self.height() - 2 * pad) / self.paper.height())
        pw, ph = self.paper.width() * k, self.paper.height() * k
        paper = QRectF((self.width() - pw) / 2, (self.height() - ph) / 2, pw, ph)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 28)); p.drawRect(paper.translated(2, 3))
        p.setBrush(QColor("#FFFFFF")); p.drawRect(paper)
        if 0 <= self.page < len(self.doc):
            area = QRectF(paper.x() + self.area.x() * k, paper.y() + self.area.y() * k, self.area.width() * k, self.area.height() * k)
            pr = self.doc[self.page].rect
            rot, s = placement(pr.width, pr.height, self.area.width(), self.area.height(), self.fit, self.auto)
            w_pt, h_pt = (pr.height, pr.width) if rot else (pr.width, pr.height)
            tw, th = w_pt * s * k, h_pt * s * k
            target = QRectF(area.x() + (area.width() - tw) / 2, area.y() + (area.height() - th) / 2, tw, th)
            dpr = self.devicePixelRatioF()
            key = (self.page, rot, round(tw * dpr), self.color, self.annots)
            img = self._cache.get(key)
            if img is None:
                img = _page_image(self.doc, self.page, max(0.05, s * k * dpr), rot, self.color, self.annots, self.lock)
                self._cache = {key: img}
            p.save(); p.setClipRect(paper)
            p.drawImage(target, img)
            p.restore()
            if self.area.width() < self.paper.width() - 1:  # 프린터가 못 찍는 가장자리
                p.setPen(QPen(QColor(theme.ACCENT), 1, Qt.PenStyle.DashLine)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.setOpacity(0.35); p.drawRect(area); p.setOpacity(1)
        p.setPen(QPen(QColor(theme.CUR["FIELD_LINE"]), 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(paper)
        p.end()


# ── 인쇄 창 ──────────────────────────────────────────────────────
class PrintDialog(QDialog):
    def __init__(self, parent, doc: fitz.Document, current: int, remember: dict | None = None, lock=None):
        super().__init__(parent)
        from .dialogs import PageRangeEdit

        self.setWindowTitle("인쇄")
        self.doc, self.lock = doc, lock
        r = dict(remember or {})
        root = QHBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # 왼쪽: 미리보기와 쪽 넘기기
        left = QWidget(); left.setObjectName("printleft"); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 12); ll.setSpacing(8)
        self.preview = Preview(doc, lock); ll.addWidget(self.preview, 1)
        nav = QHBoxLayout(); nav.addStretch()
        self.prev_btn = QToolButton(); self.prev_btn.setObjectName("quick"); self.prev_btn.setIcon(icons.icon("prev", 16))
        self.next_btn = QToolButton(); self.next_btn.setObjectName("quick"); self.next_btn.setIcon(icons.icon("next", 16))
        self.pos = QLabel(""); self.pos.setMinimumWidth(90); self.pos.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prev_btn.clicked.connect(lambda: self._step(-1)); self.next_btn.clicked.connect(lambda: self._step(1))
        nav.addWidget(self.prev_btn); nav.addWidget(self.pos); nav.addWidget(self.next_btn); nav.addStretch()
        ll.addLayout(nav)
        root.addWidget(left, 1)

        # 오른쪽: 설정
        right = QWidget(); right.setObjectName("printright"); right.setFixedWidth(340)
        right.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rl = QVBoxLayout(right); rl.setContentsMargins(14, 14, 14, 14); rl.setSpacing(10)
        from .sidebar import group_card

        def section(text):  # 옅은 회색 바탕 위 흰 카드 하나씩
            box, form = group_card(text); rl.addWidget(box)
            return form

        f = section("프린터")

        self.printer = QComboBox()
        names = QPrinterInfo.availablePrinterNames()
        self.printer.addItems(names)
        want = r.get("printer") if r.get("printer") in names else QPrinterInfo.defaultPrinterName()
        if want in names:
            self.printer.setCurrentText(want)
        f.addRow(self.printer)

        f = section("쪽")
        self.range = PageRangeEdit(len(doc), current); f.addRow(self.range)
        self.subset = QComboBox()
        for k, label in SUBSETS:
            self.subset.addItem(label, k)
        f.addRow("고르기", self.subset)
        self.reverse = QCheckBox("마지막 쪽부터"); f.addRow("", self.reverse)

        f = section("용지·크기")
        self.paper = QComboBox(); f.addRow("용지", self.paper)
        self.fit = QComboBox()
        for k, label in FITS:
            self.fit.addItem(label, k)
        self.fit.setCurrentIndex(max(0, self.fit.findData(r.get("fit", "fit"))))
        f.addRow("크기", self.fit)
        self.orient = QComboBox()
        for k, label in ORIENTS:
            self.orient.addItem(label, k)
        self.orient.setCurrentIndex(max(0, self.orient.findData(r.get("orient", "auto"))))
        f.addRow("방향", self.orient)

        f = section("매수·색")
        crow = QWidget(); ch = QHBoxLayout(crow); ch.setContentsMargins(0, 0, 0, 0); ch.setSpacing(10)
        self.copies = QSpinBox(); self.copies.setRange(1, 999); self.copies.setFixedWidth(80)
        self.collate = QCheckBox("한 부씩"); self.collate.setChecked(True)
        ch.addWidget(self.copies); ch.addWidget(self.collate); ch.addStretch()
        f.addRow("매수", crow)
        self.duplex = QComboBox(); f.addRow("양면", self.duplex)
        self.color = QComboBox(); f.addRow("색", self.color)
        self.annots = QCheckBox("주석·양식 칸도 인쇄"); self.annots.setChecked(r.get("annots", True)); f.addRow("", self.annots)

        rl.addStretch()
        self.summary = QLabel(""); self.summary.setObjectName("dim"); rl.addWidget(self.summary)
        self.err = QLabel(""); self.err.setStyleSheet(f"color:{theme.ACCENT};"); self.err.setWordWrap(True); rl.addWidget(self.err)
        brow = QHBoxLayout(); brow.addStretch()
        self.ok = QPushButton("인쇄"); self.ok.setDefault(True); self.ok.clicked.connect(self._accept)
        cancel = QPushButton("취소"); cancel.clicked.connect(self.reject)
        brow.addWidget(self.ok); brow.addWidget(cancel); rl.addLayout(brow)
        root.addWidget(right)

        self._remember = r
        self._idx = 0
        self._pages: list[int] = []
        self._printer_changed()
        self.printer.currentTextChanged.connect(self._printer_changed)
        for w in (self.subset, self.paper, self.fit, self.orient, self.duplex, self.color):
            w.currentIndexChanged.connect(self._refresh)
        for w in (self.reverse, self.annots, self.collate):
            w.toggled.connect(self._refresh)
        self.copies.valueChanged.connect(self._refresh)
        for w in (self.range.all, self.range.cur, self.range.rng):
            w.toggled.connect(self._refresh)
        self.range.edit.textChanged.connect(self._refresh)
        self.resize(900, 620)
        self._refresh()

    # 프린터가 바뀌면 그 프린터가 받는 용지·양면·색으로 다시 채운다
    def _printer_changed(self, *_):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = QPrinterInfo.printerInfo(self.printer.currentText())
            self._info = info
            self._sizes = {s.name(): s for s in info.supportedPageSizes()} or {"A4": _page_size("A4")}
            # 처음 열 때는 문서 첫 쪽과 같은 크기의 용지(B4 위클리면 B4)가 있으면 그것, 없으면 지난번 용지, 그다음 프린터 기본
            want_paper = self.paper.currentText() or self._doc_paper() or self._remember.get("paper") or info.defaultPageSize().name()
            self.paper.blockSignals(True); self.paper.clear()
            sizes = list(self._sizes)
            self.paper.addItems(sizes)
            self.paper.setCurrentText(want_paper if want_paper in sizes else (info.defaultPageSize().name() if info.defaultPageSize().name() in sizes else sizes[0]))
            self.paper.blockSignals(False)
            dmodes = set(info.supportedDuplexModes())
            want_dup = self.duplex.currentData() or self._remember.get("duplex", "none")
            self.duplex.blockSignals(True); self.duplex.clear()
            for k, label, m in DUPLEX:
                if k == "none" or m in dmodes:
                    self.duplex.addItem(label, k)
            idx = self.duplex.findData(want_dup); self.duplex.setCurrentIndex(max(0, idx)); self.duplex.blockSignals(False)
            cmodes = set(info.supportedColorModes())
            want_col = self.color.currentData()
            if want_col is None:
                want_col = self._remember.get("color", True)
            self.color.blockSignals(True); self.color.clear()
            if QPrinter.ColorMode.Color in cmodes or not cmodes:
                self.color.addItem("컬러", True)
            self.color.addItem("흑백", False)
            idx = self.color.findData(want_col); self.color.setCurrentIndex(max(0, idx)); self.color.blockSignals(False)
            # 인쇄 영역(종이 여백)은 그 프린터의 기본 여백으로
            pr = QPrinter(info, QPrinter.PrinterMode.HighResolution)
            m = pr.pageLayout().margins(QPageLayout.Unit.Point)
            self._margins = (m.left(), m.top(), m.right(), m.bottom())
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh()

    def _base_pages(self) -> list[int]:
        return self.range.pages()  # 범위 글이 잘못되면 ValueError

    def _refresh(self, *_):
        self.err.setText("")
        try:
            self._pages = pick_pages(len(self.doc), self._base_pages(), self.subset.currentData() or "all", self.reverse.isChecked())
        except ValueError as e:
            self._pages = []
            self.err.setText(str(e))
        self.ok.setEnabled(bool(self._pages))
        self._idx = min(self._idx, max(0, len(self._pages) - 1))
        # 종이(pt): 방향을 반영
        size = self._paper_size().size(QPageSize.Unit.Point)
        orient = paper_orientation(self.doc, self._pages, self.orient.currentData() or "auto")
        w, h = size.width(), size.height()
        if (orient == QPageLayout.Orientation.Landscape) != (w > h):
            w, h = h, w
        ml, mt, mr, mb = getattr(self, "_margins", (0, 0, 0, 0))
        if orient == QPageLayout.Orientation.Landscape:  # 여백도 같이 돈다
            ml, mt, mr, mb = mt, mr, mb, ml
        area = QRectF(ml, mt, max(10, w - ml - mr), max(10, h - mt - mb))
        page = self._pages[self._idx] if self._pages else -1
        self.preview.set_state(page, QSizeF(w, h), area, self.fit.currentData() or "fit",
                               (self.orient.currentData() or "auto") == "auto", bool(self.color.currentData()), self.annots.isChecked())
        n = len(self._pages)
        self.pos.setText(f"{self._idx + 1} / {n}" if n else "0 / 0")
        self.prev_btn.setEnabled(self._idx > 0); self.next_btn.setEnabled(self._idx < n - 1)
        dup = (self.duplex.currentData() or "none") != "none"
        sheets = ((n + 1) // 2 if dup else n) * self.copies.value()
        self.summary.setText(f"{n}쪽 · {self.copies.value()}부 · 종이 {sheets}장" if n else "")

    def _doc_paper(self) -> str | None:
        if not len(self.doc):
            return None
        r = self.doc[0].rect
        a, b = sorted((r.width, r.height))
        for name, s in self._sizes.items():
            sz = s.size(QPageSize.Unit.Point)
            x, y = sorted((sz.width(), sz.height()))
            if abs(x - a) < 4 and abs(y - b) < 4:
                return name
        return None

    def _paper_size(self) -> QPageSize:
        return getattr(self, "_sizes", {}).get(self.paper.currentText()) or _page_size(self.paper.currentText())

    def _step(self, d: int):
        self._idx = max(0, min(len(self._pages) - 1, self._idx + d))
        self._refresh()

    def _accept(self):
        if self._pages:
            self.accept()

    def options(self) -> PrintOptions:
        return PrintOptions(printer=self.printer.currentText(), pages=list(self._pages), copies=self.copies.value(),
                            collate=self.collate.isChecked(), fit=self.fit.currentData(), orient=self.orient.currentData(),
                            paper=self.paper.currentText(), page_size=self._paper_size(),
                            duplex=self.duplex.currentData() or "none",
                            color=bool(self.color.currentData()), annots=self.annots.isChecked())

    def remember(self) -> dict:
        """다음에 열 때 그대로 쓸 설정(쪽 범위·매수는 뺀다)."""
        o = self.options()
        return {"printer": o.printer, "fit": o.fit, "orient": o.orient, "paper": o.paper, "duplex": o.duplex,
                "color": o.color, "annots": o.annots}

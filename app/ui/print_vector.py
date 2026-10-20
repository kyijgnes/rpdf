"""인쇄를 벡터로: MuPDF 가 쪽을 그릴 때 내는 면·선·글자 윤곽·그림을 받아 QPainter(프린터)에 그대로 그린다.

예전에는 쪽마다 프린터 해상도(600dpi) 비트맵을 떠서 넘겼다. A4 한 장이 140MB 남짓이라 드라이버가 받아 스풀에
쓰는 데만 한 장에 1초 넘게 걸렸다. 벡터로 넘기면 스풀이 작고, 글자는 프린터 해상도 그대로 찍힌다.

투명도·소프트 마스크·그라데이션·패턴처럼 GDI 로 그대로 옮기기 어려운 것이 나오면 record() 가 None 을 돌려
부른 쪽이 그 쪽만 비트맵으로 그린다(겉모습이 틀리는 일은 없게). 스텐실·알파 그림은 아래가 흰 종이이거나 한 가지
색으로 덮여 있을 때만 그 색 위에 미리 섞어 불투명한 그림으로 넘긴다(스캔본이 흔히 이렇다).
"""
from __future__ import annotations

from contextlib import nullcontext

import fitz
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen, QTransform

mupdf = fitz.mupdf

_CAPS = {0: Qt.PenCapStyle.FlatCap, 1: Qt.PenCapStyle.RoundCap, 2: Qt.PenCapStyle.SquareCap, 3: Qt.PenCapStyle.SquareCap}
_JOINS = {0: Qt.PenJoinStyle.MiterJoin, 1: Qt.PenJoinStyle.RoundJoin, 2: Qt.PenJoinStyle.BevelJoin,
          3: Qt.PenJoinStyle.MiterJoin}
_INF = 1 << 30
UNIT = QRectF(0, 0, 1, 1)


class Unsupported(Exception):
    pass


def _qt(m) -> QTransform:
    return QTransform(m.a, m.b, m.c, m.d, m.e, m.f)


class _Walker(mupdf.FzPathWalker2):
    """fz_path → QPainterPath. 처음 만들 때 느려서(0.3초) 하나만 두고 돌려 쓴다."""

    def __init__(self):
        super().__init__()
        self.use_virtual_moveto(); self.use_virtual_lineto(); self.use_virtual_curveto(); self.use_virtual_closepath()
        self.path = QPainterPath()

    def moveto(self, ctx, x, y):
        self.path.moveTo(x, y)

    def lineto(self, ctx, x, y):
        self.path.lineTo(x, y)

    def curveto(self, ctx, x1, y1, x2, y2, x3, y3):
        self.path.cubicTo(x1, y1, x2, y2, x3, y3)

    def closepath(self, ctx):
        self.path.closeSubpath()


_walker: _Walker | None = None


def _path(path) -> QPainterPath:
    global _walker
    if _walker is None:
        _walker = _Walker()
    _walker.path = QPainterPath()
    mupdf.fz_walk_path(mupdf.FzPath(mupdf.ll_fz_keep_path(path)), _walker, _walker.m_internal)
    return _walker.path


def _samples(pix) -> bytes:
    return bytes(mupdf.fz_pixmap_samples_memoryview(pix))


class Glyphs(dict):
    """글자 윤곽(글꼴 크기 1)을 외워 둔다. 한 번 인쇄하는 동안만 쓴다.
    열쇠는 글꼴 주소라서, 그 글꼴을 붙잡아 두어 다른 글꼴이 같은 주소에 오지 않게 한다."""

    def get_path(self, font: mupdf.FzFont, gid: int) -> QPainterPath:
        key = (font.m_internal_value(), gid)
        got = self.get(key)
        if got is None:
            out = mupdf.fz_outline_glyph(font, gid, mupdf.FzMatrix())
            got = self[key] = (font, _path(out.m_internal) if out.m_internal else None)
        if got[1] is None:
            raise Unsupported("bitmap glyph")  # Type3 글꼴 등 윤곽이 없는 글자
        return got[1]


class _Recorder(mupdf.FzDevice2):
    """쪽을 그리는 명령을 모아 둔다(끝까지 다 받을 수 있을 때만 프린터에 그린다)."""

    def __init__(self, gray: bool, glyphs: Glyphs):
        super().__init__()
        for name in ("fill_path", "stroke_path", "clip_path", "clip_stroke_path", "fill_text", "stroke_text", "clip_text",
                     "clip_stroke_text", "ignore_text", "fill_shade", "fill_image", "fill_image_mask", "clip_image_mask",
                     "pop_clip", "begin_mask", "begin_group", "end_group", "begin_tile"):
            getattr(self, "use_virtual_" + name)()
        self.gray, self.glyphs = gray, glyphs
        self.ops: list[tuple] = []
        self.bad = ""
        # 투명한 그림을 불투명하게 미리 섞으려고, 이미 칠한 자리를 쪽 좌표로 적어 둔다
        self.clips: list[QPainterPath] = []
        self.marks: list[tuple] = []  # (테두리 QRectF, (면, 변환, 그때 오림들, 색) 또는 None)

    # ── 도우미 ──
    def _fail(self, why: str):
        if not self.bad:
            self.bad = why

    def _color(self, cs, color, alpha) -> QColor:
        if alpha < 0.999:
            raise Unsupported("alpha")
        if not cs:
            return QColor(0, 0, 0)
        rgb = mupdf.ll_fz_convert_color(cs, color, mupdf.FzColorspace(mupdf.FzColorspace.Fixed_RGB).m_internal, None,
                                        mupdf.FzColorParams().internal())
        r, g, b = (max(0, min(255, round(v * 255))) for v in rgb[:3])
        if self.gray:
            r = g = b = round(0.299 * r + 0.587 * g + 0.114 * b)
        return QColor(r, g, b)

    def _pen(self, stroke, color: QColor) -> QPen:
        pen = QPen(color, stroke.linewidth)
        pen.setCapStyle(_CAPS.get(stroke.start_cap, Qt.PenCapStyle.FlatCap))
        pen.setJoinStyle(_JOINS.get(stroke.linejoin, Qt.PenJoinStyle.MiterJoin))
        pen.setMiterLimit(stroke.miterlimit / 2)  # Qt 는 이음 점에서 잰다(선 굵기 절반 기준)
        if stroke.dash_len:
            w = stroke.linewidth if stroke.linewidth > 0 else 1.0
            v = [max(1e-3, mupdf.floats_getitem(stroke.dash_list, i) / w) for i in range(stroke.dash_len)]
            pen.setDashPattern(v * 2 if len(v) % 2 else v)
            pen.setDashOffset(stroke.dash_phase / w)
        return pen

    def _text_path(self, text) -> QPainterPath:
        """글자 덩어리 전체 윤곽(ctm 을 곱하기 전)."""
        out = QPainterPath()
        span = text.head
        while span:
            sp = mupdf.FzTextSpan(span)
            font, trm = sp.font(), sp.trm()
            for i in range(span.len):
                it = sp.items(i)
                if it.gid >= 0:
                    out.addPath(QTransform(trm.a, trm.b, trm.c, trm.d, it.x, it.y).map(self.glyphs.get_path(font, it.gid)))
            span = span.next
        out.setFillRule(Qt.FillRule.WindingFill)
        return out

    def _under(self, r: QRectF) -> QColor:
        """r 아래에 이미 칠해진 색. 흰 종이이거나 마지막에 한 가지 색으로 다 덮였을 때만 안다."""
        for c in self.clips:  # 오림 바깥은 어차피 안 찍힌다
            r = r & c.boundingRect()
        r = r.adjusted(0.01, 0.01, -0.01, -0.01)
        if r.isEmpty():
            return QColor(255, 255, 255)
        hit = [m for m in self.marks if m[0].intersects(r)]
        if not hit:
            return QColor(255, 255, 255)
        cover = hit[-1][1]
        if cover is not None:
            path, t, clips, color = cover
            if t.map(path).contains(r) and all(c.contains(r) for c in clips):
                return color
        raise Unsupported("transparent image over drawing")

    def _image(self, image, ctm, color: QColor | None) -> QImage:
        """그림 하나를 불투명한 QImage 로. color 가 있으면 스텐실(덮개만 있는 그림)을 그 색으로 칠한 것."""
        img = mupdf.FzImage(mupdf.ll_fz_keep_image(image))
        pix, _, _ = mupdf.fz_get_pixmap_from_image(img, mupdf.FzIrect(-_INF, -_INF, _INF, _INF),
                                                   mupdf.FzMatrix(img.w(), 0, 0, img.h(), 0, 0))
        if color is not None:
            if pix.n() != 1:
                raise Unsupported("image mask format")
            a = QImage(_samples(pix), pix.w(), pix.h(), pix.stride(), QImage.Format.Format_Alpha8).copy()
            top = QImage(pix.w(), pix.h(), QImage.Format.Format_ARGB32_Premultiplied)
            top.fill(color)
            top.setAlphaChannel(a)
            return self._flatten(top, ctm)
        want = mupdf.fz_device_gray() if self.gray and not pix.alpha() else mupdf.fz_device_rgb()
        if not pix.colorspace().m_internal or pix.colorspace().m_internal != want.m_internal:
            pix = mupdf.fz_convert_pixmap(pix, want, mupdf.FzColorspace(), mupdf.FzDefaultColorspaces(None),
                                          mupdf.FzColorParams(), 1)
        w, h, n, stride = pix.w(), pix.h(), pix.n(), pix.stride()
        if pix.alpha():  # 알파 그림(SMask): MuPDF 는 미리 곱한 값
            if n != 4:
                raise Unsupported("image alpha format")
            return self._flatten(QImage(_samples(pix), w, h, stride, QImage.Format.Format_RGBA8888_Premultiplied).copy(), ctm)
        fmt = QImage.Format.Format_Grayscale8 if n == 1 else QImage.Format.Format_RGB888
        if n not in (1, 3):
            raise Unsupported("image format")
        return QImage(_samples(pix), w, h, stride, fmt).copy()

    def _flatten(self, top: QImage, ctm) -> QImage:
        """투명한 그림을 아래 색 위에 미리 섞어 불투명하게(GDI 에 알파를 넘기면 Qt 가 그 둘레를 비트맵으로 만든다)."""
        out = QImage(top.width(), top.height(), QImage.Format.Format_RGB32)
        out.fill(self._under(_qt(ctm).mapRect(UNIT)))
        p = QPainter(out); p.drawImage(0, 0, top); p.end()
        return out.convertToFormat(QImage.Format.Format_Grayscale8) if self.gray else out

    def _fill(self, ctm, q: QPainterPath, color: QColor):
        t = _qt(ctm)
        self.marks.append((t.mapRect(q.controlPointRect()), (q, t, tuple(self.clips), color)))
        self.ops.append(("fill", t, q, color))

    def _stroke(self, ctm, q: QPainterPath, pen: QPen):
        t = _qt(ctm)
        w = max(pen.widthF(), 1.0) * max(abs(t.m11()) + abs(t.m21()), abs(t.m12()) + abs(t.m22()))
        self.marks.append((t.mapRect(q.controlPointRect()).adjusted(-w, -w, w, w), None))
        self.ops.append(("stroke", t, q, pen))

    def _clip(self, ctm, q: QPainterPath):
        t = _qt(ctm)
        self.clips.append(t.map(q))
        self.ops.append(("clip", t, q))

    def _picture(self, ctm, q: QImage):
        t = _qt(ctm)
        self.marks.append((t.mapRect(UNIT), None))
        self.ops.append(("image", t, q))

    def _guard(fn):
        def run(self, ctx, *a):
            if self.bad:
                return
            try:
                fn(self, *a)
            except Unsupported as e:
                self._fail(str(e))
            except Exception as e:  # noqa: BLE001  MuPDF 쪽으로 예외가 새면 안 된다
                self._fail(f"{type(e).__name__}: {e}")
        return run

    # ── MuPDF 가 부르는 것 ──
    @_guard
    def fill_path(self, path, even_odd, ctm, cs, color, alpha, cp):
        q = _path(path)
        q.setFillRule(Qt.FillRule.OddEvenFill if even_odd else Qt.FillRule.WindingFill)
        self._fill(ctm, q, self._color(cs, color, alpha))

    @_guard
    def stroke_path(self, path, stroke, ctm, cs, color, alpha, cp):
        self._stroke(ctm, _path(path), self._pen(stroke, self._color(cs, color, alpha)))

    @_guard
    def fill_text(self, text, ctm, cs, color, alpha, cp):
        self._fill(ctm, self._text_path(text), self._color(cs, color, alpha))

    @_guard
    def stroke_text(self, text, stroke, ctm, cs, color, alpha, cp):
        self._stroke(ctm, self._text_path(text), self._pen(stroke, self._color(cs, color, alpha)))

    @_guard
    def ignore_text(self, text, ctm):
        pass

    @_guard
    def clip_path(self, path, even_odd, ctm, scissor):
        q = _path(path)
        q.setFillRule(Qt.FillRule.OddEvenFill if even_odd else Qt.FillRule.WindingFill)
        self._clip(ctm, q)

    @_guard
    def clip_stroke_path(self, path, stroke, ctm, scissor):
        self._clip(ctm, QPainterPathStroker(self._pen(stroke, QColor(0, 0, 0))).createStroke(_path(path)))

    @_guard
    def clip_text(self, text, ctm, scissor):
        self._clip(ctm, self._text_path(text))

    @_guard
    def clip_stroke_text(self, text, stroke, ctm, scissor):
        self._clip(ctm, QPainterPathStroker(self._pen(stroke, QColor(0, 0, 0))).createStroke(self._text_path(text)))

    @_guard
    def pop_clip(self):
        if self.clips:
            self.clips.pop()
        self.ops.append(("pop",))

    @_guard
    def fill_image(self, image, ctm, alpha, cp):
        if alpha < 0.999:
            raise Unsupported("image alpha")
        self._picture(ctm, self._image(image, ctm, None))

    @_guard
    def fill_image_mask(self, image, ctm, cs, color, alpha, cp):
        self._picture(ctm, self._image(image, ctm, self._color(cs, color, alpha)))

    @_guard
    def fill_shade(self, *a):
        raise Unsupported("shade")

    @_guard
    def clip_image_mask(self, *a):
        raise Unsupported("clip image mask")

    @_guard
    def begin_mask(self, *a):
        raise Unsupported("soft mask")

    @_guard
    def begin_tile(self, *a):
        raise Unsupported("tile")

    @_guard
    def begin_group(self, area, cs, isolated, knockout, blendmode, alpha):
        if alpha < 0.999 or blendmode:
            raise Unsupported("group")

    @_guard
    def end_group(self):
        pass

    del _guard


def record(page: fitz.Page, annots: bool, gray: bool, glyphs: Glyphs | None = None, lock=None) -> list[tuple] | None:
    """쪽을 그리는 명령 목록(쪽 좌표 = page.rect 좌표). 벡터로 못 옮길 것이 있으면 None."""
    dev = _Recorder(gray, glyphs if glyphs is not None else Glyphs())
    with lock if lock is not None else nullcontext():
        run = mupdf.fz_run_page if annots else mupdf.fz_run_page_contents
        try:
            run(page.this, dev, mupdf.FzMatrix(), mupdf.FzCookie())
            mupdf.fz_close_device(dev)
        except Exception as e:  # noqa: BLE001
            dev._fail(str(e))
    return None if dev.bad else dev.ops


def _sign(v: float) -> int:
    return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)


def _square(t: QTransform) -> bool:
    """돌림이 0·90·180·270도뿐인가(뒤집기 포함)."""
    return (_sign(t.m12()) == 0 and _sign(t.m21()) == 0) or (_sign(t.m11()) == 0 and _sign(t.m22()) == 0)


def play(p: QPainter, ops: list[tuple], to_device: QTransform):
    """record() 로 모은 것을 to_device(쪽 좌표 → 장치 좌표) 아래에 그린다."""
    p.save()
    depth = 0
    try:
        for op in ops:
            kind = op[0]
            if kind == "pop":
                if depth:
                    p.restore(); depth -= 1
                continue
            t = op[1] * to_device
            if kind == "clip":
                p.save(); depth += 1
                p.setWorldTransform(t)
                p.setClipPath(op[2], Qt.ClipOperation.IntersectClip)
            elif kind == "image" and _square(t):
                # 직각으로만 돌거나 뒤집힌 그림은 미리 돌려 장치 좌표 네모에 똑바로 넣는다(드라이버는 늘이기만 한다)
                img = op[2]
                flip = QTransform(_sign(t.m11()), _sign(t.m12()), _sign(t.m21()), _sign(t.m22()), 0, 0)
                if not flip.isIdentity():
                    img = img.transformed(flip)
                r = t.mapRect(UNIT)
                if img.width() > r.width() * 1.1 and img.height() > r.height() * 1.1:  # 프린터 해상도보다 촘촘하면 줄인다
                    img = img.scaled(max(1, round(r.width())), max(1, round(r.height())),
                                     Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                p.setWorldTransform(QTransform())
                p.drawImage(r, img)
            else:
                p.setWorldTransform(t)
                if kind == "fill":
                    p.fillPath(op[2], QBrush(op[3]))
                elif kind == "stroke":
                    p.strokePath(op[2], op[3])
                else:
                    p.drawImage(UNIT, op[2])
    finally:
        while depth:
            p.restore(); depth -= 1
        p.restore()

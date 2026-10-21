"""주석 XFDF·FDF 내보내기·가져오기(다른 PDF 편집기·아크로뱃과 주고받는 꼴).

길: export_annots 자료(쪽 좌표) ⇄ PDF 좌표 기록(_Rec, 아래 칸 이름) ⇄ XFDF(XML) / FDF(PDF 문법).
가져오기는 결국 import_annots 와 같은 _import_one 으로 되살린다. 첨부 파일 주석은 파일 내용을 못 담아 뺀다.

_Rec 칸: kind(PDF 하위 종류) page rect color fill border opacity width dashes clouds title subject content
name date cdate quads line le vertices ink icon fontsize text_color rotate callout rd
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Iterable

import fitz

from .annots import _import_one, export_annots
from .document import Document

NS = "http://ns.adobe.com/xfdf/"
_XFDF_NAMES = {"Highlight": "highlight", "Underline": "underline", "StrikeOut": "strikeout", "Squiggly": "squiggly",
               "Square": "square", "Circle": "circle", "Line": "line", "Polygon": "polygon", "PolyLine": "polyline",
               "Ink": "ink", "FreeText": "freetext", "Text": "text", "Caret": "caret", "Redact": "redact"}
_KINDS = {v: k for k, v in _XFDF_NAMES.items()}
LE_NAMES = ["None", "Square", "Circle", "Diamond", "OpenArrow", "ClosedArrow", "Butt", "ROpenArrow", "RClosedArrow", "Slash"]


# ── 쪽 좌표 ⇄ PDF 좌표 ─────────────────────────────────────────────
def _to_pdf(page: fitz.Page):
    m = ~page.transformation_matrix
    return lambda q: fitz.Point(q) * m


def _to_page(page: fitz.Page):
    m = page.transformation_matrix
    return lambda q: fitz.Point(q) * m


def _rect(pts: Iterable, fn) -> list[float]:
    ps = [fn(p) for p in pts]
    xs, ys = [p.x for p in ps], [p.y for p in ps]
    return [min(xs), min(ys), max(xs), max(ys)]


def _corners(r) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = r
    return [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]


def _col(c):
    return [round(float(x), 4) for x in c] if c else None


def records(doc: Document) -> tuple[list[dict], int]:
    """문서 주석 → PDF 좌표 기록들. (기록, 뺀 수: 첨부 파일 등)."""
    out, skipped = [], 0
    for e in export_annots(doc):
        kind = e["type"]
        if kind not in _XFDF_NAMES:
            skipped += 1
            continue
        page = doc.fitz[e["page"]]
        fn = _to_pdf(page)
        info, cols, b = e.get("info") or {}, e.get("colors") or {}, e.get("border") or {}
        op = e.get("opacity")
        rec = {"kind": kind, "page": e["page"], "rect": _rect(_corners(e["rect"]), fn),
               "opacity": 1.0 if op is None or op < 0 else round(op, 3),
               "title": info.get("title", ""), "subject": info.get("subject", ""), "content": info.get("content", ""),
               "name": info.get("id", ""), "date": info.get("modDate", ""), "cdate": info.get("creationDate", "")}
        if b.get("width") is not None and b.get("width", -1) >= 0:
            rec["width"] = b["width"]
        if b.get("dashes"):
            rec["dashes"] = list(b["dashes"])
        if (b.get("clouds") or 0) > 0:
            rec["clouds"] = b["clouds"]
        if e.get("rd"):
            rec["rd"] = e["rd"]
        v = e.get("vertices")
        if kind == "FreeText":
            rec["fill"] = _col(cols.get("fill"))
            rec["text_color"] = _col(cols.get("stroke")) or [0, 0, 0]
            rec["border"] = _col(cols.get("border"))
            rec["fontsize"] = e.get("fontsize", 11)
            rec["rotate"] = e.get("rotate", 0)
            if e.get("callout"):
                rec["callout"] = [c for q in e["callout"] for c in fn(q)]
        else:
            rec["color"] = _col(cols.get("stroke"))
            rec["fill"] = _col(cols.get("fill"))
        if kind in ("Highlight", "Underline", "StrikeOut", "Squiggly") and v:
            rec["quads"] = [c for q in v for c in fn(q)]
        elif kind == "Line" and v:
            rec["line"] = [*fn(v[0]), *fn(v[-1])]
            le = e.get("line_ends") or (0, 0)
            rec["le"] = [LE_NAMES[x] if 0 <= x < len(LE_NAMES) else "None" for x in le]
        elif kind in ("Polygon", "PolyLine") and v:
            rec["vertices"] = [list(fn(q)) for q in v]
        elif kind == "Ink" and v:
            strokes = v if isinstance(v[0][0], (list, tuple)) else [v]
            rec["ink"] = [[list(fn(q)) for q in s] for s in strokes]
        if kind == "Text":
            rec["icon"] = e.get("icon") or "Note"
        out.append(rec)
    return out, skipped


def _entry(doc: Document, rec: dict) -> dict | None:
    """PDF 좌표 기록 → export_annots 꼴(가져오기에 넘길 것)."""
    kind, pno = rec.get("kind"), rec.get("page", -1)
    if kind not in _XFDF_NAMES or not isinstance(pno, int) or not 0 <= pno < doc.page_count:
        return None
    page = doc.fitz[pno]
    fn = _to_page(page)
    e = {"page": pno, "type": kind, "rect": _rect(_corners(rec["rect"]), fn),
         "info": {"content": rec.get("content", ""), "title": rec.get("title", ""), "subject": rec.get("subject", "")},
         "opacity": rec.get("opacity", 1.0), "border": {}}
    if "width" in rec:
        e["border"]["width"] = rec["width"]
    if rec.get("dashes"):
        e["border"]["dashes"] = rec["dashes"]
    if rec.get("clouds"):
        e["border"]["clouds"] = rec["clouds"]
    if rec.get("rd"):
        e["rd"] = rec["rd"]
    if kind == "FreeText":
        e["colors"] = {"stroke": rec.get("text_color") or [0, 0, 0], "fill": rec.get("fill"), "border": rec.get("border")}
        e["fontsize"] = rec.get("fontsize", 11)
        e["rotate"] = rec.get("rotate", 0)
        cl = rec.get("callout")
        if cl and len(cl) >= 4:
            e["callout"] = [list(fn((cl[k], cl[k + 1]))) for k in range(0, len(cl) - 1, 2)]
    else:
        e["colors"] = {"stroke": rec.get("color"), "fill": rec.get("fill")}
    q = rec.get("quads")
    if q:
        e["vertices"] = [list(fn((q[k], q[k + 1]))) for k in range(0, len(q) - 1, 2)]
    if rec.get("line"):
        x1, y1, x2, y2 = rec["line"][:4]
        e["vertices"] = [list(fn((x1, y1))), list(fn((x2, y2)))]
        e["line_ends"] = [LE_NAMES.index(n) if n in LE_NAMES else 0 for n in (rec.get("le") or ["None", "None"])[:2]]
    if rec.get("vertices"):
        e["vertices"] = [list(fn(p)) for p in rec["vertices"]]
    if rec.get("ink"):
        e["vertices"] = [[list(fn(p)) for p in s] for s in rec["ink"]]
    if kind == "Text":
        e["icon"] = rec.get("icon") or "Note"
    return e


def import_records(doc: Document, recs: list[dict], skipped: int = 0) -> tuple[int, int]:
    """기록들을 문서에 넣는다(되돌리기 한 걸음). (넣은 수, 못 넣은 수)."""
    doc.snapshot()
    n = 0
    with doc.lock:
        for rec in recs:
            try:
                e = _entry(doc, rec)
                ok = e is not None and _import_one(doc, e)
            except Exception:  # noqa: BLE001
                ok = False
            n += bool(ok)
            skipped += not ok
    return n, skipped


# ── XFDF ─────────────────────────────────────────────────────────
def _hex(c) -> str:
    return "#" + "".join(f"{round(max(0, min(1, x)) * 255):02X}" for x in c[:3])


def _unhex(s: str | None):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (s or "").strip())
    return [int(m.group(1)[k:k + 2], 16) / 255 for k in (0, 2, 4)] if m else None


def _nums(s: str | None) -> list[float]:
    return [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", s or "")]  # PDF 는 .8 처럼 씀


def _ints(xs: list[float]) -> list:
    """점선 길이는 정수로(PyMuPDF set_border 가 3.0 을 못 받아 조용히 실선이 된다)."""
    return [int(x) if float(x).is_integer() else x for x in xs]


def _fmt(xs: Iterable[float]) -> str:
    return ",".join(f"{x:.3f}".rstrip("0").rstrip(".") for x in xs)


def _da(rec: dict) -> str:
    """글상자 기본 모양 문자열. 테두리 색은 RG 로 같이 적는다(우리 가져오기가 읽음)."""
    tc = rec.get("text_color") or [0, 0, 0]
    s = f"{tc[0]:g} {tc[1]:g} {tc[2]:g} rg /Helv {rec.get('fontsize', 11):g} Tf"
    if rec.get("border"):
        b = rec["border"]
        s = f"{b[0]:g} {b[1]:g} {b[2]:g} RG " + s
    return s


def _read_da(da: str, rec: dict) -> None:
    m = re.search(r"([\d.]+)\s+Tf", da or "")
    if m:
        rec["fontsize"] = float(m.group(1))
    m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg\b", da or "")
    if m:
        rec["text_color"] = [float(x) for x in m.groups()]
    m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+RG", da or "")
    if m:
        rec["border"] = [float(x) for x in m.groups()]


def to_xfdf(doc: Document, pdf_name: str = "") -> tuple[bytes, int, int]:
    """(XFDF 바이트, 담은 수, 뺀 수)."""
    recs, skipped = records(doc)
    ET.register_namespace("", NS)
    root = ET.Element(f"{{{NS}}}xfdf", {"xml:space": "preserve"})
    if pdf_name:
        ET.SubElement(root, f"{{{NS}}}f", {"href": pdf_name})
    annots = ET.SubElement(root, f"{{{NS}}}annots")
    for r in recs:
        at = {"page": str(r["page"]), "rect": _fmt(r["rect"])}
        for k, x in (("title", "title"), ("subject", "subject"), ("name", "name"), ("date", "date"), ("cdate", "creationdate")):
            if r.get(k):
                at[x] = r[k]
        if r.get("color"):
            at["color"] = _hex(r["color"])
        if r.get("fill"):
            at["interior-color" if r["kind"] != "FreeText" else "color"] = _hex(r["fill"])
        if r.get("opacity", 1) < 1:
            at["opacity"] = f"{r['opacity']:g}"
        if "width" in r:
            at["width"] = f"{r['width']:g}"
        if r.get("dashes"):
            at["style"], at["dashes"] = "dash", _fmt(r["dashes"])
        if r.get("clouds"):
            at["style"], at["intensity"] = "cloudy", f"{r['clouds']:g}"
        if r.get("rd"):
            at["fringe"] = _fmt(r["rd"])
        if r.get("quads"):
            at["coords"] = _fmt(r["quads"])
        if r.get("line"):
            x1, y1, x2, y2 = r["line"]
            at["start"], at["end"] = _fmt((x1, y1)), _fmt((x2, y2))
            at["head"], at["tail"] = r["le"]
        if r["kind"] == "Text":
            at["icon"] = r["icon"]
        if r["kind"] == "FreeText":
            if r.get("rotate"):
                at["rotation"] = str(r["rotate"])
            if r.get("callout"):
                at["callout"], at["intent"] = _fmt(r["callout"]), "FreeTextCallout"
        el = ET.SubElement(annots, f"{{{NS}}}{_XFDF_NAMES[r['kind']]}", at)
        if r.get("content"):
            ET.SubElement(el, f"{{{NS}}}contents").text = r["content"]
        if r.get("vertices"):
            ET.SubElement(el, f"{{{NS}}}vertices").text = ";".join(_fmt(p) for p in r["vertices"])
        if r.get("ink"):
            il = ET.SubElement(el, f"{{{NS}}}inklist")
            for s in r["ink"]:
                ET.SubElement(il, f"{{{NS}}}gesture").text = ";".join(_fmt(p) for p in s)
        if r["kind"] == "FreeText":
            ET.SubElement(el, f"{{{NS}}}defaultappearance").text = _da(r)
    data = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")
    return data, len(recs), skipped


def parse_xfdf(data: bytes) -> tuple[list[dict], int]:
    """XFDF → 기록들. (기록, 모르는 종류 수). 이름공간이 없거나 달라도 읽는다."""
    root = ET.fromstring(data)
    tag = lambda el: el.tag.rsplit("}", 1)[-1].lower()  # noqa: E731
    annots = next((el for el in root.iter() if tag(el) == "annots"), None)
    if annots is None:
        return [], 0
    recs, unknown = [], 0
    for el in annots:
        kind = _KINDS.get(tag(el))
        if not kind:
            unknown += 1
            continue
        a = {k.rsplit("}", 1)[-1].lower(): v for k, v in el.attrib.items()}
        try:
            rec = {"kind": kind, "page": int(a.get("page", -1)), "rect": _nums(a.get("rect"))[:4],
                   "title": a.get("title", ""), "subject": a.get("subject", ""), "content": ""}
        except ValueError:
            unknown += 1
            continue
        if len(rec["rect"]) != 4:
            unknown += 1
            continue
        if kind == "FreeText":
            rec["fill"] = _unhex(a.get("color"))
            rec["rotate"] = int(_nums(a.get("rotation"))[0]) if a.get("rotation") else 0
            if a.get("callout"):
                rec["callout"] = _nums(a["callout"])
        else:
            rec["color"] = _unhex(a.get("color"))
            rec["fill"] = _unhex(a.get("interior-color"))
        if a.get("opacity"):
            rec["opacity"] = float(a["opacity"])
        if a.get("width"):
            rec["width"] = float(a["width"])
        if a.get("dashes"):
            rec["dashes"] = _ints(_nums(a["dashes"]))
        if a.get("style") == "cloudy":
            rec["clouds"] = int((_nums(a.get("intensity")) or [1])[0])
        if a.get("fringe"):
            rec["rd"] = _nums(a["fringe"])[:4]
        if a.get("coords"):
            rec["quads"] = _nums(a["coords"])
        if kind == "Line" and a.get("start") and a.get("end"):
            rec["line"] = _nums(a["start"])[:2] + _nums(a["end"])[:2]
            rec["le"] = [a.get("head", "None"), a.get("tail", "None")]
        if kind == "Text":
            rec["icon"] = a.get("icon", "Note")
        for ch in el:
            t = tag(ch)
            if t == "contents":
                rec["content"] = ch.text or ""
            elif t == "contents-richtext" and not rec["content"]:
                paras = [p for p in ch.iter() if tag(p) == "p"] or [ch]
                rec["content"] = "\n".join("".join(p.itertext()).strip() for p in paras)
            elif t == "vertices":
                n = _nums(ch.text)
                rec["vertices"] = [n[k:k + 2] for k in range(0, len(n) - 1, 2)]
            elif t == "inklist":
                rec["ink"] = [[n[k:k + 2] for k in range(0, len(n) - 1, 2)] for g in ch if (n := _nums(g.text))]
            elif t == "defaultappearance":
                _read_da(ch.text or "", rec)
        recs.append(rec)
    return recs, unknown


def import_xfdf(doc: Document, data: bytes) -> tuple[int, int]:
    recs, unknown = parse_xfdf(data)
    return import_records(doc, recs, unknown)


# ── FDF ──────────────────────────────────────────────────────────
def _s(x) -> str:
    return fitz.get_pdf_str(x)


def _arr(xs) -> str:
    return "[" + " ".join(f"{x:g}" for x in xs) + "]"


def to_fdf(doc: Document, pdf_name: str = "") -> tuple[bytes, int, int]:
    """(FDF 바이트, 담은 수, 뺀 수). 모양(AP)은 담지 않는다(받는 쪽이 다시 그린다)."""
    recs, skipped = records(doc)
    objs = []
    for r in recs:
        k = r["kind"]
        d = [f"/Type/Annot/Subtype/{k}/Page {r['page']}/Rect{_arr(r['rect'])}"]
        if k == "FreeText":
            if r.get("fill"):
                d.append(f"/C{_arr(r['fill'])}")
            d.append(f"/DA{_s(_da(r))}")
            if r.get("rotate"):
                d.append(f"/Rotate {r['rotate']}")
            if r.get("callout"):
                d.append(f"/IT/FreeTextCallout/CL{_arr(r['callout'])}")
        else:
            if r.get("color"):
                d.append(f"/C{_arr(r['color'])}")
            if r.get("fill"):
                d.append(f"/IC{_arr(r['fill'])}")
        if r.get("opacity", 1) < 1:
            d.append(f"/CA {r['opacity']:g}")
        if "width" in r or r.get("dashes"):
            bs = f"/W {r.get('width', 1):g}" + (f"/S/D/D{_arr(r['dashes'])}" if r.get("dashes") else "/S/S")
            d.append(f"/BS<<{bs}>>")
        if r.get("clouds"):
            d.append(f"/BE<</S/C/I {r['clouds']:g}>>")
        if r.get("rd"):
            d.append(f"/RD{_arr(r['rd'])}")
        for key, f in (("title", "T"), ("subject", "Subj"), ("content", "Contents"), ("name", "NM"), ("date", "M"),
                       ("cdate", "CreationDate")):
            if r.get(key):
                d.append(f"/{f}{_s(r[key])}")
        if r.get("quads"):
            d.append(f"/QuadPoints{_arr(r['quads'])}")
        if r.get("line"):
            d.append(f"/L{_arr(r['line'])}/LE[/{r['le'][0]}/{r['le'][1]}]")
        if r.get("vertices"):
            d.append(f"/Vertices{_arr([c for p in r['vertices'] for c in p])}")
        if r.get("ink"):
            d.append("/InkList[" + "".join(_arr([c for p in s for c in p]) for s in r["ink"]) + "]")
        if k == "Text":
            d.append(f"/Name/{r['icon']}")
        objs.append("<<" + "".join(d) + ">>")
    refs = " ".join(f"{i + 2} 0 R" for i in range(len(objs)))
    head = f"<</FDF<<{'/F' + _s(pdf_name) if pdf_name else ''}/Annots[{refs}]>>>>"
    body = [b"%FDF-1.2\n%\xe2\xe3\xcf\xd3\n"]
    for i, o in enumerate([head] + objs, start=1):
        body.append(f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1"))
    body.append(b"trailer\n<</Root 1 0 R>>\n%%EOF\n")
    return b"".join(body), len(recs), skipped


def parse_fdf(data: bytes) -> tuple[list[dict], int]:
    """FDF → 기록들. MuPDF 가 FDF 도 PDF 처럼 열어 준다(쪽은 0)."""
    f = fitz.open("pdf", data)
    try:
        t, v = f.xref_get_key(f.pdf_catalog(), "FDF/Annots")
        if t == "xref":
            v = f.xref_object(int(v.split()[0]))
        xs = [int(x) for x in re.findall(r"(\d+)\s+0\s+R", v or "")]
        recs, unknown = [], 0
        for x in xs:
            key = lambda k: f.xref_get_key(x, k)  # noqa: E731
            kind = key("Subtype")[1].lstrip("/")
            nums = lambda k: _nums(key(k)[1]) if key(k)[0] == "array" else []  # noqa: E731

            def text(k):
                tt, vv = key(k)
                if tt != "string":
                    return ""
                return vv
            if kind not in _XFDF_NAMES:
                unknown += 1
                continue
            try:
                page = int(key("Page")[1])
            except ValueError:
                unknown += 1
                continue
            rec = {"kind": kind, "page": page, "rect": nums("Rect")[:4], "title": text("T"), "subject": text("Subj"),
                   "content": text("Contents")}
            if kind == "FreeText":
                rec["fill"] = nums("C") or None
                _read_da(text("DA"), rec)
                if key("Rotate")[0] == "int":
                    rec["rotate"] = int(key("Rotate")[1])
                if nums("CL"):
                    rec["callout"] = nums("CL")
            else:
                rec["color"] = nums("C") or None
                rec["fill"] = nums("IC") or None
            if key("CA")[0] in ("float", "int"):
                rec["opacity"] = float(key("CA")[1])
            if key("BS/W")[0] in ("float", "int"):
                rec["width"] = float(key("BS/W")[1])
            if nums("BS/D"):
                rec["dashes"] = _ints(nums("BS/D"))
            if key("BE/S")[1] == "/C":
                rec["clouds"] = int(float(key("BE/I")[1] or 1))
            if nums("RD"):
                rec["rd"] = nums("RD")[:4]
            if nums("QuadPoints"):
                rec["quads"] = nums("QuadPoints")
            if kind == "Line" and nums("L"):
                rec["line"] = nums("L")[:4]
                rec["le"] = re.findall(r"/(\w+)", key("LE")[1]) or ["None", "None"]
            if kind in ("Polygon", "PolyLine") and nums("Vertices"):
                n = nums("Vertices")
                rec["vertices"] = [n[k:k + 2] for k in range(0, len(n) - 1, 2)]
            if kind == "Ink":
                rec["ink"] = [[n[k:k + 2] for k in range(0, len(n) - 1, 2)]
                              for s in re.findall(r"\[([^\[\]]*)\]", key("InkList")[1]) if (n := _nums(s))]
            if kind == "Text":
                rec["icon"] = key("Name")[1].lstrip("/") or "Note"
            if len(rec["rect"]) == 4:
                recs.append(rec)
            else:
                unknown += 1
        return recs, unknown
    finally:
        f.close()


def import_fdf(doc: Document, data: bytes) -> tuple[int, int]:
    recs, unknown = parse_fdf(data)
    return import_records(doc, recs, unknown)

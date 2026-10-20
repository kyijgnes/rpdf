"""문서 하나: 열기·저장·쪽 그림·글자·검색·되돌리기.

화면은 이 클래스만 부른다. fitz 객체는 밖으로 새지 않게 하되,
pages.py·annots.py 같은 엔진 형제 모듈은 `doc.fitz` 로 바로 다룬다.
"""
from __future__ import annotations

import math
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

import fitz  # PyMuPDF

MAX_UNDO = 40


class DocumentError(Exception):
    pass


def _replace(src: str, dst: str):
    """같은 폴더의 사본을 원본 자리에 한 번에 바꿔 끼운다. 다른 프로그램이 잠깐 잡고 있으면 몇 번 다시 해 본다."""
    for k in range(6):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if k == 5:
                raise DocumentError("다른 프로그램이 이 파일을 열고 있어 저장하지 못했습니다(원본은 그대로)") from None
            time.sleep(0.3)


def korean_font_name(page: fitz.Page, bold: bool = False) -> str:
    """쪽에 넣을 맑은 고딕의 글꼴 자원 이름. 저장할 때 글꼴을 쓴 글자만 남기므로(subset) 다시 연 문서의 같은 이름
    글꼴에는 새 글자가 없다. 그 이름을 쓰면 PyMuPDF 가 옛 글꼴을 다시 써서 빈 네모가 나오니 새 이름을 쓴다."""
    base = "malgunbd" if bold else "malgun"
    fonts = {f[4]: f[3] for f in page.get_fonts()}
    name, k = base, 1
    while name in fonts and re.match(r"[A-Z]{6}\+", fonts[name] or ""):
        k += 1
        name = f"{base}{k}"
    return name


def _text_rotation(page: fitz.Page, rect: fitz.Rect) -> int:
    """그 자리 글의 방향을 insert_text 의 rotate 값(0·90·180·270)으로. → 0, ↑ 90, ← 180, ↓ 270."""
    for b in page.get_text("dict", clip=rect)["blocks"]:
        for l in b.get("lines", []):
            dx, dy = l["dir"]
            return int(round(math.degrees(math.atan2(-dy, dx)) / 90)) * 90 % 360
    return 0


def del_keys(f: fitz.Document, xref: int, keys: Iterable[str]) -> None:
    """객체에서 열쇠를 지운다. xref_set_key(…, "null") 만 하면 「/열쇠 null」 로 남아 MuPDF 가 그 열쇠를 계속 본다."""
    for k in keys:
        f.xref_set_key(xref, k, "null")
    f.update_object(xref, re.sub(r"/[^\s/<>\[\]()]+\s+null(?=[\s/>\]])", "", f.xref_object(xref, compressed=True)))


def keep_copy(f: fitz.Document, password: str | None = None) -> fitz.Document:
    """열린 문서를 건드리지 않는 작업 사본. 암호·권한은 그대로(사본도 KEEP 으로 저장하면 같은 암호가 남는다).

    암호 문서를 encryption 없이 tobytes·save 하면 그 문서의 암호 정보가 떨어져 나가, 그 뒤의 KEEP 저장이
    암호도 내용도 없는 파일을 쓴다(10-19 2차 점검에서 확인). 그래서 열린 문서는 늘 KEEP 바이트로만 사본을 뜬다."""
    w = fitz.open("pdf", f.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))
    pw = password if password is not None else getattr(f, "_pdfapp_pw", None)
    if w.needs_pass and not w.authenticate(pw or ""):
        w.close()
        raise DocumentError("암호가 걸린 문서라 사본을 뜨지 못했습니다(열기 암호가 맞지 않음)")
    w._pdfapp_pw = pw
    return w


def plain_bytes(f: fitz.Document, **kw) -> bytes:
    """암호를 푼 바이트. 열린 문서 자체를 encryption 없이 쓰면 그 문서가 망가지므로 사본에서 푼다."""
    if not (f.metadata or {}).get("encryption"):
        return f.tobytes(**kw)
    w = keep_copy(f)
    try:
        return w.tobytes(**kw)
    finally:
        w.close()


def redact_only(page: fitz.Page, rects: Iterable[fitz.Rect], fill=(1, 1, 1), **kw):
    """이 자리들만 지운다. apply_redactions 는 쪽에 걸린 교정 표시를 모두 적용하므로,
    사용자가 해 둔 교정 표시는 잠시 걷었다가 그대로 다시 단다."""
    keep = []
    for a in list(page.annots(types=[fitz.PDF_ANNOT_REDACT])):
        keep.append((fitz.Rect(a.rect), a.colors.get("fill")))
        page.delete_annot(a)
    for r in rects:
        page.add_redact_annot(r, fill=fill)
    page.apply_redactions(**kw)
    for r, f in keep:
        page.add_redact_annot(r, fill=f).update()


@dataclass
class SearchHit:
    page: int
    rect: fitz.Rect          # 첫 줄 자리
    text: str
    rects: list[fitz.Rect] = field(default_factory=list)  # 줄을 건너면 줄마다 하나
    context: str = ""        # 찾은 글자 앞뒤(결과 목록에 보임)

    def all_rects(self) -> list[fitz.Rect]:
        return self.rects or [self.rect]


def search_pattern(needle: str, regex: bool = False, case: bool = False, whole_word: bool = False) -> re.Pattern:
    """찾을 글자 → 정규식. 띄어쓰기는 줄바꿈·여러 칸도 받는다(줄을 건너는 검색어). 낱말 단위는 앞뒤가 글자·숫자가 아닐 때만
    (낱말 끝의 쉼표·마침표는 괜찮다)."""
    pat = needle if regex else r"\s+".join(re.escape(p) for p in needle.split())
    if whole_word:
        pat = rf"(?<!\w)(?:{pat})(?!\w)"
    return re.compile(pat, 0 if case else re.IGNORECASE)


# 글자만 읽는 flags. get_text("dict"/"rawdict") 의 기본값은 그림 데이터까지 뽑아, 수식 그림이 많은 한글 PDF 쪽은
# 한 쪽에 80~130ms 가 들었다(그림을 빼면 2~5ms, 10-20 측정).
TEXT_ONLY = fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES


def find_text(page: fitz.Page, rx: re.Pattern) -> list[tuple[str, list[fitz.Rect]]]:
    """쪽 글자에서 찾는다. 한 건 = (찾은 글자, 줄마다 네모). 줄은 띄어쓰기 하나로 이어 붙여 줄을 건너는 글도 한 건으로 잡는다.
    search_for 는 줄을 건너면 줄마다 따로 돌려줘 한 건이 두 건이 되고, 바꾸기가 두 번 들어갔다."""
    return [(t, rs) for t, rs, _ in find_text_ctx(page, rx)]


def find_text_ctx(page: fitz.Page, rx: re.Pattern, around: int = 30) -> list[tuple[str, list[fitz.Rect], str]]:
    """find_text 에 앞뒤 글자를 붙인 것. 결과 목록용 앞뒤 글자를 건마다 get_textbox 로 뽑으면 건당 40ms 가 들었다."""
    tp = page.get_textpage(flags=TEXT_ONLY)
    if not rx.search(" ".join(page.get_text("text", textpage=tp).split())):
        return []
    chars: list[str] = []
    where: list[tuple[int, tuple] | None] = []   # 글자 자리는 튜플로 둔다(글자마다 fitz.Rect 를 만들면 쪽마다 수천 번)
    line_no = 0
    for b in page.get_text("rawdict", textpage=tp)["blocks"]:
        for ln in b.get("lines", []):
            if chars:
                chars.append(" "); where.append(None)
            for sp in ln["spans"]:
                for ch in sp["chars"]:
                    chars.append(ch["c"]); where.append((line_no, ch["bbox"]))
            line_no += 1
    text = "".join(chars)
    out = []
    for m in rx.finditer(text):
        if m.end() <= m.start():
            continue
        lines: dict[int, fitz.Rect] = {}
        for k in range(m.start(), m.end()):
            if where[k] is not None:
                n, r = where[k]
                lines[n] = lines[n] | fitz.Rect(r) if n in lines else fitz.Rect(r)
        if lines:
            ctx = text[max(0, m.start() - around):m.end() + around]
            out.append((m.group(0), [lines[n] for n in sorted(lines)], " ".join(ctx.split())))
    return out


@dataclass
class Bookmark:
    level: int
    title: str
    page: int  # 0-based, -1 이면 자리 없음
    children: list["Bookmark"] = field(default_factory=list)
    dest: dict | None = None  # 쪽 안 자리·확대·글자 색(get_toc(simple=False) 의 넷째 칸). 없으면 쪽 맨 위


def toc_entries(f: fitz.Document, page_offset: int = 0) -> list[list]:
    """북마크를 쪽 안 자리까지 담아 set_toc 에 그대로 넣을 수 있는 모양으로. 이름만 넣는 간단 목록으로 다시 쓰면
    모든 북마크가 쪽 맨 위로 바뀌던 것(10-19 점검)."""
    out = []
    for e in f.get_toc(simple=False):
        lvl, title, pno = e[0], e[1], e[2]
        d = dict(e[3]) if len(e) > 3 and isinstance(e[3], dict) else {}
        keep = {k: d[k] for k in ("to", "zoom", "color", "bold", "italic", "collapse") if k in d}
        pno = pno + page_offset if pno > 0 else pno
        if d.get("kind") == fitz.LINK_GOTO and pno > 0:
            out.append([lvl, title, pno, {"kind": fitz.LINK_GOTO, **keep}])
        else:
            out.append([lvl, title, pno])
    return out


def _unmangle(s: str) -> str:
    """PyMuPDF 가 UTF-8 글자열을 낱바이트로 돌려준 것(한글 첨부 이름이 라틴 글자로 깨진 것)을 되살린다."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


class Document:
    """열린 PDF 하나. 모든 바꾸기는 `snapshot()` 뒤에 한다(되돌리기)."""

    def __init__(self, path: str | None = None, password: str | None = None):
        self.path: str | None = None
        self.fitz: fitz.Document
        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        self.modified = False
        self.lock = threading.RLock()
        self.password = password
        self.hidden_layers: set[str] = set()  # 화면에서 끈 레이어 이름(보기 설정, 파일은 그대로)
        self.dedupe = False  # 다른 PDF 를 끼웠다: 저장할 때 같은 객체를 합친다(garbage=3)
        if path:
            self._open(path, password)
        else:
            self.fitz = fitz.open()
            self.fitz.new_page(width=595, height=842)

    # ── 열고 닫기 ──────────────────────────────────────────────
    def _open(self, path: str, password: str | None):
        if not os.path.exists(path):
            raise DocumentError(f"파일이 없습니다: {path}")
        try:
            txt = os.path.splitext(path)[1].lower() == ".txt"
            if txt:
                # MuPDF 의 txt 열기는 UTF-8 로만 읽고 한글 글꼴이 없다. CP949 도 읽어 맑은 고딕으로 흘린다
                from .convert import decode_text, text_to_pdf_bytes
                with open(path, "rb") as f:
                    d = fitz.open("pdf", text_to_pdf_bytes(decode_text(f.read())))
            else:
                d = fitz.open(path)
            if d.is_pdf and not txt:
                # 파일을 잡고 열면 저장 때 바꿔 끼우기(os.replace)가 막혀 원본을 제자리에서 덮어쓰게 된다. 메모리로 연다.
                d.close()
                with open(path, "rb") as f:
                    d = fitz.open("pdf", f.read())
        except Exception as e:  # noqa: BLE001
            raise DocumentError(f"열 수 없는 파일입니다 ({e})") from e
        if d.needs_pass:
            if password is None or not d.authenticate(password):
                d.close()
                raise NeedsPassword(path)
        d._pdfapp_pw = password  # 사본을 뜰 때 같은 암호로 푼다(keep_copy)
        if not d.is_pdf:
            # 이미지·epub·xps 등은 PDF 로 바꿔 연다
            pdfbytes = d.convert_to_pdf()
            d.close()
            d = fitz.open("pdf", pdfbytes)
        if d.page_count == 0:
            d.close()
            raise DocumentError("쪽이 하나도 없는(깨진) 파일입니다")
        self.fitz = d
        self.path = path

    def _load(self, data: bytes) -> fitz.Document:
        """저장·되돌리기 뒤 바이트에서 다시 연다. 암호 문서는 열 때 쓴 암호로 다시 푼다."""
        d = fitz.open("pdf", data)
        if d.needs_pass and self.password:
            d.authenticate(self.password)
        d._pdfapp_pw = self.password
        self._apply_layers(d)
        return d

    @classmethod
    def from_bytes(cls, data: bytes, name: str | None = None) -> "Document":
        self = cls.__new__(cls)
        self.path = name
        self.fitz = fitz.open("pdf", data)
        self._undo, self._redo = [], []
        self.modified = True
        self.lock = threading.RLock()
        self.password = None
        self.hidden_layers = set()
        self.dedupe = False
        return self

    @classmethod
    def blank(cls, width: float = 595, height: float = 842, count: int = 1) -> "Document":
        self = cls.__new__(cls)
        self.path = None
        self.fitz = fitz.open()
        for _ in range(count):
            self.fitz.new_page(width=width, height=height)
        self._undo, self._redo = [], []
        self.modified = True
        self.lock = threading.RLock()
        self.password = None
        self.hidden_layers = set()
        self.dedupe = False
        return self

    def close(self):
        with self.lock:
            try:
                self.fitz.close()
            except Exception:  # noqa: BLE001
                pass

    @property
    def name(self) -> str:
        return os.path.basename(self.path) if self.path else "제목 없음.pdf"

    @property
    def page_count(self) -> int:
        return self.fitz.page_count

    def page(self, i: int) -> fitz.Page:
        return self.fitz[i]

    def page_size(self, i: int) -> tuple[float, float]:
        r = self.fitz[i].rect
        return r.width, r.height

    # ── 저장 ──────────────────────────────────────────────────
    def save(self, path: str | None = None, incremental: bool = False):
        """사본에 쓰고 바꿔 끼운다. 저장 중 튕겨도 원본이 안 깨진다."""
        target = path or self.path
        if not target:
            raise DocumentError("저장할 이름이 없습니다")
        with self.lock:
            fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(os.path.abspath(target)) or None)
            os.close(fd)
            try:
                try:
                    self.fitz.subset_fonts()  # 글자 하나만 넣어도 맑은 고딕 통째(7MB 넘게)가 실리지 않게
                except Exception:  # noqa: BLE001
                    pass
                # 열 때의 암호·권한을 그대로 둔다(그냥 저장하면 암호가 풀린다).
                # garbage=3(같은 객체 합치기)은 스캔 376쪽에서 1.3초 걸리고 크기는 0.04% 줄 뿐이라, 다른 PDF 를 끼웠을 때만 쓴다.
                # 평소엔 2(안 쓰는 것 지우고 번호 다시 매김): 1 과 빠르기는 같고 파일이 1.5% 작다
                self.fitz.save(tmp, garbage=3 if self.dedupe else 2, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP)
                # 저장 뒤에도 계속 편집할 수 있게 다시 연다
                with open(tmp, "rb") as f:
                    data = f.read()
                _replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
            self.fitz.close()
            self.fitz = self._load(data)
            self.path = target
            self.modified = False
            self.dedupe = False

    def to_bytes(self) -> bytes:
        with self.lock:
            return self.fitz.tobytes(garbage=1, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP)

    def copy(self) -> fitz.Document:
        """일꾼 스레드·변환에 넘길 사본(보는 문서는 그리는 일꾼이 같이 쓰고, 암호 문서는 그냥 쓰면 망가진다)."""
        with self.lock:
            return keep_copy(self.fitz, self.password)

    def adopt(self, f: fitz.Document):
        """일꾼이 사본(copy())에서 고친 결과를 이 문서로 바꿔 끼운다. 되돌리기 사본을 먼저 뜬다."""
        self.snapshot()
        with self.lock:
            old = self.fitz
            self._apply_layers(f)
            self.fitz = f
            old.close()

    # ── 되돌리기 ───────────────────────────────────────────────
    def snapshot(self):
        """바꾸기 직전에 부른다."""
        with self.lock:
            self._undo.append(self.fitz.tobytes(garbage=0, deflate=False, encryption=fitz.PDF_ENCRYPT_KEEP))
            if len(self._undo) > MAX_UNDO:
                self._undo.pop(0)
            self._redo.clear()
            self.modified = True

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def _swap(self, data: bytes) -> bytes:
        cur = self.fitz.tobytes(garbage=0, deflate=False, encryption=fitz.PDF_ENCRYPT_KEEP)
        self.fitz.close()
        self.fitz = self._load(data)
        self.modified = True
        return cur

    def undo(self) -> bool:
        with self.lock:
            if not self._undo:
                return False
            self._redo.append(self._swap(self._undo.pop()))
            return True

    def redo(self) -> bool:
        with self.lock:
            if not self._redo:
                return False
            self._undo.append(self._swap(self._redo.pop()))
            return True

    # ── 그리기 ────────────────────────────────────────────────
    def render(self, i: int, zoom: float = 1.0, clip: fitz.Rect | None = None,
               annots: bool = True, alpha: bool = False) -> fitz.Pixmap:
        with self.lock:
            page = self.fitz[i]
            mat = fitz.Matrix(zoom, zoom)
            return page.get_pixmap(matrix=mat, clip=clip, annots=annots, alpha=alpha)

    def render_png(self, i: int, zoom: float = 1.0) -> bytes:
        return self.render(i, zoom).tobytes("png")

    # ── 글자 ──────────────────────────────────────────────────
    def words(self, i: int) -> list[tuple]:
        """(x0,y0,x1,y1,word,block,line,wordno)"""
        with self.lock:
            return self.fitz[i].get_text("words")

    def text(self, i: int) -> str:
        with self.lock:
            return self.fitz[i].get_text("text")

    def text_in_rect(self, i: int, rect: fitz.Rect) -> str:
        with self.lock:
            return self.fitz[i].get_textbox(rect)

    def text_blocks(self, i: int) -> list[dict]:
        """글자 덩어리(type 0)와 그림 자리(type 1, bbox 만). 그림 데이터까지 뽑는 기본 flags 는 한 쪽에 75ms 가 들어
        편집 모드에서 마우스를 움직일 때마다 끊겼다. 그림 자리는 get_image_info 로 따로 받는다."""
        with self.lock:
            page = self.fitz[i]
            blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)["blocks"]
            blocks += [{"type": 1, "bbox": tuple(im["bbox"])} for im in page.get_image_info()]
            return blocks

    def has_text(self, i: int) -> bool:
        return bool(self.text(i).strip())

    def search(self, needle: str, pages: Iterable[int] | None = None,
               case: bool = False, whole_word: bool = False,
               progress: Callable[[int, int], None] | None = None) -> list[SearchHit]:
        hits: list[SearchHit] = []
        if not needle:
            return hits
        rng = list(pages) if pages is not None else range(self.page_count)
        total = len(rng)
        rx = search_pattern(needle, case=case, whole_word=whole_word)
        for n, i in enumerate(rng):
            with self.lock:  # 쪽마다 잡는다(일꾼에서 찾는 동안에도 화면 그리기가 사이사이 들어오게)
                for text, rects, ctx in find_text_ctx(self.fitz[i], rx):
                    hits.append(SearchHit(i, rects[0], text, rects, ctx))
            if progress:
                progress(n + 1, total)
        return hits

    def replace_text(self, hits: list[SearchHit], replacement: str, fontsize: float | None = None) -> int:
        """찾은 자리를 교정(흰 칠)하고 새 글자를 얹는다. 글꼴은 맑은 고딕."""
        from .fonts import korean_fontfile
        if not hits:
            return 0
        self.snapshot()
        by_page: dict[int, list[SearchHit]] = {}
        for h in hits:
            by_page.setdefault(h.page, []).append(h)
        n = 0
        with self.lock:
            for i, hs in by_page.items():
                page = self.fitz[i]
                rots = [_text_rotation(page, h.rect) for h in hs]  # 지우기 전에 원래 글 방향을 읽어 둔다
                # 줄을 건너는 한 건은 줄마다 지우고 새 글자는 첫 줄 자리에 한 번만 쓴다
                redact_only(page, [r for h in hs for r in h.all_rects()], fill=(1, 1, 1), images=fitz.PDF_REDACT_IMAGE_NONE)
                for h, rot in zip(hs, rots):
                    # 글 방향 틀로 옮겨 줄 높이·시작점을 잡고 다시 쪽 좌표로 되돌린다(세로로 누운 글도 그 방향 그대로)
                    lr = fitz.Rect(h.rect) * fitz.Matrix(rot)
                    lr.normalize()
                    fs = fontsize or max(6.0, lr.height * 0.8)
                    pt = fitz.Point(lr.x0, lr.y1 - fs * 0.22) * fitz.Matrix(-rot)
                    page.insert_text(pt, replacement, fontsize=fs, fontname=korean_font_name(page),
                                     fontfile=korean_fontfile(), rotate=rot)
                    n += 1
        return n

    # ── 책갈피 ─────────────────────────────────────────────────
    def bookmarks(self) -> list[Bookmark]:
        root: list[Bookmark] = []
        stack: list[Bookmark] = []
        for e in toc_entries(self.fitz):
            bm = Bookmark(e[0], e[1], e[2] - 1, dest=e[3] if len(e) > 3 else None)
            while stack and stack[-1].level >= bm.level:
                stack.pop()
            (stack[-1].children if stack else root).append(bm)
            stack.append(bm)
        return root

    def set_bookmarks(self, items: list[Bookmark]):
        self.snapshot()
        flat: list[list] = []

        def walk(nodes: list[Bookmark], lvl: int):
            for b in nodes:
                flat.append([lvl, b.title, b.page + 1] + ([b.dest] if b.dest and b.page >= 0 else []))
                walk(b.children, lvl + 1)
        walk(items, 1)
        with self.lock:
            self.fitz.set_toc(flat)

    def bookmark_y(self, b: Bookmark) -> float | None:
        """북마크가 가리키는 쪽 안 높이(보이는 방향, 쪽 위에서 pt). 화면을 그 자리로 옮길 때."""
        to = (b.dest or {}).get("to")
        if to is None or not 0 <= b.page < self.page_count:
            return None
        return max(0.0, (fitz.Point(to) * self.fitz[b.page].rotation_matrix).y)

    def flat_toc(self) -> list[list]:
        return toc_entries(self.fitz)

    def set_flat_toc(self, toc: list[list]):
        self.snapshot()
        with self.lock:
            self.fitz.set_toc(toc)

    # ── 첨부 ──────────────────────────────────────────────────
    def attachments(self) -> list[dict]:
        out = []
        with self.lock:
            for k in self.fitz.embfile_names():
                info = self.fitz.embfile_info(k)
                # name 은 찾기 열쇠라 PyMuPDF 가 준 그대로 두고, 보여 줄 이름만 되살린다
                out.append({"name": k, "filename": _unmangle(info.get("ufilename") or info.get("filename") or k),
                            "size": info.get("length", 0), "desc": info.get("description", "")})
        return out

    def add_attachment(self, path: str, desc: str = ""):
        self.snapshot()
        with self.lock:
            base = os.path.basename(path)
            have = {_unmangle(n) for n in self.fitz.embfile_names()}
            name, k = base, 1
            while name in have:  # 같은 이름이 있으면 「이름 (2).txt」
                k += 1
                stem, ext = os.path.splitext(base)
                name = f"{stem} ({k}){ext}"
            with open(path, "rb") as fh:
                self.fitz.embfile_add(name, fh.read(), filename=name, ufilename=name, desc=desc)

    def get_attachment(self, name: str) -> bytes:
        with self.lock:
            return self.fitz.embfile_get(name)

    def remove_attachment(self, name: str):
        self.snapshot()
        with self.lock:
            self.fitz.embfile_del(name)

    # ── 레이어(선택적 내용) ─────────────────────────────────────
    def layers(self) -> list[dict]:
        """레이어 목록(화면 켜고 끄기 단위). depth 는 묶음 안 깊이."""
        with self.lock:
            try:
                return [{"number": c["number"], "name": c["text"], "on": bool(c["on"]), "depth": c.get("depth", 0),
                         "locked": bool(c.get("locked"))}
                        for c in self.fitz.layer_ui_configs() if c.get("type") in ("checkbox", "radiobox")]
            except Exception:  # noqa: BLE001
                return []

    def set_layer(self, number: int, on: bool):
        """레이어 하나를 화면에서 켜거나 끈다. 보기 설정이라 파일은 안 바뀌고, 저장·되돌리기로 다시 열어도 유지된다.
        (set_layer 로 기본 구성을 고치면 MuPDF 가 그리는 상태에 반영되지 않는다)"""
        with self.lock:
            for c in self.fitz.layer_ui_configs():
                if c["number"] == number:
                    self.fitz.set_layer_ui_config(number, 0 if on else 2)
                    (self.hidden_layers.discard if on else self.hidden_layers.add)(c["text"])

    def _apply_layers(self, d: fitz.Document):
        if not getattr(self, "hidden_layers", None):
            return
        try:
            for c in d.layer_ui_configs():
                if c["text"] in self.hidden_layers and c["on"]:
                    d.set_layer_ui_config(c["number"], 2)
        except Exception:  # noqa: BLE001
            pass

    # ── 속성 ──────────────────────────────────────────────────
    def metadata(self) -> dict:
        return dict(self.fitz.metadata or {})

    def set_metadata(self, md: dict):
        self.snapshot()
        with self.lock:
            cur = dict(self.fitz.metadata or {})
            cur.update(md)
            self.fitz.set_metadata(cur)

    def is_scanned(self, i: int) -> bool:
        """글자 없고 그림 하나로 된 쪽."""
        page = self.fitz[i]
        return not page.get_text("text").strip() and bool(page.get_images(full=False))


class NeedsPassword(DocumentError):
    def __init__(self, path: str):
        super().__init__("암호가 걸린 문서입니다")
        self.path = path

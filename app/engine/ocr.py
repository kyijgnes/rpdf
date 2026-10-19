# -*- coding: utf-8 -*-
"""문자 인식(OCR): 윈도우 내장 Windows.Media.Ocr 를 PowerShell 로 부른다. 돈 드는 엔진·tesseract 없음.

어드민 시험 등록 툴(circled_ocr.py)과 같은 방식. 그림 여러 장을 한 번에 넘기고 낱말 상자(픽셀)를 JSON 으로 받는다.
화면(Qt) 코드는 들여오지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Callable

import fitz

from .document import korean_font_name, redact_only
from .tools import EngineError, _pages, _say, korean_font, korean_font_path

Progress = Callable[[int, int, str], None] | None
TIMEOUT = 600
NO_LANG_MSG = "이 PC 에 윈도우 한국어 문자 인식이 없습니다"

_PS_COMMON = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) {
    $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
"""

_PS_OCR = r"""
param([string]$ListFile, [string]$Lang)
""" + _PS_COMMON + r"""
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Lang))
if ($null -eq $engine) { Write-Output 'NO_OCR_LANG'; exit 3 }
$utf8 = New-Object System.Text.UTF8Encoding $false
Get-Content -Path $ListFile -Encoding UTF8 | Where-Object { $_ -ne '' } | ForEach-Object {
    $png = $_
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($png)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $res = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines = @($res.Lines | ForEach-Object {
        $ln = $_
        $words = @($ln.Words | ForEach-Object {
            $r = $_.BoundingRect
            [pscustomobject]@{ text = $_.Text; x = [double]$r.X; y = [double]$r.Y; w = [double]$r.Width; h = [double]$r.Height } })
        [pscustomobject]@{ text = $ln.Text; words = $words } })
    $out = [System.IO.Path]::ChangeExtension($png, '.json')
    [System.IO.File]::WriteAllText($out, (ConvertTo-Json -InputObject $lines -Depth 5 -Compress), $utf8)
    $stream.Dispose()
}
"""

_PS_LANGS = _PS_COMMON + r"""
$langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag }
Write-Output (ConvertTo-Json -InputObject @($langs) -Compress)
"""


def _run_ps(script_text: str, args: list[str], folder: str, name: str = "ocr.ps1") -> subprocess.CompletedProcess:
    script = os.path.join(folder, name)
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(script_text)
    try:
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script, *args],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise EngineError(f"윈도우 문자 인식을 못 돌렸습니다 ({e})") from e


def available_languages() -> list[str]:
    """윈도우 문자 인식이 되는 언어 태그 목록(예: ['ko', 'en-US'])."""
    tmp = tempfile.mkdtemp(prefix="pdfapp_ocr_")
    try:
        r = _run_ps(_PS_LANGS, [], tmp, "langs.ps1")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0:
        return []
    try:
        data = json.loads(r.stdout.decode("utf-8", "replace").strip() or "[]")
    except ValueError:
        return []
    if isinstance(data, str):
        data = [data]
    return [str(x) for x in data if x]


def _normalize(lines_json) -> list[dict]:
    """PowerShell JSON(줄 → 낱말) → 낱말 [{text,x,y,w,h,line}] (픽셀)."""
    if lines_json is None:
        return []
    if isinstance(lines_json, dict):
        lines_json = [lines_json]
    words: list[dict] = []
    for li, ln in enumerate(lines_json):
        ws = ln.get("words") if isinstance(ln, dict) else None
        if ws is None:
            continue
        if isinstance(ws, dict):
            ws = [ws]
        for w in ws:
            try:
                words.append({"text": str(w["text"]), "x": float(w["x"]), "y": float(w["y"]),
                              "w": float(w["w"]), "h": float(w["h"]), "line": li})
            except (KeyError, TypeError, ValueError):
                continue
    return words


def ocr_images(png_paths: list[str], lang: str = "ko") -> list[list[dict]]:
    """PNG 여러 장을 한 번에 인식. 그림마다 낱말 목록."""
    if not png_paths:
        return []
    tmp = tempfile.mkdtemp(prefix="pdfapp_ocr_")
    try:
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w", encoding="utf-8") as f:
            f.write("\n".join(os.path.abspath(p) for p in png_paths))
        r = _run_ps(_PS_OCR, ["-ListFile", lst, "-Lang", lang], tmp)
        if r.returncode == 3 or b"NO_OCR_LANG" in r.stdout:
            raise EngineError(NO_LANG_MSG if lang.lower().startswith("ko")
                              else f"이 PC 에 윈도우 문자 인식 언어({lang})가 없습니다")
        if r.returncode != 0:
            err = (r.stderr or r.stdout).decode("utf-8", "replace").strip().splitlines()
            raise EngineError(f"윈도우 문자 인식 실패 ({err[-1] if err else r.returncode})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = []
    for png in png_paths:
        jp = os.path.splitext(png)[0] + ".json"
        try:
            with open(jp, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = []
        finally:
            try:
                os.remove(jp)
            except OSError:
                pass
        out.append(_normalize(data))
    return out


def ocr_image(png_path: str, lang: str = "ko") -> list[dict]:
    """그림 한 장의 낱말 [{text, x, y, w, h, line}] (픽셀)."""
    if not os.path.exists(png_path):
        raise EngineError(f"그림 파일이 없습니다: {png_path}")
    return ocr_images([png_path], lang)[0]


def _render(page: fitz.Page, folder: str, name: str, dpi: int, clip: fitz.Rect | None = None) -> tuple[str, float]:
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, clip=clip, alpha=False)
    path = os.path.join(folder, name)
    pix.save(path)
    return path, 72.0 / dpi


def _write_layer(page: fitz.Page, words: list[dict], scale: float, origin: fitz.Point | None = None) -> int:
    """낱말들을 보이지 않는 글자층으로(render_mode=3). 넣은 낱말 수.
    낱말 상자는 보이는 쪽(회전 적용) 그림에서 잰 것이라, 자리는 derotation 으로 옮기고 글 방향은 rotate=page.rotation."""
    if not words:
        return 0
    font = korean_font()  # 글자 폭 재기용
    name = korean_font_name(page)
    page.insert_font(fontname=name, fontfile=korean_font_path())
    shape = page.new_shape()
    ox, oy = (origin.x, origin.y) if origin else (0.0, 0.0)
    inv = page.derotation_matrix
    n = 0
    for k, w in enumerate(words):
        text = w["text"].strip()
        if not text:
            continue
        x0, y0 = ox + w["x"] * scale, oy + w["y"] * scale
        ww, hh = w["w"] * scale, w["h"] * scale
        # 글자 크기는 낱말 폭에 맞춘다(고르기·검색 표시가 낱말을 다 덮게). 높이에서 너무 벗어나면 높이 쪽으로
        tl = font.text_length(text, fontsize=hh)
        fs = hh * ww / tl if tl > 0 else hh
        fs = max(2.0, min(max(fs, hh * 0.6), hh * 1.5))
        pos = fitz.Point(x0, y0 + hh * 0.85) * inv
        if k + 1 < len(words) and words[k + 1].get("line") == w.get("line"):
            text += " "  # 폭을 맞추면 낱말끼리 붙어 한 낱말로 읽히므로 띄어쓰기를 넣는다
        try:
            shape.insert_text(pos, text, fontsize=fs, fontname=name, rotate=page.rotation, render_mode=3)
            n += 1
        except Exception:
            continue
    if n:
        shape.commit()
    return n


def _drop_invisible_text(page: fitz.Page) -> None:
    """「다시 인식」: 전에 넣은 보이지 않는 글자층을 걷는다(안 그러면 두 벌). 보이는 글자·그림·선은 그대로."""
    if not any(s.get("type") == 3 for s in page.get_texttrace()):
        return
    whole = page.rect | (page.rect * page.derotation_matrix)
    redact_only(page, [whole], fill=False, images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE, text=fitz.PDF_REDACT_TEXT_REMOVE_INVISIBLE)


def ocr_pages(doc: fitz.Document, pages=None, lang: str = "ko", dpi: int = 300,
              progress: Progress = None, force: bool = False) -> int:
    """글자층이 없는 쪽을 인식해 보이지 않는 글자층을 넣는다. 넣은 낱말 수. in place."""
    targets = [p for p in _pages(doc, pages) if force or not doc[p].get_text("text").strip()]
    if not targets:
        return 0
    tmp = tempfile.mkdtemp(prefix="pdfapp_ocr_")
    total = 0
    try:
        pngs = []
        for k, pno in enumerate(targets):
            _say(progress, k, len(targets) * 2, f"그림 뜨는 중 {pno + 1}쪽")
            pngs.append(_render(doc[pno], tmp, f"p{pno + 1:04d}.png", dpi)[0])
        _say(progress, len(targets), len(targets) * 2, f"글자 읽는 중 ({len(targets)}쪽)")
        results = ocr_images(pngs, lang)
        for k, (pno, words) in enumerate(zip(targets, results)):
            _say(progress, len(targets) + k, len(targets) * 2, f"글자층 넣는 중 {pno + 1}쪽")
            page = doc[pno]
            if force:
                _drop_invisible_text(page)
            total += _write_layer(page, words, 72.0 / dpi)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _say(progress, len(targets) * 2, len(targets) * 2, "문자 인식 끝")
    return total


def ocr_area(doc: fitz.Document, page_index: int, rect_points, lang: str = "ko", dpi: int = 300) -> str:
    """쪽의 네모 안 글자를 읽어 돌려준다(줄바꿈은 인식한 줄 단위)."""
    if not 0 <= page_index < doc.page_count:
        raise EngineError("쪽 번호가 범위를 벗어났습니다")
    page = doc[page_index]
    clip = fitz.Rect(rect_points) & page.rect
    if clip.is_empty:
        raise EngineError("읽을 영역이 비어 있습니다")
    tmp = tempfile.mkdtemp(prefix="pdfapp_ocr_")
    try:
        png, _ = _render(page, tmp, "area.png", dpi, clip)
        words = ocr_image(png, lang)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    lines: dict[int, list[dict]] = {}
    for w in words:
        lines.setdefault(w["line"], []).append(w)
    out = []
    for li in sorted(lines):
        ws = sorted(lines[li], key=lambda w: w["x"])
        out.append(" ".join(w["text"] for w in ws))
    return "\n".join(out)


def _cluster_rows(words: list[dict]) -> list[list[dict]]:
    """y 가 겹치는 낱말끼리 한 줄로."""
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["y"], w["x"])):
        cy = w["y"] + w["h"] / 2
        for row in rows:
            ry0 = min(r["y"] for r in row)
            ry1 = max(r["y"] + r["h"] for r in row)
            if ry0 - w["h"] * 0.3 <= cy <= ry1 + w["h"] * 0.3:
                row.append(w)
                break
        else:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w["x"])
    return rows


def _column_edges(rows: list[list[dict]]) -> list[float]:
    """모든 낱말을 x 축에 눕혀 빈 틈(평균 글자 높이 이상)이 있는 자리를 열 경계로."""
    spans = sorted((w["x"], w["x"] + w["w"]) for row in rows for w in row)
    if not spans:
        return []
    avg_h = sum(w["h"] for row in rows for w in row) / max(1, sum(len(r) for r in rows))
    gap_min = avg_h * 0.8
    merged = [list(spans[0])]
    for x0, x1 in spans[1:]:
        if x0 <= merged[-1][1] + gap_min:
            merged[-1][1] = max(merged[-1][1], x1)
        else:
            merged.append([x0, x1])
    edges = []
    for a, b in zip(merged, merged[1:]):
        edges.append((a[1] + b[0]) / 2)
    return edges


def recognize_table(doc: fitz.Document, page_index: int, rect_points=None, lang: str = "ko",
                    dpi: int = 300) -> list[list[str]]:
    """표를 2차원 글자 목록으로. 글자층이 있으면 find_tables, 없으면 OCR 낱말을 줄·열로 묶는다."""
    if not 0 <= page_index < doc.page_count:
        raise EngineError("쪽 번호가 범위를 벗어났습니다")
    page = doc[page_index]
    clip = fitz.Rect(rect_points) & page.rect if rect_points is not None else page.rect
    has_text = bool(page.get_text("text", clip=clip).strip())
    if has_text:
        try:
            tabs = page.find_tables(clip=clip)
            if tabs.tables:
                best = max(tabs.tables, key=lambda t: t.row_count * t.col_count)
                return [[("" if c is None else str(c)) for c in row] for row in best.extract()]
        except Exception:
            pass
        # 표 틀을 못 찾으면 글자 낱말을 줄·열로 묶는다
        words = [{"text": w[4], "x": w[0], "y": w[1], "w": w[2] - w[0], "h": w[3] - w[1], "line": w[6]}
                 for w in page.get_text("words", clip=clip)]
    else:
        tmp = tempfile.mkdtemp(prefix="pdfapp_ocr_")
        try:
            png, scale = _render(page, tmp, "table.png", dpi, clip)
            words = ocr_image(png, lang)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        for w in words:
            for k in ("x", "y", "w", "h"):
                w[k] *= scale
    if not words:
        return []
    rows = _cluster_rows(words)
    edges = _column_edges(rows)
    ncol = len(edges) + 1
    out: list[list[str]] = []
    for row in rows:
        cells = [""] * ncol
        for w in row:
            cx = w["x"] + w["w"] / 2
            ci = sum(1 for e in edges if cx > e)
            cells[ci] = (cells[ci] + " " + w["text"]).strip()
        out.append(cells)
    return out

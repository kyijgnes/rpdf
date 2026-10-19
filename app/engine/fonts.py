"""한글 글꼴 찾기. fitz 기본 글꼴은 한글이 없어서 맑은 고딕 파일을 직접 준다."""
from __future__ import annotations

import os

import fitz

_CANDIDATES = [
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\NanumGothic.ttf",
    r"C:\Windows\Fonts\gulim.ttc",
]
_BOLD = [r"C:\Windows\Fonts\malgunbd.ttf"]


def korean_fontfile(bold: bool = False) -> str:
    for p in (_BOLD if bold else []) + _CANDIDATES:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("한글 글꼴(맑은 고딕)을 찾지 못했습니다")


def korean_font(bold: bool = False) -> fitz.Font:
    return fitz.Font(fontfile=korean_fontfile(bold))

"""배포자 서명 확인. 정책 파일(policy.json)과 새 버전 안내(latest.json)는 배포자 PC 의 비밀키로 서명해 올린다.

공개키는 여기에만 박는다(주 키·예비 키). 비밀키는 저장소 밖 %USERPROFILE%\\.rpdf\\ (signkey.py).
서명 대상 앞에 용도 머리(DOMAIN_*)를 붙여, latest.json 서명을 정책 서명으로 돌려쓰지 못하게 한다.
"""
from __future__ import annotations

import base64

from . import ed25519

PUBLIC_KEYS = (
    "8wcfHcr2GJm9xaM/Ird9ZKWE9MJBXh6uy88Dnrfy8pg=",   # 주 키 (2026-10-21 signkey.py --make)
    "XJ9haWjdnMWBiSoQ/rz63oDmA7l6zv6zZUV2jrzYqdc=",   # 예비 키
)
DOMAIN_POLICY = b"RPDF-policy-v1\n"
DOMAIN_LATEST = b"RPDF-latest-v1\n"
_keys = None


def _trusted() -> list[bytes]:
    global _keys
    if _keys is None:
        _keys = [base64.b64decode(k) for k in PUBLIC_KEYS if k]
    return _keys


def set_keys(keys) -> None:
    """시험용: 믿을 공개키를 바꾼다."""
    global _keys
    _keys = list(keys)


def ok(domain: bytes, data: bytes, sig_b64) -> bool:
    try:
        sig = base64.b64decode(str(sig_b64).strip(), validate=True)
    except (ValueError, TypeError):
        return False
    return any(ed25519.verify(k, domain + data, sig) for k in _trusted())

"""Ed25519 서명·검증(RFC 8032). 정책 파일과 latest.json 의 서명을 보려고 둔다.

앱에 새 패키지(cryptography)를 묶지 않으려고 파이썬만으로 짰다. 느리지만(검증 한 번에 수십 ms) 켤 때 몇 번이라 상관없다.
서명은 발행 도구(publish_policy.py · release.py)가 이 PC 에서만 한다. 비밀키는 저장소 밖(설계.md 1절).
"""
from __future__ import annotations

import hashlib
import os

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)   # sqrt(-1)


def _h(m: bytes) -> int:
    return int.from_bytes(hashlib.sha512(m).digest(), "little")


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    A = (y1 - x1) * (y2 - x2) % _P
    B = (y1 + x1) * (y2 + x2) % _P
    C = 2 * t1 * t2 * _D % _P
    Dd = 2 * z1 * z2 % _P
    E, F, G, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s: int, pt):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _eq(a, b) -> bool:
    x1, y1, z1, _ = a
    x2, y2, z2, _ = b
    return (x1 * z2 - x2 * z1) % _P == 0 and (y1 * z2 - y2 * z1) % _P == 0


def _recover_x(y: int, sign: int):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    if x & 1 != sign:
        x = _P - x
    return x


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(pt) -> bytes:
    x, y, z, _ = pt
    zi = pow(z, _P - 2, _P)
    x, y = x * zi % _P, y * zi % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _secret(seed: bytes) -> tuple[int, bytes]:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("비밀키는 32바이트")
    return _compress(_mul(_secret(seed)[0], _G))


def new_seed() -> bytes:
    return os.urandom(32)


def sign(seed: bytes, msg: bytes) -> bytes:
    a, prefix = _secret(seed)
    A = _compress(_mul(a, _G))
    r = _h(prefix + msg) % _L
    R = _compress(_mul(r, _G))
    s = (r + _h(R + A + msg) * a) % _L
    return R + int.to_bytes(s, 32, "little")


def verify(public: bytes, msg: bytes, sig: bytes) -> bool:
    """맞는 서명이면 True. 틀리거나 모양이 이상하면 False(예외 안 냄)."""
    if len(public) != 32 or len(sig) != 64:
        return False
    A = _decompress(public)
    R = _decompress(sig[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _L:
        return False
    k = _h(sig[:32] + public + msg) % _L
    return _eq(_mul(s, _G), _add(R, _mul(k, A)))

# -*- coding: utf-8 -*-
"""사용 제한(app/policy.py)·업데이트 서명(app/updater.py) 시험. 네트워크 없이 시험용 키·임시 폴더로만 돈다."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sys
import urllib.error

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import ed25519, policy as PL, signing, updater as U  # noqa: E402

DAY = 86400
NOW = 1_800_000_000.0
SEED = bytes(range(32))
PUB = ed25519.public_key(SEED)


@pytest.fixture(autouse=True)
def test_key():
    signing.set_keys([PUB])
    yield
    signing._keys = None


def envelope(serial=1, seed=SEED, domain=signing.DOMAIN_POLICY, **kw) -> bytes:
    d = {"app": "RPDF", "serial": serial, "issued": int(NOW), "expires": None, "block": False, "min_version": "", "message": ""}
    d.update(kw)
    payload = json.dumps(d).encode()
    sig = base64.b64encode(ed25519.sign(seed, domain + payload)).decode()
    return json.dumps({"payload": base64.b64encode(payload).decode(), "sig": sig}).encode()


def state_with(raw: bytes, last_ok=NOW, last_seen=None, max_serial=None) -> PL.State:
    return PL.State(PL.parse(raw).serial if max_serial is None else max_serial, last_ok,
                    last_ok if last_seen is None else last_seen, raw.decode())


# ── 서명 ──────────────────────────────────────────────────────
def test_rfc8032_vector():
    sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    assert ed25519.public_key(sk).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig = ed25519.sign(sk, b"")
    assert sig.hex().startswith("e5564300c360ac729086e2cc806e828a")
    assert ed25519.verify(ed25519.public_key(sk), b"", sig)
    assert not ed25519.verify(ed25519.public_key(sk), b"x", sig)


def test_matches_cryptography():
    c = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    k = c.Ed25519PrivateKey.from_private_bytes(SEED)
    for m in (b"", b"abc", os.urandom(300)):
        assert ed25519.sign(SEED, m) == k.sign(m)


def test_real_public_keys_well_formed():
    signing._keys = None
    keys = signing._trusted()
    assert len(keys) == 2 and all(len(k) == 32 for k in keys)


def test_parse_rejects_bad():
    assert PL.parse(envelope(3)).serial == 3
    with pytest.raises(PL.PolicyError):
        PL.parse(envelope(seed=b"\x01" * 32))                     # 남의 키
    with pytest.raises(PL.PolicyError):
        PL.parse(envelope(domain=signing.DOMAIN_LATEST))          # latest 서명을 돌려씀
    with pytest.raises(PL.PolicyError):
        PL.parse(envelope(app="Other"))
    env = json.loads(envelope(block=True))
    payload = json.loads(base64.b64decode(env["payload"])); payload["block"] = False
    env["payload"] = base64.b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(PL.PolicyError):
        PL.parse(json.dumps(env))                                 # 내용만 바꿔 끼움
    with pytest.raises(PL.PolicyError):
        PL.parse(b"not json")


# ── 판정 ──────────────────────────────────────────────────────
def test_normal():
    v = PL.judge(state_with(envelope()), NOW + 3600)
    assert v.ok and v.days_left > 6.9


def test_blocked():
    v = PL.judge(state_with(envelope(block=True, message="그만")), NOW)
    assert v.kind == PL.BLOCKED and v.why == "그만"


def test_min_version():
    raw = envelope(min_version="0.3.0")
    assert PL.judge(state_with(raw), NOW, version="0.2.9").kind == PL.OUTDATED
    assert PL.judge(state_with(raw), NOW, version="0.3.0").ok
    assert PL.judge(state_with(raw), NOW, version="1.0.0").ok


def test_offline_6_and_8_days():
    st = state_with(envelope())
    assert PL.judge(st, NOW + 6 * DAY).ok
    v = PL.judge(st, NOW + 8 * DAY)
    assert v.kind == PL.NEED_ONLINE and "7일" in v.why


def test_first_run_and_deleted_state(tmp_path):
    assert PL.judge(PL.State(), NOW).kind == PL.NEED_ONLINE
    assert PL.load_state(str(tmp_path / "없음.json")) == PL.State()
    bad = tmp_path / "깨짐.json"; bad.write_text("{", encoding="utf-8")
    assert PL.judge(PL.load_state(str(bad)), NOW).kind == PL.NEED_ONLINE


def test_clock_rollback():
    st = state_with(envelope(), last_ok=NOW, last_seen=NOW + 2 * DAY)   # 이틀 뒤까지 썼는데
    assert PL.judge(st, NOW + 1 * DAY).kind == PL.NEED_ONLINE          # 시계를 하루 뒤로 돌림
    assert PL.judge(st, NOW + 2 * DAY + 60).ok
    st2 = state_with(envelope(), last_ok=NOW)
    assert PL.judge(st2, NOW - 3600).kind == PL.NEED_ONLINE            # 마지막 확인보다 이른 시각
    assert PL.judge(st2, NOW - 60).ok                                   # 몇 분 오차는 봐준다


def test_expired_policy():
    st = state_with(envelope(expires=int(NOW + DAY)))
    assert PL.judge(st, NOW + 3600).ok
    assert PL.judge(st, NOW + 2 * DAY).kind == PL.NEED_ONLINE


def test_cached_older_than_seen():
    st = state_with(envelope(serial=2), max_serial=5)   # 상태 파일의 정책만 옛것으로 바꿔 끼움
    assert PL.judge(st, NOW).kind == PL.NEED_ONLINE


# ── 확인(받기) ────────────────────────────────────────────────
def test_rollback_serial_rejected():
    st = state_with(envelope(serial=5, block=True))
    with pytest.raises(PL.PolicyError):
        PL.refresh(st, NOW + 10, lambda: envelope(serial=4, block=False))
    new = PL.refresh(st, NOW + 10, lambda: envelope(serial=6, block=False))
    assert new.max_serial == 6 and PL.judge(new, NOW + 20).ok


def test_gate_flow(tmp_path):
    path = str(tmp_path / "policy_state.json")

    def offline():
        raise urllib.error.URLError("없음")
    v, err = PL.gate(NOW, offline, path)
    assert v.kind == PL.NEED_ONLINE and "인터넷" in err and not os.path.exists(path)

    v, err = PL.gate(NOW, lambda: envelope(serial=1), path)
    assert v.ok and not err and PL.load_state(path).max_serial == 1

    v, _ = PL.gate(NOW + 6 * DAY, offline, path)                        # 6일 오프라인: 열림
    assert v.ok
    v, err = PL.gate(NOW + 8 * DAY, offline, path)                      # 8일: 확인 필요
    assert v.kind == PL.NEED_ONLINE and err

    v, _ = PL.gate(NOW + 8 * DAY, lambda: envelope(serial=2, block=True, message="멈춤"), path)
    assert v.kind == PL.BLOCKED
    v, err = PL.gate(NOW + 8 * DAY + 60, lambda: envelope(serial=1), path, force=True)   # 되감기 시도
    assert v.kind == PL.BLOCKED and "옛것" in err
    v, _ = PL.gate(NOW + 8 * DAY + 120, lambda: envelope(serial=3), path, force=True)    # 풀기
    assert v.ok

    v, _ = PL.gate(NOW + 8 * DAY - 7200, offline, path)                 # 시계 두 시간 뒤로
    assert v.kind == PL.NEED_ONLINE
    v, _ = PL.gate(NOW + 8 * DAY - 7200, lambda: envelope(serial=3), path)   # 연결해 확인하면 풀림
    assert v.ok

    os.remove(path)                                                     # 상태를 지우면 처음 상태
    v, _ = PL.gate(NOW + 9 * DAY, offline, path)
    assert v.kind == PL.NEED_ONLINE


def test_installed_ignores_env(monkeypatch):
    monkeypatch.setenv(PL.SOURCE_ENV, "C:/가짜/policy.json")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert PL.source() == PL.POLICY_URL and PL.enforced()
    monkeypatch.delattr(sys, "frozen")
    assert PL.source() == "C:/가짜/policy.json" and PL.enforced()
    monkeypatch.delenv(PL.SOURCE_ENV)
    assert not PL.enforced()


# ── 업데이트 ──────────────────────────────────────────────────
def make_release(folder, version="9.9.9", sign=True, seed=SEED, setup_bytes=b"MZ fake setup " * 1000, **over):
    os.makedirs(folder, exist_ok=True)
    name = f"RPDF-setup-{version}.exe"
    with open(os.path.join(folder, name), "wb") as f:
        f.write(setup_bytes)
    data = {"app": "RPDF", "version": version, "setup": name, "sha256": hashlib.sha256(setup_bytes).hexdigest(),
            "size": len(setup_bytes), "url": f"https://github.com/kyijgnes/rpdf/releases/download/v{version}/{name}"}
    data.update(over)
    raw = json.dumps(data).encode()
    with open(os.path.join(folder, "latest.json"), "wb") as f:
        f.write(raw)
    if sign:
        with open(os.path.join(folder, U.SIG_NAME), "w") as f:
            f.write(base64.b64encode(ed25519.sign(seed, signing.DOMAIN_LATEST + raw)).decode())
    return folder


@pytest.fixture
def dl_dir(tmp_path, monkeypatch):
    d = str(tmp_path / "dl")
    monkeypatch.setattr(U, "_DOWNLOAD_DIR", d)
    return d


def test_allowed_url():
    assert U.allowed_url("https://github.com/kyijgnes/rpdf/releases/latest/download/latest.json")
    assert U.allowed_url("https://release-assets.githubusercontent.com/x")
    assert U.allowed_url("https://objects.githubusercontent.com/x")
    for bad in ("http://github.com/x", "https://github.com.evil.com/x", "https://evil.com/github.com",
                "https://user@github.com/x", "file:///C:/x.exe", "https://raw.githubusercontent.com/x"):
        assert not U.allowed_url(bad), bad


def test_redirect_to_foreign_host_refused():
    h = U._Redirect()
    with pytest.raises(urllib.error.URLError):
        h.redirect_request(None, None, 302, "Found", {}, "https://evil.example.com/setup.exe")


def test_check_signed(tmp_path, monkeypatch, dl_dir):
    folder = make_release(str(tmp_path / "rel"))
    monkeypatch.setenv(U.SOURCE_ENV, folder)
    rel = U.check()
    assert rel.version == "9.9.9" and rel.newer
    path = U.download(rel)
    assert os.path.dirname(os.path.dirname(path)) == dl_dir and open(path, "rb").read().startswith(b"MZ fake")


def test_check_unsigned_or_tampered(tmp_path, monkeypatch):
    folder = make_release(str(tmp_path / "a"), sign=False)
    monkeypatch.setenv(U.SOURCE_ENV, folder)
    with pytest.raises(ValueError, match="서명"):
        U.check()
    folder = make_release(str(tmp_path / "b"), seed=b"\x02" * 32)        # 남의 키로 서명
    monkeypatch.setenv(U.SOURCE_ENV, folder)
    with pytest.raises(ValueError, match="서명"):
        U.check()
    folder = make_release(str(tmp_path / "c"))
    p = os.path.join(folder, "latest.json")
    d = json.load(open(p)); d["sha256"] = "0" * 64                        # 서명한 뒤 sha256 바꿔 끼움
    open(p, "w").write(json.dumps(d))
    monkeypatch.setenv(U.SOURCE_ENV, folder)
    with pytest.raises(ValueError, match="서명"):
        U.check()


def test_check_bad_fields(tmp_path, monkeypatch):
    for i, over in enumerate(({"setup": "..\\evil.exe"}, {"url": "https://evil.com/x.exe"}, {"sha256": ""},
                              {"setup": "x.bat"})):
        folder = make_release(str(tmp_path / f"f{i}"), **over)
        monkeypatch.setenv(U.SOURCE_ENV, folder)
        if "url" in over:   # 로컬 자리에서는 url 을 안 쓴다. 주소 자리에서 막히는지는 allowed_url 시험이 본다
            continue
        with pytest.raises(ValueError):
            U.check()


def test_download_refuses(tmp_path, monkeypatch, dl_dir):
    folder = make_release(str(tmp_path / "old"), version="0.0.1")
    monkeypatch.setenv(U.SOURCE_ENV, folder)
    with pytest.raises(ValueError, match="높지 않아"):
        U.download(U.check())                                             # 버전 내리기
    folder = make_release(str(tmp_path / "new"))
    monkeypatch.setenv(U.SOURCE_ENV, folder)
    rel = U.check()
    with open(os.path.join(folder, rel.setup), "ab") as f:
        f.write(b"tamper")                                                # 받을 파일이 바뀜
    with pytest.raises(ValueError, match="크기|sha256"):
        U.download(rel)
    rel = U.check(); rel.size = 0
    with pytest.raises(ValueError, match="sha256"):
        U.download(rel)


def test_run_setup_only_from_download_dir(tmp_path, dl_dir):
    with pytest.raises(ValueError):
        U.run_setup(str(tmp_path / "elsewhere.exe"))


def test_clean_env_drops_sources(monkeypatch):
    monkeypatch.setenv(U.SOURCE_ENV, "x"); monkeypatch.setenv(PL.SOURCE_ENV, "y")
    env = U.clean_env()
    assert U.SOURCE_ENV not in env and PL.SOURCE_ENV not in env


@pytest.mark.skipif(os.name != "nt", reason="윈도우 전용")
def test_authenticode(tmp_path):
    plain = tmp_path / "plain.exe"; plain.write_bytes(b"MZ" + b"\0" * 4000)
    assert U.authenticode(str(plain)) == "unsigned"
    if U.authenticode(sys.executable) != "signed":
        pytest.skip("이 python.exe 는 서명이 없음")
    bad = tmp_path / "bad.exe"
    shutil.copy(sys.executable, bad)
    b = bytearray(bad.read_bytes()); b[len(b) // 3] ^= 0xFF; bad.write_bytes(bytes(b))
    assert U.authenticode(str(bad)) == "bad"

"""사용 제한(배포자 정책). Qt 모름(화면 쪽은 ui/gate.py).

무료 배포라 배포자가 정책 파일로 앱을 멈출 수 있게 한다(2026-10-21 사용자 결정).
- 정책 파일은 GitHub 릴리스 `policy` 의 policy.json(POLICY_URL). 배포자 비밀키로 서명한다(publish_policy.py).
  모양: {"payload": "<정책 JSON 의 base64>", "sig": "<서명 base64>"}. 서명 대상은 DOMAIN_POLICY + payload 바이트.
- 정책 항목: serial(발행 번호, 늘기만 함) · issued · expires(정책 기한, 없으면 null) · block(전부 차단) ·
  min_version(이보다 낮으면 막고 업데이트로 안내) · message(알림 문구).
- 켤 때 보고 CHECK_EVERY 마다 다시 본다. 마지막으로 확인에 성공한 뒤 OFFLINE_DAYS(7일)까지는 인터넷 없이 열린다.
  넘으면 「인터넷에 한 번 연결해 확인해야 열린다」. 상태 파일을 지우면 처음 상태(=확인 필요)가 된다.
- 되감기 막기: 지금까지 본 가장 큰 발행 번호보다 작은 정책은 받지 않는다.
- 시계 되돌리기: 지금 시각이 마지막으로 본 시각(확인·사용)보다 SKEW 넘게 이르면 의심해서 다시 확인을 요구한다.
- 설치본(exe)만 지킨다. 소스로 띄울 때는 PDFAPP_POLICY_SOURCE 를 준 때만(시험용, 설치본에서는 이 변수를 무시).

한계: 파이썬 앱이라 마음먹고 exe 안 코드를 고치거나 상태 파일을 손대면 우회할 수 있다. 막는 것은 보통 사용자의 계속 사용.
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field

from . import signing
from .appinfo import VERSION, data_dir
from .updater import RELEASE_REPO, installed, parse_version, read_small

POLICY_TAG = "policy"   # 정책만 담는 릴리스(사전 공개로 둬서 releases/latest 에 안 잡힌다)
POLICY_URL = f"https://github.com/{RELEASE_REPO}/releases/download/{POLICY_TAG}/policy.json"
SOURCE_ENV = "PDFAPP_POLICY_SOURCE"
OFFLINE_DAYS = 7
CHECK_EVERY = 6 * 3600          # 켜 둔 동안 다시 보는 간격(초)
SKEW = 10 * 60                  # 시계 오차 봐주는 폭(초)
STATE = os.path.join(data_dir(), "policy_state.json")

OK, BLOCKED, OUTDATED, NEED_ONLINE = "ok", "blocked", "outdated", "need_online"


class PolicyError(ValueError):
    pass


@dataclass
class Policy:
    serial: int
    issued: int = 0
    expires: int | None = None
    block: bool = False
    min_version: str = ""
    message: str = ""


@dataclass
class Verdict:
    kind: str                       # OK · BLOCKED · OUTDATED · NEED_ONLINE
    why: str = ""                   # 화면에 보일 한 줄
    policy: Policy | None = None
    days_left: float | None = None  # 인터넷 없이 더 열 수 있는 날

    @property
    def ok(self) -> bool:
        return self.kind == OK


@dataclass
class State:
    max_serial: int = -1
    last_ok: float = 0.0            # 마지막으로 확인에 성공한 시각(이 PC 시계)
    last_seen: float = 0.0          # 이 PC 시계로 본 가장 늦은 시각
    envelope: str = ""              # 마지막으로 받은 서명된 정책(원문)
    shown: list[int] = field(default_factory=list)   # 알림 문구를 보여 준 발행 번호


def enforced() -> bool:
    return installed() or bool(os.environ.get(SOURCE_ENV, "").strip())


def source() -> str:
    if installed():
        return POLICY_URL
    return os.environ.get(SOURCE_ENV, "").strip() or POLICY_URL


# ── 서명된 정책 읽기 ──────────────────────────────────────────
def parse(envelope: bytes | str) -> Policy:
    """서명을 보고 정책을 꺼낸다. 틀리면 PolicyError."""
    try:
        env = json.loads(envelope)
        payload = base64.b64decode(env["payload"], validate=True)
        sig = env["sig"]
    except (ValueError, KeyError, TypeError) as e:
        raise PolicyError("정책 파일 모양이 틀립니다") from e
    if not signing.ok(signing.DOMAIN_POLICY, payload, sig):
        raise PolicyError("정책 파일의 배포자 서명이 맞지 않습니다")
    try:
        d = json.loads(payload.decode("utf-8"))
        if d.get("app") != "RPDF":   # 서명한 정책 안의 열쇠라 앱 이름(PDF메트리)과 따로 둔다(옛 버전도 같은 정책을 읽음)
            raise PolicyError("다른 앱의 정책입니다")
        exp = d.get("expires")
        return Policy(serial=int(d["serial"]), issued=int(d.get("issued") or 0),
                      expires=int(exp) if exp is not None else None, block=bool(d.get("block")),
                      min_version=str(d.get("min_version") or ""), message=str(d.get("message") or ""))
    except (ValueError, KeyError, TypeError) as e:
        raise PolicyError("정책 내용이 틀립니다") from e


# ── 상태 파일 ────────────────────────────────────────────────
def load_state(path: str = STATE) -> State:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return State(int(d.get("max_serial", -1)), float(d.get("last_ok", 0)), float(d.get("last_seen", 0)),
                     str(d.get("envelope", "")), [int(x) for x in d.get("shown", [])][-20:])
    except (OSError, ValueError, TypeError):
        return State()


def save_state(st: State, path: str = STATE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"max_serial": st.max_serial, "last_ok": st.last_ok, "last_seen": st.last_seen,
                   "envelope": st.envelope, "shown": st.shown[-20:]}, f, ensure_ascii=False)
    os.replace(tmp, path)


# ── 판정(네트워크 없음) ──────────────────────────────────────
def judge(st: State, now: float, version: str = VERSION) -> Verdict:
    if not st.envelope or st.last_ok <= 0:
        return Verdict(NEED_ONLINE, "처음 켤 때는 인터넷에 연결해 사용 확인을 받아야 합니다")
    if now + SKEW < max(st.last_ok, st.last_seen):
        return Verdict(NEED_ONLINE, "PC 시계가 마지막 확인 시각보다 이릅니다. 시계를 맞추고 인터넷에 연결해 확인하세요")
    left = OFFLINE_DAYS - (now - st.last_ok) / 86400
    if left < 0:
        return Verdict(NEED_ONLINE, f"인터넷 없이 {OFFLINE_DAYS}일이 지났습니다. 인터넷에 한 번 연결해 확인해야 열립니다")
    try:
        pol = parse(st.envelope)
    except PolicyError:
        return Verdict(NEED_ONLINE, "저장해 둔 사용 확인이 깨졌습니다. 인터넷에 연결해 다시 확인하세요")
    if pol.serial < st.max_serial:
        return Verdict(NEED_ONLINE, "저장해 둔 사용 확인이 옛것입니다. 인터넷에 연결해 다시 확인하세요")
    if pol.expires is not None and now > pol.expires:
        return Verdict(NEED_ONLINE, "사용 확인 기한이 지났습니다. 인터넷에 연결해 다시 확인하세요", pol)
    if pol.block:
        return Verdict(BLOCKED, pol.message or "배포자가 이 앱의 사용을 멈췄습니다", pol, left)
    if pol.min_version and parse_version(version) < parse_version(pol.min_version):
        return Verdict(OUTDATED, pol.message or f"이 버전({version})은 더 쓸 수 없습니다. {pol.min_version} 이상으로 업데이트하세요", pol, left)
    return Verdict(OK, "", pol, left)


# ── 확인(네트워크) ───────────────────────────────────────────
def fetch(timeout: float = 10) -> bytes:
    data, _, _ = read_small(source(), timeout)
    return data


def refresh(st: State, now: float, fetcher=fetch) -> State:
    """정책을 새로 받아 상태를 고친다(저장은 부른 쪽이). 실패하면 예외(상태는 그대로)."""
    raw = fetcher()
    pol = parse(raw)
    if pol.serial < st.max_serial:
        raise PolicyError(f"받은 정책이 전에 본 것보다 옛것입니다(발행 번호 {pol.serial} < {st.max_serial})")
    return State(max(st.max_serial, pol.serial), now, now, raw.decode("utf-8") if isinstance(raw, bytes) else str(raw),
                 list(st.shown))


def touch(st: State, now: float) -> None:
    """쓰는 동안 본 시각을 남긴다(되돌린 시계를 알아채려고). 시계가 뒤로 갔으면 늘리지 않는다."""
    if now > st.last_seen:
        st.last_seen = now


def gate(now: float | None = None, fetcher=fetch, path: str = STATE, force: bool = False) -> tuple[Verdict, str]:
    """켤 때·다시 볼 때 부른다. (판정, 확인 실패 이유 또는 '').
    저장해 둔 판정으로 열 수 있으면 그대로 두고(force 면 늘 새로 받는다), 아니면 새로 받아 다시 판정한다."""
    now = time.time() if now is None else now
    st = load_state(path)
    v = judge(st, now)
    err = ""
    if force or v.kind == NEED_ONLINE:
        try:
            st = refresh(st, now, fetcher)
            v = judge(st, now)
        except Exception as e:  # noqa: BLE001
            err = _why(e)
    if v.kind != NEED_ONLINE or st.last_ok:
        touch(st, now)
        try:
            save_state(st, path)
        except OSError:
            pass
    return v, err


def mark_shown(serial: int, path: str = STATE) -> None:
    st = load_state(path)
    if serial not in st.shown:
        st.shown.append(serial)
        save_state(st, path)


def _why(e: Exception) -> str:
    import urllib.error
    if isinstance(e, urllib.error.HTTPError):
        return f"확인 자리에 닿았지만 정책 파일을 못 받았습니다 ({e.code})"
    if isinstance(e, urllib.error.URLError):
        return f"인터넷 연결을 확인하세요 ({e.reason})"
    if isinstance(e, OSError):
        return f"확인 자리를 못 읽었습니다 ({e})"
    return str(e) or type(e).__name__


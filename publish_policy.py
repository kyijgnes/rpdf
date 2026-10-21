"""RPDF 사용 제한(정책 파일) 걸기·풀기. 서명해서 GitHub 릴리스 `policy` 에 policy.json 으로 올린다(gh 필요).

    python publish_policy.py                      지금 올라간 정책 보기
    python publish_policy.py 차단 "문구"           전부 차단(문구는 차단 화면에 보임)
    python publish_policy.py 풀기                  차단을 풀고 문구도 지움(최소 버전은 그대로)
    python publish_policy.py 최소버전 0.2.0 "문구"  그보다 낮은 버전은 막고 업데이트로 안내(0 이면 없앰)
    python publish_policy.py 알림 "문구"           막지는 않고 켤 때 한 번 알림("" 이면 지움)
    python publish_policy.py 그대로                내용은 그대로 두고 다시 서명만(기한 늘리기 등)

    덧붙이는 것: --기한 30   정책을 30일 뒤에 무효로(그때까지 다시 올려야 앱이 계속 열림. 기본: 기한 없음, 지금 기한 유지)
                --기한없음  기한을 없앤다
                --out 폴더 GitHub 에 올리지 않고 그 폴더에 policy.json 만 쓴다(시험: PDFAPP_POLICY_SOURCE=폴더\\policy.json)

- 발행 번호(serial)는 올릴 때마다 1씩 는다. 앱은 본 것보다 작은 번호를 받지 않는다.
- 비밀키는 %USERPROFILE%\\.rpdf\\sign_key.json (signkey.py). 올린 기록은 같은 폴더 policy_log.jsonl.
- 앱은 마지막 확인 뒤 7일까지 인터넷 없이 열리므로, 차단은 늦어도 7일 안에 모든 PC 에 걸린다(켜 둔 앱은 6시간마다 다시 봄).
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from app import policy, signing  # noqa: E402
from app.updater import RELEASE_REPO, parse_version, read_small  # noqa: E402
import signkey  # noqa: E402

LOG = os.path.join(signkey.KEY_DIR, "policy_log.jsonl")


def die(msg: str):
    print(f"\n[멈춤] {msg}", flush=True)
    sys.exit(1)


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        die(f"gh {' '.join(args)}\n{(r.stderr or r.stdout).strip()}")
    return r


def online() -> tuple[dict | None, int]:
    """지금 올라간 정책(내용, 발행 번호). 없으면 (None, -1)."""
    import urllib.error
    try:
        raw, _, _ = read_small(policy.POLICY_URL, 15)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, -1
        raise
    p = policy.parse(raw)   # 서명이 틀리면 여기서 멈춘다(누가 바꿔 끼웠다)
    return json.loads(base64.b64decode(json.loads(raw)["payload"])), p.serial


def local_max() -> int:
    best = -1
    try:
        with open(LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    best = max(best, int(json.loads(line)["serial"]))
                except (ValueError, KeyError):
                    pass
    except OSError:
        pass
    return best


def show(d: dict | None, serial: int):
    if d is None:
        print("올라간 정책 없음(설치본은 확인을 못 해 처음 켤 때 안 열린다. 첫 정책: python publish_policy.py 그대로)")
        return
    def ts(t):
        return "없음" if t is None else f"{datetime.datetime.fromtimestamp(t):%Y-%m-%d %H:%M}"
    print(f"발행 번호 {serial} · 올린 때 {ts(d.get('issued'))} · 기한 {ts(d.get('expires'))}")
    print(f"  차단: {'예' if d.get('block') else '아니오'}")
    print(f"  최소 버전: {d.get('min_version') or '없음'}")
    print(f"  문구: {d.get('message') or '없음'}")


def envelope(d: dict) -> bytes:
    payload = json.dumps(d, ensure_ascii=False, sort_keys=True).encode("utf-8")
    env = {"payload": base64.b64encode(payload).decode(), "sig": signkey.sign(signing.DOMAIN_POLICY, payload)}
    raw = json.dumps(env, indent=1).encode("utf-8")
    policy.parse(raw)   # 앱이 받는 것과 같은 길로 다시 확인
    return raw


def upload(raw: bytes):
    if gh("auth", "status", check=False).returncode:
        die("gh 로그인이 안 돼 있습니다: gh auth login")
    if gh("release", "view", policy.POLICY_TAG, "--repo", RELEASE_REPO, check=False).returncode:
        print(f"릴리스 {policy.POLICY_TAG} 를 처음 만든다(사전 공개, latest 아님)")
        gh("release", "create", policy.POLICY_TAG, "--repo", RELEASE_REPO, "--title", "policy", "--notes", "",
           "--prerelease", "--latest=false")
    # 올릴 파일은 키 자리에 둔다(이 PC 의 TEMP 가 C:\Users\Public 아래라 남이 바꿔 끼울 수 있다)
    os.makedirs(signkey.KEY_DIR, exist_ok=True)
    path = os.path.join(signkey.KEY_DIR, "policy.json")
    with open(path, "wb") as f:
        f.write(raw)
    gh("release", "upload", policy.POLICY_TAG, path, "--repo", RELEASE_REPO, "--clobber")


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--기한", dest="days", type=float, help="며칠 뒤 정책 무효")
    common.add_argument("--기한없음", dest="no_exp", action="store_true")
    common.add_argument("--out", help="올리지 않고 이 폴더에 policy.json 만")
    ap = argparse.ArgumentParser(description="RPDF 사용 제한(정책) 걸기·풀기", parents=[common])
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("차단", aliases=["block"], parents=[common]); b.add_argument("message", nargs="?", default="")
    sub.add_parser("풀기", aliases=["unblock"], parents=[common])
    m = sub.add_parser("최소버전", aliases=["min"], parents=[common]); m.add_argument("version"); m.add_argument("message", nargs="?")
    n = sub.add_parser("알림", aliases=["notice"], parents=[common]); n.add_argument("message")
    sub.add_parser("그대로", aliases=["resign"], parents=[common])
    a = ap.parse_args()

    if a.out:
        cur, cur_serial = None, -1
        prev = os.path.join(a.out, "policy.json")
        if os.path.exists(prev):
            with open(prev, "rb") as f:
                raw0 = f.read()
            cur_serial = policy.parse(raw0).serial
            cur = json.loads(base64.b64decode(json.loads(raw0)["payload"]))
    else:
        cur, cur_serial = online()
    if not a.cmd:
        show(cur, cur_serial)
        return 0

    d = dict(cur or {"app": "RPDF", "block": False, "min_version": "", "message": "", "expires": None})
    cmd = {"block": "차단", "unblock": "풀기", "min": "최소버전", "notice": "알림", "resign": "그대로"}.get(a.cmd, a.cmd)
    if cmd == "차단":
        d["block"] = True; d["message"] = a.message
    elif cmd == "풀기":
        d["block"] = False; d["message"] = ""
    elif cmd == "최소버전":
        if a.version in ("0", ""):
            d["min_version"] = ""
        else:
            if parse_version(a.version) == (0, 0, 0):
                die(f"버전은 세 자리로: {a.version}")
            d["min_version"] = a.version
        if a.message is not None:
            d["message"] = a.message
    elif cmd == "알림":
        d["message"] = a.message
    now = int(time.time())
    if a.no_exp:
        d["expires"] = None
    elif a.days:
        d["expires"] = now + int(a.days * 86400)
    if d.get("expires") is not None and d["expires"] <= now:
        die("기한이 이미 지났습니다. --기한 며칠 또는 --기한없음 을 주세요")
    d["app"] = "RPDF"
    d["issued"] = now
    d["serial"] = max(cur_serial, local_max() if not a.out else -1) + 1
    raw = envelope(d)

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "policy.json"), "wb") as f:
            f.write(raw)
        print(f"썼다(올리지 않음): {os.path.join(a.out, 'policy.json')}")
    else:
        upload(raw)
        os.makedirs(signkey.KEY_DIR, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({**d, "at": f"{datetime.datetime.now():%Y-%m-%d %H:%M}"}, ensure_ascii=False) + "\n")
        for _ in range(6):   # 올라간 것을 앱과 같은 길로 다시 읽어 본다
            got, serial = online()
            if serial == d["serial"]:
                break
            time.sleep(5)
        else:
            print("(올렸지만 아직 새 번호가 안 보인다. 잠시 뒤 python publish_policy.py 로 확인)")
        print("올렸다:", policy.POLICY_URL)
    show(d, d["serial"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

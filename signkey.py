"""배포자 쪽 서명키(정책 파일·latest.json 서명). 앱에는 공개키만 들어간다(app/signing.py PUBLIC_KEYS).

    python signkey.py --make     키 두 벌(주 키·예비 키)을 만들고 앱에 넣을 공개키를 보여 준다(이미 있으면 멈춤)
    python signkey.py            지금 키 자리와 공개키를 보여 준다

- 자리: %USERPROFILE%\\.rpdf\\ (저장소 밖. git 에 절대 안 올린다)
  · sign_key.json         주 키. 평소 서명은 이것으로
  · sign_key_backup.json  예비 키. 만든 뒤 USB 등 이 PC 밖으로 옮겨 두고 PC 에서는 지운다(주 키를 잃었을 때 쓴다)
- 둘 다 잃으면 설치된 앱에 새 정책·새 버전을 더는 못 보낸다(앱이 서명을 못 믿으므로). 주 키도 따로 한 벌 보관할 것.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from app import ed25519  # noqa: E402
from app.signing import PUBLIC_KEYS  # noqa: E402

KEY_DIR = os.path.join(os.path.expanduser("~"), ".rpdf")
KEY_FILES = {"main": os.path.join(KEY_DIR, "sign_key.json"), "backup": os.path.join(KEY_DIR, "sign_key_backup.json")}


def load_seed(which: str | None = None) -> bytes:
    """주 키(없으면 예비 키)의 비밀값. 앱이 믿는 공개키와 짝이 맞는지도 본다."""
    for name in ([which] if which else ["main", "backup"]):
        path = KEY_FILES[name]
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                seed = bytes.fromhex(json.load(f)["seed"])
            pub = base64.b64encode(ed25519.public_key(seed)).decode()
            if pub not in PUBLIC_KEYS:
                raise SystemExit(f"[멈춤] {path} 의 공개키가 app/signing.py PUBLIC_KEYS 에 없습니다: {pub}")
            return seed
    raise SystemExit(f"[멈춤] 서명키가 없습니다: {KEY_FILES['main']}\n(새로 만들려면 python signkey.py --make, 옮겨 둔 키가 있으면 그 자리에 복사)")


def have_key() -> bool:
    return any(os.path.exists(p) for p in KEY_FILES.values())


def sign(domain: bytes, data: bytes, which: str | None = None) -> str:
    return base64.b64encode(ed25519.sign(load_seed(which), domain + data)).decode()


def make():
    if have_key():
        raise SystemExit(f"[멈춤] 이미 키가 있습니다: {KEY_DIR}")
    os.makedirs(KEY_DIR, exist_ok=True)
    pubs = []
    for name, path in KEY_FILES.items():
        seed = ed25519.new_seed()
        pub = base64.b64encode(ed25519.public_key(seed)).decode()
        with open(path, "x", encoding="utf-8") as f:
            json.dump({"seed": seed.hex(), "public": pub, "kind": name,
                       "made": f"{datetime.datetime.now():%Y-%m-%d %H:%M}"}, f, indent=1)
        pubs.append(pub)
        print(f"{name:7} {path}\n        {pub}")
    print("\napp/signing.py PUBLIC_KEYS 에 위 두 줄을 넣는다. 예비 키 파일은 이 PC 밖으로 옮긴다.")


def show():
    for name, path in KEY_FILES.items():
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                pub = json.load(f)["public"]
            print(f"{name:7} {path}\n        {pub} {'(앱이 믿음)' if pub in PUBLIC_KEYS else '(앱에 없음!)'}")
        else:
            print(f"{name:7} 없음 ({path})")


def main() -> int:
    ap = argparse.ArgumentParser(description="RPDF 서명키")
    ap.add_argument("--make", action="store_true", help="키 두 벌 만들기")
    a = ap.parse_args()
    make() if a.make else show()
    return 0


if __name__ == "__main__":
    sys.exit(main())

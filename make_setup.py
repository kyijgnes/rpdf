"""설치 프로그램(Inno Setup) 만들기: build.py 가 지은 dist\\<APP_ID> → release\\<버전>\\RPDF-setup-<버전>.exe + latest.json

    python make_setup.py                 이 폴더의 dist 로(GitHub Actions 가 부른다)
    python make_setup.py --root <폴더>   그 폴더의 dist·installer 로(release.py --build-only 가 HEAD 사본으로 부른다)
    python make_setup.py --out <폴더>    결과 자리(기본: <이 폴더>\\release\\<버전>)

- 이름·버전은 app/appinfo.py 한 곳. 바꾸지 않는 열쇠(설치 GUID 등)는 아래 머리에 있다.
- latest.json 은 앱 안 업데이트가 보는 것(버전·setup 이름·받을 주소·sha256·크기). 바뀐 것(notes)은 적지 않는다(2026-10-20 결정).
  배포자 서명(latest.sig)은 여기서 안 붙인다(Actions 에는 비밀키가 없다). release.py 가 이 PC 에서 붙인다.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from app.updater import MUTEX_NAME, RELEASE_REPO  # noqa: E402

# ── 바꾸지 않는 열쇠. 바꾸면 같은 앱으로 이어지지 않고 따로 깔린다 ──
INNO_GUID = "A5A02529-0CA9-4430-A2AD-3140C6CEEFAC"   # 설치 정보(설정 > 앱) 열쇠

# ── 이름들. 10-20 옛 이름 PDFEditor 를 RPDF 로 통일(0.1.4). 옛 이름은 설치 프로그램이 걷는다(OLD_*) ──
PROGID = "RPDF.kyijgnes.Document"                    # .pdf 연결
REG_KEY = r"Software\kyijgnes\RPDF"                  # 기본 앱 목록(Capabilities) 자리
REG_APP = "RPDF.kyijgnes"                            # RegisteredApplications 값 이름
ASSET = "RPDF"                                       # GitHub 에 올리는 파일 이름(영어로. 한글 이름은 GitHub 이 바꿔 버린다)
OLD_PROGID = "PDFEditor.kyijgnes.Document"           # 0.1.0~0.1.3 이 쓰던 이름들
OLD_REG_KEY = r"Software\kyijgnes\PDFEditor"
OLD_REG_APP = "PDFEditor.kyijgnes"
OLD_MUTEX = "PDFEditor.kyijgnes.Running"             # 0.1.3 이하에서 업데이트할 때 그 앱이 꺼지기를 기다리려고
LEGACY_ID = "PDF편집기"                              # 10-19 손 설치(dist 를 가리키던 바로 가기·Software\PDF편집기)를 걷을 때


def die(msg: str):
    print(f"\n[멈춤] {msg}", flush=True)
    sys.exit(1)


def read_info(root: str) -> dict:
    return runpy.run_path(os.path.join(root, "app", "appinfo.py"))


def find_iscc() -> str:
    for p in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
              r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe",
              shutil.which("iscc") or ""):
        if p and os.path.exists(p):
            return p
    die("Inno Setup 6 이 없습니다: winget install JRSoftware.InnoSetup --override \"/VERYSILENT /CURRENTUSER\"")


def iss_str(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def setup_name(version: str) -> str:
    return f"{ASSET}-setup-{version}.exe"


def make_setup(root: str, out: str | None = None) -> str:
    info = read_info(root)
    version = info["VERSION"]
    dist = os.path.join(root, "dist", info["APP_ID"])
    if not os.path.isdir(dist):
        die(f"빌드 결과가 없습니다(먼저 build.py): {dist}")
    out = out or os.path.join(HERE, "release", version)
    os.makedirs(out, exist_ok=True)
    defs = {
        "AppName": info["APP_NAME"], "AppIdName": info["APP_ID"], "AppVersion": version, "Org": info["ORG"],
        "AppGuid": INNO_GUID, "ProgId": PROGID, "RegKey": REG_KEY, "RegKeyParent": REG_KEY.rsplit("\\", 1)[0],
        "RegAppName": REG_APP, "AppMutex": MUTEX_NAME, "LegacyId": LEGACY_ID,
        "OldProgId": OLD_PROGID, "OldRegKey": OLD_REG_KEY, "OldRegApp": OLD_REG_APP, "OldMutex": OLD_MUTEX,
        "SourceDir": dist, "OutputDir": out, "OutputBase": setup_name(version)[:-4],
    }
    icon = os.path.join(root, "assets", "app.ico")
    if os.path.exists(icon):
        defs["AppIcon"] = icon
    with open(os.path.join(root, "installer", "defs.iss"), "w", encoding="utf-8-sig") as f:
        f.write("; make_setup.py 가 적는다. 고치지 말 것\n")
        for k, v in defs.items():
            f.write(f"#define {k} {iss_str(v)}\n")
    print("== 설치 프로그램 만들기(Inno Setup)", flush=True)
    r = subprocess.call([find_iscc(), "/Qp", os.path.join(root, "installer", "setup.iss")])
    setup = os.path.join(out, setup_name(version))
    if r or not os.path.exists(setup):
        die(f"Inno Setup 실패 (돌려준 값 {r})")
    write_latest(setup, version)
    print(f"  {setup} ({os.path.getsize(setup) / 1048576:.0f} MB)", flush=True)
    return setup


def write_latest(setup: str, version: str) -> str:
    h = hashlib.sha256()
    with open(setup, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    name = os.path.basename(setup)
    data = {"app": "RPDF", "version": version, "setup": name,
            "url": f"https://github.com/{RELEASE_REPO}/releases/download/v{version}/{name}",
            "sha256": h.hexdigest(), "size": os.path.getsize(setup),
            "date": f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M} UTC"}
    path = os.path.join(os.path.dirname(setup), "latest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="RPDF 설치 프로그램 만들기")
    ap.add_argument("--root", default=HERE, help="dist·installer·app 이 있는 폴더(기본: 이 폴더)")
    ap.add_argument("--out", help="결과 자리(기본: release\\<버전>)")
    a = ap.parse_args()
    make_setup(os.path.abspath(a.root), a.out and os.path.abspath(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

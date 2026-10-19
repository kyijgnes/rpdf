"""PDF 앱 새 버전 내기: 버전 올리기 → HEAD 사본 빌드(PyInstaller) → 설치 프로그램(Inno Setup) → GitHub 릴리스에 올리기.

    python release.py                         끝자리 +1 (0.1.0 → 0.1.1) 로 올려 내놓는다
    python release.py 0.2.0                   그 버전으로
    python release.py --build-only            빌드·설치 프로그램만(git·GitHub 안 건드림)
    python release.py --build-only --as 0.0.1 빌드 사본 안의 버전만 바꿔서(시험용, appinfo.py 그대로)
    python release.py --setup-only            지난 빌드로 설치 프로그램만 다시(setup.iss 를 고칠 때, 작업 트리의 setup.iss 를 씀)
    python release.py --upload 0.1.1          release\\0.1.1 에 만들어 둔 것을 올리기만(올리다 끊겼을 때·시험 버전)

- 이름·버전은 app/appinfo.py 한 곳. 버전은 여기서만 올린다(세 자리). 올린 줄만 따로 커밋하고, 다 올라가면 git 태그 vX.Y.Z.
- 빌드는 작업 트리가 아니라 **HEAD 를 꺼낸 사본**(%TEMP%\\PDFEditor_release\\src)에서 한다. 커밋 안 한 것은 실리지 않는다.
- 빌드는 한 번에 한 세션(공용 규칙 ③): 작업 보드(`코딩\\.claude\\작업중`)에 `_PDF앱 빌드중.md` 를 잡고 끝나면 지운다.
- 결과물은 release\\<버전>\\ (git 밖): PDFEditor-setup-<버전>.exe · latest.json. 정식 릴리스는 main 에서만.
- 올리는 곳은 GitHub 공개 저장소(app/updater.py 의 RELEASE_REPO). 앱의 「업데이트 확인」은 releases/latest 의 latest.json 을 본다.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from app.updater import LATEST_URL, MUTEX_NAME, RELEASE_REPO, parse_version  # noqa: E402

# ── 바꾸지 않는 열쇠. 앱 이름을 바꿔도 그대로 둬야 같은 앱으로 이어진다(바꾸면 따로 깔린다) ──
INNO_GUID = "A5A02529-0CA9-4430-A2AD-3140C6CEEFAC"   # 설치 정보(설정 > 앱) 열쇠
PROGID = "PDFEditor.kyijgnes.Document"               # .pdf 연결. 10-19 손 설치 때 정한 것
REG_KEY = r"Software\kyijgnes\PDFEditor"             # 기본 앱 목록(Capabilities) 자리
REG_APP = "PDFEditor.kyijgnes"                       # RegisteredApplications 값 이름
ASSET = "PDFEditor"                                  # GitHub 에 올리는 파일 이름(한글 이름은 GitHub 이 바꿔 버린다)
LEGACY_ID = "PDF편집기"                              # 10-19 손 설치(dist 를 가리키던 바로 가기·Software\PDF편집기)를 걷을 때

WORK = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "Temp", "PDFEditor_release")
SRC = os.path.join(WORK, "src")
OUT = os.path.join(HERE, "release")
APPINFO = os.path.join("app", "appinfo.py")
VERSION_RE = re.compile(r'^(VERSION\s*=\s*")([^"]*)(")', re.M)
LOCK_NAME = "_PDF앱 빌드중.md"
KEEP_LOCAL = 3   # release\ 에 남길 버전 수


def die(msg: str):
    print(f"\n[멈춤] {msg}")
    sys.exit(1)


def step(msg: str):
    print(f"\n== {msg}", flush=True)


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode:
        die(f"git {' '.join(args)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def read_info(root: str) -> dict:
    return runpy.run_path(os.path.join(root, APPINFO))


def set_version(root: str, version: str):
    path = os.path.join(root, APPINFO)
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    text, n = VERSION_RE.subn(rf"\g<1>{version}\g<3>", text, count=1)
    if n != 1:
        die(f"{path} 에서 VERSION = \"…\" 줄을 못 찾았습니다")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def check_version(v: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        die(f"버전은 세 자리 숫자로: {v}")
    return v


def bump(v: str) -> str:
    a, b, c = parse_version(v)
    return f"{a}.{b}.{c + 1}"


# ── 잠금(작업 보드) ─────────────────────────────────────────────
def board_dir() -> str | None:
    d = HERE
    while True:
        cand = os.path.join(d, ".claude", "작업중")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


class Lock:
    def __init__(self, what: str):
        self.what = what
        b = board_dir()
        self.path = os.path.join(b, LOCK_NAME) if b else None

    def __enter__(self):
        if not self.path:
            print("(작업 보드를 못 찾아 잠금 없이 진행)")
            return self
        try:
            with open(self.path, "x", encoding="utf-8") as f:
                f.write(f"앱: PDF 앱\n하는 일: {self.what} (release.py, pid {os.getpid()})\n"
                        f"폴더: {HERE}\n시작: {datetime.datetime.now():%m-%d %H:%M}\n")
        except FileExistsError:
            with open(self.path, encoding="utf-8") as f:
                held = f.read()
            die(f"다른 빌드가 돌고 있습니다. 끝나길 기다렸다 다시 하세요.\n{self.path}\n{held}"
                "\n(시작이 한참 전이고 python 이 안 돌면 죽은 것이니 그 파일을 지우고 다시)")
        return self

    def __exit__(self, *exc):
        if self.path and os.path.exists(self.path):
            os.remove(self.path)


# ── 빌드 ────────────────────────────────────────────────────────
def export_head():
    step("HEAD 를 사본으로 꺼내기")
    shutil.rmtree(SRC, ignore_errors=True)
    os.makedirs(SRC)
    data = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=HERE, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(SRC, filter="data")
    print(f"  {git('rev-parse', '--short', 'HEAD')} → {SRC}")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        print("  (커밋 안 한 변경은 실리지 않음)\n  " + dirty.replace("\n", "\n  "))


def build(info: dict):
    step("PyInstaller 빌드(3분쯤)")
    r = subprocess.call([sys.executable, "build.py"], cwd=SRC)
    exe = os.path.join(SRC, "dist", info["APP_ID"], info["APP_ID"] + ".exe")
    if r or not os.path.exists(exe):
        die(f"빌드 실패 (돌려준 값 {r})")
    for d, _, files in os.walk(os.path.join(SRC, "build")):
        for n in files:
            if n.startswith("warn-") and n.endswith(".txt"):
                with open(os.path.join(d, n), encoding="utf-8", errors="replace") as f:
                    bad = [ln for ln in f if "invalid module named" in ln]
                if bad:
                    print(f"  [주의] {n} 에 invalid module named {len(bad)}줄")


def find_iscc() -> str:
    for p in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
              r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe",
              shutil.which("iscc") or ""):
        if p and os.path.exists(p):
            return p
    die("Inno Setup 6 이 없습니다: winget install JRSoftware.InnoSetup --override \"/VERYSILENT /CURRENTUSER\"")


def iss_str(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def make_setup(info: dict, use_tree_iss: bool = False) -> str:
    step("설치 프로그램 만들기(Inno Setup)")
    version = info["VERSION"]
    dist = os.path.join(SRC, "dist", info["APP_ID"])
    if not os.path.isdir(dist):
        die(f"빌드 결과가 없습니다: {dist}")
    if use_tree_iss:
        shutil.copy2(os.path.join(HERE, "installer", "setup.iss"), os.path.join(SRC, "installer", "setup.iss"))
    out = os.path.join(OUT, version)
    os.makedirs(out, exist_ok=True)
    defs = {
        "AppName": info["APP_NAME"], "AppIdName": info["APP_ID"], "AppVersion": version, "Org": info["ORG"],
        "AppGuid": INNO_GUID, "ProgId": PROGID, "RegKey": REG_KEY, "RegKeyParent": REG_KEY.rsplit("\\", 1)[0],
        "RegAppName": REG_APP, "AppMutex": MUTEX_NAME, "LegacyId": LEGACY_ID,
        "SourceDir": dist, "OutputDir": out, "OutputBase": f"{ASSET}-setup-{version}",
    }
    icon = os.path.join(SRC, "assets", "app.ico")
    if os.path.exists(icon):
        defs["AppIcon"] = icon
    with open(os.path.join(SRC, "installer", "defs.iss"), "w", encoding="utf-8-sig") as f:
        f.write("; release.py 가 적는다. 고치지 말 것\n")
        for k, v in defs.items():
            f.write(f"#define {k} {iss_str(v)}\n")
    r = subprocess.call([find_iscc(), "/Qp", os.path.join(SRC, "installer", "setup.iss")])
    setup = os.path.join(out, defs["OutputBase"] + ".exe")
    if r or not os.path.exists(setup):
        die(f"Inno Setup 실패 (돌려준 값 {r})")
    print(f"  {setup} ({os.path.getsize(setup) / 1048576:.0f} MB)")
    return setup


def notes_since_last_tag() -> list[str]:
    last = git("describe", "--tags", "--abbrev=0", "--match", "v*", check=False)
    rng = f"{last}..HEAD" if last else "HEAD"
    subs = git("log", "--format=%s", rng, check=False).splitlines()
    return [s for s in subs if not re.fullmatch(r"버전 \d+\.\d+\.\d+", s)][:15]


def write_latest(setup: str, version: str, notes: list[str]) -> str:
    h = hashlib.sha256()
    with open(setup, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    name = os.path.basename(setup)
    data = {"version": version, "setup": name,
            "url": f"https://github.com/{RELEASE_REPO}/releases/download/v{version}/{name}",
            "sha256": h.hexdigest(), "size": os.path.getsize(setup),
            "date": f"{datetime.datetime.now():%Y-%m-%d %H:%M}", "notes": notes}
    path = os.path.join(os.path.dirname(setup), "latest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return path


def prune_local():
    if not os.path.isdir(OUT):
        return
    vers = sorted((d for d in os.listdir(OUT) if re.fullmatch(r"\d+\.\d+\.\d+", d)), key=parse_version)
    for d in vers[:-KEEP_LOCAL]:
        shutil.rmtree(os.path.join(OUT, d), ignore_errors=True)


# ── 올리기 ──────────────────────────────────────────────────────
def remote_latest() -> str | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(LATEST_URL, headers={"Cache-Control": "no-cache"}), timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))["version"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def upload(version: str):
    folder = os.path.join(OUT, version)
    latest = os.path.join(folder, "latest.json")
    setup = os.path.join(folder, f"{ASSET}-setup-{version}.exe")
    if not (os.path.exists(latest) and os.path.exists(setup)):
        die(f"올릴 것이 없습니다: {folder}")
    with open(latest, encoding="utf-8") as f:
        meta = json.load(f)
    info = read_info(HERE)
    step(f"GitHub 에 올리기: {RELEASE_REPO} v{version}")
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode:
        die("gh 로그인이 안 돼 있습니다: gh auth login")
    tag = f"v{version}"
    if subprocess.run(["gh", "release", "view", tag, "--repo", RELEASE_REPO], capture_output=True).returncode == 0:
        die(f"이미 올라가 있습니다: {tag}")
    body = "\n".join(f"- {n}" for n in meta.get("notes") or []) or "-"
    body += ("\n\n처음 설치: 아래 `" + os.path.basename(setup) + "` 를 받아 실행.\n"
             "설치돼 있으면 앱의 파일 > 업데이트 확인(켤 때도 저절로 봄).")
    notes_file = os.path.join(WORK, "notes.md")
    os.makedirs(WORK, exist_ok=True)
    with open(notes_file, "w", encoding="utf-8") as f:
        f.write(body)
    r = subprocess.call(["gh", "release", "create", tag, setup, latest, "--repo", RELEASE_REPO,
                         "--title", f"{info['APP_NAME']} {version}", "--notes-file", notes_file, "--latest"])
    if r:
        die(f"올리기 실패. 다시: python release.py --upload {version}")
    got = remote_latest()
    print(f"  releases/latest 의 버전: {got}" + ("" if got == version else "  (아직 안 바뀜. 몇 초 뒤 다시 확인)"))


# ── 흐름 ────────────────────────────────────────────────────────
def release(target: str | None, any_branch: bool):
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main" and not any_branch:
        die(f"정식 릴리스는 main 에서 합니다(지금 {branch}). 시험이면 --build-only")
    cur = read_info(HERE)["VERSION"]
    target = check_version(target or bump(cur))
    if git("status", "--porcelain", "--", APPINFO):
        die(f"{APPINFO} 에 커밋 안 한 변경이 있습니다. 먼저 커밋하세요")
    if git("tag", "--list", f"v{target}"):
        die(f"v{target} 은 이미 냈습니다")
    if parse_version(target) < parse_version(cur):
        die(f"지금 버전({cur})보다 낮습니다: {target}")
    online = remote_latest()
    if online and parse_version(target) <= parse_version(online):
        die(f"GitHub 에 이미 {online} 이 있습니다. 그보다 높게: python release.py {bump(online)}")
    with Lock(f"릴리스 {target}"):
        if cur != target:
            step(f"버전 {cur} → {target}")
            set_version(HERE, target)
            git("commit", "-m", f"버전 {target}", "--", APPINFO)
        export_head()
        info = read_info(SRC)
        if info["VERSION"] != target:
            die(f"사본의 버전이 {info['VERSION']} 입니다(HEAD 에 {target} 이 안 들어감)")
        build(info)
        setup = make_setup(info)
        write_latest(setup, target, notes_since_last_tag())
    upload(target)
    git("tag", f"v{target}")
    prune_local()
    print(f"\n끝: {info['APP_NAME']} {target} · 태그 v{target} · https://github.com/{RELEASE_REPO}/releases/tag/v{target}")


def build_only(as_version: str | None):
    with Lock("시험 빌드"):
        export_head()
        if as_version:
            set_version(SRC, check_version(as_version))
        info = read_info(SRC)
        build(info)
        setup = make_setup(info)
        write_latest(setup, info["VERSION"], [f"시험 빌드 {git('rev-parse', '--short', 'HEAD')}"])
    print(f"\n끝: {setup}\n올리려면: python release.py --upload {info['VERSION']}")


def setup_only():
    with Lock("설치 프로그램만 다시"):
        if not os.path.isdir(os.path.join(SRC, "dist")):
            die("지난 빌드가 없습니다. 먼저 --build-only")
        info = read_info(SRC)
        setup = make_setup(info, use_tree_iss=True)
        write_latest(setup, info["VERSION"], [f"시험 빌드 {git('rev-parse', '--short', 'HEAD')}"])
    print(f"\n끝: {setup}")


def main() -> int:
    ap = argparse.ArgumentParser(description="PDF 앱 새 버전 내기")
    ap.add_argument("version", nargs="?", help="올릴 버전(세 자리). 빼면 끝자리 +1")
    ap.add_argument("--build-only", action="store_true", help="빌드·설치 프로그램만")
    ap.add_argument("--as", dest="as_version", help="--build-only 와 같이: 사본 안 버전만 바꾼다(시험용)")
    ap.add_argument("--setup-only", action="store_true", help="지난 빌드로 설치 프로그램만 다시")
    ap.add_argument("--upload", metavar="버전", help="release\\<버전> 을 올리기만")
    ap.add_argument("--any-branch", action="store_true", help="main 이 아니어도 정식 릴리스")
    a = ap.parse_args()
    os.chdir(HERE)
    if a.upload:
        upload(check_version(a.upload))
    elif a.setup_only:
        setup_only()
    elif a.build_only:
        build_only(a.as_version)
    else:
        release(a.version, a.any_branch)
    return 0


if __name__ == "__main__":
    sys.exit(main())

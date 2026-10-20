"""RPDF 새 버전 내기(클로드 쿨다운과 같은 방식): 버전 올리기 → 빈 annotated 태그 → push → GitHub Actions 가 빌드·설치 프로그램·릴리스.

    python release.py                         끝자리 +1 (0.1.0 → 0.1.1) 로 올려 내놓는다
    python release.py 0.2.0                   그 버전으로
    python release.py --counts                릴리스 내려받은 횟수를 적고 합계를 보여 준다
    python release.py --prune                 횟수를 적은 뒤 최신 릴리스 하나만 남기고 옛 릴리스를 지운다(태그는 남김)
    python release.py --build-only            이 PC 에서 HEAD 사본으로 빌드·설치 프로그램만(git·GitHub 안 건드림, 시험용)
    python release.py --build-only --as 0.0.1 사본 안의 버전만 바꿔서(시험용, appinfo.py 그대로)

- 이름·버전은 app/appinfo.py 한 곳. 버전은 여기서만 올린다(세 자리). 올린 줄만 따로 커밋(`버전 X.Y.Z`).
- 태그는 `git tag -a vX.Y.Z -m ""`(annotated·빈 메시지). lightweight 면 GitHub 이 릴리스 페이지에 커밋 메시지를 띄운다.
- 빌드는 이 PC 가 아니라 GitHub Actions(.github/workflows/release.yml, windows 러너)가 태그의 커밋으로 한다.
  **커밋 안 한 것은 실리지 않는다.** 릴리스에는 setup 과 latest.json 만, 본문(릴리스 노트)은 비운다.
- 정식 릴리스는 main 에서만(`--any-branch` 로 풀 수 있다). 다 올라가면 횟수를 적고 옛 릴리스를 지운다(--prune 과 같은 일).
- --build-only 는 이 PC 에서 빌드하므로 한 번에 한 세션(공용 규칙 ③): 작업 보드에 `_PDF앱 빌드중.md` 를 잡고 끝나면 지운다.
"""
from __future__ import annotations

import argparse
import datetime
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
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from app.updater import LATEST_URL, RELEASE_REPO, parse_version  # noqa: E402

WORKFLOW = "release.yml"
WORK = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "Temp", "RPDF_release")
SRC = os.path.join(WORK, "src")
APPINFO = os.path.join("app", "appinfo.py")
VERSION_RE = re.compile(r'^(VERSION\s*=\s*")([^"]*)(")', re.M)
LOCK_NAME = "_PDF앱 빌드중.md"
COUNTS = os.path.join(os.path.expanduser("~"), ".rpdf_downloads.json")   # 집 폴더라 저장소에 안 섞인다


def die(msg: str):
    print(f"\n[멈춤] {msg}", flush=True)
    sys.exit(1)


def step(msg: str):
    print(f"\n== {msg}", flush=True)


def run(cmd: list[str], check: bool = True) -> str:
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        die(f"{' '.join(cmd)}\n{(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def git(*args: str, check: bool = True) -> str:
    return run(["git", *args], check)


def gh(*args: str, check: bool = True) -> str:
    return run(["gh", *args], check)


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


def remote_latest() -> str | None:
    try:
        req = urllib.request.Request(LATEST_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))["version"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


# ── 내려받은 횟수 · 옛 릴리스 지우기 ─────────────────────────────
# GitHub 은 릴리스를 지우면 내려받은 횟수도 같이 지운다. 그래서 적고 나서 지운다(쿨다운 cooldown_release.py 와 같은 일).
def fetch_releases() -> list[dict]:
    raw = gh("api", f"repos/{RELEASE_REPO}/releases?per_page=100")
    return [{"tag": r["tag_name"], "published": r.get("published_at") or r.get("created_at"),
             "assets": {a["name"]: int(a["download_count"]) for a in r.get("assets", [])}}
            for r in json.loads(raw)]


def record_counts() -> list[dict]:
    try:
        with open(COUNTS, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {"releases": {}}
    rels = fetch_releases()
    for r in rels:
        old = data["releases"].setdefault(r["tag"], {"published": r["published"], "assets": {}})
        for name, n in r["assets"].items():
            old["assets"][name] = max(n, int(old["assets"].get(name, 0)))   # 줄지 않는다
    data["updated"] = f"{datetime.datetime.now():%Y-%m-%d %H:%M}"
    with open(COUNTS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    step(f"내려받은 횟수(setup 기준, {COUNTS})")
    total = 0
    for tag in sorted(data["releases"], key=parse_version):
        n = sum(v for k, v in data["releases"][tag]["assets"].items() if k.endswith(".exe"))
        total += n
        print(f"  {tag:10} {n}")
    print(f"  합계       {total}")
    return rels


def prune():
    rels = record_counts()
    if not rels:
        return
    keep = max(rels, key=lambda r: parse_version(r["tag"]))["tag"]
    old = [r["tag"] for r in rels if r["tag"] != keep]
    if not old:
        print(f"  지울 옛 릴리스 없음(남은 것 {keep})")
        return
    step(f"옛 릴리스 지우기: {', '.join(old)} (남길 것 {keep}, 태그는 그대로)")
    for tag in old:
        gh("release", "delete", tag, "--repo", RELEASE_REPO, "--yes")
        print(f"  {tag} 지움")


# ── 내놓기 ──────────────────────────────────────────────────────
def find_run(tag: str) -> str | None:
    for _ in range(30):   # 태그를 밀고 워크플로가 뜨기까지 몇 초 걸린다
        raw = gh("run", "list", "--repo", RELEASE_REPO, "--workflow", WORKFLOW, "--limit", "10",
                 "--json", "databaseId,headBranch,createdAt", check=False)
        for r in json.loads(raw or "[]"):
            if r["headBranch"] == tag:
                return str(r["databaseId"])
        time.sleep(5)
    return None


def release(target: str | None, any_branch: bool):
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main" and not any_branch:
        die(f"정식 릴리스는 main 에서 합니다(지금 {branch}). 시험이면 --build-only")
    if not git("remote", "get-url", "origin", check=False):
        die(f"git 원격 origin 이 없습니다: git remote add origin https://github.com/{RELEASE_REPO}.git")
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode:
        die("gh 로그인이 안 돼 있습니다: gh auth login")
    cur = read_info(HERE)["VERSION"]
    target = check_version(target or bump(cur))
    tag = f"v{target}"
    if git("status", "--porcelain", "--", APPINFO):
        die(f"{APPINFO} 에 커밋 안 한 변경이 있습니다. 먼저 커밋하세요")
    if git("tag", "--list", tag) or git("ls-remote", "--tags", "origin", f"refs/tags/{tag}"):
        die(f"{tag} 은 이미 냈습니다")
    if parse_version(target) < parse_version(cur):
        die(f"지금 버전({cur})보다 낮습니다: {target}")
    online = remote_latest()
    if online and parse_version(target) <= parse_version(online):
        die(f"GitHub 에 이미 {online} 이 있습니다. 그보다 높게: python release.py {bump(online)}")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        print("(커밋 안 한 변경은 실리지 않음)\n  " + dirty.replace("\n", "\n  "))

    if cur != target:
        step(f"버전 {cur} → {target}")
        set_version(HERE, target)
        git("commit", "-m", f"버전 {target}", "--", APPINFO)
    step(f"태그 {tag}(annotated·빈 메시지) 밀기")
    git("tag", "-a", tag, "-m", "")
    git("push", "origin", branch)
    git("push", "origin", tag)

    step("GitHub Actions 가 빌드·설치 프로그램·릴리스(10분쯤)")
    rid = find_run(tag)
    if not rid:
        die(f"워크플로가 안 떴습니다. https://github.com/{RELEASE_REPO}/actions 에서 확인")
    print(f"  https://github.com/{RELEASE_REPO}/actions/runs/{rid}", flush=True)
    if subprocess.call(["gh", "run", "watch", rid, "--repo", RELEASE_REPO, "--exit-status", "--interval", "20"]):
        die(f"워크플로 실패. 로그: gh run view {rid} --repo {RELEASE_REPO} --log-failed\n"
            f"고친 뒤 태그를 지우고(git push origin :{tag} · git tag -d {tag}) 다시 python release.py {target}")
    for _ in range(12):
        got = remote_latest()
        if got == target:
            break
        time.sleep(5)
    print(f"  releases/latest 의 버전: {got}" + ("" if got == target else "  (아직 안 바뀜. 몇 초 뒤 다시 확인)"))
    prune()
    print(f"\n끝: {tag} · https://github.com/{RELEASE_REPO}/releases/tag/{tag}")


# ── 이 PC 에서 시험 빌드 ────────────────────────────────────────
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


def export_head():
    step("HEAD 를 사본으로 꺼내기")
    shutil.rmtree(SRC, ignore_errors=True)
    os.makedirs(SRC)
    data = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=HERE, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(SRC, filter="data")
    print(f"  {git('rev-parse', '--short', 'HEAD')} → {SRC}")


def build_only(as_version: str | None):
    with Lock("시험 빌드"):
        export_head()
        if as_version:
            set_version(SRC, check_version(as_version))
        version = read_info(SRC)["VERSION"]
        step("PyInstaller 빌드(3분쯤)")
        if subprocess.call([sys.executable, "build.py"], cwd=SRC):
            die("빌드 실패")
        out = os.path.join(HERE, "release", version)
        if subprocess.call([sys.executable, os.path.join(SRC, "make_setup.py"), "--root", SRC, "--out", out], cwd=SRC):
            die("설치 프로그램 실패")
    print(f"\n끝: {out}\n시험: PDFAPP_UPDATE_SOURCE={out} 로 설치본을 켜면 그 자리를 본다")


def main() -> int:
    ap = argparse.ArgumentParser(description="RPDF 새 버전 내기")
    ap.add_argument("version", nargs="?", help="올릴 버전(세 자리). 빼면 끝자리 +1")
    ap.add_argument("--counts", action="store_true", help="내려받은 횟수 적기·보기")
    ap.add_argument("--prune", action="store_true", help="횟수를 적고 옛 릴리스 지우기")
    ap.add_argument("--build-only", action="store_true", help="이 PC 에서 빌드·설치 프로그램만(시험)")
    ap.add_argument("--as", dest="as_version", help="--build-only 와 같이: 사본 안 버전만 바꾼다(시험용)")
    ap.add_argument("--any-branch", action="store_true", help="main 이 아니어도 정식 릴리스")
    a = ap.parse_args()
    os.chdir(HERE)
    if a.counts:
        record_counts()
    elif a.prune:
        prune()
    elif a.build_only:
        build_only(a.as_version)
    else:
        release(a.version, a.any_branch)
    return 0


if __name__ == "__main__":
    sys.exit(main())

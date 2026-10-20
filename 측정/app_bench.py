"""앱 안에서 동작마다 시간 재기. 창을 실제로 띄우고 MainWindow 의 함수를 그대로 부른다.

- 「걸림」: 함수가 UI 스레드에서 돈 시간(그동안 화면이 멈춘다)
- 「끝까지」: 화면에 다 그려질 때까지(일꾼 스레드 포함)
- 「최대 멈춤」: 그동안 10ms 타이머가 못 돈 가장 긴 틈(일꾼이 GIL·잠금을 잡아 UI 가 밀린 것 포함)

APPDATA 를 임시 폴더로 바꿔 사용자 설정을 건드리지 않는다. 문서는 사본(docs.py)만 쓴다.
python 측정/app_bench.py big_b4 [small_b4 scan ...]
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="rpdf_bench_")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import fitz  # noqa: E402
import psutil  # noqa: E402
from PySide6.QtCore import QElapsedTimer, QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import docs  # noqa: E402

PROC = psutil.Process()
app = QApplication(sys.argv[:1])
app.setFont(QFont("Malgun Gothic", 9))
t = time.perf_counter()
from app.engine import annots as A  # noqa: E402
from app.ui.viewer import Selection  # noqa: E402
from app.ui.window import MainWindow  # noqa: E402
IMPORT_S = time.perf_counter() - t


class Stall:
    """UI 스레드가 얼마나 오래 못 돌았나: 10ms 타이머의 틈 가운데 가장 긴 것."""
    def __init__(self):
        self.timer = QTimer(); self.timer.setInterval(10); self.timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer(); self.gaps: list[float] = []

    def _tick(self):
        self.gaps.append(self.clock.restart() / 1000)

    def start(self):
        self.gaps = []; self.clock.start(); self.timer.start()

    def stop(self):
        self.timer.stop()
        self._tick()
        g = self.gaps
        return {"max_stall": round(max(g), 3) if g else 0, "stall_over_50ms": round(sum(x for x in g if x > 0.05), 3)}


ST = Stall()


def flush_deletes():
    """deleteLater 는 이벤트 루프(app.exec)로 돌아갈 때 지운다. 이 측정은 exec 없이 processEvents 만 돌려 그대로 두면
    닫은 탭이 안 지워진 채 남아 메모리가 새는 것처럼 보인다. 앱이 하는 대로 지금 지운다."""
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def pump(sec: float):
    end = time.perf_counter() + sec
    while time.perf_counter() < end:
        app.processEvents(); time.sleep(0.002)


def wait(cond, timeout=60.0) -> float:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        app.processEvents()
        if cond():
            return time.perf_counter() - t0
        time.sleep(0.002)
    return float("nan")


def rendered(v) -> bool:
    vis = v.visible_pages()
    return bool(vis) and all(v.items[i].pm is not None and v.items[i].pm_zoom == v.zoom for i in vis)


def measure(name, fn, done=None, timeout=120.0, out=None):
    """fn 을 UI 스레드에서 부르고(걸림), done() 이 참이 될 때까지 기다린다(끝까지)."""
    ST.start()
    t0 = time.perf_counter()
    r = fn()
    sync = time.perf_counter() - t0
    total = sync
    if done is not None:
        pump(0.12)  # 앱이 거는 짧은 타이머(창 맞춤 80ms 등)가 돌게
        w = wait(done, timeout)
        total = time.perf_counter() - t0 if w == w else float("nan")
    st = ST.stop()
    row = {"동작": name, "걸림": round(sync, 3), "끝까지": round(total, 3), **st,
           "rss_mb": round(PROC.memory_info().rss / 2**20)}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    if out is not None:
        out.append(row)
    return r


def common_word(doc) -> str:
    from collections import Counter
    c = Counter()
    for i in range(min(5, doc.page_count)):
        for w in doc.fitz[i].get_text("words"):
            if len(w[4]) >= 2 and not w[4].isdigit():
                c[w[4]] += 1
    return c.most_common(1)[0][0] if c else "the"


def bench(win: MainWindow, name: str) -> list[dict]:
    out: list[dict] = []
    src = docs.path(name)
    work = os.path.join(docs.DIR, f"{name}_work.pdf")
    import shutil
    shutil.copyfile(src, work)
    print(f"== {name}: {docs.SOURCES[name][1]}", flush=True)

    def tab():
        return win.cur()

    measure("열기 → 첫 화면", lambda: win.open_path(work), lambda: rendered(tab().viewer), out=out)
    t_ = tab(); v = t_.viewer; d = t_.doc
    thumbs_busy = lambda: t_.thumbs.thumbs.busy() or t_.organize.thumbs.busy()
    measure("열고 나서 썸네일·구성 일꾼이 다 그릴 때까지(숨은 패널)", lambda: None, lambda: not thumbs_busy(), out=out)

    # 쪽 넘기기: 한 화면씩 내려가며 그 화면이 다 그려질 때까지
    sb = v.verticalScrollBar()
    steps = []
    ST.start()
    for k in range(15):
        t0 = time.perf_counter()
        sb.setValue(sb.value() + v.viewport().height())
        wait(lambda: rendered(v), 20)
        steps.append(time.perf_counter() - t0)
    st = ST.stop()
    row = {"동작": "한 화면씩 내리기(15번, 한 번 평균)", "걸림": 0, "끝까지": round(sum(steps) / len(steps), 3), **st,
           "가장 느린 한 번": round(max(steps), 3), "rss_mb": round(PROC.memory_info().rss / 2**20)}
    print(json.dumps(row, ensure_ascii=False)); out.append(row)

    # 빠르게 굴리기: 16ms 마다 120px 씩 3초(휠을 계속 굴리는 것)
    ST.start()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 3:
        sb.setValue(sb.value() + 120)
        pump(0.016)
    pump(0.05)
    lag = wait(lambda: rendered(v), 20)
    st = ST.stop()
    row = {"동작": "휠 계속 굴리기 3초", "걸림": 0, "끝까지": round(lag, 3), **st, "rss_mb": round(PROC.memory_info().rss / 2**20)}
    print(json.dumps(row, ensure_ascii=False)); out.append(row)

    # 끝쪽까지 훑고 메모리(그린 그림을 버리지 않으면 쪽 수만큼 쌓인다)
    rss0 = PROC.memory_info().rss
    ST.start(); t0 = time.perf_counter()
    while sb.value() < sb.maximum() and v.current < 160:  # 959쪽을 다 훑으면 수 GB 가 쌓여 PC 가 버벅인다
        sb.setValue(sb.value() + v.viewport().height())
        wait(lambda: rendered(v), 20)
    st = ST.stop()
    held = sum(1 for it in v.items if it.pm is not None)
    mb = sum(it.pm.width() * it.pm.height() * 4 for it in v.items if it.pm is not None) / 2**20
    row = {"동작": "끝쪽까지 한 화면씩 훑기", "걸림": 0, "끝까지": round(time.perf_counter() - t0, 3), **st,
           "들고 있는 쪽 그림": held, "쪽 그림 MB": round(mb), "rss 늘어남 MB": round((PROC.memory_info().rss - rss0) / 2**20),
           "rss_mb": round(PROC.memory_info().rss / 2**20)}
    print(json.dumps(row, ensure_ascii=False)); out.append(row)

    v.goto(0); wait(lambda: rendered(v), 20)
    measure("끝 쪽으로 건너뛰기(End)", lambda: v.goto(d.page_count - 1), lambda: rendered(v), out=out)
    v.goto(0); wait(lambda: rendered(v), 20)
    measure("확대 한 번(120%)", lambda: v.zoom_in(), lambda: rendered(v), out=out)
    measure("Ctrl+휠 확대 5번 연달아", lambda: [v.set_zoom(v.zoom * 1.1) for _ in range(5)], lambda: rendered(v), out=out)
    measure("축소 6번 연달아", lambda: [v.zoom_out() for _ in range(6)], lambda: rendered(v), out=out)
    v.set_zoom_mode("fit_width"); wait(lambda: rendered(v), 20)
    measure("창 크기 바꾸기(1360→1000 폭, 창 너비 맞춤)", lambda: win.resize(1000, 820), lambda: rendered(v), out=out)
    win.resize(1360, 820); pump(0.2); wait(lambda: rendered(v), 20)

    lt = getattr(t_.thumbs, "thumbs", None)  # 고친 뒤: 보이는 칸만 그리는 LazyThumbs
    measure("썸네일 패널 열기 → 보이는 칸 다 그림", lambda: win.toggle_side("thumbs"),
            (lambda: bool(lt.have) and not lt.busy()) if lt else None, out=out)
    if lt:
        print("   그린 썸네일", len(lt.have), "/", d.page_count)
        lsb = t_.thumbs.list.verticalScrollBar()
        measure("썸네일 패널 맨 끝으로 → 보이는 칸 다 그림", lambda: lsb.setValue(lsb.maximum()),
                lambda: (d.page_count - 1) in lt.have and not lt.busy(), out=out)
        print("   그린 썸네일", len(lt.have), "/", d.page_count)
    win.toggle_side("thumbs")

    # 검색
    word = common_word(d)
    t_.search.edit.setText(word)
    measure(f"검색 「{word}」 전체", lambda: t_.search.run(), lambda: t_.search.count.text() != "찾는 중", out=out)
    print("   찾은 수", len(t_.search.hits))
    t_.search.edit.setText(""); t_.search.run()

    # 글자 선택(쪽 전체를 끌어 고름)
    v.words_cache.clear()
    pr = d.fitz[0].rect
    measure("글자 끌어 고르기(첫 쪽 전체, 처음)", lambda: v._select_words(0, pr, click=False, scene_pt=None), None, out=out)
    measure("글자 끌어 고르기(두 번째, 캐시)", lambda: v._select_words(0, pr, click=False, scene_pt=None), None, out=out)
    v.clear_selection()

    # 마우스 움직임 한 번에 드는 일
    import timeit
    i = v.current
    lk = timeit.timeit(lambda: d.fitz[i].get_links(), number=50) / 50
    tb = timeit.timeit(lambda: d.text_blocks(i), number=10) / 10
    row = {"동작": "마우스 한 번 움직일 때: 손 도구 링크 찾기 / 편집 모드 글자 덩어리", "걸림": round(lk, 4), "끝까지": round(tb, 4),
           "max_stall": 0, "stall_over_50ms": 0, "rss_mb": round(PROC.memory_info().rss / 2**20)}
    print(json.dumps(row, ensure_ascii=False)); out.append(row)
    measure("편집 모드 켜고 한 화면 다시 그리기", lambda: (win.on_action("edit_all_toggle"), v.viewport().repaint()), None, out=out)
    measure("편집 모드 끄기", lambda: win.on_action("edit_all_toggle"), None, out=out)

    # 주석: 네모 하나 넣기(되돌리기 사본 + 패널 새로 고침 + 다시 그리기)
    r = fitz.Rect(72, 72, 200, 150)

    def add_rect():
        A.rect(d, 0, r, (1, 0, 0), None, 1.5, 1.0, "")
        t_.changed([0])
    measure("주석 네모 넣기", add_rect, lambda: rendered(v), out=out)
    pg = d.fitz[0]  # 쪽을 붙잡고 있어야 주석을 읽을 수 있다(먼저 버리면 튕김)
    a = list(pg.annots())[-1]
    xref, ar = a.xref, fitz.Rect(a.rect)
    del a, pg
    v.sel = Selection("annot", 0, xref, ar + (30, 30, 30, 30))
    measure("주석 옮기기(놓을 때)", lambda: v._commit_move(), lambda: rendered(v), out=out)
    measure("되돌리기 사본 한 벌(snapshot)", lambda: d.snapshot(), None, out=out)
    print("   되돌리기 사본 크기 MB", round(len(d._undo[-1]) / 2**20, 1), "원본 MB", round(os.path.getsize(work) / 2**20, 1))
    measure("되돌리기", lambda: win.on_action("undo"), lambda: rendered(v), out=out)

    # 저장
    d.modified = True
    measure("저장(Ctrl+S)", lambda: win.save(t_), lambda: rendered(v), out=out)
    out2 = os.path.join(docs.DIR, f"{name}_saveas.pdf")
    measure("다른 이름으로 저장(경로 정해 둠)", lambda: (d.save(out2), t_.viewer.refresh_pages(None)), lambda: rendered(v), out=out)
    print("   저장 뒤 크기 MB", round(os.path.getsize(work) / 2**20, 2))

    # 쪽 구성
    measure("구성 탭 열기", lambda: win.on_ribbon_tab("page"), lambda: not thumbs_busy(), out=out)
    measure("구성: 첫 쪽 오른쪽 회전", lambda: win.pages_action("rotate_right", [0]), lambda: not thumbs_busy(), out=out)
    measure("구성: 끝 쪽 삭제", lambda: win.pages_action("delete", [d.page_count - 1]), lambda: not thumbs_busy(), out=out)
    order = list(range(d.page_count)); order.insert(0, order.pop(1))
    measure("구성: 끌어 옮기기(2쪽을 맨 앞으로)", lambda: t_.reorder(order), lambda: not thumbs_busy(), out=out)
    win.on_ribbon_tab("home"); wait(lambda: rendered(v), 20)
    measure("보기 화면에서 회전(썸네일 패널 닫힌 채)", lambda: win.pages_action("rotate_left", [0]), lambda: rendered(v) and not thumbs_busy(), out=out)

    d.modified = False
    measure("탭 닫기", lambda: win.close_tab(win.tabs.index(t_)), None, out=out)
    return out


def leak(win: MainWindow, name: str, n: int = 6) -> list[dict]:
    """큰 문서를 열고 화면 몇 개 훑고 닫기를 되풀이: 메모리가 계속 느나."""
    work = docs.path(name)
    rows = []
    for k in range(n):
        win.open_path(work)
        t_ = win.cur(); v = t_.viewer
        wait(lambda: rendered(v), 30)
        sb = v.verticalScrollBar()
        for _ in range(10):
            sb.setValue(sb.value() + v.viewport().height()); wait(lambda: rendered(v), 20)
        wait(lambda: not (t_.thumbs.thumbs.busy() or t_.organize.thumbs.busy()), 120)
        win.close_tab(win.tabs.index(t_))
        pump(0.3)
        import gc; flush_deletes(); gc.collect(); pump(0.2)
        rows.append(round(PROC.memory_info().rss / 2**20))
    row = {"동작": f"열고 닫기 {n}번(닫은 뒤 rss MB)", "값": rows}
    print(json.dumps(row, ensure_ascii=False))
    return [row]


def main():
    names = sys.argv[1:] or ["small_b4"]
    leak_name = None
    if names and names[-1].startswith("leak:"):
        leak_name = names.pop()[5:]
    t0 = time.perf_counter()
    win = MainWindow()
    win.show_initial()
    win.resize(1360, 820)
    t1 = time.perf_counter()
    wait(lambda: win.isVisible(), 5); pump(0.1)
    print(json.dumps({"동작": "창 만들기", "import": round(IMPORT_S, 3), "MainWindow": round(t1 - t0, 3),
                      "rss_mb": round(PROC.memory_info().rss / 2**20)}, ensure_ascii=False))
    res = {}
    for n in names:
        res[n] = bench(win, n)
    if leak_name:
        res["leak"] = leak(win, leak_name)
    with open(os.path.join(HERE, "결과_" + "_".join(sys.argv[1:]).replace(":", "-") + ".json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    win.close()


if __name__ == "__main__":
    main()

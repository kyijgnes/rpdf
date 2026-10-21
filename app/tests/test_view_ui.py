"""화면 틀·보기 시험(창을 offscreen 으로 띄움): 단축키 · 문서별 보기 기억 · 탭 메뉴 · 검색 「i/N」·하나씩 바꾸기 · 이전 보기 · 보이는 쪽 찾기.

python -m pytest app/tests/test_view_ui.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="rpdf_view_test_")   # 사용자 설정을 건드리지 않게

import fitz  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv[:1])

from app.ui import shortcuts as K  # noqa: E402
from app.ui.window import MainWindow  # noqa: E402


def pump(sec: float = 0.15):
    end = time.perf_counter() + sec
    while time.perf_counter() < end:
        app.processEvents(); time.sleep(0.005)


def make_pdf(path: str, n: int = 12, word: str = "사과"):
    d = fitz.open()
    for i in range(n):
        p = d.new_page(width=595 if i % 3 else 842, height=842 if i % 3 else 595)
        p.insert_font(fontname="malgun", fontfile=r"C:\Windows\Fonts\malgun.ttf")
        p.insert_text((72, 100), f"{i + 1}쪽 {word} 하나", fontsize=14, fontname="malgun")
        p.insert_text((72, 300), f"둘째 줄 {word} 둘", fontsize=14, fontname="malgun")
    d.save(path); d.close()


@pytest.fixture()
def win():
    w = MainWindow(); w.show(); w.resize(1200, 800); pump(0.05)
    yield w
    for t in list(w.tabs):
        t.doc.modified = False
    w.close(); pump(0.05)


@pytest.fixture()
def pdf():
    p = os.path.join(tempfile.mkdtemp(), "보기시험.pdf"); make_pdf(p)
    return p


def test_shortcut_table_defaults_like_alpdf():
    keys = K.current(None)
    assert keys["zoom_page"] == ["Ctrl+0"] and keys["zoom_width"] == ["Ctrl+2"] and keys["zoom_height"] == ["Ctrl+3"]
    assert keys["insert_blank"] == ["Ctrl+Shift+T"] and keys["thumbs"] == ["Ctrl+Shift+2"]
    assert not K.clashes(keys), K.clashes(keys)   # 기본 키끼리는 겹치지 않는다
    # 바꾼 것만 남고, 겹치면 찾는다
    mine = dict(keys); mine["zoom_page"] = ["Ctrl+9"]; mine["print"] = ["Ctrl+O"]
    assert K.diff(mine) == {"zoom_page": ["Ctrl+9"], "print": ["Ctrl+O"]}
    assert K.clashes(mine) == {"Ctrl+O": {"open", "print"}}
    assert K.current({"zoom_page": ["ctrl+9"], "모르는": ["F9"]})["zoom_page"] == ["Ctrl+9"]


def test_shortcuts_rebind(win, pdf):
    win.open_path(pdf); pump(0.2)
    acts = {sc.key().toString(): sc for sc in win._sc}
    assert "Ctrl+0" in acts and "Ctrl+2" in acts
    v = win.cur().viewer
    acts["Ctrl+0"].activated.emit(); assert v.zoom_mode == "fit_page"
    acts["Ctrl+2"].activated.emit(); assert v.zoom_mode == "fit_width"
    win.settings["hotkeys"] = {"zoom_page": ["Ctrl+9"]}; win._shortcuts()
    acts = {sc.key().toString(): sc for sc in win._sc}
    assert "Ctrl+0" not in acts
    acts["Ctrl+9"].activated.emit(); assert v.zoom_mode == "fit_page"
    assert win.key_text("zoom_page").strip() == "Ctrl+9"


def test_editor_values():
    ed = K.ShortcutEditor({"close": ["Ctrl+F4"]})
    assert ed.values() == {"close": ["Ctrl+F4"]}
    ed.reset(); assert ed.values() == {}


def test_view_state_remembered(win, pdf):
    win.open_path(pdf); pump(0.2)
    t = win.cur(); v = t.viewer
    v.set_layout_mode("facing_continuous")
    v.zoom_mode = "fixed"; v.set_zoom(1.5); pump(0.05)
    v.goto(7, 120); pump(0.05)
    page, y, _ = v.view_pos()
    win.close_tab(0); pump(0.05)
    saved = win._saved_view(pdf)
    assert saved["layout"] == "facing_continuous" and saved["mode"] == "fixed" and abs(saved["zoom"] - 1.5) < 1e-3
    win.open_path(pdf); pump(0.3)
    v2 = win.cur().viewer
    assert v2.layout_mode == "facing_continuous" and abs(v2.zoom - 1.5) < 1e-3
    assert v2.view_pos()[0] == page and abs(v2.view_pos()[1] - y) < 2


def test_tab_menu_close_others(win, pdf):
    other = os.path.join(os.path.dirname(pdf), "둘째.pdf"); make_pdf(other, 3)
    third = os.path.join(os.path.dirname(pdf), "셋째.pdf"); make_pdf(third, 3)
    for p in (pdf, other, third):
        win.open_path(p)
    pump(0.1)
    keep = win.tabs[1]
    assert win.close_tabs([x for x in win.tabs if x is not keep])
    assert win.tabs == [keep]


def test_history_back_forward(win, pdf):
    win.open_path(pdf); pump(0.2)
    v = win.cur().viewer
    v.goto(0, remember=False); pump(0.05)
    v.goto(5); pump(0.05); v.goto(9); pump(0.05)
    v.back(); assert v.current == 5
    v.back(); assert v.current == 0
    v.forward(); assert v.current == 5
    v.next_page(); assert not v._fwd or v.current == 6   # 한 쪽 넘기기는 기록하지 않는다


def test_search_count_and_replace_one(win, pdf):
    win.open_path(pdf); pump(0.2)
    t = win.cur(); s = t.search
    win.quick_search("사과")
    assert len(s.hits) == 24 and s.count.text() == "1/24"
    s.step(1); assert s.count.text() == "2/24"
    s.repl.setText("배")
    s.replace_one()   # 1쪽 둘째 줄을 바꾸고 다음(2쪽 첫 줄)으로
    assert len(s.hits) == 23 and s.count.text() == "2/23"
    assert s.results[s.current].page == 1
    assert "배" in t.doc.fitz[0].get_text()
    # 다른 쪽을 고치면 그 쪽만 다시 찾고 보기는 그대로
    v = t.viewer; v.goto(10, remember=False); pump(0.05)
    t.doc.snapshot(); t.doc.fitz[3].insert_text((72, 500), "x", fontsize=8); t.changed([3])
    assert v.current == 10 and len(s.hits) == 23


@pytest.mark.parametrize("layout", ["continuous", "facing_continuous"])
def test_visible_pages_matches_full_scan(win, pdf, layout):
    win.open_path(pdf); pump(0.2)
    v = win.cur().viewer
    v.set_layout_mode(layout); v.zoom_mode = "fixed"; v.set_zoom(0.6); pump(0.05)
    sb = v.verticalScrollBar()
    for val in range(0, sb.maximum() + 1, max(1, sb.maximum() // 23)):
        sb.setValue(val)
        vr = v.mapToScene(v.viewport().rect()).boundingRect()
        full = [it.index for it in v.items if it.isVisible() and it.sceneBoundingRect().intersects(vr)]
        assert v.visible_pages() == full, (val, full)


def test_zoom_steps(win, pdf):
    win.open_path(pdf); pump(0.2)
    v = win.cur().viewer
    v.zoom_mode = "fixed"; v.set_zoom(1.0)
    v.zoom_in(); assert abs(v.zoom - 1.25) < 1e-6
    v.zoom_out(); v.zoom_out(); assert abs(v.zoom - 0.75) < 1e-6
    v.set_zoom(0.9); v.zoom_in(); assert abs(v.zoom - 1.0) < 1e-6

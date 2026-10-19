"""화면 없이 창을 띄워 대화상자 없는 동작을 한 바퀴 돌려 본다. 예외가 나면 바로 알 수 있다.

python -m app.tests.smoke_ui
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import fitz  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def make_pdf(path: str):
    d = fitz.open()
    for i in range(4):
        p = d.new_page()
        p.insert_font(fontname="malgun", fontfile=r"C:\Windows\Fonts\malgun.ttf")
        p.insert_text((72, 100), f"{i + 1}쪽 제목 Title", fontsize=20, fontname="malgun")
        p.insert_text((72, 140), "본문 글자 body text PDF 편집기 시험", fontsize=11, fontname="malgun")
    d.save(path); d.close()


def main() -> int:
    app = QApplication([])
    from app.ui.window import MainWindow
    from app.engine import annots as A
    w = MainWindow(); w.show()
    pdf = os.path.join(tempfile.gettempdir(), "smoke_ui.pdf"); make_pdf(pdf)
    w.open_path(pdf)
    t = w.cur(); v = t.viewer
    bad = []

    def step(name, fn):
        print("..", name, flush=True)
        try:
            fn(); app.processEvents()
        except Exception:  # noqa: BLE001
            bad.append((name, traceback.format_exc()))

    for tab in ("home", "edit", "comment", "convert", "view", "page", "tools", "form", "protect", "home"):
        step(f"tab {tab}", lambda k=tab: w.ribbon.set_tab(k))
    for key in ("zoomin", "zoomout", "zoom_actual", "zoom_width", "zoom_height", "zoom_page", "layout_single", "layout_facing",
                "layout_facing_continuous", "layout_continuous", "canvas_white", "canvas_gray", "first", "last", "next", "prev",
                "thumbs", "bookmark", "comments", "attach", "search", "layers", "thumbs", "fullscreen", "fullscreen", "auto_bookmark",
                "rotate_view_cw", "rotate_view_ccw", "undo", "redo", "thumb_in", "thumb_out", "edit_all_toggle", "edit_all_toggle",
                "tool_hand", "tool_select", "form_reset", "recognize", "form_preview", "sign_clear"):
        step(f"action {key}", lambda k=key: w.on_action(k))
    for tool in ("hand", "select", "pencil", "eraser", "highlight", "areahl", "underline", "strike", "squiggly", "caret", "typewriter",
                 "textbox", "callout", "note", "rect", "oval", "line", "arrow", "polygon", "polyline", "cloud", "attach", "m_distance",
                 "m_perimeter", "m_area", "ocrarea", "redact", "snapshot", "ftext", "fcheck", "fradio", "fcombo", "flist", "fbutton",
                 "fimage", "fsign", "fdate", "crop", "link", "addtext", "hand"):
        step(f"tool {tool}", lambda k=tool: w.on_tool(k))
    for key, on in (("edit_all", True), ("edit_all", False), ("form_edit", True), ("form_edit", False), ("show_annots", False),
                    ("show_annots", True), ("read_mode", True), ("read_mode", False), ("dark", True), ("dark", False)):
        step(f"toggle {key}", lambda k=key, o=on: w.on_toggle(k, o))
    # 페이지 동작(대화상자 없는 것)
    for key, pages in (("rotate_left", [0]), ("rotate_right", [0]), ("duplicate", [1]), ("delete", [4]), ("reverse", []), ("reverse", []),
                       ("delete_blank", [])):
        step(f"pages {key}", lambda k=key, p=pages: w.pages_action(k, p))
    # 엔진 직접
    step("annot add", lambda: (A.rect(t.doc, 0, fitz.Rect(50, 50, 150, 150)), t.changed([0])))
    step("search", lambda: (t.search.edit.setText("PDF"), t.search.run()))
    step("undo/redo", lambda: (w.on_action("undo"), w.on_action("redo")))
    step("props panel", lambda: w.right_action("props"))
    step("fields panel", lambda: w.right_action("fields"))
    step("reorder", lambda: t.reorder(list(range(t.doc.page_count))[::-1]))
    step("save", lambda: t.doc.save(os.path.join(tempfile.gettempdir(), "smoke_ui_out.pdf")))
    # 엔진 변환 모듈 연결 확인
    def conv():
        from app.engine import convert as C, tools as T, ocr as O  # noqa: F401
        out = os.path.join(tempfile.gettempdir(), "smoke_ui_conv")
        os.makedirs(out, exist_ok=True)
        C.to_text(t.doc.fitz, os.path.join(out, "a.txt")); C.to_word(t.doc.fitz, os.path.join(out, "a.docx"))
        T.watermark(t.doc.fitz, text="시험"); T.header_footer(t.doc.fitz, footer_center="{page}/{total}")
    step("engine conv", conv)
    step("close tab", lambda: (setattr(t.doc, "modified", False), w.close_tab(0)))
    step("start page", lambda: w.start.set_mode("folder"))
    if bad:
        for n, tb in bad:
            print("FAIL", n); print(tb)
        return 1
    print("smoke ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

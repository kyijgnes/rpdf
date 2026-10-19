"""업데이트 화면 쪽: 상태줄 [새 버전 x 설치] 단추, 파일 메뉴 「업데이트 확인」, 받기·설치 흐름. 일은 app/updater.py.

켤 때 한 번 조용히 본다(설치본만). 새 버전이 있으면 상태줄에 단추만 띄우고, 누르면 받아서 조용히 설치한 뒤 다시 켠다.
"""
from __future__ import annotations

import os
import threading
import urllib.error

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from .. import updater as U
from ..appinfo import VERSION
from . import dialogs as D


class _Done(QObject):
    done = Signal(object, object, str)   # Release 또는 None, 사람이 눌렀나, 실패 글


def _why(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError) and e.code == 404:
        return "배포 자리에 올린 버전이 아직 없습니다"
    if isinstance(e, urllib.error.URLError):
        return f"인터넷 연결을 확인하세요 ({e.reason})"
    return str(e) or type(e).__name__


class UpdateUI(QObject):
    """창이 하나씩 쥔다. `btn` 은 창이 상태줄에 놓는다(새 버전이 있을 때만 보인다)."""
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.btn = QPushButton(); self.btn.setObjectName("accent"); self.btn.setFixedHeight(22); self.btn.hide()
        self.btn.clicked.connect(lambda: self.found and self.install(self.found))
        self.found: U.Release | None = None
        self._busy = False
        self._sig = _Done()
        self._sig.done.connect(self._checked)

    def menu_label(self) -> str:
        return f"업데이트 확인 · 지금 {VERSION}"

    def auto_check(self):
        """켤 때 한 번. 설치본만, 닿지 않으면 아무 말 없이 넘어간다."""
        if U.installed():
            self._start(False)

    def check_now(self):
        self._start(True)

    def _start(self, manual: bool):
        if self._busy:
            return
        self._busy = True
        if manual:
            self.win.say("업데이트 확인 중")

        def run():
            try:
                self._sig.done.emit(U.check(), manual, "")
            except Exception as e:  # noqa: BLE001
                self._sig.done.emit(None, manual, _why(e))
        threading.Thread(target=run, daemon=True).start()

    def _checked(self, rel, manual, err):
        self._busy = False
        if rel is None:
            if manual:
                QMessageBox.warning(self.win, "업데이트 확인", f"새 버전을 확인하지 못했습니다\n{err}")
            return
        if not rel.newer:
            if manual:
                QMessageBox.information(self.win, "업데이트 확인", f"최신 버전입니다 · {VERSION}")
            return
        self.found = rel
        self.btn.setText(f"새 버전 {rel.version} 설치"); self.btn.show()
        if manual:
            self.install(rel)

    def install(self, rel: U.Release):
        w = self.win
        text = (f"새 버전 {rel.version} 받아서 설치합니다 (지금 {VERSION})\n"
                "설치가 끝나면 다시 켜지고, 열려 있던 문서도 다시 엽니다.")
        if rel.notes:
            text += "\n\n바뀐 것\n" + "\n".join("· " + n for n in rel.notes[:12])
        box = QMessageBox(QMessageBox.Icon.Question, "업데이트", text, parent=w)
        go = box.addButton("설치", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("나중에", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(go)
        box.exec()
        if box.clickedButton() is not go:
            return
        path = D.ProgressDialog(w, "업데이트 받기", U.download, rel).run()
        if not path:
            return
        paths = [t.doc.path for t in w.tabs if t.doc.path]
        if not w.close():   # 저장 안 한 문서는 닫을 때 묻는다. 그만두면 업데이트도 미룬다
            w.say("업데이트를 미뤘습니다 · 닫지 않은 문서가 있음")
            return
        from .window import save_settings
        w.settings[U.REOPEN_KEY] = paths
        save_settings(w.settings)
        U.run_setup(path)
        QApplication.quit()


def after_update(win, flagged: bool):
    """업데이트로 다시 켜졌으면 그 전에 열려 있던 문서를 다시 연다."""
    paths = win.settings.pop(U.REOPEN_KEY, None)
    if paths is not None:
        from .window import save_settings
        save_settings(win.settings)
        for p in paths:
            if os.path.exists(p):
                win.open_path(p)
    if flagged:
        win.say(f"새 버전 {VERSION} 설치 끝")

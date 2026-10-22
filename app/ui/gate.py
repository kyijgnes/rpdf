"""사용 제한 화면 쪽. 판정은 app/policy.py.

켤 때(startup_gate): 저장해 둔 판정으로 열 수 있으면 바로 열고, 아니면 이 화면에서 인터넷으로 다시 확인한다.
막힌 화면(차단·최소 버전)에서도 [새 버전 받기]는 된다. 켜 둔 동안(PolicyWatch)은 6시간마다 다시 보고, 막히면 이 화면을 띄운 뒤 창을 닫는다.
"""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from .. import policy as PL
from .. import updater as U
from ..appinfo import APP_NAME, VERSION

_TITLE = {PL.BLOCKED: "사용이 멈춰졌습니다", PL.OUTDATED: "업데이트가 필요합니다", PL.NEED_ONLINE: "사용 확인이 필요합니다"}


class _Sig(QObject):
    checked = Signal(object, str)      # Verdict, 실패 이유
    found = Signal(object, str)        # Release 또는 None, 실패 이유


class GateDialog(QDialog):
    """막혔을 때의 화면. exec() 가 Accepted 면 열어도 된다(다시 확인해 풀림). 새 버전 설치를 시작했으면 installing=True."""

    def __init__(self, parent=None, verdict: PL.Verdict | None = None, err: str = "", check_first: bool = True, installer=None):
        super().__init__(parent)
        self.installer = installer   # 창이 떠 있으면 창의 업데이트 흐름(저장 안 한 문서 묻기·다시 열기)을 쓴다
        self.setWindowTitle(APP_NAME)
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.installing = False
        self.verdict = verdict
        lay = QVBoxLayout(self); lay.setContentsMargins(24, 20, 24, 18); lay.setSpacing(10)
        self.head = QLabel(); f = self.head.font(); f.setPointSizeF(f.pointSizeF() * 1.35); f.setBold(True); self.head.setFont(f)
        self.body = QLabel(); self.body.setWordWrap(True)
        self.note = QLabel(); self.note.setObjectName("dim"); self.note.setWordWrap(True)
        lay.addWidget(self.head); lay.addWidget(self.body); lay.addWidget(self.note)
        row = QHBoxLayout(); row.addStretch(1)
        self.get_btn = QPushButton("새 버전 받기")
        self.again_btn = QPushButton("다시 확인")
        close = QPushButton("닫기")
        for b in (self.get_btn, self.again_btn, close):
            b.setAutoDefault(False)
            row.addWidget(b)
        lay.addLayout(row)
        self.get_btn.clicked.connect(self._find_update)
        self.again_btn.clicked.connect(self._check)
        close.clicked.connect(self.reject)
        self._sig = _Sig()
        self._sig.checked.connect(self._checked)
        self._sig.found.connect(self._found)
        if verdict:
            self._show(verdict, err)
        if check_first:
            QTimer.singleShot(0, self._check)

    def _show(self, v: PL.Verdict, err: str = ""):
        self.verdict = v
        self.head.setText(_TITLE.get(v.kind, "사용 확인"))
        self.body.setText(v.why)
        self.note.setText(f"지금 버전 {VERSION}" + (f" · 확인 못 함: {err}" if err else ""))
        get = v.kind in (PL.BLOCKED, PL.OUTDATED)
        self.get_btn.setVisible(get)
        self.get_btn.setDefault(get); self.again_btn.setDefault(not get)   # 할 일 하나만 파랗게
        self.adjustSize()   # 글이 길어져 줄이 늘면 창도 늘린다

    def _busy(self, text: str):
        self.note.setText(text)
        self.get_btn.setEnabled(False); self.again_btn.setEnabled(False)

    def _idle(self):
        self.get_btn.setEnabled(True); self.again_btn.setEnabled(True)

    # ── 다시 확인 ─────────────────────────────────────────────
    def _check(self):
        if not self.verdict:
            self.head.setText("사용 확인 중"); self.body.setText("인터넷으로 배포자 정책을 확인합니다")
            self.get_btn.hide(); self.again_btn.setDefault(True)
        self._busy("확인 중")

        def run():
            v, err = PL.gate(force=True)
            self._sig.checked.emit(v, err)
        threading.Thread(target=run, daemon=True).start()

    def _checked(self, v: PL.Verdict, err: str):
        self._idle()
        if v.ok:
            self.verdict = v
            self.accept()
            return
        self._show(v, err)

    # ── 새 버전 받기 ──────────────────────────────────────────
    def _find_update(self):
        self._busy("새 버전 확인 중")

        def run():
            try:
                self._sig.found.emit(U.check(), "")
            except Exception as e:  # noqa: BLE001
                from .update import _why
                self._sig.found.emit(None, _why(e))
        threading.Thread(target=run, daemon=True).start()

    def _found(self, rel, err: str):
        self._idle()
        if rel is None:
            self.note.setText(f"새 버전을 확인하지 못했습니다 · {err}")
            self.adjustSize()
            return
        if not rel.newer:
            self.note.setText(f"아직 새 버전이 없습니다 · 지금 {VERSION}")
            return
        if self.installer:
            self.installer(rel)   # 설치를 시작하면 앱이 끝난다. 그만두면 이 화면으로 돌아온다
            return
        from . import dialogs as D
        path = D.ProgressDialog(self, "업데이트 받기", U.download, rel).run()
        if not path:
            return
        self.installing = True
        U.run_setup(path)
        self.reject()


def startup_gate() -> bool:
    """켤 때. 열어도 되면 True. 아니면 화면을 보여 주고, 끝내 안 풀리면 False(앱을 끝낸다)."""
    if not PL.enforced():
        return True
    now = time.time()
    st = PL.load_state()
    v = PL.judge(st, now)
    if v.ok:
        return True
    from . import theme
    QApplication.instance().setStyleSheet(theme.qss(False))
    dlg = GateDialog(None, v if v.kind != PL.NEED_ONLINE else None)
    return dlg.exec() == QDialog.DialogCode.Accepted and not dlg.installing


class PolicyWatch(QObject):
    """켜 둔 동안. 켠 뒤 잠깐 있다 한 번, 그 뒤 CHECK_EVERY 마다 정책을 새로 받는다."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self._sig = _Sig()
        self._sig.checked.connect(self._checked)
        self._busy = False
        self._open = False
        self.timer = QTimer(self); self.timer.setInterval(PL.CHECK_EVERY * 1000); self.timer.timeout.connect(self.check)

    def start(self):
        if not PL.enforced():
            return
        QTimer.singleShot(5000, self.check)
        self.timer.start()

    def check(self):
        if self._busy or self._open:
            return
        self._busy = True

        def run():
            v, err = PL.gate(force=True)
            self._sig.checked.emit(v, err)
        threading.Thread(target=run, daemon=True).start()

    def _checked(self, v: PL.Verdict, err: str):
        self._busy = False
        if v.ok:
            p = v.policy
            if p and p.message and p.serial not in PL.load_state().shown:
                PL.mark_shown(p.serial)
                QMessageBox.information(self.win, APP_NAME, p.message)
            return
        self._open = True
        dlg = GateDialog(self.win, v, err, check_first=False, installer=self.win.updates.install)
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        self._open = False
        if not ok and not self.win.close():   # 저장 안 한 문서는 닫을 때 묻는다. 그만두면 잠시 뒤 다시
            QTimer.singleShot(60_000, self.check)

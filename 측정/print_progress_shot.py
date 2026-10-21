"""인쇄 진행 창 스크린샷: 고치기 전(막대 안 퍼센트 글자)과 지금을 나란히 PNG 로.

python 측정/print_progress_shot.py [출력.png]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QProgressDialog  # noqa: E402

from app.ui import printing as PR, theme  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def shot(dlg: QProgressDialog) -> QPixmap:
    dlg.setValue(12); dlg.setLabelText("12 / 48장 보내는 중")
    dlg.show(); QApplication.processEvents()
    return dlg.grab()


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.qss())  # 앱과 같은 스타일(막대 높이 6px)
    old = QProgressDialog("인쇄 준비 중", "그만두기", 0, 48)  # 고치기 전 모양
    old.setWindowTitle("인쇄"); old.setMinimumWidth(320); old.setMinimumDuration(0)
    a = shot(old)
    b = shot(PR.progress_dialog(None, 48))
    out = QPixmap(a.width() + b.width() + 20, max(a.height(), b.height()))
    out.fill()
    p = QPainter(out); p.drawPixmap(0, 0, a); p.drawPixmap(a.width() + 20, 0, b); p.end()
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "인쇄잘림", "진행창_전후.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out.save(path)
    print(path)


if __name__ == "__main__":
    main()

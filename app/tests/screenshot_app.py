"""화면 없이(offscreen) 앱을 띄워 그림으로 찍는다. 개발 중 확인용.

python -m app.tests.screenshot_app <pdf> <out.png> [탭키] [--organize]
"""
from __future__ import annotations

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main():
    pdf, out = sys.argv[1], sys.argv[2]
    tab = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else "home"
    app = QApplication([])
    app.setFont(QFont("Malgun Gothic", 9))
    from app.ui.window import MainWindow
    w = MainWindow()
    w.resize(1456, 790)
    w.show()
    if pdf != "-":
        w.open_path(pdf)
        w.ribbon.set_tab(tab)
        if "--side" in sys.argv:
            w.toggle_side("thumbs")
        if "--props" in sys.argv:
            w.right_action("props")

    def shot():
        app.processEvents()
        w.grab().save(out)
        print("saved", out)
        app.quit()
    QTimer.singleShot(2500, shot)
    app.exec()


if __name__ == "__main__":
    main()

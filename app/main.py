"""시작점. `python -m app.main [파일...]`"""
from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from . import updater
    updater.hold_running_mutex()   # 설치·제거 프로그램이 앱이 켜져 있는지 이것으로 본다
    after_update = updater.AFTER_FLAG in argv
    argv = [a for a in argv if a != updater.AFTER_FLAG]
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    from .appinfo import APP_NAME, ORG, VERSION
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG)
    app.setApplicationVersion(VERSION)
    app.setFont(QFont("Malgun Gothic", 9))
    from .ui.window import MainWindow
    w = MainWindow()
    w.show()
    for p in argv:
        if os.path.exists(p):
            w.open_path(p)
    from PySide6.QtCore import QTimer
    from .ui.update import after_update as reopen
    reopen(w, after_update)
    QTimer.singleShot(3000, w.updates.auto_check)   # 새 버전이 있으면 상태줄에 단추(설치본만)
    # 개발 확인용: PDFAPP_SHOT=그림경로[;탭키[;side|props|organize]] 이면 3초 뒤 창을 찍고 끝낸다
    shot = os.environ.get("PDFAPP_SHOT")
    if shot:
        from PySide6.QtCore import QTimer
        parts = shot.split(";")
        def go():
            if len(parts) > 1 and parts[1]:
                w.ribbon.set_tab(parts[1])
            if len(parts) > 2:
                if "side" in parts[2]: w.toggle_side("thumbs")
                if "props" in parts[2]: w.right_action("props")
                if "comments" in parts[2]: w.toggle_side("comments")
        def snap():
            app.processEvents(); w.grab().save(parts[0]); app.quit()
        QTimer.singleShot(1500, go); QTimer.singleShot(3500, snap)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

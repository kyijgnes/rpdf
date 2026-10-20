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
    from .appinfo import APP_ID, APP_NAME, ICON, ORG, VERSION
    if sys.platform == "win32" and not getattr(sys, "frozen", False):
        # python 으로 띄울 때 작업표시줄이 python 아이콘 대신 앱 아이콘을 쓰게(exe 는 exe 아이콘을 쓴다)
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{ORG}.{APP_ID}.dev")
        except Exception:  # noqa: BLE001
            pass
    if os.path.isfile(ICON):
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(ICON))
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG)
    app.setApplicationVersion(VERSION)
    app.setFont(QFont("Malgun Gothic", 9))
    from . import single
    alone = bool(os.environ.get("PDFAPP_SHOT"))   # 화면 찍기 확인은 켜져 있는 창과 상관없이
    first = alone or single.claim_first()
    if not first and not after_update:
        # 이미 켜진 창이 있다: 파일을 넘기고(그 창에 탭으로 열린다) 끝낸다. 못 넘기면 그냥 이 창을 띄운다
        if single.send([p for p in argv if os.path.exists(p)]):
            return 0
        first = single.claim_first()   # 받는 창이 그사이 닫혔으면 이쪽이 첫 창이 된다
    from .ui.window import MainWindow
    w = MainWindow()
    if first and not alone:
        w._receiver = single.Receiver(w.open_forwarded)
    w.show_initial()
    files = [p for p in argv if os.path.exists(p)]
    if not files and not after_update:
        w.reopen_last()
    for p in files:
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

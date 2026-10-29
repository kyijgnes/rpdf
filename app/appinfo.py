"""앱 이름·버전 한 곳. 이름을 바꾸면 여기만 고친다(창 제목·도움말·exe·설정 폴더·설치 프로그램이 다 여기서 읽는다)."""
import os
import shutil
import sys

APP_NAME = "PDF메트리"    # 화면에 보이는 이름(창 제목·도움말·바로 가기). 10-29 RPDF 에서 바꿈(메트리 시리즈)
APP_ID = "PDFmetry"       # exe·설정 폴더 이름(띄어쓰기 없이, 영어로)
OLD_APP_IDS = ("RPDF", "PDF편집기")  # 예전 APP_ID(새것부터). 처음 켤 때 그 설정 폴더를 새 자리로 복사한다
ORG = "kyijgnes"
VERSION = "0.2.1"         # 설치 프로그램·업데이트가 대조하는 버전

# 앱 아이콘(창·작업표시줄·exe·설치 프로그램 공용). exe 안에서는 PyInstaller 가 풀어 둔 자리(_MEIPASS)에서 찾는다
ICON = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "app.ico")


def data_dir() -> str:
    """설정·사용 확인·주석 모양을 두는 자리(%APPDATA%\\<APP_ID>)."""
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_ID)


def copy_old_data():
    """이름을 바꾸면 설정 폴더도 바뀐다. 새 자리에 설정이 없으면 옛 이름 자리를 통째로 복사해 온다
    (옛 exe 도 그대로 쓰게 옮기지 않고 복사). 사용 확인(policy_state.json)도 따라와 바꾼 뒤 첫 실행에 인터넷 확인을 다시 묻지 않는다."""
    new = data_dir()
    if os.path.isfile(os.path.join(new, "settings.json")):
        return
    root = os.path.dirname(new)
    for old in OLD_APP_IDS:
        src = os.path.join(root, old)
        if old != APP_ID and os.path.isfile(os.path.join(src, "settings.json")):
            try:
                shutil.copytree(src, new, dirs_exist_ok=True)
            except OSError:
                pass
            return

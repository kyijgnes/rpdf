"""앱 이름·버전 한 곳. 이름을 바꾸면 여기만 고친다(창 제목·도움말·exe·설정 폴더·설치 프로그램이 다 여기서 읽는다)."""
import os
import sys

APP_NAME = "RPDF"         # 화면에 보이는 이름(창 제목·도움말·바로 가기). 알PDF 의 「알」을 R 로(2026-10-20)
APP_ID = "RPDF"           # exe·설정 폴더 이름(띄어쓰기 없이)
OLD_APP_IDS = ("PDF편집기",)  # 예전 APP_ID. 처음 켤 때 그 설정을 새 자리로 복사한다(설치 프로그램이 옛 흔적 정리할 때도 씀)
ORG = "kyijgnes"
VERSION = "0.1.8"         # 설치 프로그램·업데이트가 대조하는 버전

# 앱 아이콘(창·작업표시줄·exe·설치 프로그램 공용). exe 안에서는 PyInstaller 가 풀어 둔 자리(_MEIPASS)에서 찾는다
ICON = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "app.ico")

"""앱 아이콘 가져오기: python assets/make_icon.py

10-27 부터 아이콘은 메트리 시리즈(메스·패드·한글·PDF메트리) 한 벌로 그린다. 정본은 `코딩\14. 도구\메트리 아이콘`
(후보.py 의 FINAL·SMALL_MARK, 뽑기는 만들기.py). 48px 까지 평면, 64px 부터 입체라 크기마다 그림이 다르다.
여기서는 그쪽에서 뽑은 ico 를 assets/app.ico 로 복사만 한다.
"""
import os
import shutil

here = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(here, "..", "..", "메트리 아이콘", "ico", "PDF메트리.ico")
shutil.copyfile(src, os.path.join(here, "app.ico"))
print("assets/app.ico 갱신")

"""잴 문서: 원본은 읽기만 하고, 쓰기(저장·편집)는 스크래치 폴더의 사본에서 한다.

PERF_DOCS 환경 변수가 있으면 거기에 사본을 둔다(없으면 %TEMP%\\rpdf_perf).
"""
import os
import shutil

K = r"C:\Users\kyijgnes\Desktop\코딩\11. 한글 변환기"
SOURCES = {
    # 이름: (원본, 설명)
    "small_b4": (K + r"\프로젝트\00. 사용완료\2026\07. 세미파이널\6회\세미파이널_6회_해설(영어+수학).pdf",
                 "B4 시험지 5쪽(한글에서 만든 PDF)"),
    "big_b4": (K + r"\프로젝트\01. 기출\22학년도\22학년도 전체합본.pdf", "B4 기출 합본 126쪽(한글 PDF)"),
    "huge": (K + r"\자료\교수님별 수업자료\장황자료\기출문제 합본(26_20) 최종본.pdf", "기출 합본 959쪽(한글 PDF)"),
    "scan": (K + r"\자료\기출\22학년도 수학 기출 해설.pdf", "스캔본 156쪽 6.6MB"),
    "scan_big": (K + r"\자료\수강교재_수학\13. 2026 TOP선형대수.pdf", "스캔본 376쪽 12MB"),
}
DIR = os.environ.get("PERF_DOCS") or os.path.join(os.environ.get("TEMP", "."), "rpdf_perf")


def path(name: str) -> str:
    """사본 경로(없으면 만든다)."""
    os.makedirs(DIR, exist_ok=True)
    dst = os.path.join(DIR, name + ".pdf")
    if not os.path.exists(dst):
        shutil.copyfile(SOURCES[name][0], dst)
    return dst


ALL = list(SOURCES)

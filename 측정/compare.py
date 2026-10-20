"""고치기 전 결과 json 과 고친 뒤 json 을 맞대어 표 줄로 뽑는다.

python 측정/compare.py <뒤 json> <앞 json>...
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
after = json.load(open(os.path.join(HERE, sys.argv[1]), encoding="utf-8"))
before = {}
for f in sys.argv[2:]:
    before.update(json.load(open(os.path.join(HERE, f), encoding="utf-8")))
WANT = ["열기 → 첫 화면", "끝쪽까지 한 화면씩 훑기", "검색", "편집 모드 켜고", "주석 네모 넣기", "되돌리기\"", "저장(Ctrl+S)",
        "구성 탭 열기", "구성: 첫 쪽 오른쪽 회전", "구성: 끝 쪽 삭제", "구성: 끌어 옮기기", "보기 화면에서 회전"]
for doc, rows in after.items():
    if doc not in before:
        continue
    b = {r["동작"]: r for r in before[doc]}
    a = {r["동작"]: r for r in rows}
    print("==", doc)
    for w in WANT:
        exact = w.endswith('"')
        w = w.rstrip('"')
        kb = [k for k in b if (k == w if exact else k.startswith(w))]
        ka = [k for k in a if (k == w if exact else k.startswith(w))]
        if not kb or not ka:
            continue
        rb, ra = b[kb[0]], a[ka[0]]
        extra = f" | 메모리 {rb['rss_mb']}→{ra['rss_mb']}MB" if w.startswith("끝쪽") else ""
        print(f"| {w} | {rb['끝까지']}초 (멈춤 {rb['max_stall']}) | {ra['끝까지']}초 (멈춤 {ra['max_stall']}){extra} |")

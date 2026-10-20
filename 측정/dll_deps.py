"""설치 폴더에서 어떤 DLL 을 누가 가져다 쓰나(PE import 표). 뺄 후보를 다른 파일이 쓰면 알려 준다.

python 측정/dll_deps.py <_internal 폴더> 이름1 이름2 ...
"""
import os
import sys

import pefile

root = sys.argv[1]
want = {n.lower() for n in sys.argv[2:]}
users: dict[str, list[str]] = {w: [] for w in want}
for dp, _, fs in os.walk(root):
    for f in fs:
        if not f.lower().endswith((".dll", ".pyd", ".exe")):
            continue
        p = os.path.join(dp, f)
        try:
            pe = pefile.PE(p, fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
                n = e.dll.decode().lower()
                if n in users and f.lower() != n:
                    users[n].append(os.path.relpath(p, root))
            pe.close()
        except Exception:  # noqa: BLE001
            pass
for n, u in sorted(users.items()):
    print(n, "←", u if u else "아무도 안 씀")

"""빌드한 _internal(지우고 남은 Qt·OpenSSL)을 먼저 읽게 해서 앱 시험을 돈다: 인쇄·변환 시험과 업데이트 확인(HTTPS).
exe 안에서는 임의 코드를 못 돌려서, 같은 DLL·pyd 를 쓰는 이 방법으로 대신한다. 실제 프린터로는 아무것도 안 보낸다.

python 측정/bundle_check.py <_internal 폴더>
"""
import os
import sys

internal = os.path.abspath(sys.argv[1])
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [internal, HERE]
os.add_dll_directory(internal)
os.add_dll_directory(os.path.join(internal, "PySide6"))
os.environ["QT_PLUGIN_PATH"] = os.path.join(internal, "PySide6", "plugins")

import PySide6  # noqa: E402  (__init__ 은 빌드의 압축 안에 있어 설치된 것을 쓰고, 모듈 .pyd 는 빌드 폴더에서)
PySide6.__path__.insert(0, os.path.join(internal, "PySide6"))
import ssl  # noqa: E402
import _ssl  # noqa: E402
from PySide6 import QtCore  # noqa: E402

print("QtCore ←", QtCore.__file__)
print("_ssl ←", _ssl.__file__, ssl.OPENSSL_VERSION)
assert QtCore.__file__.startswith(internal) and _ssl.__file__.startswith(internal), "빌드 폴더 것을 안 읽음"

from app import updater  # noqa: E402
rel = updater.check()
print("업데이트 확인(HTTPS):", rel.version, "새 버전" if rel.newer else "최신")

import pytest  # noqa: E402
r = pytest.main(["-q", "-p", "no:cacheprovider", os.path.join(HERE, "app", "tests")])

# 이 프로세스가 실제로 올린 Qt·OpenSSL DLL 이 어디서 왔나
import psutil  # noqa: E402
libs = sorted({m.path for m in psutil.Process().memory_maps() if os.path.basename(m.path).lower().startswith(("qt6", "libssl", "libcrypto", "opengl"))})
outside = [p for p in libs if not os.path.abspath(p).lower().startswith(internal.lower())]
print("올린 Qt·OpenSSL DLL", len(libs), "개, 빌드 폴더 밖", outside or "없음")
sys.exit(r or bool(outside))

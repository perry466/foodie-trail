"""pytest 公共装置：把数据目录指向临时目录，绝不触碰真实的 data/foodmap.db。

原理：`app/pathconf.py` 支持 FOODMAP_DATA_DIR 环境变量。这里在**导入 app 之前**
设置该变量，之后 `app.db` / `app.crypto` / `app.main` 拿到的就都是临时路径。
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 必须在 import app.* 之前设置；导入 app.main 时会 init_db() 并生成 .fernet.key
TMP_DATA = Path(tempfile.mkdtemp(prefix="foodmap-test-"))
os.environ["FOODMAP_DATA_DIR"] = str(TMP_DATA)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import get_conn  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """整个测试会话共用一个 TestClient（不启动真实端口）。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_tables():
    """每个用例前清空业务表，避免互相污染。"""
    with get_conn() as conn:
        conn.execute("DELETE FROM photos")
        conn.execute("DELETE FROM records")
        conn.execute("DELETE FROM settings")
    yield


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TMP_DATA, ignore_errors=True)

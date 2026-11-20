"""pytest 共用設定：測試用獨立的暫存資料庫，不會動到 data/trust.db。"""
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["GEMINI_API_KEY"] = ""  # 測試時不連 Gemini，用備援回答
os.environ["STAFF_PASSWORD"] = "test-pass"

import pytest  # noqa: E402

from pathlib import Path  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.seed import seed  # noqa: E402

settings.upload_dir = Path(_tmp) / "uploads"  # 測試照片不寫進專案資料夾


@pytest.fixture()
def fresh_db():
    """每個測試前重建資料庫。"""
    seed()

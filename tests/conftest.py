# -*- coding: utf-8 -*-
"""pytest 公共夹具：把仓库里的数据库复制到临时目录，测试不写坏真实数据。"""
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app  # noqa: E402

SOURCE_DB = os.path.join(ROOT, "data", "db", "mentor.db")


@pytest.fixture(autouse=True)
def isolate_chat_store(tmp_path, monkeypatch):
    """聊天历史写到临时目录，避免测试污染真实用户目录。"""
    monkeypatch.setenv("JIAOWODAO_HOME", str(tmp_path / "chat"))
    from assistant import store
    store._db_path = None
    yield
    store._db_path = None


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    if not os.path.exists(SOURCE_DB):
        pytest.skip("缺少 data/db/mentor.db，跳过接口测试")
    target = tmp_path_factory.mktemp("db") / "mentor.db"
    shutil.copy2(SOURCE_DB, target)
    return str(target)


@pytest.fixture()
def app(db_path, tmp_path):
    return create_app({
        "DB_PATH": db_path,
        "AI_CONFIG_PATH": str(tmp_path / "ai_config.json"),
        "IMPORT_DIR": str(tmp_path / "imports"),
        "IMPORT_BACKUP_DIR": str(tmp_path / "backup"),
        "TESTING": True,
        "LOG_LEVEL": "WARNING",
    })


@pytest.fixture()
def client(app):
    return app.test_client()

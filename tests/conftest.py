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


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    if not os.path.exists(SOURCE_DB):
        pytest.skip("缺少 data/db/mentor.db，跳过接口测试")
    target = tmp_path_factory.mktemp("db") / "mentor.db"
    shutil.copy2(SOURCE_DB, target)
    return str(target)


@pytest.fixture()
def app(db_path):
    return create_app({
        "DB_PATH": db_path,
        "TESTING": True,
        "LOG_LEVEL": "WARNING",
    })


@pytest.fixture()
def client(app):
    return app.test_client()

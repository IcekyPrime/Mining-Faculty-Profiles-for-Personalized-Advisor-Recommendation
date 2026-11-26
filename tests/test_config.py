# -*- coding: utf-8 -*-
"""运行配置契约：路径、端口、超时和上传限制必须能由环境变量覆盖。"""
from app.config import default_config


def test_config_env_overrides(monkeypatch, tmp_path):
    db = tmp_path / "mentor-test.db"
    monkeypatch.setenv("MENTOR_DB_PATH", str(db))
    monkeypatch.setenv("MENTOR_IMPORT_BACKUP_DIR", str(tmp_path / "backup"))
    monkeypatch.setenv("MENTOR_PORT", "9123")
    monkeypatch.setenv("MENTOR_PIPELINE_TIMEOUT", "42")
    monkeypatch.setenv("MENTOR_MAX_UPLOAD_BYTES", "4096")
    monkeypatch.setenv("MENTOR_STATIC_MAX_AGE", "3600")
    monkeypatch.setenv("MENTOR_GZIP_MIN_BYTES", "0")

    cfg = default_config()
    assert cfg["DB_PATH"] == str(db)
    assert cfg["IMPORT_BACKUP_DIR"] == str(tmp_path / "backup")
    assert cfg["PORT"] == 9123
    assert cfg["PIPELINE_TIMEOUT"] == 42
    assert cfg["MAX_UPLOAD_BYTES"] == 4096
    assert cfg["MAX_CONTENT_LENGTH"] == 4096
    assert cfg["STATIC_MAX_AGE"] == 3600
    assert cfg["GZIP_MIN_BYTES"] == 0


def test_config_bad_int_falls_back(monkeypatch):
    monkeypatch.setenv("MENTOR_PORT", "not-a-port")
    monkeypatch.setenv("MENTOR_MAX_UPLOAD_BYTES", "0")
    cfg = default_config()
    assert cfg["PORT"] == 8765
    assert cfg["MAX_CONTENT_LENGTH"] == 1024

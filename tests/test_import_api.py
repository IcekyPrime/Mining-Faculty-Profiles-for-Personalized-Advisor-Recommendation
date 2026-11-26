# -*- coding: utf-8 -*-
"""数据工坊 API 契约测试：预览不写库、应用前备份、重复应用被拒绝。"""
import io
import sqlite3

from app import import_api


def test_import_status_and_templates(client):
    status = client.get("/api/import/status")
    assert status.status_code == 200
    assert status.json["limits"]["max_rows"] == 20000
    for entity in ("teacher", "paper", "course"):
        response = client.get(f"/api/import/template?type={entity}")
        assert response.status_code == 200
        assert response.mimetype == "text/csv"
        assert response.data.decode("utf-8-sig").strip()


def test_preview_does_not_write_database(client, db_path):
    before = _teacher_count(db_path)
    csv_bytes = (
        "姓名,学院,职称,研究方向\n"
        "接口预览教师,计算机学院,副教授,数据挖掘、知识图谱\n"
    ).encode()
    response = client.post(
        "/api/import/preview",
        data={
            "file": (io.BytesIO(csv_bytes), "preview.csv"),
            "mode": "auto",
            "conflict": "skip",
            "ai": "0",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    token = response.json["token"]
    assert response.json["summary"]["entity_counts"]["teacher"] == 1
    assert len(token) == 16
    assert _teacher_count(db_path) == before


def test_ai_review_without_config_returns_clear_error(client):
    csv_bytes = "姓名,学院\nAI未配置教师,计算机学院\n".encode()
    response = client.post(
        "/api/import/preview",
        data={"file": (io.BytesIO(csv_bytes), "ai.csv"), "mode": "teacher"},
        content_type="multipart/form-data",
    )
    token = response.json["token"]
    review = client.post("/api/import/ai", json={"token": token})
    assert review.status_code == 400
    assert review.json["error"]["code"] == "ai_not_configured"


def test_apply_creates_backup_and_writes(client, db_path, tmp_path):
    csv_bytes = (
        "姓名,学院,职称,研究方向,邮箱\n"
        "接口入库教师,计算机学院,教授,数据挖掘、图学习,demo@example.com\n"
    ).encode()
    response = client.post(
        "/api/import/preview",
        data={"file": (io.BytesIO(csv_bytes), "apply.csv"), "mode": "teacher"},
        content_type="multipart/form-data",
    )
    token = response.json["token"]
    applied = client.post(
        "/api/import/apply",
        json={"token": token, "conflict": "skip", "start_pipeline": False},
    )
    assert applied.status_code == 200
    assert applied.json["totals"]["teachers_inserted"] == 1
    assert applied.json["backup"].startswith("mentor_before_import_")
    assert (tmp_path / "backup" / applied.json["backup"]).exists()
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM teachers WHERE name = '接口入库教师'"
        ).fetchone()[0] == 1
    finally:
        conn.close()
    again = client.post("/api/import/apply", json={"token": token})
    assert again.status_code == 409
    assert again.json["error"]["code"] == "already_applied"


def test_apply_rejects_empty_or_invalid_selected_rows(client, db_path):
    before = _teacher_count(db_path)
    csv_bytes = (
        "姓名,学院,职称\n"
        "选择性写入甲,计算机学院,教授\n"
        "选择性写入乙,计算机学院,副教授\n"
    ).encode()
    response = client.post(
        "/api/import/preview",
        data={"file": (io.BytesIO(csv_bytes), "selected.csv"), "mode": "teacher"},
        content_type="multipart/form-data",
    )
    token = response.json["token"]
    for selected in ([], ["1"], [99], [True]):
        applied = client.post(
            "/api/import/apply",
            json={"token": token, "start_pipeline": False, "selected_rows": selected},
        )
        assert applied.status_code == 400
        assert applied.json["error"]["code"] in {"invalid_param", "no_row_selected"}
        assert _teacher_count(db_path) == before
    applied = client.post(
        "/api/import/apply",
        json={"token": token, "start_pipeline": False, "selected_rows": [1]},
    )
    assert applied.status_code == 200
    assert applied.json["totals"]["teachers_inserted"] == 1
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM teachers WHERE name LIKE '选择性写入%'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_apply_duplicate_only_does_not_queue_pipeline(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        existing = conn.execute(
            "SELECT name, college_raw, college FROM teachers "
            "WHERE name != '' AND COALESCE(college_raw, college, '') != '' LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if existing is None:
        return
    college = existing["college_raw"] or existing["college"]
    csv_bytes = f"姓名,学院\n{existing['name']},{college}\n".encode()
    response = client.post(
        "/api/import/preview",
        data={"file": (io.BytesIO(csv_bytes), "duplicate.csv"), "mode": "teacher"},
        content_type="multipart/form-data",
    )
    token = response.json["token"]
    assert response.json["summary"]["duplicate_rows"] == 1
    applied = client.post(
        "/api/import/apply",
        json={"token": token, "conflict": "skip", "start_pipeline": True},
    )
    assert applied.status_code == 200
    assert applied.json["totals"]["teachers_inserted"] == 0
    assert applied.json["pipeline_status"] == "idle"


def test_apply_string_false_does_not_queue_pipeline(client, db_path, monkeypatch):
    calls = []
    monkeypatch.setattr(import_api, "_start_pipeline", lambda *args: calls.append(args))
    csv_bytes = "姓名,学院,职称,研究方向\n字符串布尔教师,计算机学院,教授,数据库\n".encode()
    preview = client.post(
        "/api/import/preview",
        data={"file": (io.BytesIO(csv_bytes), "bool.csv"), "mode": "teacher"},
        content_type="multipart/form-data",
    )
    token = preview.json["token"]
    try:
        applied = client.post(
            "/api/import/apply",
            json={"token": token, "conflict": "skip", "start_pipeline": "false"},
        )
        assert applied.status_code == 200
        assert applied.json["totals"]["teachers_inserted"] == 1
        assert applied.json["pipeline_status"] == "idle"
        assert calls == []
    finally:
        # 这个 client 复用会话级 db_path，清理测试插入的行，避免污染
        # test_chat_status 的 773 计数。
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("DELETE FROM teachers WHERE name = '字符串布尔教师'")
            conn.commit()
        finally:
            conn.close()

    assert client.get("/api/import/jobs/not-a-token").status_code == 400
    assert client.get("/api/import/jobs/0000000000000000").status_code == 404

    csv_bytes = (
        "姓名,学院,职称,研究方向\n"
        "筛选教师,计算机学院,教授,数据库\n"
        "坏行,计算机学院,教授,\n"
    ).encode()
    response = client.post(
        "/api/import/preview",
        data={"file": (io.BytesIO(csv_bytes), "filter.csv"), "mode": "teacher"},
        content_type="multipart/form-data",
    )
    token = response.json["token"]
    detail = client.get(f"/api/import/jobs/{token}?limit=50&status=warning")
    assert detail.status_code == 200
    assert detail.json["total"] == 1
    exported = client.get(f"/api/import/jobs/{token}/export")
    assert exported.status_code == 200
    assert exported.mimetype == "text/csv"


def test_workspace_page_available(client):
    response = client.get("/workspace")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "数据工坊" in html
    assert "import" in html
    assert 'id="settings-drawer"' in html
    assert 'id="settings-btn"' in html
    assert 'id="ai-api-base"' in html
    assert "/static/css/ai-features.css" in html
    assert "论文 0.10 / 引用 0.20 / 荣誉 0.35 / 教学 0.25" in html
    assert "/static/js/app-shell.js" in html


def test_workspace_url_can_restore_job(client):
    """任务 token 出现在 URL 中，刷新/分享后仍能重新打开同一预览。"""
    csv_bytes = "姓名,学院\nURL恢复教师,计算机学院\n".encode()
    response = client.post(
        "/api/import/preview",
        data={"file": (io.BytesIO(csv_bytes), "resume.csv"), "mode": "teacher"},
        content_type="multipart/form-data",
    )
    token = response.json["token"]
    assert len(token) == 16
    assert client.get(f"/api/import/jobs/{token}?limit=1").status_code == 200


def test_import_store_recovers_interrupted_pipeline(client, db_path):
    """服务重启后，中断的 running 任务不能永久卡在 running。"""
    from app import import_store

    csv_bytes = "姓名,学院\n恢复任务教师,计算机学院\n".encode()
    preview = client.post(
        "/api/import/preview",
        data={"file": (io.BytesIO(csv_bytes), "recover.csv"), "mode": "teacher"},
        content_type="multipart/form-data",
    )
    token = preview.json["token"]
    import_store.update_job(
        db_path, token, pipeline_status="running",
        pipeline_steps=[{"name": "preprocess", "label": "预处理", "status": "running"}],
    )
    assert import_store.ensure_schema(db_path) is True
    job = import_store.get_job(db_path, token)
    assert job["pipeline_status"] == "failed"
    assert job["pipeline_steps"][0]["status"] == "failed"
    assert "服务重启" in job["error"]


def _teacher_count(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
    finally:
        conn.close()


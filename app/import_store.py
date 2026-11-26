# -*- coding: utf-8 -*-
"""导入任务持久化：只新增 import_jobs 表与独立预览文件，不改动原有表结构。

设计目标与 ``app/ai_store.py`` 保持一致：
1. 审计优先：每次上传都能追溯到文件、模式、模型、行数与处理结果；
2. 预览与写库分离：预览行写入 data/imports，只有用户确认后才进入正式库；
3. 失败可恢复：任务状态和错误信息保留，旧功能不依赖这张表。
"""
import contextlib
import json
import os
import sqlite3
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS import_jobs (
    token TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'auto',
    conflict TEXT NOT NULL DEFAULT 'skip',
    ai_enabled INTEGER NOT NULL DEFAULT 0,
    ai_model TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'preview',
    total_rows INTEGER DEFAULT 0,
    ready_rows INTEGER DEFAULT 0,
    warning_rows INTEGER DEFAULT 0,
    error_rows INTEGER DEFAULT 0,
    duplicate_rows INTEGER DEFAULT 0,
    entity_counts TEXT DEFAULT '{}',
    summary TEXT DEFAULT '{}',
    columns TEXT DEFAULT '[]',
    rows_file TEXT DEFAULT '',
    applied_counts TEXT DEFAULT '{}',
    backup_path TEXT DEFAULT '',
    pipeline_status TEXT DEFAULT 'idle',
    pipeline_steps TEXT DEFAULT '[]',
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def ensure_schema(db_path):
    """建导入审计表；数据库不可写时返回 False，不影响应用启动。"""
    if not db_path or not os.path.exists(db_path):
        return False
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        conn.execute("PRAGMA busy_timeout = 8000")
        conn.execute(SCHEMA)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_import_jobs_created "
            "ON import_jobs(created_at DESC)"
        )
        _recover_pipeline_jobs(conn)
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()


def _recover_pipeline_jobs(conn):
    """服务重启后，把中断的 queued/running 任务标记为失败。

    数据已经入库，处理层只是派生结果；标记失败比永久停在 running 更可控，
    用户可以重新运行处理层，不会重复写业务表。
    """
    rows = conn.execute(
        "SELECT token, pipeline_status, pipeline_steps FROM import_jobs "
        "WHERE pipeline_status IN ('queued', 'running')"
    ).fetchall()
    if not rows:
        return
    message = "服务重启，处理层刷新中断；数据已入库，可重新运行处理层"
    for row in rows:
        try:
            steps = json.loads(row[2] or "[]")
        except (TypeError, ValueError):
            steps = []
        for step in steps if isinstance(steps, list) else []:
            if isinstance(step, dict) and step.get("status") in {"pending", "running", "queued"}:
                step["status"] = "failed"
                step["output"] = message
        conn.execute(
            "UPDATE import_jobs SET pipeline_status = 'failed', pipeline_steps = ?, "
            "error = ?, updated_at = ? WHERE token = ?",
            (json.dumps(steps, ensure_ascii=False), message, now_text(), row[0]),
        )


def new_token():
    return uuid.uuid4().hex[:16]


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _json(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def rows_path(import_dir, token):
    return os.path.join(import_dir, token + ".json")


def save_rows(import_dir, token, rows):
    os.makedirs(import_dir, exist_ok=True)
    path = rows_path(import_dir, token)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return path


def load_rows(import_dir, token):
    path = rows_path(import_dir, token)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        # 预览文件被截断/手工改坏时，让上层按“预览丢失”处理，而不是 500。
        return []
    return data if isinstance(data, list) else []


def create_job(db_path, import_dir, payload, rows):
    """写入任务元数据与预览行；返回 (token, row_file)。"""
    token = new_token()
    os.makedirs(import_dir, exist_ok=True)
    file_path = save_rows(import_dir, token, rows)
    created = now_text()
    fields = {
        "token": token,
        "filename": str(payload.get("filename") or "")[:240],
        "file_size": int(payload.get("file_size") or 0),
        "mode": str(payload.get("mode") or "auto"),
        "conflict": str(payload.get("conflict") or "skip"),
        "ai_enabled": 1 if payload.get("ai_enabled") else 0,
        "ai_model": str(payload.get("ai_model") or "")[:160],
        "status": str(payload.get("status") or "preview"),
        "total_rows": int(payload.get("total_rows") or len(rows)),
        "ready_rows": int(payload.get("ready_rows") or 0),
        "warning_rows": int(payload.get("warning_rows") or 0),
        "error_rows": int(payload.get("error_rows") or 0),
        "duplicate_rows": int(payload.get("duplicate_rows") or 0),
        "entity_counts": json.dumps(payload.get("entity_counts") or {}, ensure_ascii=False),
        "summary": json.dumps(payload.get("summary") or {}, ensure_ascii=False),
        "columns": json.dumps(payload.get("columns") or [], ensure_ascii=False),
        "rows_file": os.path.basename(file_path),
        "applied_counts": json.dumps(payload.get("applied_counts") or {}, ensure_ascii=False),
        "backup_path": str(payload.get("backup_path") or ""),
        "pipeline_status": str(payload.get("pipeline_status") or "idle"),
        "pipeline_steps": json.dumps(payload.get("pipeline_steps") or [], ensure_ascii=False),
        "error": str(payload.get("error") or "")[:2000],
        "created_at": created,
        "updated_at": created,
    }
    columns = list(fields.keys())
    placeholders = ",".join("?" for _ in columns)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        conn.execute("PRAGMA busy_timeout = 8000")
        conn.execute(SCHEMA)
        conn.execute(
            "INSERT INTO import_jobs (" + ",".join(columns) + ") VALUES (" + placeholders + ")",
            [fields[key] for key in columns],
        )
        conn.commit()
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(file_path)
        raise
    finally:
        conn.close()
    return token, file_path


def get_job(db_path, token, include_rows=False, import_dir=None):
    conn = sqlite3.connect(db_path, timeout=8.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 8000")
        conn.execute(SCHEMA)
        row = conn.execute("SELECT * FROM import_jobs WHERE token = ?", (token,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    data = dict(row)
    data["entity_counts"] = _json(data.get("entity_counts"), {})
    data["summary"] = _json(data.get("summary"), {})
    data["columns"] = _json(data.get("columns"), [])
    data["applied_counts"] = _json(data.get("applied_counts"), {})
    data["pipeline_steps"] = _json(data.get("pipeline_steps"), [])
    data["ai_enabled"] = bool(data.get("ai_enabled"))
    if include_rows and import_dir:
        data["rows"] = load_rows(import_dir, token)
    return data


def update_job(db_path, token, **changes):
    if not changes:
        return
    allowed = {
        "status", "total_rows", "ready_rows", "warning_rows", "error_rows",
        "duplicate_rows", "entity_counts", "summary", "applied_counts",
        "backup_path", "pipeline_status", "pipeline_steps", "error",
        "ai_enabled", "ai_model", "conflict",
    }
    updates = {key: value for key, value in changes.items() if key in allowed}
    if not updates:
        return
    encoded = {}
    for key, value in updates.items():
        if key in {"entity_counts", "summary", "applied_counts", "pipeline_steps"}:
            encoded[key] = json.dumps(value, ensure_ascii=False)
        elif key == "ai_enabled":
            encoded[key] = 1 if value else 0
        else:
            encoded[key] = value
    encoded["updated_at"] = now_text()
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        conn.execute("PRAGMA busy_timeout = 8000")
        conn.execute(SCHEMA)
        conn.execute(
            "UPDATE import_jobs SET " +
            ", ".join(key + " = ?" for key in encoded) +
            " WHERE token = ?",
            list(encoded.values()) + [token],
        )
        conn.commit()
    finally:
        conn.close()


def claim_apply(db_path, token):
    """原子地把任务从预览态切到 applying，防止并发重复写库。

    返回 True 表示本次请求获得写库权；False 表示任务已入库或已有请求在写。
    """
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        conn.execute("PRAGMA busy_timeout = 8000")
        conn.execute(SCHEMA)
        cursor = conn.execute(
            "UPDATE import_jobs SET status = 'applying', updated_at = ? "
            "WHERE token = ? AND status NOT IN ('applied', 'applying')",
            (now_text(), token),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def list_jobs(db_path, limit=20):
    conn = sqlite3.connect(db_path, timeout=8.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 8000")
        conn.execute(SCHEMA)
        rows = conn.execute(
            "SELECT token, filename, mode, conflict, ai_enabled, ai_model, status, "
            "total_rows, ready_rows, warning_rows, error_rows, duplicate_rows, "
            "entity_counts, applied_counts, pipeline_status, created_at, updated_at "
            "FROM import_jobs ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        item = dict(row)
        item["entity_counts"] = _json(item.get("entity_counts"), {})
        item["applied_counts"] = _json(item.get("applied_counts"), {})
        item["ai_enabled"] = bool(item.get("ai_enabled"))
        result.append(item)
    return result

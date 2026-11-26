# -*- coding: utf-8 -*-
"""AI 补全任务的暂存与审计表。

表只新增，不改动 `teachers/papers/courses/processing` 的既有结构。
"""
import contextlib
import json
import os
import sqlite3
import uuid
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_enrichment_jobs (
    token TEXT PRIMARY KEY,
    teacher_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    query TEXT,
    model TEXT,
    proposed TEXT,
    sources TEXT,
    diff TEXT,
    selected_fields TEXT,
    before_json TEXT,
    after_json TEXT,
    pipeline_status TEXT DEFAULT 'idle',
    pipeline_steps TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_jobs_teacher ON ai_enrichment_jobs(teacher_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_jobs_status ON ai_enrichment_jobs(status);
"""


def now():
    return datetime.now().isoformat(timespec="seconds")


def ensure_schema(db_path):
    if not os.path.exists(db_path):
        return False
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.executescript(SCHEMA)
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def create_job(db_path, teacher_id, query, model, proposed, sources, diff):
    token = uuid.uuid4().hex
    stamp = now()
    conn = connect(db_path)
    try:
        conn.execute(
            """INSERT INTO ai_enrichment_jobs
               (token, teacher_id, status, query, model, proposed, sources, diff,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                token, teacher_id, "preview", query, model,
                json.dumps(proposed, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
                json.dumps(diff, ensure_ascii=False),
                stamp, stamp,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def get_job(db_path, token):
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT * FROM ai_enrichment_jobs WHERE token = ?", (token,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    job = dict(row)
    for key in ("proposed", "sources", "diff", "selected_fields", "before_json",
                "after_json", "pipeline_steps"):
        if job.get(key):
            with contextlib.suppress(ValueError):
                job[key] = json.loads(job[key])
    return job


def update_job(db_path, token, **changes):
    allowed = {
        "status", "selected_fields", "before_json", "after_json",
        "pipeline_status", "pipeline_steps", "error",
    }
    fields = []
    values = []
    for key, value in changes.items():
        if key not in allowed:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        fields.append(f"{key} = ?")
        values.append(value)
    if not fields:
        return
    fields.append("updated_at = ?")
    values.extend([now(), token])
    conn = connect(db_path)
    try:
        conn.execute(
            f"UPDATE ai_enrichment_jobs SET {', '.join(fields)} WHERE token = ?",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def list_jobs(db_path, teacher_id=None, limit=30):
    conn = connect(db_path)
    try:
        if teacher_id:
            rows = conn.execute(
                """SELECT token, teacher_id, status, query, model, selected_fields,
                          pipeline_status, created_at, updated_at
                   FROM ai_enrichment_jobs WHERE teacher_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (teacher_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT token, teacher_id, status, query, model, selected_fields,
                          pipeline_status, created_at, updated_at
                   FROM ai_enrichment_jobs ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]

# -*- coding: utf-8 -*-
"""对话历史存储。

使用独立的 SQLite 文件，避免 run_pipeline.py 重置 mentor.db 时被清空。
每个浏览器客户端通过 Cookie 中的随机 ID 区分，历史只保存在本机。
"""
import json
import os
import sqlite3
import threading

_lock = threading.Lock()
_db_path = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_client ON messages(client_id, id);
"""


def data_dir():
    env = os.environ.get("JIAOWODAO_HOME")
    if env:
        path = env
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "JiaWoDao")
    else:
        path = os.path.join(os.path.expanduser("~"), ".jiaowodao")
    os.makedirs(path, exist_ok=True)
    return path


def _init():
    global _db_path
    if _db_path:
        return _db_path
    with _lock:
        if _db_path:
            return _db_path
        path = os.path.join(data_dir(), "chat.db")
        conn = sqlite3.connect(path, timeout=5)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()
        _db_path = path
    return _db_path


def add(client_id, role, content, meta=None):
    path = _init()
    payload = json.dumps(meta, ensure_ascii=False) if meta is not None else None
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute(
            "INSERT INTO messages(client_id, role, content, meta, created_at) "
            "VALUES(?,?,?,?,strftime('%s','now'))",
            (client_id, role, content, payload),
        )
        conn.execute(
            "DELETE FROM messages WHERE client_id=? AND id NOT IN "
            "(SELECT id FROM messages WHERE client_id=? ORDER BY id DESC LIMIT 400)",
            (client_id, client_id),
        )
        conn.commit()
    finally:
        conn.close()


def history(client_id, limit=40):
    path = _init()
    limit = max(1, min(100, int(limit or 40)))
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT role, content, meta, created_at FROM messages "
            "WHERE client_id=? ORDER BY id DESC LIMIT ?",
            (client_id, limit),
        ).fetchall()
    finally:
        conn.close()

    out = []
    for row in reversed(rows):
        meta = None
        if row["meta"]:
            try:
                meta = json.loads(row["meta"])
            except (ValueError, TypeError):
                meta = None
        out.append({
            "role": row["role"],
            "content": row["content"],
            "meta": meta,
            "created_at": row["created_at"],
        })
    return out


def last_meta(client_id):
    path = _init()
    conn = sqlite3.connect(path, timeout=5)
    try:
        row = conn.execute(
            "SELECT meta FROM messages WHERE client_id=? AND role='assistant' "
            "AND meta IS NOT NULL ORDER BY id DESC LIMIT 1",
            (client_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return None


def clear(client_id):
    path = _init()
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute("DELETE FROM messages WHERE client_id=?", (client_id,))
        conn.commit()
    finally:
        conn.close()

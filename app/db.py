# -*- coding: utf-8 -*-
"""数据库访问：只读连接 + WAL + 索引自检。

要点：
1. 查询一律用 SQLite 的只读 URI（mode=ro），从机制上避免接口误写库；
2. 每个请求复用同一连接（Flask `g`），请求结束自动关闭；
3. 启动时补建索引并开启 WAL，让「读」不阻塞「写」（补录脚本可能随时写库）。
"""
import os
import sqlite3
from urllib.parse import quote

from flask import current_app, g

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_teachers_college ON teachers(college)",
    "CREATE INDEX IF NOT EXISTS idx_teachers_name ON teachers(name)",
    "CREATE INDEX IF NOT EXISTS idx_teachers_h_index ON teachers(h_index)",
    "CREATE INDEX IF NOT EXISTS idx_courses_teacher ON courses(teacher_id)",
    "CREATE INDEX IF NOT EXISTS idx_papers_teacher ON papers(teacher_id)",
    (
        "CREATE INDEX IF NOT EXISTS idx_papers_teacher_citations "
        "ON papers(teacher_id, citation_count DESC)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_processing_score ON processing(score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_processing_teaching ON processing(teaching_score)",
)


def readonly_uri(path):
    return "file:" + quote(os.path.abspath(path).replace("\\", "/"), safe="/:") + "?mode=ro"


def connect(path, readonly=True, timeout=5.0):
    """建连接；readonly=True 时用 URI 只读模式。"""
    if readonly:
        conn = sqlite3.connect(readonly_uri(path), uri=True, timeout=timeout)
    else:
        conn = sqlite3.connect(path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_db():
    """当前请求共享的连接。"""
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"], readonly=True)
    return g.db


def close_db(_exception=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(path):
    """启动时补索引、开 WAL；数据库只读或不存在时不阻塞启动。"""
    if not os.path.exists(path):
        current_app.logger.warning("数据库不存在：%s", path)
        return False
    try:
        conn = connect(path, readonly=False, timeout=10.0)
    except sqlite3.Error as exc:
        current_app.logger.warning("数据库无法写入，跳过索引自检：%s", exc)
        return False
    try:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error as exc:
            current_app.logger.info("WAL 未启用：%s", exc)
        for sql in INDEXES:
            try:
                conn.execute(sql)
            except sqlite3.Error as exc:
                current_app.logger.warning("建索引失败 %s：%s", sql.split(" ON ")[0], exc)
        conn.commit()
        return True
    finally:
        conn.close()


def db_stamp(path):
    """(路径, 修改时间, 大小) —— 作为缓存键，库被重写后缓存自动失效。"""
    try:
        st = os.stat(path)
        return (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return (path, 0, 0)


def file_stamp(path):
    try:
        st = os.stat(path)
        return (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return (path, 0, 0)

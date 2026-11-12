"""SQLite 数据库 schema 与写入。"""
import sqlite3

from crawler import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    name_pinyin TEXT,
    college TEXT,
    college_raw TEXT,
    title TEXT,
    email TEXT,
    discipline TEXT,
    research_directions TEXT,
    bio TEXT,
    homepage_url TEXT,
    is_advisor INTEGER DEFAULT 0,
    is_phd_advisor INTEGER DEFAULT 0,
    filter_reason TEXT,
    honors TEXT,
    course_community_id INTEGER,
    teacher_code TEXT,
    course_community_url TEXT,
    scholar_id TEXT,
    scholar_name TEXT,
    paper_count INTEGER,
    citation_count INTEGER,
    h_index INTEGER,
    research_topics TEXT,
    institute TEXT,
    personal_homepage TEXT
);

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER,
    title TEXT,
    year INTEGER,
    citation_count INTEGER,
    venue TEXT,
    doi TEXT,
    paper_id TEXT
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER,
    course_name TEXT,
    course_code TEXT,
    rating_score REAL,
    rating_avg REAL,
    rating_count INTEGER,
    last_semester TEXT,
    course_url TEXT
);
"""


def connect(db_path=None):
    path = db_path or config.DB_PATH
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def reset(db_path=None):
    conn = connect(db_path)
    conn.execute("DROP TABLE IF EXISTS papers")
    conn.execute("DROP TABLE IF EXISTS courses")
    conn.execute("DROP TABLE IF EXISTS teachers")
    conn.executescript(SCHEMA)
    return conn


def save_teachers(conn, teachers):
    cur = conn.cursor()
    for t in teachers:
        cur.execute(
            """INSERT INTO teachers (
                name, name_pinyin, college, college_raw, title, email, discipline,
                research_directions, bio, homepage_url, is_advisor, is_phd_advisor,
                filter_reason, honors, course_community_id, teacher_code,
                course_community_url, scholar_id, scholar_name, paper_count,
                citation_count, h_index, research_topics, institute, personal_homepage)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                t.get("name"),
                t.get("name_pinyin"),
                t.get("college"),
                t.get("college_raw"),
                t.get("title"),
                t.get("email"),
                t.get("discipline"),
                t.get("research_directions"),
                t.get("bio"),
                t.get("homepage_url"),
                t.get("is_advisor", 0),
                t.get("is_phd_advisor", 0),
                t.get("filter_reason"),
                t.get("honors"),
                t.get("course_community_id"),
                t.get("teacher_code"),
                t.get("course_community_url"),
                t.get("scholar_id"),
                t.get("scholar_name"),
                t.get("paper_count"),
                t.get("citation_count"),
                t.get("h_index"),
                t.get("research_topics"),
                t.get("institute"),
                t.get("personal_homepage"),
            ),
        )
        tid = cur.lastrowid
        for p in t.get("papers") or []:
            cur.execute(
                """INSERT INTO papers (teacher_id, title, year, citation_count, venue, doi, paper_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (tid, p.get("title"), p.get("year"), p.get("citation_count"),
                 p.get("venue"), p.get("doi"), p.get("paper_id")),
            )
        for p in t.get("papers_cs") or []:
            cur.execute(
                """INSERT INTO papers (teacher_id, title, venue)
                   VALUES (?,?,?)""",
                (tid, p.get("citation"), p.get("venue")),
            )
        for c in t.get("courses") or []:
            cur.execute(
                """INSERT INTO courses (teacher_id, course_name, course_code, rating_score,
                   rating_avg, rating_count, last_semester, course_url)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (tid, c.get("course_name"), c.get("course_code"), c.get("rating_score"),
                 c.get("rating_avg"), c.get("rating_count"), c.get("last_semester"),
                 c.get("course_url")),
            )
    conn.commit()

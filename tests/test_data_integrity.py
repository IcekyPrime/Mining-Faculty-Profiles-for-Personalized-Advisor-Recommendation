# -*- coding: utf-8 -*-
"""数据完整性测试：把「数据口径」当成契约来守住。

这些断言一旦失败，说明补录/重跑管线引入了回归，而不是接口写错了。
"""
import json
import sqlite3

import pytest


@pytest.fixture(scope="module")
def conn(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_teacher_count(conn):
    assert conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0] >= 700


def test_pinyin_and_college_complete(conn):
    assert conn.execute(
        "SELECT COUNT(*) FROM teachers WHERE name_pinyin IS NULL OR name_pinyin=''"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM teachers WHERE college IS NULL OR college=''"
    ).fetchone()[0] == 0


def test_honors_are_json_lists(conn):
    for row in conn.execute("SELECT id, honors FROM teachers WHERE honors IS NOT NULL"):
        value = json.loads(row["honors"])
        assert isinstance(value, list), f"teacher {row['id']} honors 不是数组"


def test_no_numbering_prefix_in_honors(conn):
    import re
    # 只认「[1] 」「1.」「一、」这类编号；「2018 上海交通大学…」「2006、2017年…」
    # 里的年份不是编号，不能被清掉
    pattern = re.compile(
        r"^(?:[\s]*[\[\(（【]\s*(?:\d+|[一二三四五六七八九十]+)\s*[\]\)）】]"
        r"|[\s]*(?:\d{1,2}|[一二三四五六七八九十]+)[\.、,，:：](?!\d))\s*"
    )
    for row in conn.execute("SELECT id, honors FROM teachers WHERE honors IS NOT NULL"):
        for item in json.loads(row["honors"]):
            assert not pattern.match(item), f"teacher {row['id']} 荣誉仍带编号：{item}"


def test_paper_years_valid(conn):
    bad = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE year IS NOT NULL AND (year < 1950 OR year > 2027)"
    ).fetchone()[0]
    assert bad == 0


def test_no_orphan_records(conn):
    assert conn.execute(
        "SELECT COUNT(*) FROM papers WHERE teacher_id NOT IN (SELECT id FROM teachers)"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM courses WHERE teacher_id NOT IN (SELECT id FROM teachers)"
    ).fetchone()[0] == 0


def test_no_duplicate_papers(conn):
    # 标题规范化在 SQL 里做不了，退化为「完全同标题 + 同年份」检查
    dup = conn.execute(
        "SELECT COUNT(*) FROM (SELECT teacher_id, title, year, COUNT(*) n FROM papers "
        "GROUP BY teacher_id, title, year HAVING n > 1)"
    ).fetchone()[0]
    assert dup == 0


def test_score_range_and_parts(conn):
    for row in conn.execute("SELECT teacher_id, score, score_coverage, score_parts FROM processing"):
        assert row["score"] is None or 0 <= row["score"] <= 100
        assert row["score_coverage"] is None or 0 <= row["score_coverage"] <= 1
        if row["score_parts"]:
            parts = json.loads(row["score_parts"])
            assert set(parts) <= {"papers", "citations", "h_index", "honors", "teaching"}
            for part in parts.values():
                assert part["used"] in (True, False)


def test_missing_values_stay_null(conn):
    """未知量必须是 NULL：如果被写成 0，评审会把「没查到」当成「确实没有」。"""
    null_cites = conn.execute(
        "SELECT COUNT(*) FROM teachers WHERE citation_count IS NULL"
    ).fetchone()[0]
    assert null_cites > 0, "引用量全部有值，说明又有环节把缺失填成了 0"
    zero_cites = conn.execute(
        "SELECT COUNT(*) FROM teachers WHERE citation_count = 0"
    ).fetchone()[0]
    assert zero_cites <= 5


def test_processing_coverage_reasonable(conn):
    keywords = conn.execute(
        "SELECT COUNT(*) FROM processing WHERE keywords IS NOT NULL"
    ).fetchone()[0]
    assert keywords >= 700

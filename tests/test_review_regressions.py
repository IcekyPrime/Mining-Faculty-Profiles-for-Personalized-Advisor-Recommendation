# -*- coding: utf-8 -*-
"""审查回归测试：防止论文回退、topic 召回污染、legacy 洞察字段和 WAL 缓存失效。"""
import sqlite3

from app.db import db_stamp


def test_search_does_not_recall_topic_only_records(client):
    """默认 score 排序不能被 topic 分单独拉进无关教师。"""
    payload = client.get(
        "/api/search", query_string={"q": "机器学习", "sort": "score", "size": 5}
    ).get_json()
    assert payload["total"] < 400, "默认召回应回到词法证据，而不是 600+ 条"
    assert payload["items"]
    for item in payload["items"]:
        assert item["bm25"] > 0, f"{item['name']} 只靠 topic 分被召回"


def test_insights_keeps_legacy_contract(client):
    data = client.get("/api/insights").get_json()
    assert data["total"] > 0
    assert "filled" in data["teaching"] and "pct" in data["teaching"]
    assert data["coverage"][0]["filled"] == data["coverage"][0]["count"]
    assert data["coverage"][0]["pct"] >= 0
    assert len(data["histogram"]["counts"]) == 10
    assert data["top"] and "score" in data["top"][0]
    assert data["scores"]["top_improved"]
    for community in data["communities"]:
        assert community["sample"]
        assert community["keywords"]
        assert community["members"]


def test_original_score_has_teaching_imputed(client):
    payload = client.get("/api/insights").get_json()
    assert payload["teaching"]["filled"] > 0
    assert payload["teaching"]["filled"] < payload["total"], "应有教师使用均值填充"


def test_db_stamp_detects_wal_incremental_write(tmp_path):
    path = str(tmp_path / "wal.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
    conn.commit()
    before = db_stamp(path)
    conn.execute("INSERT INTO t(v) VALUES('x')")
    conn.commit()
    after = db_stamp(path)
    conn.close()
    assert before != after, "WAL 增量写入后缓存键必须变化"
    assert after[1] == before[1], "主库 mtime 可能不变，测试覆盖的正是这个场景"

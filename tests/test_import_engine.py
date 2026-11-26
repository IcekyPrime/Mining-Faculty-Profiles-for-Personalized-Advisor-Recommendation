# -*- coding: utf-8 -*-
"""数据工坊导入引擎测试：解析、分类、清洗、去重与事务入库。"""
import io
import json
import os
import shutil
import sqlite3

import pandas as pd
import pytest

from app import import_ai, import_engine, import_store


@pytest.fixture()
def import_db(db_path, tmp_path):
    target = tmp_path / "import.db"
    shutil.copy2(db_path, target)
    return str(target)


def test_parse_csv_maps_chinese_headers():
    content = (
        "姓名,学院,职称,邮箱,研究方向\n"
        "张三,计算机学院,教授,zhangsan@example.com,计算机视觉、自然语言处理\n"
    ).encode()
    rows, columns, notes = import_engine.parse_upload("teachers.csv", content)
    assert len(rows) == 1
    assert columns[:3] == ["姓名", "学院", "职称"]
    assert notes


def test_parse_json_classified_containers():
    payload = json.dumps({
        "teachers": [{"姓名": "李四", "学院": "计算机学院"}],
        "papers": [{"教师姓名": "陈海波", "论文标题": "A Test Paper", "年份": 2024}],
    }, ensure_ascii=False).encode()
    rows, _columns, _notes = import_engine.parse_upload("mixed.json", payload)
    assert len(rows) == 2
    assert rows[0]["entity_type"] == "teacher"
    assert rows[1]["entity_type"] == "paper"


def test_parse_xlsx_first_sheet():
    frame = pd.DataFrame([
        {"姓名": "王五", "学院": "计算机学院", "职称": "副教授"},
    ])
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False)
    rows, columns, _notes = import_engine.parse_upload("teachers.xlsx", buffer.getvalue())
    assert len(rows) == 1
    assert rows[0]["姓名"] == "王五"
    assert columns == ["姓名", "学院", "职称"]


@pytest.mark.parametrize("row,expected", [
    (
        {"姓名": "张三", "学院": "计算机学院", "职称": "教授", "研究方向": "数据挖掘"},
        "teacher",
    ),
    (
        {"教师姓名": "陈海波", "论文标题": "Operating System Paper", "年份": "2024",
         "期刊": "SOSP", "DOI": "10.1/test"},
        "paper",
    ),
    (
        {"教师姓名": "陈海波", "课程名称": "操作系统", "课程代码": "CS101",
         "评分": "4.8"},
        "course",
    ),
])
def test_detect_entity_type(row, expected):
    assert import_engine.detect_entity_type(import_engine.map_row(row))[0] == expected


def test_clean_teacher_fields(import_db):
    rows, summary = import_engine.analyse(import_db, [{
        "姓名": "  测试教师丙  ",
        "学院": "计算机学院",
        "职称": "教授",
        "邮箱": "BAD-EMAIL",
        "研究方向": "计算机视觉，自然语言处理; 计算机视觉",
        "个人主页": "www.example.com/profile",
        "是否博导": "是",
        "荣誉": "优秀教师、IEEE Fellow",
    }], mode="teacher")
    clean = rows[0]["clean"]
    assert clean["name"] == "测试教师丙"
    assert clean["email"] == ""
    assert clean["research_directions"] == "计算机视觉、自然语言处理"
    assert clean["personal_homepage"] == "https://www.example.com/profile"
    assert clean["is_phd_advisor"] is True
    assert json.loads(clean["honors"]) == ["优秀教师", "IEEE Fellow"]
    assert summary["total_rows"] == 1
    assert rows[0]["status"] == "warning"  # 邮箱无效被清空


def test_clean_teacher_honors_keep_year_with_award(import_db):
    """逗号是“年份，奖项”的一部分，不能被普通 split_list 切断。"""
    rows, _summary = import_engine.analyse(import_db, [{
        "姓名": "年份荣誉测试教师",
        "学院": "计算机学院",
        "荣誉": "2025年，上海市科技进步一等奖（排4）；2024年，吴文俊人工智能青年科技奖；杰青、优青",
    }], mode="teacher")
    assert json.loads(rows[0]["clean"]["honors"]) == [
        "2025年，上海市科技进步一等奖(排4)",
        "2024年，吴文俊人工智能青年科技奖",
        "杰青",
        "优青",
    ]


def test_clean_course_score_and_duplicate(import_db):
    rows, _summary = import_engine.analyse(import_db, [{
        "教师姓名": "陈海波",
        "课程名称": "操作系统",
        "课程代码": "SE3357",
        "评分": "95",
    }], mode="course")
    assert rows[0]["clean"]["rating_score"] == 4.75
    assert rows[0]["status"] == "duplicate"
    assert rows[0]["duplicate"]["scope"] == "database"


def test_file_level_duplicate_detection(import_db):
    rows, _summary = import_engine.analyse(import_db, [
        {"姓名": "重复甲", "学院": "计算机学院", "研究方向": "数据挖掘"},
        {"姓名": "重复甲", "学院": "计算机学院", "研究方向": "数据挖掘"},
    ], mode="teacher")
    assert rows[0]["status"] == "ready"
    assert rows[1]["status"] == "duplicate"
    assert rows[1]["duplicate"]["scope"] == "file"


def test_apply_rows_writes_transactionally(import_db):
    rows, _summary = import_engine.analyse(import_db, [
        {"姓名": "导入教师甲", "学院": "计算机学院", "职称": "教授",
         "研究方向": "数据挖掘、图神经网络"},
        {"教师姓名": "陈海波", "论文标题": "Import Engine Test Paper",
         "年份": "2025", "DOI": "10.9999/import-engine-test", "期刊": "KDD"},
        {"教师姓名": "陈海波", "课程名称": "导入课程甲", "课程代码": "IMP101",
         "评分": "4.5"},
    ], mode="auto")
    result = import_engine.apply_rows(import_db, rows, conflict="skip")
    assert result["totals"]["teachers_inserted"] == 1
    assert result["totals"]["papers_inserted"] == 1
    assert result["totals"]["courses_inserted"] == 1
    assert result["totals"]["failed"] == 0
    conn = sqlite3.connect(import_db)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM teachers WHERE name = '导入教师甲'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT title FROM papers WHERE doi = '10.9999/import-engine-test'"
        ).fetchone()[0] == "Import Engine Test Paper"
        assert conn.execute(
            "SELECT rating_score FROM courses WHERE course_code = 'IMP101'"
        ).fetchone()[0] == 4.5
    finally:
        conn.close()


def test_apply_duplicate_update_empty(import_db):
    conn = sqlite3.connect(import_db)
    # 测试库可能所有教师都已补全邮箱；主动清空一条，保证用例不依赖当前数据分布。
    conn.execute("UPDATE teachers SET email='' WHERE id = (SELECT id FROM teachers ORDER BY id LIMIT 1)")
    conn.commit()
    row = conn.execute(
        "SELECT id, name, college FROM teachers "
        "WHERE email IS NULL OR email = '' ORDER BY id LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None
    rows, _summary = import_engine.analyse(import_db, [{
        "姓名": row[1], "学院": row[2], "邮箱": "filled@example.com",
    }], mode="teacher")
    assert rows[0]["duplicate"]["scope"] == "database"
    result = import_engine.apply_rows(import_db, rows, conflict="update_empty")
    assert result["totals"]["teachers_updated"] == 1
    conn = sqlite3.connect(import_db)
    try:
        assert conn.execute(
            "SELECT email FROM teachers WHERE id = ?", (row[0],)
        ).fetchone()[0] == "filled@example.com"
    finally:
        conn.close()


def test_apply_ai_suggestions_forces_type_and_fields(import_db):
    rows, _summary = import_engine.analyse(import_db, [{
        "姓名": "AI 测试行",
        "单位": "计算机学院",
        "研究方向": "data mining, graph learning",
    }], mode="auto")
    suggestions = [{
        "row_number": 1,
        "entity_type": "teacher",
        "confidence": 88,
        "field_updates": {"college": "计算机学院", "research_directions": "数据挖掘、图学习"},
        "notes": ["方向已规范化"],
        "drop_reason": "",
    }]
    merged = import_engine.apply_ai_suggestions(import_db, rows, suggestions, mode="auto")
    assert merged[0]["entity_type"] == "teacher"
    assert merged[0]["clean"]["research_directions"] == "数据挖掘、图学习"
    assert any(issue["field"] == "ai" for issue in merged[0]["issues"])


def test_ai_local_endpoint_without_key(monkeypatch, import_db):
    config = {
        "enabled": True,
        "api_base": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
        "api_key": "",
    }
    assert import_ai.is_available(config)
    assert not import_ai.is_available({**config, "enabled": False})
    rows, _summary = import_engine.analyse(import_db, [{
        "姓名": "AI 本地测试教师", "学院": "计算机学院", "研究方向": "data mining",
    }], mode="auto")

    def fake_chat_json(_config, _system, _user, **_kwargs):
        return {"rows": [{
            "row_number": 1,
            "entity_type": "teacher",
            "confidence": 90,
            "field_updates": {
                "research_directions": "数据挖掘",
                "email": "should-not-be-written@example.com",
            },
            "notes": ["本地模型只做规范化"],
        }]}

    monkeypatch.setattr(import_ai, "chat_json", fake_chat_json)
    result = import_ai.assist(rows, config)
    assert result["processed"] == 1
    assert result["suggestions"][0]["field_updates"] == {"research_directions": "数据挖掘"}
    merged = import_engine.apply_ai_suggestions(import_db, rows, result["suggestions"])
    assert merged[0]["clean"]["research_directions"] == "数据挖掘"


def test_backup_database_creates_copy(import_db, tmp_path):
    backup = import_engine.backup_database(import_db, str(tmp_path / "backup"))
    assert os.path.exists(backup)
    assert os.path.getsize(backup) > 0


def test_claim_apply_is_atomic(import_db, tmp_path):
    token, _ = import_store.create_job(
        import_db, str(tmp_path / "imports"),
        {"filename": "claim.csv", "mode": "teacher", "status": "preview"},
        [{"row_number": 1, "entity_type": "teacher", "clean": {"name": "甲"}}],
    )
    assert import_store.claim_apply(import_db, token) is True
    assert import_store.claim_apply(import_db, token) is False
    job = import_store.get_job(import_db, token)
    assert job["status"] == "applying"


def test_corrupted_preview_rows_return_empty(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"rows": [', encoding="utf-8")
    assert import_store.load_rows(str(tmp_path), "broken") == []


def test_existing_index_handles_percent_encoded_path(db_path, tmp_path):
    target = tmp_path / "mentor%20copy.db"
    shutil.copy2(db_path, target)
    index = import_engine.existing_index(str(target))
    assert len(index["teachers"]) > 0
    assert index["teacher_names"]


def test_same_name_teachers_require_disambiguation(import_db):
    conn = sqlite3.connect(import_db)
    try:
        conn.executemany(
            "INSERT INTO teachers (name, college) VALUES (?, ?)",
            [("同名测试", "甲学院"), ("同名测试", "乙学院")],
        )
        conn.commit()
    finally:
        conn.close()
    index = import_engine.existing_index(import_db)
    assert len(index["teacher_names"]["同名测试"]) == 2
    rows, _summary = import_engine.analyse(import_db, [{
        "论文标题": "同名教师论文",
        "作者": "测试作者",
        "教师姓名": "同名测试",
    }], mode="auto")
    assert rows[0]["status"] == "error"
    assert any(
        issue["field"] == "teacher_name" and "同名教师" in issue["message"]
        for issue in rows[0]["issues"]
    )


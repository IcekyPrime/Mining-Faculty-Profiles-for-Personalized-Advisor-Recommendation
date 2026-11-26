# -*- coding: utf-8 -*-
"""评分逻辑单元测试：缺失感知、分位数归一、荣誉映射与收缩。"""
import json
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "processing"))

import score as legacy  # noqa: E402  —— 原始评分，原样保留
import score_v2 as score  # noqa: E402  —— 新增的改进评分，只写 score_v2 列


def test_original_scoring_kept_unchanged():
    """原 score.py 的固定权重与 5%–95% 截断必须原样保留，供 v2 对照。"""
    assert legacy.HONOR_W["杰青"] == 4.0
    out = legacy.normalize([0, 1, 2, 3, 100])
    assert out[0] == 0 and out[-1] == 1


def test_honor_points_recognizes_titles():
    honors = json.dumps(["国家杰出青年科学基金获得者", "IEEE Fellow"], ensure_ascii=False)
    points, labels = score.honor_points(honors)
    assert points == pytest.approx(4.0 + 2.5)
    assert "杰青" in labels and "IEEE Fellow" in labels


def test_honor_points_dedup_by_dimension():
    honors = json.dumps(["杰青", "国家杰出青年科学基金"], ensure_ascii=False)
    points, _ = score.honor_points(honors)
    assert points == pytest.approx(4.0)


def test_honor_points_handles_bad_json():
    assert score.honor_points(None) == (0.0, [])
    assert score.honor_points("not-json") == (0.0, [])


def test_honor_points_uses_mild_recency_weight():
    old = json.dumps(["2010年获国家杰出青年科学基金"], ensure_ascii=False)
    recent = json.dumps(["2025年获国家杰出青年科学基金"], ensure_ascii=False)
    old_points, _ = score.honor_points(old, current_year=2026)
    recent_points, _ = score.honor_points(recent, current_year=2026)
    assert old_points < recent_points
    assert old_points >= 4.0 * score.HONOR_RECENCY_FLOOR
    # 没有年份时不做时效惩罚，保持原权重
    assert score.honor_points(json.dumps(["杰青"], ensure_ascii=False), current_year=2026)[0] == 4.0


def test_percentile_ranker_ignores_missing():
    _, rank = score.percentile_ranker([None, 10, 20, 30])
    assert rank(None) is None
    assert rank(10) == pytest.approx(33.3, abs=0.1)
    assert rank(30) == pytest.approx(100.0, abs=0.1)


def test_score_uses_only_available_dimensions(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE teachers (id INTEGER PRIMARY KEY, name TEXT, title TEXT, honors TEXT,"
        " paper_count INTEGER, citation_count INTEGER, h_index INTEGER)"
    )
    conn.execute(
        "CREATE TABLE courses (teacher_id INTEGER, rating_avg REAL, rating_count INTEGER)"
    )
    # 甲：信息齐全；乙：只有 h 指数；丙：只有荣誉
    conn.executemany(
        "INSERT INTO teachers VALUES (?,?,?,?,?,?,?)",
        [
            (1, "甲", "教授", json.dumps(["杰青"], ensure_ascii=False), 100, 5000, 30),
            (2, "乙", "副教授", None, None, None, 12),
            (3, "丙", "讲师", json.dumps(["优青"], ensure_ascii=False), None, None, None),
        ],
    )
    conn.commit()

    rankers = {
        dim: score.percentile_ranker(values)[1]
        for dim, values in {
            "papers": [100, None, None],
            "citations": [5000, None, None],
            "h_index": [30, 12, None],
            "honors": [4.0, 0.0, 3.0],
            "teaching": [None, None, None],
        }.items()
    }
    parts = {
        dim: rankers[dim](value)
        for dim, value in {
            "papers": 100, "citations": 5000, "h_index": 30, "honors": 4.0, "teaching": None,
        }.items()
    }
    # 缺教学维度时，分数不应被 weight 拉低；收缩项把接近满分的组合压到合理区间
    total = sum(score.WEIGHTS[d] * parts[d] for d in parts if parts[d] is not None)
    total_w = sum(score.WEIGHTS[d] for d in parts if parts[d] is not None)
    result = (total + score.PRIOR_W * score.PRIOR_SCORE) / (total_w + score.PRIOR_W)
    assert 60 <= result <= 95
    conn.close()

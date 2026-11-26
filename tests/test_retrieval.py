# -*- coding: utf-8 -*-
"""BM25F 单元测试：分词、索引和排序行为。"""
from app.retrieval import build_index, tokenize


def _record(tid, name, directions="", keywords=None, pinyin=""):
    return {
        "item": {
            "id": tid,
            "name": name,
            "name_pinyin": pinyin,
            "keywords": keywords or [],
            "research_directions": directions,
            "institute": "",
            "title": "",
        },
        "name": name,
    }


def test_tokenize_mixes_cjk_bigrams_and_ascii_words():
    tokens = tokenize("医学图像 AI 实验室")
    assert "医学" in tokens and "图像" in tokens
    assert "ai" in tokens


def test_index_prefers_name_match():
    records = [
        _record(1, "操作系统", "系统软件"),
        _record(2, "张三", "操作系统、分布式系统"),
        _record(3, "李四", "计算机视觉"),
    ]
    scores = build_index(records).scores("操作系统")
    assert scores[1] > scores[2]
    assert 3 not in scores


def test_empty_query_returns_empty_scores():
    index = build_index([_record(1, "张三", "机器学习")])
    assert index.scores("") == {}
    assert index.scores("   ") == {}


def test_document_frequency_counts_once_per_teacher():
    """同一词出现在关键词和方向两个字段时，df 只能计一次。"""
    records = [
        _record(1, "张三", "机器学习", keywords=["机器学习"]),
        _record(2, "李四", "数据挖掘"),
    ]
    index = build_index(records)
    assert index.n == 2
    assert index.df["学习"] == 1
    assert index.df["机器"] == 1
    assert index.df["数据"] == 1


def test_query_aliases_expand_to_existing_keywords():
    records = [
        _record(1, "张三", "", keywords=["机器学习"]),
        _record(2, "李四", "计算机视觉"),
    ]
    index = build_index(records)
    assert index.scores("ML").get(1, 0) > 0
    assert index.scores("CV").get(2, 0) > 0


# -*- coding: utf-8 -*-
"""通用数据挖掘组件测试：不依赖某一位教师或某一批固定数据。"""
from app.mining import (
    QueryExpander,
    build_topic_model,
    cluster_with_auto_k,
    learn_acronyms,
    load_lexicon,
    serialize_topic_model,
    topic_scores,
)


def test_lexicon_is_external_and_replaceable():
    lex = load_lexicon()
    assert lex["aliases"]["ml"]
    assert lex["areas"]


def test_learn_acronyms_from_corpus_and_word_boundary():
    docs = [
        "机器学习（ML）与数据挖掘",
        "机器学习(ML)模型",
        "自然语言处理（NLP）",
        "医学影像（Medical Imaging）",
    ]
    learned = learn_acronyms(docs)
    assert learned["ml"] == "机器学习"
    assert learned["nlp"] == "自然语言处理"

    expander = QueryExpander({"ml": ["机器学习"]}, learned)
    assert "机器学习" in expander.expand("ML")
    # 短英文缩写不能命中 html / said 这类普通单词。
    assert "机器学习" not in expander.expand("html")
    assert "机器学习" not in expander.expand("said")


def test_topic_model_outputs_distribution_and_query_scores():
    texts = [
        "机器学习 数据挖掘 图神经网络",
        "数据挖掘 推荐系统 机器学习",
        "计算机视觉 图像处理 多模态",
        "自然语言处理 大模型 语音识别",
    ]
    model = build_topic_model(texts, n_topics=2)
    assert model["k"] == 2
    assert len(model["topics"]) == 2
    ids = [101, 102, 103, 104]
    payload = serialize_topic_model(model, ids)
    assert set(payload["doc_topics"]) == {str(i) for i in ids}
    for values in payload["doc_topics"].values():
        assert abs(sum(item["weight"] for item in values) - 1.0) < 0.02
    scores = topic_scores(payload, "机器学习")
    assert scores
    assert max(scores.values()) <= 1.0001


def test_cluster_auto_k_handles_small_and_high_dimensional_data():
    from sklearn.feature_extraction.text import TfidfVectorizer

    texts = ["机器学习", "数据挖掘", "计算机视觉", "自然语言处理", "电力系统", "芯片设计"]
    matrix = TfidfVectorizer(tokenizer=lambda x: list(x), token_pattern=None).fit_transform(texts)
    labels, k, score = cluster_with_auto_k(matrix, k_min=2, k_max=4)
    assert len(labels) == len(texts)
    assert 2 <= k <= 4
    assert -1.0 <= score <= 1.0

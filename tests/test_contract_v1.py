# -*- coding: utf-8 -*-
"""v1.0 接口契约回归：原有字段一个都不能少（新增字段另行断言）。

本文件对应"功能只添加、不删除"的约束：无论内部如何分层，v1.0 的
路径、参数与响应字段必须继续可用。
"""
import pytest


@pytest.fixture()
def client(app):
    return app.test_client()


def test_stats_keeps_v1_fields(client):
    data = client.get("/api/stats").get_json()
    for key in ("total_teachers", "total_papers", "total_courses", "colleges", "h_index", "h_histogram"):
        assert key in data
    assert data["h_index"]["count"] >= 0


def test_search_keeps_v1_envelope_and_adds_score_v2(client):
    data = client.get("/api/search?q=操作系统&sort=score").get_json()
    for key in ("total", "page", "size", "pages", "sort", "items"):
        assert key in data
    item = data["items"][0]
    for key in ("id", "name", "college", "title", "keywords", "honors", "rating",
                "score", "h_index", "citation_count", "paper_count", "relevance"):
        assert key in item
    assert "score_v2" in item  # v1.1 新增


def test_search_sort_score2_works(client):
    data = client.get("/api/search?sort=score2&size=5").get_json()
    assert data["sort"] == "score2"
    values = [item["score_v2"] for item in data["items"] if item["score_v2"] is not None]
    assert values == sorted(values, reverse=True)


def test_teacher_detail_keeps_v1_fields(client):
    data = client.get("/api/teacher/401").get_json()
    for key in ("id", "name", "college", "courses", "papers", "paper_total",
                "similar", "collaborators", "radar", "rating", "score"):
        assert key in data
    for dim in ("论文产出", "引用影响", "学术声誉", "荣誉头衔", "教学口碑"):
        assert dim in data["radar"]
    course = data["courses"][0]
    for key in ("name", "code", "rating", "rating_avg", "count", "semester"):
        assert key in course
    # 新增字段
    assert "score_v2" in data and "score_parts" in data

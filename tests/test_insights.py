# -*- coding: utf-8 -*-
"""数据洞察接口与检索边界条件测试（v1.1.1 新增）。"""
import pytest


@pytest.fixture()
def client(app):
    return app.test_client()


def test_insights_sections(client):
    data = client.get("/api/insights").get_json()
    assert len(data["colleges"]) == 5
    assert len(data["coverage"]) == 9
    for item in data["coverage"]:
        assert 0.0 <= item["ratio"] <= 1.0
        assert item["count"] <= item["total"]


def test_insights_clusters_cover_corpus(client):
    data = client.get("/api/insights").get_json()
    clusters = data["clusters"]
    assert 0 < len(clusters) <= 8
    assert sum(cluster["size"] for cluster in clusters) > 700
    for cluster in clusters:
        assert cluster["keywords"], "每个簇都应该有主题词"
        assert len(cluster["members"]) <= 3


def test_insights_scores_and_rules(client):
    data = client.get("/api/insights").get_json()
    histogram = data["scores"]["histogram"]
    assert len(histogram["labels"]) == 10
    assert len(histogram["original"]) == 10
    assert len(histogram["improved"]) == 10
    top = data["scores"]["top_improved"]
    assert top and top[0]["score_v2"] >= top[-1]["score_v2"]
    assert data["rules"], "应导出关联规则"


def test_teacher_not_found_returns_json_404(client):
    response = client.get("/api/teacher/999999")
    assert response.status_code == 404
    body = response.get_json()
    assert "error" in body or body.get("detail") is None


def test_college_filter_matches_meta(client):
    meta = client.get("/api/meta").get_json()
    for college in meta["colleges"]:
        payload = client.get("/api/search", query_string={"college": college["name"], "size": 1}).get_json()
        assert payload["total"] == college["count"]


def test_rated_filter_only_rated(client):
    payload = client.get("/api/search", query_string={"rated": 1, "size": 10}).get_json()
    assert payload["total"] > 0
    for item in payload["items"]:
        assert item["rating"]["avg"] is not None


def test_phd_filter_only_phd(client):
    payload = client.get("/api/search", query_string={"phd": 1, "size": 10}).get_json()
    assert payload["total"] > 0
    for item in payload["items"]:
        assert item["is_phd_advisor"] is True


def test_page_beyond_range_returns_empty(client):
    payload = client.get("/api/search", query_string={"page": 500, "size": 20}).get_json()
    assert payload["items"] == []


def test_invalid_arguments_rejected(client):
    for query in ({"size": 0}, {"size": 500}, {"page": 0}, {"sort": "bogus"}):
        response = client.get("/api/search", query_string=query)
        assert response.status_code == 400, query
        assert response.get_json()["error"]["code"] in {"invalid_param", "invalid_sort"}


def test_boolean_flag_is_tolerant(client):
    # 非 0/1 的布尔值按 False 处理，保持 v1.0 的宽松行为
    payload = client.get("/api/search", query_string={"phd": "maybe", "size": 1}).get_json()
    assert payload["total"] > 1

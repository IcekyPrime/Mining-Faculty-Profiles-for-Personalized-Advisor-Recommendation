# -*- coding: utf-8 -*-
"""接口契约测试：字段、状态码、参数校验与分页语义。"""


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["teachers"] >= 700
    assert payload["db"]["exists"] is True
    assert response.headers["Cache-Control"] == "no-store"


def test_meta(client):
    payload = client.get("/api/meta").get_json()
    assert payload["version"]
    assert len(payload["colleges"]) >= 5
    assert set(payload["sorts"]) >= {"score", "academic", "teaching", "relevance"}
    assert "score2" in payload["sorts"]  # v1.1 新增排序
    assert payload["counts"]["teachers"] >= 700
    assert payload["db_updated_at"]


def test_stats_legacy_contract(client):
    payload = client.get("/api/stats").get_json()
    assert payload["total_teachers"] >= 700
    assert payload["total_papers"] >= 10000
    assert payload["h_histogram"] and len(payload["h_histogram"]) == 10


def test_search_basic(client):
    payload = client.get("/api/search?q=操作系统&size=5").get_json()
    assert payload["total"] > 0
    assert len(payload["results"]) <= 5
    # 前端读取 items，旧脚本读取 results，两个键必须同时存在
    assert payload["items"] == payload["results"]
    first = payload["results"][0]
    for field in ("id", "name", "college", "score", "keywords"):
        assert field in first
    assert payload["took_ms"] >= 0


def test_search_college_filter(client):
    college = client.get("/api/meta").get_json()["colleges"][0]["name"]
    payload = client.get(f"/api/search?college={college}&size=100").get_json()
    assert payload["total"] > 0
    assert all(item["college"] == college for item in payload["results"])


def test_search_pagination(client):
    total = client.get("/api/search?size=1").get_json()["total"]
    payload = client.get("/api/search?size=1&page=2").get_json()
    assert payload["pages"] == total
    assert payload["page"] == 2
    assert len(payload["results"]) == 1
    # 第二页的结果不应与第一页重复
    first = client.get("/api/search?size=1&page=1").get_json()["results"][0]["id"]
    assert payload["results"][0]["id"] != first


def test_search_sort_orders(client):
    payload = client.get("/api/search?sort=academic&size=10").get_json()
    values = [item["h_index"] for item in payload["results"] if item["h_index"] is not None]
    assert values == sorted(values, reverse=True)


def test_search_invalid_params(client):
    assert client.get("/api/search?sort=unknown").status_code == 400
    assert client.get("/api/search?page=abc").status_code == 400
    assert client.get("/api/search?size=1000").status_code == 400
    assert client.get("/api/search?sort=unknown").get_json()["error"]["code"] == "invalid_sort"


def test_teacher_detail_contract(client):
    # 取教学口碑最高的一位（必然有课程与评分），避免依赖某个固定 id
    top = client.get("/api/search?sort=teaching&size=1").get_json()["results"][0]
    payload = client.get(f"/api/teacher/{top['id']}").get_json()
    assert payload["name"]
    assert "score_parts" in payload and payload["score_parts"]
    assert set(payload["radar"]) == {"论文产出", "引用影响", "学术声誉", "荣誉头衔", "教学口碑"}
    assert isinstance(payload["radar_known"], dict)
    assert "similar" in payload and "collaborators" in payload
    assert payload["courses"] and payload["courses"][0]["name"]


def test_teacher_detail_404(client):
    response = client.get("/api/teacher/999999")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "导师" in response.get_data(as_text=True)


def test_api_unknown_route_json(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_gzip_when_client_supports_it(client):
    response = client.get("/api/search?size=20", headers={"Accept-Encoding": "gzip"})
    assert response.headers.get("Content-Encoding") == "gzip"
    assert response.headers.get("Vary") == "Accept-Encoding"

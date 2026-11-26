# -*- coding: utf-8 -*-
"""接口契约测试：字段、状态码、参数校验与分页语义。"""
import io


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["teachers"] >= 700
    assert payload["db"]["exists"] is True
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Request-ID"]


def test_html_and_api_errors_have_the_right_shape(client):
    page = client.get("/definitely-not-a-page")
    assert page.status_code == 404
    assert page.mimetype == "text/html"
    body = page.data.decode("utf-8")
    assert "请求没有完成" in body
    assert "404" in body

    api = client.get("/api/definitely-not-a-page")
    assert api.status_code == 404
    error = api.get_json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"]


def test_upload_size_limit_returns_json(client):
    app = client.application
    old = app.config["MAX_CONTENT_LENGTH"]
    app.config["MAX_CONTENT_LENGTH"] = 1024
    try:
        response = client.post(
            "/api/import/preview",
            data={"file": (io.BytesIO(b"x" * 2048), "large.csv")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 413
        assert response.get_json()["error"]["code"] == "payload_too_large"
    finally:
        app.config["MAX_CONTENT_LENGTH"] = old


def test_file_limit_uses_configured_upload_bytes(client):
    """路由内的文件上限应与 MENTOR_MAX_UPLOAD_BYTES 一致，而不是第二套 20 MB。"""
    app = client.application
    old_upload = app.config["MAX_UPLOAD_BYTES"]
    old_content = app.config["MAX_CONTENT_LENGTH"]
    app.config["MAX_UPLOAD_BYTES"] = 1024
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
    try:
        response = client.post(
            "/api/import/preview",
            data={"file": (io.BytesIO(b"x" * 2048), "large.csv")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 413
        assert response.get_json()["error"]["code"] == "file_too_large"
        assert "1 KB" in response.get_json()["error"]["message"]
    finally:
        app.config["MAX_UPLOAD_BYTES"] = old_upload
        app.config["MAX_CONTENT_LENGTH"] = old_content



def test_meta(client):
    payload = client.get("/api/meta").get_json()
    assert payload["version"]
    assert len(payload["colleges"]) >= 5
    assert set(payload["sorts"]) >= {"score", "academic", "teaching", "relevance"}
    assert "score2" in payload["sorts"]  # v1.1 新增排序
    assert "bm25" in payload["sorts"]  # v1.9 新增信息检索基线
    assert "topic" in payload["sorts"]  # 主题模型排序
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


def test_search_bm25_orders(client):
    payload = client.get("/api/search?q=操作系统&sort=bm25&size=10").get_json()
    assert payload["sort"] == "bm25"
    assert payload["total"] > 0
    scores = [item["bm25"] for item in payload["results"]]
    assert all(value > 0 for value in scores)
    assert scores == sorted(scores, reverse=True)


def test_default_search_recalls_multi_term_bm25_hits(client):
    """默认排序不能被“完整查询串”过滤掉 BM25 的部分词命中。"""
    payload = client.get("/api/search?q=机器学习 量子计算&size=10").get_json()
    assert payload["total"] > 0
    assert any(item["bm25"] > 0 for item in payload["results"])


def test_search_alias_ml_recalls_machine_learning(client):
    payload = client.get("/api/search?q=ML&sort=bm25&size=10").get_json()
    assert payload["total"] > 0
    assert any(item["bm25"] > 0 for item in payload["results"])


def test_search_topic_sort_and_mining_endpoint(client):
    mining = client.get("/api/mining").get_json()
    assert mining["method"] == "TF-IDF + NMF"
    assert mining["k"] >= 1
    assert mining["topics"]

    payload = client.get("/api/search?q=机器学习&sort=topic&size=10").get_json()
    assert payload["sort"] == "topic"
    assert payload["total"] > 0
    scores = [item["topic"] for item in payload["results"]]
    assert all(value > 0 for value in scores)
    assert scores == sorted(scores, reverse=True)


def test_teacher_detail_has_topic_profile(client):
    top = client.get("/api/search?sort=teaching&size=1").get_json()["results"][0]
    payload = client.get(f"/api/teacher/{top['id']}").get_json()
    assert "topic_label" in payload
    assert isinstance(payload["topic_distribution"], list)


def test_normalize_honors_filters_headers_and_sorts_by_year():
    from app.services import honor_stats, normalize_honors

    honors = normalize_honors(
        '["国内奖励：", "无年份荣誉", "2020年，某省科技进步一等奖", "2025年，某竞赛金奖"]'
    )
    assert honors == ["2025年，某竞赛金奖", "2020年，某省科技进步一等奖", "无年份荣誉"]
    stats = honor_stats(honors)
    assert stats["count"] == 3
    assert stats["dated"] == 2
    assert stats["latest_year"] == 2025
    assert stats["categories"]["competition"] == 1


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


def test_mobile_preview_and_favicon(client):
    mobile = client.get("/mobile/")
    assert mobile.status_code == 200
    assert "mobile.css" in mobile.get_data(as_text=True)
    assert client.get("/favicon.ico").status_code == 200


def test_api_unknown_route_json(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_gzip_when_client_supports_it(client):
    response = client.get("/api/search?size=20", headers={"Accept-Encoding": "gzip"})
    assert response.headers.get("Content-Encoding") == "gzip"
    assert response.headers.get("Vary") == "Accept-Encoding"

"""v2.7 对话助手接口与统一配置的回归测试。"""
from assistant import llm, rag, retrieval


def test_graph_rag_adds_collaborator_for_relation_query(db_path):
    old_path = retrieval.DB_PATH
    try:
        retrieval.set_db_path(db_path)
        results = rag.search(["朱燕民", "合作者"], limit=10)
        names = [r["teacher"]["name"] for r in results]
        assert "朱燕民" in names
        assert any(
            r["graph_reason"] and r["teacher"]["name"] != "朱燕民"
            for r in results
        )
    finally:
        retrieval.set_db_path(old_path)


def test_chat_payload_does_not_send_deepseek_thinking(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, **kwargs):
        captured["payload"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr(llm, "load_settings", lambda: {
        "enabled": True,
        "base_url": "https://api.example.com/v1",
        "model": "mock-model",
        "api_key": "sk-test",
    })
    monkeypatch.setattr(llm.requests, "post", fake_post)
    assert llm.chat([{"role": "user", "content": "hi"}], json_mode=True) == "ok"
    assert "thinking" not in captured["payload"]
    assert captured["payload"]["response_format"] == {"type": "json_object"}



def test_chat_routes_registered(app):
    rules = {str(rule) for rule in app.url_map.iter_rules()}
    for path in (
        "/api/chat",
        "/api/chat/status",
        "/api/chat/settings",
        "/api/chat/test",
        "/api/chat/history",
        "/api/chat/clear",
    ):
        assert path in rules


def test_chat_status_reads_local_database(client):
    data = client.get("/api/chat/status").get_json()
    assert data["ok"] is True
    assert data["teachers"] == 773
    assert data["engine"]["mode"] == "rule"
    assert data["online_tools"] == ["official", "arxiv", "crossref", "acemap"]


def test_chat_rule_recommendation_has_consistent_cards(client):
    data = client.post(
        "/api/chat",
        json={"message": "我喜欢数据挖掘，推荐几位导师", "lang": "zh"},
    ).get_json()
    assert data["ok"] is True
    assert data["intent"] == "recommend"
    assert data["engine"]["mode"] == "rule"
    cards = data["cards"]
    assert 4 <= len(cards) <= 6
    # 卡片数量应与正文列出的教师一致，避免“正文 5 位、卡片 4 张”
    for card in cards:
        assert card["name"] in data["reply"]


def test_chat_resolves_english_and_reversed_pinyin(client):
    for question in ("介绍 yu yong", "who is Yong Yu"):
        data = client.post(
            "/api/chat", json={"message": question, "lang": "zh"}
        ).get_json()
        assert data["intent"] == "teacher"
        assert data["cards"][0]["name"] == "俞勇"


def test_chat_settings_and_ai_config_share_one_source(client):
    saved = client.post(
        "/api/chat/settings",
        json={
            "enabled": True,
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5:7b",
            "api_key": "",
        },
    ).get_json()
    assert saved["ok"] is True
    assert saved["status"]["mode"] == "api"
    assert saved["status"]["local_endpoint"] is True
    assert "api_key" not in saved["settings"]

    config = client.get("/api/ai/config").get_json()
    assert config["enabled"] is True
    assert config["api_base"] == "http://127.0.0.1:11434/v1"
    assert config["model"] == "qwen2.5:7b"
    assert config["local_endpoint"] is True


def test_chat_history_and_clear(client):
    headers = {"X-Client-Id": "a" * 32}
    response = client.post(
        "/api/chat",
        json={"message": "计算机学院有哪些导师", "lang": "zh"},
        headers=headers,
    )
    assert response.status_code == 200

    history = client.get("/api/chat/history?limit=10", headers=headers).get_json()
    assert [msg["role"] for msg in history["messages"]] == ["user", "assistant"]

    cleared = client.post("/api/chat/clear", headers=headers).get_json()
    assert cleared["ok"] is True
    history = client.get("/api/chat/history?limit=10", headers=headers).get_json()
    assert history["messages"] == []

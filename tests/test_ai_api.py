# -*- coding: utf-8 -*-
"""AI 配置、自然语言检索与联网补全的接口/单元测试（全部 mock，不访问外网）。"""
import json
import os
import shutil
import sqlite3

from app import ai_config, ai_enrich, ai_search
from app.ai_enrich import apply_enrichment, preview_enrichment
from app.ai_store import ensure_schema, get_job


def _enable_ai(client):
    response = client.post("/api/ai/config", json={
        "enabled": True,
        "api_base": "https://api.example.com/v1",
        "model": "mock-model",
        "api_key": "sk-test-secret",
        "web_search": {
            "enabled": True,
            "provider": "tavily",
            "api_key": "tvly-test-secret",
            "max_results": 3,
        },
    })
    assert response.status_code == 200


def test_ai_config_masks_keys(client, app):
    _enable_ai(client)
    payload = client.get("/api/ai/config").get_json()
    assert payload["configured"] is True
    assert payload["enabled"] is True
    assert payload["has_api_key"] is True
    assert payload["web_search"]["has_api_key"] is True
    assert "sk-test-secret" not in json.dumps(payload)
    assert "tvly-test-secret" not in json.dumps(payload)
    assert os.path.exists(app.config["AI_CONFIG_PATH"])


def test_ai_search_requires_config(client):
    response = client.post("/api/ai/search", json={"q": "医学图像"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "ai_not_configured"


def test_ai_config_tolerates_manual_bad_types(tmp_path):
    """手工改坏配置不应让 /api/ai/config 或 /api/chat/settings 500。"""
    path = tmp_path / "ai_config.json"
    path.write_text(json.dumps({
        "enabled": "false",
        "api_base": 123,
        "model": ["not-a-model"],
        "api_key": {"bad": "type"},
        "web_search": {"enabled": "false", "max_results": "abc"},
    }), encoding="utf-8")
    view = ai_config.public_config(str(tmp_path), str(path))
    assert view["enabled"] is False
    assert view["model"] == ""
    assert view["has_api_key"] is False
    assert view["web_search"]["enabled"] is False
    assert view["web_search"]["max_results"] == 5
    # 保存接口同样不能因手工/异常类型崩溃
    saved = ai_config.save_config(str(tmp_path), {
        "enabled": "false",
        "api_base": "https://api.example.com/v1",
        "model": 123,
        "api_key": {"bad": "type"},
    }, str(path))
    assert saved["enabled"] is False
    assert saved["model"] == "123"
    assert saved["has_api_key"] is False


def test_ai_search_accepts_local_endpoint_without_key(client, monkeypatch):
    saved = client.post("/api/ai/config", json={
        "enabled": True,
        "api_base": "http://10.0.2.2:11434/v1",
        "model": "qwen2.5:7b",
        "api_key": "",
    })
    assert saved.status_code == 200
    assert saved.get_json()["config"]["configured"] is True
    assert saved.get_json()["config"]["local_endpoint"] is True

    monkeypatch.setattr(ai_search, "chat_json", lambda *args, **kwargs: {
        "keywords": ["人工智能"], "college": "", "title": "",
        "phd_only": False, "sort": "score", "summary": "本地端点测试",
    })
    response = client.post("/api/ai/search", json={"q": "人工智能", "size": 2})
    assert response.status_code == 200
    assert response.get_json()["total"] > 0



def test_ai_search_uses_model_intent_and_local_corpus(client, monkeypatch):
    _enable_ai(client)

    def fake_chat(config, system_prompt, user_prompt, **kwargs):
        if "意图解析器" in system_prompt:
            return {
                "keywords": ["人工智能"],
                "college": "",
                "title": "",
                "phd_only": False,
                "sort": "teaching",
                "summary": "找人工智能方向、教学口碑好的导师",
            }
        return {
            "summary": "优先看人工智能方向且教学评分较高的老师。",
            "reasons": {"401": "人工智能与生物信息交叉，教学评分较高。"},
        }

    monkeypatch.setattr(ai_search, "chat_json", fake_chat)
    response = client.post("/api/ai/search", json={"q": "想找人工智能方向、讲课好的老师", "size": 5})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] > 0
    assert payload["items"]
    assert payload["ai"]["keywords"] == ["人工智能"]
    assert payload["ai"]["filters"]["sort"] == "teaching"
    assert payload["ai"]["summary"]

    # AI 结果不应把 ai_reason/ai_score 写回共享语料缓存，普通检索仍保持原字段
    normal = client.get("/api/search?q=人工智能&size=5").get_json()
    assert all("ai_reason" not in item for item in normal["items"])


def test_preview_and_apply_enrichment(db_path, tmp_path, monkeypatch):
    work_db = tmp_path / "mentor.db"
    shutil.copy2(db_path, work_db)
    ensure_schema(str(work_db))
    config = {
        "enabled": True,
        "api_base": "https://api.example.com/v1",
        "api_key": "sk-test",
        "model": "mock-model",
        "web_search": {"enabled": True, "provider": "tavily", "api_key": "tvly-test", "max_results": 3},
    }

    monkeypatch.setattr(ai_enrich, "web_search", lambda config, query: [{
        "title": "沈红斌 教师主页",
        "url": "https://example.com/shen",
        "content": "沈红斌，上海交通大学教授，研究方向为人工智能、生物信息学。邮箱 hbshen@sjtu.edu.cn。",
        "score": 0.9,
    }])
    monkeypatch.setattr(ai_enrich, "fetch_page_text", lambda url, max_chars=5000: "")
    monkeypatch.setattr(ai_enrich, "chat_json", lambda *args, **kwargs: {
        "name": "沈红斌",
        "college": "自动化与感知学院",
        "title": "教授",
        "institute": "系统控制与信息处理教育部重点实验室",
        "research_directions": "人工智能、生物信息学",
        "email": "new-hbshen@sjtu.edu.cn",
        "homepage_url": "https://example.com/shen",
        "personal_homepage": "",
        "bio": "从事人工智能与生物信息学研究。",
        "confidence": 82,
        "field_confidence": {"email": 90, "homepage_url": 88},
        "sources": ["https://example.com/shen"],
    })

    preview = preview_enrichment(tmp_path, str(work_db), config, 401)
    assert preview["token"]
    assert preview["diff"]
    fields = [item["field"] for item in preview["diff"]]
    assert "email" in fields

    result = apply_enrichment(str(work_db), preview["token"], ["email"], start_pipeline=False)
    assert result["status"] == "running"
    job = get_job(str(work_db), preview["token"])
    assert job["status"] == "running"
    assert job["pipeline_status"] == "idle"
    conn = sqlite3.connect(work_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT email FROM teachers WHERE id = 401").fetchone()
    conn.close()
    assert row["email"] == "new-hbshen@sjtu.edu.cn"
    assert os.path.exists(os.path.join(tmp_path, "backup"))

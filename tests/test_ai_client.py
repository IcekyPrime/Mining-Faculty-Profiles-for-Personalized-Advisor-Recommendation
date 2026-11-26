# -*- coding: utf-8 -*-
"""AI 客户端测试：用假 HTTP 响应验证 URL、鉴权头、JSON 容错与搜索适配。"""
import pytest
import requests

from app.ai_client import AIError, chat_completion, parse_json_object, web_search


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _config():
    return {
        "enabled": True,
        "api_base": "https://api.example.com/v1",
        "model": "mock-model",
        "api_key": "sk-test",
        "web_search": {"enabled": True, "provider": "tavily", "api_key": "tvly-test", "max_results": 3},
    }


def test_chat_completion_headers_and_content(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update({"url": url, "headers": headers, "json": json})
        return FakeResponse(payload={"choices": [{"message": {"content": "OK"}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    assert chat_completion(_config(), [{"role": "user", "content": "ping"}]) == "OK"
    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer sk-test"
    assert seen["json"]["model"] == "mock-model"


def test_chat_completion_accepts_full_endpoint(monkeypatch):
    seen = {}
    config = dict(_config(), api_base="https://api.example.com/v1/chat/completions")

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        return FakeResponse(payload={"choices": [{"message": {"content": "OK"}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    assert chat_completion(config, [{"role": "user", "content": "ping"}]) == "OK"
    assert seen["url"] == "https://api.example.com/v1/chat/completions"


def test_chat_completion_auth_error(monkeypatch):
    monkeypatch.setattr(
        requests, "post",
        lambda *args, **kwargs: FakeResponse(status=401, payload={"error": {"message": "bad key"}}),
    )
    with pytest.raises(AIError) as exc:
        chat_completion(_config(), [{"role": "user", "content": "ping"}])
    assert exc.value.code == "ai_auth"


def test_parse_json_object_tolerates_code_fence():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('说明\n{"a": 2}\n结束') == {"a": 2}


def test_web_search_tavily_normalises(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        assert url == "https://api.tavily.com/search"
        return FakeResponse(payload={"results": [
            {"title": "主页", "url": "https://example.com/a", "content": "<p>研究人工智能</p>"},
            {"title": "坏链接", "url": "javascript:alert(1)", "content": ""},
        ]})

    monkeypatch.setattr(requests, "post", fake_post)
    results = web_search(_config(), "上海交通大学 教师")
    assert len(results) == 1
    assert results[0]["url"] == "https://example.com/a"
    assert "人工智能" in results[0]["content"]

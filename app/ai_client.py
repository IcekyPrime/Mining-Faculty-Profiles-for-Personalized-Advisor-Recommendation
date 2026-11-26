# -*- coding: utf-8 -*-
"""OpenAI 兼容 Chat Completions 与联网搜索客户端。

只依赖项目已有的 `requests`，不引入新的 SDK，方便课程环境离线部署时替换
base_url 到 DeepSeek / Qwen / 本地 vLLM 等兼容服务。
"""
import ipaddress
import json
import re
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

TIMEOUT = (8, 75)
MAX_PAGE_BYTES = 1_500_000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 MentorProfileBot/1.0"
)


class AIError(Exception):
    def __init__(self, message, code="ai_error", status=502):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message}}


def _base_url(config):
    base = (config.get("api_base") or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")].rstrip("/")
    return base


def is_local_base(base):
    """本机/模拟器 OpenAI 兼容服务通常不校验 API Key。

    覆盖 Ollama、vLLM、llama.cpp 常见地址：
    - 本机回环：localhost、127.0.0.0/8、::1、0.0.0.0
    - Android 模拟器宿主机：10.0.2.2
    - mDNS 局域网主机：*.local
    """
    try:
        parsed = urlparse(str(base or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    if host in {"localhost", "0.0.0.0", "10.0.2.2"} or host.endswith(".local"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _headers(config):
    key = (config.get("api_key") or "").strip()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _short_error(response):
    try:
        payload = response.json()
        message = payload.get("error", {}).get("message") or payload.get("message") or ""
    except ValueError:
        message = response.text[:240]
    return (message or f"HTTP {response.status_code}")[:320]


def chat_completion(config, messages, temperature=0.2, max_tokens=900, timeout=TIMEOUT):
    """调用 `/chat/completions`，返回纯文本内容。"""
    base = _base_url(config)
    if not config.get("api_key") and not is_local_base(base):
        raise AIError("尚未配置 AI API Key，请先在设置中填写。", code="ai_not_configured", status=400)
    if not config.get("model"):
        raise AIError("尚未配置模型名称，请先在设置中填写。", code="ai_not_configured", status=400)
    if not base:
        raise AIError("尚未配置 API Base URL。", code="ai_not_configured", status=400)

    try:
        response = requests.post(
            f"{base}/chat/completions",
            headers=_headers(config),
            json={
                "model": config["model"],
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise AIError("AI 接口请求超时，请检查网络或稍后重试。", code="ai_timeout", status=504) from exc
    except requests.RequestException as exc:
        raise AIError(f"AI 接口连接失败：{exc}", code="ai_network", status=502) from exc

    if response.status_code in (401, 403):
        raise AIError("API Key 无效或没有该模型的权限。", code="ai_auth", status=401)
    if response.status_code == 429:
        raise AIError("AI 接口触发限流，请稍后重试。", code="ai_rate_limit", status=429)
    if response.status_code >= 400:
        raise AIError(f"AI 接口返回错误：{_short_error(response)}", code="ai_http", status=502)

    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIError("AI 接口返回了无法解析的响应。", code="ai_bad_response") from exc
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "").strip()


def chat_json(config, system_prompt, user_prompt, temperature=0.1, max_tokens=1200):
    """要求模型返回 JSON，并容忍 ```json 代码块/前后说明文字。"""
    content = chat_completion(
        config,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return parse_json_object(content)


def parse_json_object(text):
    if not text:
        raise AIError("模型没有返回内容。", code="ai_empty")
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise AIError("模型返回的不是 JSON 对象。", code="ai_bad_json") from None
        try:
            data = json.loads(cleaned[start:end + 1])
        except ValueError as exc:
            raise AIError("模型返回的 JSON 无法解析。", code="ai_bad_json") from exc
    if not isinstance(data, dict):
        raise AIError("模型返回的 JSON 不是对象。", code="ai_bad_json")
    return data


def _host_is_public(host):
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # DNS 解析失败时交给 requests 处理，但明确拦截 localhost 等字面量
        return host.lower() not in {"localhost", "127.0.0.1", "::1"}
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def is_safe_public_url(url):
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    return _host_is_public(parsed.hostname)


def fetch_page_text(url, max_chars=5000):
    """只抓公开 http(s) 页面，限制大小并转纯文本；失败返回空字符串。"""
    if not is_safe_public_url(url):
        return ""
    try:
        with requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"},
            timeout=TIMEOUT,
            stream=True,
            allow_redirects=True,
        ) as response:
            if response.status_code >= 400:
                return ""
            if not is_safe_public_url(response.url):
                return ""
            content_type = response.headers.get("Content-Type", "").lower()
            if not any(kind in content_type for kind in ("text", "html", "xml")):
                return ""
            chunks, total = [], 0
            for chunk in response.iter_content(64_000):
                total += len(chunk)
                if total > MAX_PAGE_BYTES:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
    except requests.RequestException:
        return ""
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return text[:max_chars]


def _clean_web_results(items, max_results):
    cleaned = []
    for item in items[:max_results]:
        url = (item.get("url") or item.get("link") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        content = item.get("raw_content") or item.get("content") or item.get("snippet") or ""
        content = " ".join(BeautifulSoup(str(content), "lxml").get_text(" ", strip=True).split())
        cleaned.append({
            "title": (item.get("title") or "")[:200],
            "url": url,
            "content": content[:4000],
            "score": item.get("score"),
        })
    return cleaned


def _coerce_int(value, default, minimum, maximum):
    """配置可能被手工改坏；非整数时回退默认值，避免接口 500。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def web_search(config, query):
    """按配置调用 Tavily 或 Serper；返回统一的结果列表。"""
    web = config.get("web_search") or {}
    if not isinstance(web, dict):
        return []
    provider = str(web.get("provider") or "none").strip().lower()
    if not web.get("enabled") or provider == "none":
        return []
    key = str(web.get("api_key") or "").strip()
    if not key:
        raise AIError("尚未配置联网搜索 API Key。", code="search_not_configured", status=400)
    max_results = _coerce_int(web.get("max_results"), 5, 1, 10)
    query = (query or "").strip()
    if not query:
        return []

    if provider == "tavily":
        try:
            response = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": max_results,
                    "include_answer": False,
                    "include_raw_content": True,
                },
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise AIError(f"联网搜索连接失败：{exc}", code="search_network", status=502) from exc
        if response.status_code in (401, 403):
            raise AIError("联网搜索 API Key 无效。", code="search_auth", status=401)
        if response.status_code >= 400:
            raise AIError(f"联网搜索返回错误：{_short_error(response)}", code="search_http")
        try:
            data = response.json()
        except ValueError as exc:
            raise AIError("联网搜索返回了无法解析的响应。", code="search_bad_response") from exc
        return _clean_web_results(data.get("results") or [], max_results)

    if provider == "serper":
        try:
            response = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json={"q": query, "num": max_results},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise AIError(f"联网搜索连接失败：{exc}", code="search_network", status=502) from exc
        if response.status_code in (401, 403):
            raise AIError("联网搜索 API Key 无效。", code="search_auth", status=401)
        if response.status_code >= 400:
            raise AIError(f"联网搜索返回错误：{_short_error(response)}", code="search_http")
        try:
            data = response.json()
        except ValueError as exc:
            raise AIError("联网搜索返回了无法解析的响应。", code="search_bad_response") from exc
        return _clean_web_results(data.get("organic") or [], max_results)

    raise AIError(f"不支持的联网搜索提供方：{provider}", code="search_provider")


def test_connection(config):
    """最小化测试：chat 回复 OK；如果启用联网则附带一次搜索。"""
    content = chat_completion(
        config,
        [
            {"role": "system", "content": "你是连通性测试助手，只回复 OK。"},
            {"role": "user", "content": "ping"},
        ],
        temperature=0,
        max_tokens=12,
        timeout=(8, 30),
    )
    result = {"chat": True, "chat_reply": content[:40], "search": None}
    web = config.get("web_search") or {}
    if web.get("enabled") and (web.get("provider") or "none") != "none":
        results = web_search(config, "上海交通大学 计算机学院 教师")
        result["search"] = {"ok": True, "count": len(results)}
    return result

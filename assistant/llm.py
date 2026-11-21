# -*- coding: utf-8 -*-
"""OpenAI 兼容 API 客户端。

设置保存在本机用户目录，不写入项目仓库：
    %LOCALAPPDATA%/JiaWoDao/settings.json

API 只负责把本地检索结果组织成 2-4 句自然语言结论，
教师、论文、薪资等事实仍来自本地数据库与模板。
"""
import json
import os
import re
import time

import requests

from . import store

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-flash"
TIMEOUT = 40

# 模型可能加入评价性表述，检测到就直接退回模板回答
# 注意：不拦截“招生/薪资”等词，避免误伤“不代表招生意愿”这类合法免责声明
BAD_WORDS = (
    "机智", "严谨", "优秀", "出色", "杰出", "卓越", "突出", "权威", "顶尖",
    "著名", "资深", "和蔼", "亲切", "耐心", "负责", "友好", "厉害",
    "很强", "较强",
)


def _settings_path():
    return os.path.join(store.data_dir(), "settings.json")


def load_settings():
    data = {}
    path = _settings_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (ValueError, OSError):
            data = {}
    return {
        "enabled": bool(data.get("enabled")),
        "base_url": str(data.get("base_url") or DEFAULT_BASE_URL).strip(),
        "model": str(data.get("model") or DEFAULT_MODEL).strip(),
        "api_key": str(data.get("api_key") or "").strip(),
    }


def save_settings(payload):
    current = load_settings()
    if "enabled" in payload:
        current["enabled"] = bool(payload.get("enabled"))
    if "base_url" in payload:
        current["base_url"] = str(payload.get("base_url") or "").strip() or DEFAULT_BASE_URL
    if "model" in payload:
        current["model"] = str(payload.get("model") or "").strip() or DEFAULT_MODEL
    key = payload.get("api_key")
    # 空字符串表示“保持原 Key”，避免前端回填时误删
    if isinstance(key, str) and key.strip():
        current["api_key"] = key.strip()

    path = _settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return public_settings(current)


def public_settings(settings=None):
    s = settings or load_settings()
    key = s["api_key"]
    hint = ""
    if key:
        hint = (key[:5] + "…" + key[-4:]) if len(key) > 12 else "已保存"
    return {
        "enabled": s["enabled"],
        "base_url": s["base_url"],
        "model": s["model"],
        "has_key": bool(key),
        "key_hint": hint,
    }


def status():
    s = load_settings()
    base = {
        "name": s["model"],
        "preset": s["model"],
        "base_url": s["base_url"],
        "has_key": bool(s["api_key"]),
    }
    if not s["enabled"]:
        base.update({"mode": "rule", "reason": "未启用 API，使用本地规则检索"})
    elif not s["api_key"]:
        base.update({"mode": "rule", "reason": "已启用 API，但未配置 Key"})
    else:
        base.update({"mode": "api", "reason": ""})
    return base


def _endpoint(base):
    base = (base or DEFAULT_BASE_URL).strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def chat(messages, max_tokens=600, temperature=0.3, json_mode=False):
    """通用 OpenAI 兼容对话调用。"""
    s = load_settings()
    if not s["api_key"]:
        raise RuntimeError("missing api key")

    headers = {
        "Authorization": "Bearer " + s["api_key"],
        "Content-Type": "application/json",
    }
    payload = {
        "model": s["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    resp = requests.post(_endpoint(s["base_url"]), headers=headers,
                         json=payload, timeout=TIMEOUT)
    if resp.status_code == 400:
        # 部分兼容服务不支持 thinking / response_format，去掉后重试一次
        payload.pop("thinking", None)
        payload.pop("response_format", None)
        resp = requests.post(_endpoint(s["base_url"]), headers=headers,
                             json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("empty choices")
    return ((choices[0].get("message") or {}).get("content") or "").strip()


def _post(messages, max_tokens):
    return chat(messages, max_tokens=max_tokens)


def _clean(text):
    text = (text or "").strip()
    text = re.sub(r"(?s)<think(?:ing)?>.*?</think(?:ing)?>", "", text).strip()
    text = text.replace("```", "").strip()
    text = re.sub(r"\s*\n+\s*", " ", text).strip()
    return text


def enhance(question, draft, lang="zh", names=None):
    """基于本地检索草稿生成 2-4 句结论；失败时返回 None。"""
    s = load_settings()
    if not s["enabled"] or not s["api_key"]:
        return None

    zh = lang != "en"
    system = (
        "你是“交我导”的导师检索助手。只能依据给定的本地检索结果回答，"
        "不得编造教师、论文、薪资、招生名额或其他外部事实，"
        "不得评价导师人品、性格或指导质量。"
        "用 2-4 句话先给结论，再给关键依据；保留姓名和数字；"
        "证据不足时直接说明。不要输出列表、代码块或额外解释。"
    )
    user = "用户问题：%s\n\n本地检索结果：\n%s" % (question, (draft or "")[:1800])
    try:
        text = _clean(_post([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], 420))
    except Exception:
        return None

    if not text or not (10 <= len(text) <= 600):
        return None
    if "作为AI" in text or "作为 AI" in text or "As an AI" in text:
        return None
    if any(word in text for word in BAD_WORDS):
        return None
    if names and any(word in text for word in ("老师", "教授")):
        if not any(name in text for name in names):
            return None
    return text


def test_connection():
    s = load_settings()
    if not s["api_key"]:
        return {"ok": False, "message": "未配置 API Key", "latency_ms": 0}

    started = time.time()
    try:
        text = _clean(_post([
            {"role": "user", "content": "只回复：连接成功"}
        ], 16))
        return {
            "ok": True,
            "message": text[:60] or "连接成功",
            "latency_ms": int((time.time() - started) * 1000),
        }
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        body = (exc.response.text or "")[:160] if exc.response is not None else str(exc)
        return {
            "ok": False,
            "message": "HTTP %s %s" % (code, body),
            "latency_ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "message": str(exc)[:160],
            "latency_ms": int((time.time() - started) * 1000),
        }

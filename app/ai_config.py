# -*- coding: utf-8 -*-
"""AI 配置：保存 OpenAI 兼容接口与联网搜索的本地配置。

设计原则：
1. 密钥只存在服务器本地 `data/ai_config.json`，不写入前端 localStorage，
   也不出现在任何 GET 响应里；接口只返回“是否已配置”。
2. 支持环境变量覆盖，便于课程演示时用临时 key 启动：
       MENTOR_AI_BASE / MENTOR_AI_MODEL / MENTOR_AI_KEY
       MENTOR_SEARCH_PROVIDER / MENTOR_SEARCH_KEY
3. 保存时采用临时文件 + os.replace，避免写一半损坏配置；Windows 下尽量
   设置为仅当前用户可读。
"""
import contextlib
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime
from urllib.parse import urlparse

from .ai_client import is_local_base

CONFIG_RELATIVE_PATH = os.path.join("data", "ai_config.json")

DEFAULTS = {
    "enabled": False,
    "api_base": "https://api.openai.com/v1",
    "model": "",
    "api_key": "",
    "web_search": {
        "enabled": True,
        "provider": "tavily",
        "api_key": "",
        "max_results": 5,
    },
    "updated_at": None,
}

PROVIDERS = {"tavily", "serper", "none"}
_FALSE_TEXT = {"", "0", "false", "no", "off", "none", "null"}
_TRUE_TEXT = {"1", "true", "yes", "on"}


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _FALSE_TEXT:
        return False
    if text in _TRUE_TEXT:
        return True
    return bool(text)


def _as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _as_int(value, default, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def config_path(base_dir):
    return os.path.join(base_dir, CONFIG_RELATIVE_PATH)


def _env(name):
    return (os.environ.get(name) or "").strip()


def _apply_env(config):
    """环境变量优先，便于无 UI 的临时演示。"""
    if _env("MENTOR_AI_BASE"):
        config["api_base"] = _env("MENTOR_AI_BASE")
    if _env("MENTOR_AI_MODEL"):
        config["model"] = _env("MENTOR_AI_MODEL")
    if _env("MENTOR_AI_KEY"):
        config["api_key"] = _env("MENTOR_AI_KEY")
        config["enabled"] = True
    if _env("MENTOR_SEARCH_PROVIDER"):
        config["web_search"]["provider"] = _env("MENTOR_SEARCH_PROVIDER")
    if _env("MENTOR_SEARCH_KEY"):
        config["web_search"]["api_key"] = _env("MENTOR_SEARCH_KEY")
        config["web_search"]["enabled"] = True
    return config


def load_config(base_dir, path=None):
    """读取配置；文件缺失/损坏时回退默认值，不阻塞应用启动。"""
    config = deepcopy(DEFAULTS)
    path = path or config_path(base_dir)
    try:
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)
        if isinstance(saved, dict):
            if "enabled" in saved:
                config["enabled"] = _as_bool(saved.get("enabled"))
            for key in ("api_base", "model", "api_key", "updated_at"):
                if key in saved:
                    config[key] = _as_text(saved.get(key))
            if isinstance(saved.get("web_search"), dict):
                web = saved["web_search"]
                if "enabled" in web:
                    config["web_search"]["enabled"] = _as_bool(web.get("enabled"), True)
                if "provider" in web:
                    provider = _as_text(web.get("provider")).strip().lower()
                    if provider in PROVIDERS:
                        config["web_search"]["provider"] = provider
                if "api_key" in web:
                    config["web_search"]["api_key"] = _as_text(web.get("api_key"))
                if "max_results" in web:
                    config["web_search"]["max_results"] = _as_int(
                        web.get("max_results"), 5, 1, 10
                    )
    except (OSError, ValueError, TypeError):
        pass
    return _apply_env(config)


def _is_local_base(value):
    """统一走 ai_client 的本地端点判定，避免 app 与助手口径不一致。"""
    return is_local_base(value)


def public_config(base_dir, path=None):
    """给前端的安全视图：绝不返回密钥原文。"""
    config = load_config(base_dir, path)
    web = config.get("web_search") or {}
    if not isinstance(web, dict):
        web = {}
    has_key = bool(_as_text(config.get("api_key")).strip())
    local = _is_local_base(config.get("api_base"))
    provider = _as_text(web.get("provider") or "tavily").strip().lower()
    if provider not in PROVIDERS:
        provider = "tavily"
    return {
        "enabled": _as_bool(config.get("enabled")),
        "api_base": _as_text(config.get("api_base")),
        "model": _as_text(config.get("model")),
        "has_api_key": has_key,
        "local_endpoint": local,
        "configured": bool(
            (has_key or local)
            and _as_text(config.get("model"))
            and _as_text(config.get("api_base"))
        ),
        "web_search": {
            "enabled": _as_bool(web.get("enabled"), True),
            "provider": provider,
            "has_api_key": bool(_as_text(web.get("api_key"))),
            "max_results": _as_int(web.get("max_results"), 5, 1, 10),
        },
        "updated_at": config.get("updated_at"),
    }


def _clean_url(value):
    value = _as_text(value).strip().rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API Base URL 必须是 http(s) 地址")
    return value


def save_config(base_dir, payload, path=None):
    """保存配置；空 key 表示保留旧 key，`clear_api_key` 可显式清除。"""
    if not isinstance(payload, dict):
        raise ValueError("配置格式不正确")
    path = path or config_path(base_dir)
    current = load_config(base_dir, path)
    next_config = deepcopy(current)

    if "enabled" in payload:
        next_config["enabled"] = _as_bool(payload.get("enabled"))
    if "api_base" in payload:
        next_config["api_base"] = _clean_url(payload.get("api_base"))
    if "model" in payload:
        next_config["model"] = _as_text(payload.get("model")).strip()
    if len(next_config.get("model", "")) > 120:
        raise ValueError("模型名称过长")

    incoming_key = _as_text(payload.get("api_key")).strip()
    if _as_bool(payload.get("clear_api_key")):
        next_config["api_key"] = ""
    elif incoming_key:
        next_config["api_key"] = incoming_key

    web_payload = payload.get("web_search")
    if isinstance(web_payload, dict):
        web = next_config["web_search"]
        if "enabled" in web_payload:
            web["enabled"] = _as_bool(web_payload.get("enabled"), True)
        if "provider" in web_payload:
            provider = _as_text(web_payload.get("provider") or "tavily").strip().lower()
            if provider not in PROVIDERS:
                raise ValueError("联网搜索提供方只能是 tavily、serper 或 none")
            web["provider"] = provider
        if "max_results" in web_payload:
            try:
                max_results = int(web_payload["max_results"])
            except (TypeError, ValueError) as exc:
                raise ValueError("联网搜索条数必须是整数") from exc
            web["max_results"] = max(1, min(10, max_results))
        search_key = _as_text(web_payload.get("api_key")).strip()
        if _as_bool(web_payload.get("clear_api_key")):
            web["api_key"] = ""
        elif search_key:
            web["api_key"] = search_key

    if next_config["enabled"]:
        if not next_config["api_key"] and not _is_local_base(next_config["api_base"]):
            raise ValueError("启用 AI 前需要填写 API Key；本地 Ollama 可留空")
        if not next_config["model"]:
            raise ValueError("启用 AI 前需要填写模型名称")
        if not next_config["api_base"]:
            raise ValueError("启用 AI 前需要填写 API Base URL")

    next_config["updated_at"] = datetime.now().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="ai_config.", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(next_config, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        with contextlib.suppress(OSError):
            os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return public_config(base_dir, path)

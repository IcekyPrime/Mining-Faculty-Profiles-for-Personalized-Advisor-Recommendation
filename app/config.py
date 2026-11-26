# -*- coding: utf-8 -*-
"""应用层配置：路径与运行参数集中管理，全部可用环境变量覆盖。

参考 12-factor app 的做法：配置不写死在代码里，部署环境用环境变量调整。
    MENTOR_DB_PATH     数据库路径
    MENTOR_HOST        监听地址（默认 127.0.0.1）
    MENTOR_PORT        监听端口（默认 8765）
    MENTOR_LOG_LEVEL   日志级别（默认 INFO）
    MENTOR_AI_CONFIG   AI 模型/搜索配置文件（默认 data/ai_config.json）
"""
import os
import sys


def base_dir():
    """资源根目录，兼容源码运行与 PyInstaller 打包。"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE = base_dir()


def _env(name, default):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_path(name, default):
    return os.path.abspath(os.path.expanduser(_env(name, default)))


def _env_int(name, default, minimum=0):
    try:
        return max(minimum, int(_env(name, str(default))))
    except (TypeError, ValueError):
        return default


def default_config():
    return {
        "BASE_DIR": BASE,
        "DB_PATH": _env_path("MENTOR_DB_PATH", os.path.join(BASE, "data", "db", "mentor.db")),
        "AI_CONFIG_PATH": _env_path(
            "MENTOR_AI_CONFIG",
            os.path.join(BASE, "data", "ai_config.json"),
        ),
        "IMPORT_DIR": _env_path("MENTOR_IMPORT_DIR", os.path.join(BASE, "data", "imports")),
        "IMPORT_BACKUP_DIR": _env_path(
            "MENTOR_IMPORT_BACKUP_DIR", os.path.join(BASE, "data", "backup")
        ),
        "COLLAB_CSV": _env_path(
            "MENTOR_COLLAB_CSV", os.path.join(BASE, "data", "exports", "collab_edges.csv")
        ),
        "SIMILAR_JSON": _env_path(
            "MENTOR_SIMILAR_JSON", os.path.join(BASE, "data", "exports", "similar_pairs.json")
        ),
        "TOPICS_JSON": _env_path(
            "MENTOR_TOPICS_JSON", os.path.join(BASE, "data", "exports", "topics.json")
        ),
        "MINING_LEXICON": _env_path(
            "MENTOR_LEXICON_PATH", os.path.join(BASE, "data", "mining", "lexicon.json")
        ),
        "HOST": _env("MENTOR_HOST", "127.0.0.1"),
        "PORT": _env_int("MENTOR_PORT", 8765, 1),
        "LOG_LEVEL": _env("MENTOR_LOG_LEVEL", "INFO"),
        "APP_VERSION": _env("MENTOR_APP_VERSION", "2.7.0"),
        "MAX_UPLOAD_BYTES": _env_int(
            "MENTOR_MAX_UPLOAD_BYTES", 25 * 1024 * 1024, 1024
        ),
        "MAX_CONTENT_LENGTH": _env_int(
            "MENTOR_MAX_UPLOAD_BYTES", 25 * 1024 * 1024, 1024
        ),
        "PIPELINE_TIMEOUT": _env_int("MENTOR_PIPELINE_TIMEOUT", 300, 10),
        "STATIC_MAX_AGE": _env_int("MENTOR_STATIC_MAX_AGE", 0, 0),
        "JSON_SORT_KEYS": False,
        "GZIP_MIN_BYTES": _env_int("MENTOR_GZIP_MIN_BYTES", 800, 0),
    }

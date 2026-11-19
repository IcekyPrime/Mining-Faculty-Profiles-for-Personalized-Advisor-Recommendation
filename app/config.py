# -*- coding: utf-8 -*-
"""应用层配置：路径与运行参数集中管理，全部可用环境变量覆盖。

参考 12-factor app 的做法：配置不写死在代码里，部署环境用环境变量调整。
    MENTOR_DB_PATH     数据库路径
    MENTOR_HOST        监听地址（默认 127.0.0.1）
    MENTOR_PORT        监听端口（默认 8765）
    MENTOR_LOG_LEVEL   日志级别（默认 INFO）
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


def default_config():
    return {
        "BASE_DIR": BASE,
        "DB_PATH": _env("MENTOR_DB_PATH", os.path.join(BASE, "data", "db", "mentor.db")),
        "COLLAB_CSV": os.path.join(BASE, "data", "exports", "collab_edges.csv"),
        "SIMILAR_JSON": os.path.join(BASE, "data", "exports", "similar_pairs.json"),
        "HOST": _env("MENTOR_HOST", "127.0.0.1"),
        "PORT": int(_env("MENTOR_PORT", "8765")),
        "LOG_LEVEL": _env("MENTOR_LOG_LEVEL", "INFO"),
        "APP_VERSION": "1.1.0",
        # 静态资源交给浏览器缓存一天；接口响应由 after_request 统一加 no-cache
        "SEND_FILE_MAX_AGE_DEFAULT": 86400,
        "JSON_SORT_KEYS": False,
        "GZIP_MIN_BYTES": 800,
    }

# -*- coding: utf-8 -*-
"""Flask 应用工厂。

采用应用工厂（app factory）而不是模块级单例，好处是测试可以传入临时数据库、
不同部署可以传入不同配置，也方便以后挂多个蓝图。参考 Flask 官方
"Application Factories" 模式。
"""
import gzip
import logging
import os
import sys
import time
import uuid

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import ai_config
from .ai_api import bp as ai_api_bp
from .ai_store import ensure_schema as ensure_ai_schema
from .api import ApiError
from .api import bp as api_bp
from .config import default_config
from .db import close_db, db_stamp, init_db
from .import_api import bp as import_api_bp
from .import_store import ensure_schema as ensure_import_schema
from .insights import bp as insights_bp

GZIP_TYPES = {"application/json", "text/html", "text/css", "text/plain",
              "application/javascript", "text/javascript"}


def _setup_logging(app):
    level = getattr(logging, str(app.config["LOG_LEVEL"]).upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    app.logger.setLevel(level)


def _json_error(status, code, message):
    body = {"error": {"code": code, "message": message}}
    request_id = request.environ.get("mentor.request_id")
    if request_id:
        body["error"]["request_id"] = request_id
    response = jsonify(body)
    response.status_code = status
    return response


def _is_api():
    return request.path.startswith("/api/")


def _html_error(status, code, message):
    return render_template(
        "error.html",
        status=status,
        code=code,
        message=message,
        request_id=request.environ.get("mentor.request_id", ""),
        path=request.path,
    ), status


def create_app(overrides=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(default_config())
    if overrides:
        app.config.update(overrides)
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    _setup_logging(app)
    app.logger.info("数据库：%s", app.config["DB_PATH"])
    init_db(app.config["DB_PATH"])
    if not ensure_ai_schema(app.config["DB_PATH"]):
        app.logger.warning("AI 审计表初始化失败，联网补全功能可能不可用")
    if not ensure_import_schema(app.config["DB_PATH"]):
        app.logger.warning("导入审计表初始化失败，数据工坊可能不可用")

    app.register_blueprint(api_bp)
    app.register_blueprint(ai_api_bp)
    app.register_blueprint(insights_bp)
    app.register_blueprint(import_api_bp)
    app.teardown_appcontext(close_db)

    # v2.7 的对话助手作为独立模块挂载，和 /api/ai（单次查询+联网补全）、
    # /api/import（数据工坊）并存；不覆盖原有蓝图。
    root = os.path.dirname(app.root_path)
    if root not in sys.path:
        sys.path.insert(0, root)
    from assistant.api import register_chat

    def _load_chat_settings():
        cfg = ai_config.load_config(root, app.config["AI_CONFIG_PATH"])
        return {
            "enabled": bool(cfg.get("enabled")),
            "base_url": cfg.get("api_base") or "",
            "model": cfg.get("model") or "",
            "api_key": cfg.get("api_key") or "",
        }

    def _save_chat_settings(payload):
        bridge = {}
        for src, dst in (("enabled", "enabled"), ("base_url", "api_base"),
                         ("model", "model"), ("api_key", "api_key")):
            if src in payload:
                bridge[dst] = payload.get(src)
        if "clear_api_key" in payload:
            bridge["clear_api_key"] = bool(payload.get("clear_api_key"))
        ai_config.save_config(root, bridge, app.config["AI_CONFIG_PATH"])
        return _load_chat_settings()

    register_chat(
        app,
        db_path=app.config["DB_PATH"],
        settings_loader=_load_chat_settings,
        settings_saver=_save_chat_settings,
    )

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        body = error.to_dict()
        request_id = request.environ.get("mentor.request_id")
        if request_id:
            body["error"]["request_id"] = request_id
        return jsonify(body), error.status

    @app.errorhandler(404)
    def handle_not_found(error):
        if _is_api():
            return _json_error(404, "not_found", "接口不存在")
        return _html_error(404, "not_found", "页面不存在")

    @app.errorhandler(405)
    def handle_method(error):
        if _is_api():
            return _json_error(405, "method_not_allowed", "请求方法不允许")
        return _html_error(405, "method_not_allowed", "请求方法不允许")

    @app.errorhandler(413)
    def handle_too_large(error):
        if _is_api():
            return _json_error(413, "payload_too_large", "上传文件超过大小限制")
        return _html_error(413, "payload_too_large", "上传文件超过大小限制")

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return jsonify(error.to_dict()), error.status
        if isinstance(error, HTTPException):
            if _is_api():
                return _json_error(error.code or 500, "http_error", error.description)
            return _html_error(error.code or 500, "http_error", error.description)
        app.logger.exception(
            "未处理异常 [%s]：%s",
            request.environ.get("mentor.request_id", "-"),
            error,
        )
        if _is_api():
            return _json_error(500, "internal_error", "服务内部错误")
        return _html_error(500, "internal_error", "服务内部错误")

    @app.before_request
    def _start_timer():
        request.environ["mentor.started"] = time.perf_counter()
        request.environ["mentor.request_id"] = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]

    @app.after_request
    def _finalize(response):
        started = request.environ.get("mentor.started")
        if started is not None:
            response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        request_id = request.environ.get("mentor.request_id")
        if request_id:
            response.headers["X-Request-ID"] = request_id

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )

        if _is_api():
            response.headers["Cache-Control"] = "no-store"
        elif request.path.startswith("/static/"):
            # 默认 ETag 重新校验；部署时可提高 MENTOR_STATIC_MAX_AGE。
            max_age = app.config.get("STATIC_MAX_AGE", 0)
            if max_age > 0:
                response.headers.setdefault(
                    "Cache-Control", f"public, max-age={max_age}, immutable"
                )
            else:
                response.headers.setdefault(
                    "Cache-Control", "public, max-age=0, must-revalidate"
                )
        else:
            response.headers.setdefault("Cache-Control", "no-cache")

        accept = request.headers.get("Accept-Encoding", "")
        if ("gzip" in accept
                and response.status_code == 200
                and not response.direct_passthrough
                and response.mimetype in GZIP_TYPES
                and not response.headers.get("Content-Encoding")):
            payload = response.get_data()
            if len(payload) >= app.config["GZIP_MIN_BYTES"]:
                compressed = gzip.compress(payload, 6)
                response.set_data(compressed)
                response.headers["Content-Encoding"] = "gzip"
                response.headers["Content-Length"] = str(len(compressed))
                response.headers.add("Vary", "Accept-Encoding")
        return response

    @app.get("/")
    def index():
        stamp = db_stamp(app.config["DB_PATH"])
        return render_template(
            "index.html", db_updated_at=stamp[1] or 0, current_page="home"
        )

    @app.get("/favicon.ico")
    def favicon():
        # 复用 v1.9 的 app.ico；文件放在项目根目录，而不是 app/static 下。
        root = os.path.dirname(app.root_path)
        icon = os.path.join(root, "app.ico")
        if os.path.exists(icon):
            return send_from_directory(root, "app.ico", mimetype="image/x-icon")
        return ("", 204)

    @app.get("/workspace")
    @app.get("/import")
    def workspace():
        """独立的数据工坊页面，不改动原首页三功能区。"""
        return render_template("workspace.html", current_page="workspace")

    @app.get("/mobile/")
    def mobile_index():
        """桌面端也能预览 v1.9 的离线 WebView 移动端页面。"""
        www = os.path.join(os.path.dirname(app.root_path), "mobile", "android", "assets", "www")
        return send_from_directory(www, "index.html")

    @app.get("/mobile/<path:filename>")
    def mobile_asset(filename):
        www = os.path.join(os.path.dirname(app.root_path), "mobile", "android", "assets", "www")
        return send_from_directory(www, filename)

    app.config["STARTED_AT"] = time.time()
    app.logger.info("应用就绪：http://%s:%s", app.config["HOST"], app.config["PORT"])
    return app

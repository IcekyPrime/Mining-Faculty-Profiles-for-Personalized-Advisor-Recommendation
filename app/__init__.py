# -*- coding: utf-8 -*-
"""Flask 应用工厂。

采用应用工厂（app factory）而不是模块级单例，好处是测试可以传入临时数据库、
不同部署可以传入不同配置，也方便以后挂多个蓝图。参考 Flask 官方
"Application Factories" 模式。
"""
import gzip
import logging
import time

from flask import Flask, jsonify, render_template, request

from .api import ApiError
from .api import bp as api_bp
from .config import default_config
from .db import close_db, db_stamp, init_db
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
    response = jsonify({"error": {"code": code, "message": message}})
    response.status_code = status
    return response


def _is_api():
    return request.path.startswith("/api/")


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

    app.register_blueprint(api_bp)
    app.register_blueprint(insights_bp)
    app.teardown_appcontext(close_db)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify(error.to_dict()), error.status

    @app.errorhandler(404)
    def handle_not_found(error):
        if _is_api():
            return _json_error(404, "not_found", "接口不存在")
        return error

    @app.errorhandler(405)
    def handle_method(error):
        if _is_api():
            return _json_error(405, "method_not_allowed", "请求方法不允许")
        return error

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return jsonify(error.to_dict()), error.status
        app.logger.exception("未处理异常：%s", error)
        if _is_api():
            return _json_error(500, "internal_error", "服务内部错误")
        return _json_error(500, "internal_error", "服务内部错误")

    @app.before_request
    def _start_timer():
        request.environ["mentor.started"] = time.perf_counter()

    @app.after_request
    def _finalize(response):
        started = request.environ.get("mentor.started")
        if started is not None:
            response.headers["X-Response-Time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"

        if _is_api():
            response.headers["Cache-Control"] = "no-store"
        elif request.path.startswith("/static/"):
            # 静态资源交给 ETag 重新校验，避免改完前端后浏览器一天都读旧文件
            response.headers.setdefault("Cache-Control", "public, max-age=0, must-revalidate")
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
        return render_template("index.html", db_updated_at=stamp[1] or 0)

    @app.get("/favicon.ico")
    def favicon():
        return ("", 204)

    app.config["STARTED_AT"] = time.time()
    app.logger.info("应用就绪：http://%s:%s", app.config["HOST"], app.config["PORT"])
    return app

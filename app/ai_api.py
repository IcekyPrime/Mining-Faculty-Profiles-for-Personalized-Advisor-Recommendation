# -*- coding: utf-8 -*-
"""AI 相关接口：配置、连通性测试、自然语言检索、联网补全与处理任务。"""
from flask import Blueprint, current_app, jsonify, request

from .ai_client import AIError, test_connection
from .ai_config import load_config, public_config, save_config
from .ai_enrich import apply_enrichment, job_public, preview_enrichment
from .ai_search import ai_search
from .ai_store import list_jobs
from .api import ApiError

bp = Blueprint("ai_api", __name__, url_prefix="/api/ai")


def _base_dir():
    return current_app.config["BASE_DIR"]


def _db_path():
    return current_app.config["DB_PATH"]


def _config():
    return load_config(_base_dir(), current_app.config.get("AI_CONFIG_PATH"))


def _json_body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError("请求体必须是 JSON 对象。", code="invalid_json")
    return payload


def _teacher_id(value):
    try:
        teacher_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ApiError("teacher_id 必须是整数。", code="invalid_param") from exc
    if teacher_id <= 0:
        raise ApiError("teacher_id 必须大于 0。", code="invalid_param")
    return teacher_id


def _page(value, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(100, number))


def _ai_error(exc):
    raise ApiError(exc.message, status=exc.status, code=exc.code) from exc


@bp.get("/config")
def get_config():
    return jsonify(public_config(_base_dir(), current_app.config.get("AI_CONFIG_PATH")))


@bp.post("/config")
def post_config():
    payload = _json_body()
    try:
        result = save_config(
            _base_dir(), payload, current_app.config.get("AI_CONFIG_PATH")
        )
    except ValueError as exc:
        raise ApiError(str(exc), code="invalid_config") from exc
    return jsonify({"ok": True, "config": result})


@bp.post("/test")
def test():
    config = _config()
    try:
        result = test_connection(config)
    except AIError as exc:
        _ai_error(exc)
    return jsonify({"ok": True, "result": result})


@bp.post("/search")
def search():
    payload = _json_body()
    query = str(payload.get("q") or "").strip()
    college = str(payload.get("college") or "").strip()
    sort = str(payload.get("sort") or "").strip()
    page = _page(payload.get("page", 1), 1)
    size = _page(payload.get("size", 20), 20)
    try:
        result = ai_search(
            _db_path(), _config(), query,
            college=college, sort=sort, page=page, size=size,
        )
    except AIError as exc:
        _ai_error(exc)
    return jsonify(result)


@bp.post("/enrich/preview")
def enrich_preview():
    payload = _json_body()
    teacher_id = _teacher_id(payload.get("teacher_id"))
    extra = str(payload.get("extra") or "").strip()[:80]
    try:
        result = preview_enrichment(
            _base_dir(), _db_path(), _config(), teacher_id, extra=extra,
        )
    except AIError as exc:
        _ai_error(exc)
    return jsonify(result)


@bp.post("/enrich/apply")
def enrich_apply():
    payload = _json_body()
    token = str(payload.get("token") or "").strip()
    fields = payload.get("fields")
    if not token:
        raise ApiError("缺少补全任务 token。", code="invalid_param")
    if not isinstance(fields, list) or not fields:
        raise ApiError("fields 必须是非空数组。", code="invalid_param")
    try:
        result = apply_enrichment(_db_path(), token, [str(field) for field in fields])
    except AIError as exc:
        _ai_error(exc)
    return jsonify(result)


@bp.get("/jobs/<token>")
def get_job(token):
    try:
        result = job_public(_db_path(), token)
    except AIError as exc:
        _ai_error(exc)
    return jsonify(result)


@bp.get("/enrichments")
def enrichments():
    teacher_raw = request.args.get("teacher_id")
    teacher_id = _teacher_id(teacher_raw) if teacher_raw else None
    return jsonify({"items": list_jobs(_db_path(), teacher_id=teacher_id)})

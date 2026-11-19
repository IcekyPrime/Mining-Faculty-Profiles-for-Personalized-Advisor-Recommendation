# -*- coding: utf-8 -*-
"""HTTP 接口层：只做参数校验与响应组装，业务逻辑在 services。

接口一览：
    GET /api/health              健康检查（教师数、库文件、版本）
    GET /api/meta               前端启动时拉取的元信息（学院、排序项、计数）
    GET /api/stats              统计卡片数据（保留旧接口）
    GET /api/colleges           学院列表（保留旧接口）
    GET /api/search             检索 + 筛选 + 排序 + 分页
    GET /api/teacher/<id>       教师详情（课程、论文、相似导师、合作网络、评分构成）
"""
import os
import time
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from .db import db_stamp, file_stamp, get_db
from .services import (
    SORTS,
    build_detail,
    relevance,
    search_corpus,
    sort_records,
    stats_payload,
)

bp = Blueprint("api", __name__, url_prefix="/api")


class ApiError(Exception):
    """接口层显式错误：返回结构化 JSON，而不是 HTML 错误页。"""

    def __init__(self, message, status=400, code="bad_request"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message}}


def _stamp():
    return db_stamp(current_app.config["DB_PATH"])


def _int_arg(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ApiError(f"参数 {name} 必须是整数，收到 {raw!r}", code="invalid_param") from exc
    if value < minimum or value > maximum:
        raise ApiError(f"参数 {name} 超出范围 [{minimum}, {maximum}]", code="invalid_param")
    return value


def _bool_arg(name):
    return (request.args.get(name) or "").lower() in {"1", "true", "yes", "on"}


def _took_ms(started):
    return round((time.perf_counter() - started) * 1000, 1)


@bp.get("/health")
def health():
    started = time.perf_counter()
    path = current_app.config["DB_PATH"]
    conn = get_db()
    try:
        teachers = conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
        status = "ok"
    except Exception as exc:  # 库缺失或损坏
        current_app.logger.exception("健康检查失败")
        teachers = None
        status = "degraded"
        current_app.logger.warning("health: %s", exc)
    stamp = _stamp()
    return jsonify({
        "status": status,
        "teachers": teachers,
        "db": {
            "file": os.path.basename(path),
            "exists": os.path.exists(path),
            "size": stamp[2],
            "updated_at": datetime.fromtimestamp(stamp[1] / 1e9).isoformat(timespec="seconds")
            if stamp[1] else None,
        },
        "version": current_app.config["APP_VERSION"],
        "took_ms": _took_ms(started),
    })


@bp.get("/meta")
def meta():
    started = time.perf_counter()
    stamp = _stamp()
    stats = stats_payload(stamp)
    return jsonify({
        "version": current_app.config["APP_VERSION"],
        "sorts": SORTS,
        "colleges": stats["colleges"],
        "counts": {
            "teachers": stats["total_teachers"],
            "papers": stats["total_papers"],
            "courses": stats["total_courses"],
            "phd_advisors": stats["phd_advisors"],
        },
        "db_updated_at": datetime.fromtimestamp(stamp[1] / 1e9).isoformat(timespec="seconds")
        if stamp[1] else None,
        "took_ms": _took_ms(started),
    })


@bp.get("/stats")
def stats():
    started = time.perf_counter()
    payload = stats_payload(_stamp())
    payload["took_ms"] = _took_ms(started)
    return jsonify(payload)


@bp.get("/colleges")
def colleges():
    return jsonify(stats_payload(_stamp())["colleges"])


@bp.get("/search")
def search():
    started = time.perf_counter()
    query = (request.args.get("q") or "").strip()
    college = (request.args.get("college") or "").strip()
    sort = (request.args.get("sort") or "score").strip()
    page = _int_arg("page", 1, 1, 10000)
    size = _int_arg("size", 20, 1, 100)
    if sort not in SORTS:
        raise ApiError(f"未知排序方式 {sort!r}，可选：{', '.join(SORTS)}", code="invalid_sort")

    records = list(search_corpus(_stamp()))
    if college:
        records = [r for r in records if r["item"]["college"] == college]
    if _bool_arg("phd"):
        records = [r for r in records if r["item"]["is_phd_advisor"]]
    if _bool_arg("rated"):
        records = [r for r in records if (r["item"]["rating"] or {}).get("avg") is not None]

    if query:
        query_lower = query.lower()
        scored = []
        for record in records:
            score = relevance(record, query)
            if score > 0 or query_lower in record["directions_lower"]:
                scored.append((score, record))
        records = [record for _, record in scored]
        if sort == "relevance":
            records.sort(key=lambda r: -relevance(r, query))
        else:
            sort_records(records, sort)
    else:
        sort_records(records, "score" if sort == "relevance" else sort)

    total = len(records)
    pages = max(1, (total + size - 1) // size)
    start = (page - 1) * size
    items = [r["item"] for r in records[start:start + size]]
    if query:
        # 与 v1.0 一致：每条结果带 relevance 分值（新增字段，不影响旧调用方）
        items = [dict(item, relevance=relevance(r, query))
                 for item, r in zip(items, records[start:start + size], strict=False)]

    return jsonify({
        "query": query,
        "college": college,
        "sort": sort,
        "page": page,
        "size": size,
        "total": total,
        "pages": pages,
        "took_ms": _took_ms(started),
        "items": items,
        "results": items,  # 兼容旧命名
    })


@bp.get("/teacher/<int:tid>")
def teacher_detail(tid):
    started = time.perf_counter()
    item = build_detail(
        get_db(),
        tid,
        file_stamp(current_app.config["COLLAB_CSV"]),
        file_stamp(current_app.config["SIMILAR_JSON"]),
        _stamp(),
    )
    if item is None:
        raise ApiError(f"未找到 id={tid} 的教师", status=404, code="not_found")
    item["took_ms"] = _took_ms(started)
    return jsonify(item)

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
from .mining import combine_scores, load_lexicon
from .services import (
    SORTS,
    bm25_scores,
    build_detail,
    relevance,
    search_corpus,
    sort_records,
    stats_payload,
    topic_query_scores,
    topics_payload,
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


@bp.get("/mining")
def mining():
    """数据挖掘模型元信息：主题数、主题词、词典规模与文件状态。"""
    started = time.perf_counter()
    topic_stamp = file_stamp(current_app.config["TOPICS_JSON"])
    payload = topics_payload(topic_stamp)
    lexicon = load_lexicon(current_app.config["MINING_LEXICON"])
    topics = [
        {
            "id": item.get("id"),
            "label": item.get("label"),
            "terms": item.get("terms", [])[:8],
        }
        for item in payload.get("topics", [])
    ]
    return jsonify({
        "method": payload.get("method", "未生成"),
        "k": payload.get("k", 0),
        "document_count": payload.get("document_count", 0),
        "vocabulary": payload.get("vocabulary", 0),
        "topics": topics,
        "lexicon": {
            "version": lexicon.get("version", 1),
            "aliases": len(lexicon.get("aliases") or {}),
            "areas": len(lexicon.get("areas") or []),
            "path": os.path.relpath(current_app.config["MINING_LEXICON"], current_app.config["BASE_DIR"]),
        },
        "generated": bool(payload.get("topics")),
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
        scores = bm25_scores(_stamp(), query)
        topic_stamp = file_stamp(current_app.config["TOPICS_JSON"])
        topic_scores_map = topic_query_scores(topic_stamp, query)
        topic_hybrid_scores = {}
        if sort == "topic":
            # 主题相关度不是纯主题排序：在 BM25 召回集内融合主题分数，
            # 既保留词法证据，又体现 NMF 主题画像。纯主题分数仅作诊断。
            topic_hybrid = combine_scores(scores, topic_scores_map, topic_weight=0.4)
            topic_hybrid_scores = topic_hybrid
            if topic_hybrid:
                records = [r for r in records if topic_hybrid.get(r["item"]["id"], 0) > 0]
                records.sort(key=lambda r: (
                    -topic_hybrid.get(r["item"]["id"], 0),
                    -scores.get(r["item"]["id"], 0),
                    r["name"],
                ))
            else:
                records = [r for r in records if scores.get(r["item"]["id"], 0) > 0]
                records.sort(key=lambda r: (-scores.get(r["item"]["id"], 0), r["name"]))
        elif sort == "bm25":
            # BM25 自己负责召回：只保留词项真正命中的档案，按 BM25 降序。
            records = [r for r in records if scores.get(r["item"]["id"], 0) > 0]
            records.sort(key=lambda r: (-scores.get(r["item"]["id"], 0), r["name"]))
        else:
            scored = []
            for record in records:
                score = relevance(record, query)
                # relevance 只认完整子串；多词查询（“机器学习 数据挖掘”）需要
                # 用 BM25 的词项命中兜底召回，否则会被提前过滤掉。
                # 主题分只在 sort=topic 时参与召回，避免污染默认 score/relevance。
                if (
                    score > 0
                    or query_lower in record["directions_lower"]
                    or scores.get(record["item"]["id"], 0) > 0
                ):
                    scored.append((score, record))
            records = [record for _, record in scored]
            if sort == "relevance":
                records.sort(key=lambda r: -relevance(r, query))
            else:
                sort_records(records, sort)
    else:
        topic_scores_map = {}
        sort_records(records, "score" if sort in ("relevance", "bm25", "topic") else sort)

    total = len(records)
    pages = max(1, (total + size - 1) // size)
    start = (page - 1) * size
    page_records = records[start:start + size]
    items = [r["item"] for r in page_records]
    if query:
        # 新增字段，不改变旧调用方：relevance 为规则分，bm25 为信息检索基线分。
        items = [
            dict(
                item,
                relevance=relevance(r, query),
                bm25=scores.get(item["id"], 0),
                topic=topic_hybrid_scores.get(
                    item["id"], topic_scores_map.get(item["id"], 0)
                ),
                topic_similarity=topic_scores_map.get(item["id"], 0),
            )
            for item, r in zip(items, page_records, strict=False)
        ]

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

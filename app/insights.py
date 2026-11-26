# -*- coding: utf-8 -*-
"""数据洞察接口（v1.1 新增，不改动既有接口）。

给前端的「数据洞察」页提供一次性聚合数据：学院分布、字段覆盖率、评分分布、
K-means 研究方向簇、Louvain 合作社区、关联规则。数据都来自只读连接与
`data/exports/` 下处理层已导出的 JSON，不写库。
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime

from flask import Blueprint, current_app, jsonify

from .db import db_stamp, get_db

bp = Blueprint("insights", __name__, url_prefix="/api")

# 教师表里需要在洞察页展示覆盖率的字段
COVERAGE_FIELDS = (
    ("research_directions", "研究方向"),
    ("bio", "个人简介"),
    ("honors", "荣誉"),
    ("email", "邮箱"),
    ("institute", "研究所"),
    ("homepage_url", "教师主页"),
    ("h_index", "h 指数"),
    ("citation_count", "引用量"),
    ("paper_count", "论文数"),
)


def _json_files():
    root = current_app.config.get("BASE_DIR")
    if root is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data", "exports")


def _load_json(name, default):
    path = os.path.join(_json_files(), name)
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def _parse_keywords(value):
    try:
        items = json.loads(value or "[]")
    except (ValueError, TypeError):
        return []
    return [str(x) for x in items] if isinstance(items, list) else []


def _communities(db, limit=6):
    """社区摘要：同时提供新版 members 与移动端旧版 sample/keywords。"""
    rows = db.execute(
        """SELECT p.teacher_id, p.community, p.keywords, t.name
           FROM processing p JOIN teachers t ON t.id = p.teacher_id
           WHERE p.community IS NOT NULL"""
    ).fetchall()
    buckets = defaultdict(list)
    for row in rows:
        buckets[int(row["community"])].append(dict(row))
    out = []
    for cid, members in buckets.items():
        words = Counter()
        for member in members:
            words.update(_parse_keywords(member["keywords"]))
        names = [member["name"] for member in members]
        out.append({
            "id": cid,
            "size": len(members),
            "members": [str(member["teacher_id"]) for member in members],
            "sample": names[:6],
            "keywords": [w for w, _ in words.most_common(6)],
        })
    out.sort(key=lambda item: (-item["size"], item["id"]))
    return out[:limit]


def _legacy_top(db, limit=10):
    rows = db.execute(
        """SELECT t.id, t.name, t.college, p.score
           FROM processing p JOIN teachers t ON t.id = p.teacher_id
           WHERE p.score IS NOT NULL
           ORDER BY p.score DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _cluster_summaries(db, limit=8):
    rows = db.execute(
        """SELECT t.id, t.name, t.college, t.h_index, p.cluster, p.keywords
           FROM teachers t JOIN processing p ON p.teacher_id = t.id
           WHERE p.cluster IS NOT NULL"""
    ).fetchall()
    buckets = defaultdict(list)
    for row in rows:
        buckets[int(row["cluster"])].append(dict(row))

    summaries = []
    for cid, members in buckets.items():
        words = Counter()
        for member in members:
            words.update(_parse_keywords(member["keywords"]))
        reps = sorted(
            members,
            key=lambda m: (m["h_index"] is None, -(m["h_index"] or 0), m["name"]),
        )[:3]
        summaries.append({
            "id": cid,
            "size": len(members),
            "keywords": [w for w, _ in words.most_common(6)],
            "members": [
                {"id": m["id"], "name": m["name"], "college": m["college"]} for m in reps
            ],
        })
    summaries.sort(key=lambda item: -item["size"])
    return summaries[:limit]


def _score_histogram(db):
    def buckets(sql):
        counts = [0] * 10
        for row in db.execute(sql):
            value = row[0]
            if value is None:
                continue
            idx = min(int(float(value) // 10), 9)
            counts[idx] += 1
        return counts

    return {
        "original": buckets("SELECT score FROM processing"),
        "improved": buckets("SELECT score_v2 FROM processing"),
        "labels": [f"{i * 10}-{i * 10 + 10}" for i in range(10)],
    }


def _top_improved(db, limit=10):
    rows = db.execute(
        """SELECT t.id, t.name, t.college, t.title, p.score, p.score_v2
           FROM teachers t JOIN processing p ON p.teacher_id = t.id
           WHERE p.score_v2 IS NOT NULL
           ORDER BY p.score_v2 DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _coverage(db):
    total = db.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
    items = []
    for field, label in COVERAGE_FIELDS:
        have = db.execute(
            f"SELECT COUNT(*) FROM teachers WHERE {field} IS NOT NULL AND TRIM({field}) <> '' "
            f"AND TRIM({field}) <> '[]'"
        ).fetchone()[0]
        pct = round(have / total * 100, 1) if total else 0.0
        items.append({
            "field": field,
            "label": label,
            "count": have,
            "filled": have,
            "total": total,
            "ratio": round(have / total, 3) if total else 0.0,
            "pct": pct,
        })
    return items


def _number_stats(db, column):
    row = db.execute(
        f"SELECT COUNT({column}) AS n, MIN({column}) AS lo, MAX({column}) AS hi FROM processing"
    ).fetchone()
    return {"count": row["n"], "min": row["lo"], "max": row["hi"]}


def _topics(limit=8):
    payload = _load_json("topics.json", {})
    topics = payload.get("topics") or []
    return {
        "method": payload.get("method", "未生成"),
        "k": payload.get("k", 0),
        "document_count": payload.get("document_count", 0),
        "vocabulary": payload.get("vocabulary", 0),
        "items": [
            {
                "id": item.get("id"),
                "label": item.get("label"),
                "terms": [term.get("term") for term in (item.get("terms") or [])[:6]],
            }
            for item in topics[:limit]
        ],
    }


@bp.get("/insights")
def insights():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
    colleges = [
        {"name": r["college"], "count": r["n"]}
        for r in db.execute(
            "SELECT college, COUNT(*) AS n FROM teachers "
            "WHERE college IS NOT NULL AND college <> '' GROUP BY college ORDER BY n DESC"
        )
    ]
    communities = _communities(db, limit=6)
    community_sizes = [
        {"id": r["community"], "size": r["n"]}
        for r in db.execute(
            "SELECT community, COUNT(*) AS n FROM processing "
            "WHERE community IS NOT NULL GROUP BY community ORDER BY n DESC"
        )
    ]
    rules = _load_json("association_rules.json", [])
    histogram = _score_histogram(db)
    teach = db.execute(
        "SELECT COUNT(teaching_score) FROM processing WHERE teaching_score IS NOT NULL"
    ).fetchone()[0]
    stamp = db_stamp(current_app.config["DB_PATH"])
    updated_at = None
    if stamp[1]:
        updated_at = datetime.fromtimestamp(stamp[1] / 1e9).isoformat(timespec="seconds")
    return jsonify({
        # 兼容旧前端/移动端：total、teaching、coverage.filled/pct、
        # histogram、top 与社区 keywords/sample 全部保留。
        "total": total,
        "teaching": {
            "filled": teach,
            "total": total,
            "pct": round(teach / total * 100, 1) if total else 0.0,
        },
        "colleges": colleges,
        "coverage": _coverage(db),
        "histogram": {"bins": histogram["labels"], "counts": histogram["original"]},
        "top": _legacy_top(db),
        "scores": {
            "histogram": histogram,
            "top_improved": _top_improved(db),
            "improved": _number_stats(db, "score_v2"),
        },
        "clusters": _cluster_summaries(db, limit=8),
        "topics": _topics(),
        "community_count": len(community_sizes),
        "communities": communities,
        "rules": rules,
        "db": {"file": os.path.basename(current_app.config["DB_PATH"]),
               "updated_at": updated_at},
    })

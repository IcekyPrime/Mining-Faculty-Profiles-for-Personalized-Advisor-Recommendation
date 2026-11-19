# -*- coding: utf-8 -*-
"""查询与缓存层：把「组装教师档案」的逻辑从路由里拆出来。

缓存策略（参考 Flask 官方文档与常见 OSS 项目做法）：
- 用 `lru_cache` 缓存「整份检索语料」「统计数据」「百分位序列」；
- 缓存键带上数据库文件的 (mtime, size)，补录脚本重写库后缓存自动失效，
  不需要重启进程，也不会读到旧数据；
- 详情页里的相似导师、合作网络按文件时间戳缓存映射表，避免每次请求重读
  JSON/CSV。
"""
import contextlib
import csv
import json
from bisect import bisect_right
from collections import defaultdict
from functools import lru_cache

from .db import connect

SORTS = {
    "score": "综合评分",
    "score2": "改进评分（v2）",
    "academic": "学术能力",
    "teaching": "教学口碑",
    "relevance": "相关度",
}

RADAR_FIELDS = ("论文产出", "引用影响", "学术声誉", "荣誉头衔", "教学口碑")


def as_json(value, default):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def to_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


def build_summary(row, processing):
    """列表页用的精简教师对象。"""
    t = dict(row)
    keywords = as_json(processing["keywords"] if processing else None, [])
    ts = processing["teaching_score"] if processing else None
    tc = (processing["teaching_count"] or 0) if processing else 0
    return {
        "id": t["id"],
        "name": t["name"],
        "name_pinyin": t.get("name_pinyin") or "",
        "college": t.get("college") or "",
        "title": t.get("title") or "",
        "institute": t.get("institute") or "",
        "is_advisor": bool(t.get("is_advisor")),
        "is_phd_advisor": bool(t.get("is_phd_advisor")),
        "research_directions": t.get("research_directions") or "",
        "keywords": keywords,
        "h_index": t.get("h_index"),
        "citation_count": t.get("citation_count"),
        "paper_count": t.get("paper_count"),
        "honors": as_json(t.get("honors"), []),
        "rating": {"avg": to_float(ts), "count": tc},
        "score": processing["score"] if processing else None,
        "score_v2": (processing.get("score_v2") if processing else None),
        "score_coverage": processing["score_coverage"] if processing else None,
    }


def _processing_rows(conn):
    try:
        return {r["teacher_id"]: dict(r) for r in conn.execute("SELECT * FROM processing")}
    except Exception:  # noqa: BLE001 —— 库可能还没有 processing 表，退化为「无评分」
        return {}


@lru_cache(maxsize=8)
def search_corpus(stamp):
    """整份检索语料；stamp = (path, mtime, size)。"""
    path = stamp[0]
    conn = connect(path)
    try:
        rows = conn.execute("SELECT * FROM teachers ORDER BY name").fetchall()
        procs = _processing_rows(conn)
    finally:
        conn.close()
    records = []
    for row in rows:
        item = build_summary(row, procs.get(row["id"]))
        name = item["name"] or ""
        records.append({
            "item": item,
            "name": name,
            "pinyin_lower": (item["name_pinyin"] or "").lower(),
            "keywords_lower": [str(k).lower() for k in item["keywords"]],
            "directions_lower": (item["research_directions"] or "").lower(),
            "institute_lower": (item["institute"] or "").lower(),
            "title_lower": (item["title"] or "").lower(),
        })
    return tuple(records)


@lru_cache(maxsize=8)
def stats_payload(stamp):
    path = stamp[0]
    conn = connect(path)
    try:
        colleges = [
            {"name": r["college"], "count": r["n"]}
            for r in conn.execute(
                "SELECT college, COUNT(*) AS n FROM teachers "
                "WHERE college IS NOT NULL AND college <> '' "
                "GROUP BY college ORDER BY n DESC"
            )
        ]
        total_teachers = conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
        total_papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        total_courses = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        phd = conn.execute("SELECT COUNT(*) FROM teachers WHERE is_phd_advisor=1").fetchone()[0]
        h_index = conn.execute(
            "SELECT COUNT(h_index) AS n, MIN(h_index) AS lo, MAX(h_index) AS hi "
            "FROM teachers WHERE h_index IS NOT NULL"
        ).fetchone()

        hist = [0] * 10
        for r in conn.execute("SELECT h_index FROM teachers WHERE h_index IS NOT NULL"):
            try:
                value = int(r["h_index"])
            except (TypeError, ValueError):
                continue
            if value >= 0:
                hist[min(value // 10, 9)] += 1
    finally:
        conn.close()

    return {
        "total_teachers": total_teachers,
        "total_papers": total_papers,
        "total_courses": total_courses,
        "phd_advisors": phd,
        "colleges": colleges,
        "h_index": {"count": h_index["n"], "min": h_index["lo"], "max": h_index["hi"]},
        "h_histogram": hist,
    }


@lru_cache(maxsize=8)
def percentile_data(stamp):
    """雷达图与详情页需要的分位数序列，只查一次并排序。"""
    path = stamp[0]
    papers, cites, h_values, honors, ratings = [], [], [], [], []
    conn = connect(path)
    try:
        for r in conn.execute(
            "SELECT paper_count, citation_count, h_index, honors FROM teachers"
        ):
            papers.append(r["paper_count"] or 0)
            cites.append(r["citation_count"] or 0)
            if r["h_index"] is not None:
                with contextlib.suppress(TypeError, ValueError):
                    h_values.append(int(r["h_index"]))
            honors.append(len(as_json(r["honors"], [])))
        for r in conn.execute(
            "SELECT teaching_score FROM processing WHERE teaching_score IS NOT NULL"
        ):
            value = to_float(r["teaching_score"], 0) or 0
            if value > 0:
                ratings.append(value)
    finally:
        conn.close()
    return (
        tuple(sorted(papers)),
        tuple(sorted(cites)),
        tuple(sorted(h_values)),
        tuple(sorted(honors)),
        tuple(sorted(ratings)),
    )


def percentile_rank(sequence, value):
    """全库百分位；值为空表示「没查到」，返回 None 而不是 0。"""
    if not sequence or value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return 0.0
    return round(bisect_right(sequence, value) / len(sequence) * 100, 1)


@lru_cache(maxsize=8)
def similar_map(stamp):
    path = stamp[0]
    try:
        with open(path, encoding="utf-8") as fh:
            pairs = json.load(fh)
    except (OSError, ValueError):
        pairs = []
    mapping = defaultdict(set)
    for item in pairs:
        try:
            a, b = int(item[0]), int(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        mapping[a].add(b)
        mapping[b].add(a)
    return {key: tuple(sorted(value)) for key, value in mapping.items()}


@lru_cache(maxsize=8)
def collab_map(stamp):
    path = stamp[0]
    mapping = defaultdict(lambda: defaultdict(int))
    try:
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    src, dst, weight = int(row["src"]), int(row["dst"]), int(row["weight"])
                except (KeyError, TypeError, ValueError):
                    continue
                mapping[src][dst] += weight
                mapping[dst][src] += weight
    except OSError:
        pass
    return {key: dict(value) for key, value in mapping.items()}


def teacher_briefs(conn, ids):
    ids = [int(i) for i in ids]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, name, college, title FROM teachers WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def relevance(record, query):
    """多级匹配打分：姓名 > 拼音 > 关键词 > 研究方向 > 研究所 > 职称。"""
    q = query
    q_lower = query.lower()
    if record["name"] == q:
        return 100
    if q in record["name"]:
        return 85
    if q_lower and q_lower in record["pinyin_lower"]:
        return 75
    if any(q_lower in keyword for keyword in record["keywords_lower"]):
        return 60
    if q_lower in record["directions_lower"]:
        return 50
    if q_lower in record["institute_lower"]:
        return 30
    if q_lower in record["title_lower"]:
        return 20
    return 0


def sort_records(records, sort):
    if sort == "academic":
        records.sort(key=lambda r: (
            r["item"]["h_index"] is None,
            -(r["item"]["h_index"] or 0),
            -(r["item"]["citation_count"] or 0),
            r["name"],
        ))
    elif sort == "teaching":
        records.sort(key=lambda r: (
            (r["item"]["rating"] or {}).get("avg") is None,
            -((r["item"]["rating"] or {}).get("avg") or 0),
            -((r["item"]["rating"] or {}).get("count") or 0),
            r["name"],
        ))
    elif sort == "relevance":
        records.sort(key=lambda r: r["name"])
    elif sort == "score2":
        records.sort(key=lambda r: (
            r["item"]["score_v2"] is None,
            -(r["item"]["score_v2"] or 0),
            -(r["item"]["score"] or 0),
            r["name"],
        ))
    else:
        records.sort(key=lambda r: (
            r["item"]["score"] is None,
            -(r["item"]["score"] or 0),
            -(r["item"]["h_index"] or 0),
            r["name"],
        ))


def build_detail(conn, tid, collab_stamp, similar_stamp, db_stamp):
    row = conn.execute("SELECT * FROM teachers WHERE id = ?", (tid,)).fetchone()
    if row is None:
        return None
    processing_row = conn.execute(
        "SELECT * FROM processing WHERE teacher_id = ?", (tid,)
    ).fetchone()
    processing = dict(processing_row) if processing_row else None
    item = build_summary(row, processing)
    item["email"] = row["email"] or ""
    item["homepage_url"] = row["homepage_url"] or ""
    item["personal_homepage"] = row["personal_homepage"] or ""

    courses = [
        {
            "name": r["course_name"],
            "code": r["course_code"],
            "rating": to_float(r["rating_avg"]) if (r["rating_count"] or 0) > 0 else None,
            "rating_avg": to_float(r["rating_avg"]),
            "count": r["rating_count"],
            "semester": r["last_semester"],
        }
        for r in conn.execute(
            "SELECT * FROM courses WHERE teacher_id = ? "
            "ORDER BY (rating_count>0) DESC, rating_score DESC, rating_count DESC",
            (tid,),
        )
    ]

    paper_cols = {r["name"] for r in conn.execute("PRAGMA table_info(papers)")}
    authors_expr = "authors" if "authors" in paper_cols else "NULL AS authors"
    papers = [
        {
            "title": r["title"],
            "venue": r["venue"],
            "year": r["year"],
            "citations": r["citation_count"],
            "authors": r["authors"],
        }
        for r in conn.execute(
            f"SELECT title, venue, year, citation_count, {authors_expr} "
            "FROM papers WHERE teacher_id = ? "
            "ORDER BY COALESCE(citation_count, 0) DESC, COALESCE(year, 0) DESC LIMIT 20",
            (tid,),
        )
    ]
    item["courses"] = courses
    item["papers"] = papers
    item["paper_total"] = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE teacher_id = ?", (tid,)
    ).fetchone()[0]

    if processing:
        item["cluster"] = processing.get("cluster")
        item["community"] = processing.get("community")
        item["pagerank"] = to_float(processing.get("pagerank"))
        item["hits_authority"] = to_float(processing.get("hits_authority"))
        item["hits_hub"] = to_float(processing.get("hits_hub"))
        item["score_parts"] = as_json(processing.get("score_parts"), {})
        item["teaching_score"] = to_float(processing.get("teaching_score"))
        item["teaching_count"] = processing.get("teaching_count")

    similar_ids = similar_map(similar_stamp).get(tid, ())
    briefs = teacher_briefs(conn, similar_ids)
    item["similar"] = sorted(briefs.values(), key=lambda r: r["name"])

    neighbors = collab_map(collab_stamp).get(tid, {})
    top = sorted(neighbors.items(), key=lambda kv: (-kv[1], kv[0]))[:30]
    ego_briefs = teacher_briefs(conn, [oid for oid, _ in top])
    item["collaborators"] = [
        {
            "id": oid,
            "name": ego_briefs[oid]["name"],
            "college": ego_briefs[oid]["college"],
            "weight": weight,
        }
        for oid, weight in top if oid in ego_briefs
    ]

    papers_all, cites_all, h_all, honors_all, ratings_all = percentile_data(db_stamp)
    radar_values = {
        "论文产出": (papers_all, item.get("paper_count")),
        "引用影响": (cites_all, item.get("citation_count")),
        "学术声誉": (h_all, item.get("h_index")),
        "荣誉头衔": (honors_all, len(item.get("honors", []))),
        "教学口碑": (ratings_all, (item.get("rating") or {}).get("avg")),
    }
    item["radar"] = {}
    item["radar_known"] = {}
    for name, (sequence, value) in radar_values.items():
        rank = percentile_rank(sequence, value)
        item["radar"][name] = rank if rank is not None else 0
        item["radar_known"][name] = rank is not None
    return item

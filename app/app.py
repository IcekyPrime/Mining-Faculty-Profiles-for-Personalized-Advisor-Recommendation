# -*- coding: utf-8 -*-
"""导师选择系统 · 应用层后端

基于 Flask 提供检索、详情、排序与可视化数据接口。
数据来源为处理层写入的 SQLite 数据库与导出文件。
"""
import os
import sys
import json
import csv
import sqlite3

from flask import Flask, render_template, jsonify, request, send_from_directory


def base_dir():
    """返回资源根目录，兼容源码运行与 PyInstaller 打包。"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE = base_dir()
# 对话模块位于项目根目录的 assistant/，同时兼容源码运行与打包运行
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
DB_PATH = os.path.join(BASE, "data", "db", "mentor.db")
COLLAB_CSV = os.path.join(BASE, "data", "exports", "collab_edges.csv")
SIMILAR_JSON = os.path.join(BASE, "data", "exports", "similar_pairs.json")

app = Flask(
    __name__,
    template_folder=os.path.join(BASE, "app", "templates"),
    static_folder=os.path.join(BASE, "app", "static"),
)

# 排序字段（数值越大越靠前，缺失值排最后）
SORTS = {
    "score": ("综合评分", "score"),
    "academic": ("学术能力", "h_index"),
    "teaching": ("教学口碑", "rating"),
    "relevance": ("相关度", "relevance"),
}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _json(value, default):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _to_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------- 缓存
_collab_edges = None
_similar_pairs = None


def load_collab_edges():
    global _collab_edges
    if _collab_edges is not None:
        return _collab_edges
    edges = []
    if os.path.exists(COLLAB_CSV):
        with open(COLLAB_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                edges.append({
                    "src": int(row["src"]),
                    "dst": int(row["dst"]),
                    "weight": int(row["weight"]),
                })
    _collab_edges = edges
    return edges


def load_similar_pairs():
    global _similar_pairs
    if _similar_pairs is not None:
        return _similar_pairs
    pairs = []
    if os.path.exists(SIMILAR_JSON):
        with open(SIMILAR_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                pairs.append({
                    "a": int(item[0]),
                    "b": int(item[1]),
                    "sim": _to_float(item[2], 0.0),
                })
    _similar_pairs = pairs
    return pairs


# ---------------------------------------------------------------- 数据组装
def build_summary(row, processing):
    """构造列表页所需的精简教师对象。"""
    t = dict(row)
    keywords = _json(processing["keywords"] if processing else None, [])
    directions = t.get("research_directions") or ""
    ts = _to_float(processing.get("teaching_score")) if processing else None
    tc = (processing.get("teaching_count") or 0) if processing else 0
    imputed = bool(processing.get("teaching_imputed")) if processing else False
    # 展示口径：无课程评分的教师教学评分仍为 0；均值仅用于评分计算
    rating = {"avg": 0.0 if imputed else ts, "count": tc}
    return {
        "id": t["id"],
        "name": t["name"],
        "name_pinyin": t.get("name_pinyin") or "",
        "college": t.get("college") or "",
        "title": t.get("title") or "",
        "institute": t.get("institute") or "",
        "is_advisor": bool(t.get("is_advisor")),
        "is_phd_advisor": bool(t.get("is_phd_advisor")),
        "research_directions": directions,
        "keywords": keywords,
        "h_index": t.get("h_index"),
        "citation_count": t.get("citation_count"),
        "paper_count": t.get("paper_count"),
        "honors": _json(t.get("honors"), []),
        "rating": rating,
        "teaching_used": ts,
        "teaching_imputed": imputed,
        "score": processing["score"] if processing else None,
    }


# ---------------------------------------------------------------- 路由
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stats")
def api_stats():
    conn = get_db()
    try:
        colleges = [
            {"name": r["college"], "count": r["n"]}
            for r in conn.execute(
                "SELECT college, COUNT(*) AS n FROM teachers GROUP BY college ORDER BY n DESC"
            )
        ]
        total_teachers = conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
        total_papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        total_courses = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        h_index = conn.execute(
            "SELECT COUNT(h_index) AS n, MIN(h_index) AS lo, MAX(h_index) AS hi "
            "FROM teachers WHERE h_index IS NOT NULL"
        ).fetchone()

        # h 指数分布（10 段直方图）
        hist = [0] * 10
        for r in conn.execute("SELECT h_index FROM teachers WHERE h_index IS NOT NULL"):
            v = int(r["h_index"])
            bucket = min(v // 10, 9)
            hist[bucket] += 1

        return jsonify({
            "total_teachers": total_teachers,
            "total_papers": total_papers,
            "total_courses": total_courses,
            "colleges": colleges,
            "h_index": {"count": h_index["n"], "min": h_index["lo"], "max": h_index["hi"]},
            "h_histogram": hist,
        })
    finally:
        conn.close()


@app.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    college = (request.args.get("college") or "").strip()
    sort = request.args.get("sort", "score")
    if sort not in SORTS:
        sort = "score"
    page = max(int(request.args.get("page", 1)), 1)
    size = min(max(int(request.args.get("size", 20)), 1), 100)

    q_lower = q.lower()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM teachers ORDER BY name"
        ).fetchall()
        procs = {
            r["teacher_id"]: dict(r)
            for r in conn.execute("SELECT * FROM processing")
        }
    finally:
        conn.close()

    results = []
    for row in rows:
        p = procs.get(row["id"])
        item = build_summary(row, p)
        item["relevance"] = 0
        results.append(item)

    # 计算相关度
    if q:
        for item in results:
            rel = 0
            name = item["name"]
            if name == q:
                rel = 100
            elif q in name:
                rel = 85
            elif q_lower in (item["name_pinyin"] or "").lower():
                rel = 75
            elif any(q in kw for kw in item["keywords"]):
                rel = 60
            elif q in (item["research_directions"] or ""):
                rel = 50
            elif q in (item["institute"] or ""):
                rel = 30
            elif q in (item["title"] or ""):
                rel = 20
            item["relevance"] = rel
        # 相关度为 0 的条目在关键词检索时过滤掉
        results = [r for r in results if r["relevance"] > 0]

    if college:
        results = [r for r in results if r["college"] == college]

    # 排序
    if sort == "relevance":
        results.sort(key=lambda r: (-r["relevance"], r["name"]))
    elif sort == "academic":
        results.sort(key=lambda r: (
            r["h_index"] is None, -(r["h_index"] or 0), -(r["citation_count"] or 0)
        ))
    elif sort == "teaching":
        results.sort(key=lambda r: (
            (r["rating"] or {}).get("avg") is None,
            -((r["rating"] or {}).get("avg") or 0),
            -((r["rating"] or {}).get("count") or 0),
        ))
    else:  # score
        results.sort(key=lambda r: (
            r["score"] is None, -(r["score"] or 0), -(r["h_index"] or 0)
        ))

    total = len(results)
    start = (page - 1) * size
    page_items = results[start:start + size]
    return jsonify({
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
        "sort": sort,
        "items": page_items,
    })


# ---------------------------------------------------------------- 评分构成
# 与 processing/score.py 保持一致的口径
HONOR_W = {
    "院士": 5.0, "杰青": 4.0, "长江": 3.5, "万人计划": 3.5, "优青": 3.0,
    "国家级高层次人才": 3.0, "海外高层次": 3.0, "国家级青年人才": 2.5,
    "IEEE Fellow": 2.5, "Fellow": 2.0, "ACM Fellow": 2.5, "CCF Fellow": 2.0,
    "博导": 1.0, "国家级人才": 3.0, "青年长江": 3.0,
}
SCORE_W = [
    ("paper", 0.10),
    ("citation", 0.20),
    ("honor", 0.35),
    ("teaching", 0.25),
]


def _percentile(sorted_vals, q):
    """线性插值分位数，与 numpy.percentile 默认口径接近。"""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_vals[0])
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _norm_p5_95(vals, v):
    if not vals:
        return 0.0
    s = sorted(vals)
    lo, hi = _percentile(s, 0.05), _percentile(s, 0.95)
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


def _honor_score(honors, title):
    s = sum(HONOR_W.get(x, 0) for x in (honors or []))
    t = title or ""
    if "院士" in t:
        s += 5
    elif "教授" in t and "副" not in t:
        s += 1.0
    return s


def build_score_parts(conn, item):
    """返回四项分项：原始值、归一值、权重与贡献分，贡献之和即综合评分。"""
    papers, cites, honors, teach = [], [], [], []
    for r in conn.execute("SELECT paper_count, citation_count, honors, title FROM teachers"):
        papers.append(r["paper_count"] or 0)
        cites.append(r["citation_count"] or 0)
        honors.append(_honor_score(_json(r["honors"], []), r["title"]))
    for r in conn.execute(
        "SELECT t.id, p.teaching_score FROM teachers t "
        "LEFT JOIN processing p ON p.teacher_id = t.id"
    ):
        teach.append(_to_float(r["teaching_score"], 0) or 0)

    raw = {
        "paper": item.get("paper_count") or 0,
        "citation": item.get("citation_count") or 0,
        "honor": _honor_score(item.get("honors", []), item.get("title")),
        "teaching": item.get("teaching_used") or 0,
    }
    pools = {"paper": papers, "citation": cites, "honor": honors, "teaching": teach}
    has = {
        "paper": item.get("paper_count") is not None,
        "citation": item.get("citation_count") is not None,
        "honor": True,
        "teaching": item.get("teaching_used") is not None,
    }

    parts, total = [], 0.0
    for key, w in SCORE_W:
        n = _norm_p5_95(pools[key], raw[key]) if has[key] else 0.0
        exact = n * w * 100
        total += exact
        parts.append({
            "key": key, "weight": w, "raw": raw[key],
            "norm": round(n, 3), "contribution": round(exact, 1),
        })
    return {"parts": parts, "total": round(total, 1)}


@app.route("/api/teacher/<int:tid>")
def api_teacher(tid):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM teachers WHERE id = ?", (tid,)).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        p = conn.execute("SELECT * FROM processing WHERE teacher_id = ?", (tid,)).fetchone()
        processing = dict(p) if p else None

        item = build_summary(row, processing)

        # 详情页专用字段
        item["bio"] = row["bio"] or ""
        item["email"] = row["email"] or ""
        item["personal_homepage"] = row["personal_homepage"] or ""
        item["homepage_url"] = row["homepage_url"] or ""

        # 课程
        courses = [
            {
                "name": r["course_name"],
                "code": r["course_code"],
                "rating": _to_float(r["rating_avg"]) if (r["rating_count"] or 0) > 0 else None,
                "rating_avg": _to_float(r["rating_avg"]),
                "count": r["rating_count"],
                "semester": r["last_semester"],
            }
            for r in conn.execute(
                "SELECT * FROM courses WHERE teacher_id = ? "
                "ORDER BY (rating_count>0) DESC, rating_score DESC, rating_count DESC",
                (tid,),
            )
        ]

        # 论文（按引用量排序，最多返回 20 篇）
        papers = [
            {
                "title": r["title"],
                "venue": r["venue"],
                "year": r["year"],
                "citations": r["citation_count"],
                "authors": r["authors"],
            }
            for r in conn.execute(
                "SELECT * FROM papers WHERE teacher_id = ? "
                "ORDER BY COALESCE(citation_count, 0) DESC, COALESCE(year, 0) DESC LIMIT 20",
                (tid,),
            )
        ]

        item["courses"] = courses
        item["papers"] = papers
        item["paper_total"] = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE teacher_id = ?", (tid,)
        ).fetchone()[0]

        # 处理层字段
        if processing:
            item["cluster"] = processing.get("cluster")
            item["community"] = processing.get("community")
            item["pagerank"] = _to_float(processing.get("pagerank"))
            item["hits_authority"] = _to_float(processing.get("hits_authority"))
            item["hits_hub"] = _to_float(processing.get("hits_hub"))

        # 相似导师
        sim_ids = set()
        for pair in load_similar_pairs():
            if pair["a"] == tid:
                sim_ids.add(pair["b"])
            elif pair["b"] == tid:
                sim_ids.add(pair["a"])
        similar = []
        for sid in sim_ids:
            r = conn.execute("SELECT id, name, college, title FROM teachers WHERE id = ?", (sid,)).fetchone()
            if r:
                similar.append(dict(r))
        item["similar"] = similar

        # 合作网络（自我中心）
        neighbors = {}
        for edge in load_collab_edges():
            other = None
            if edge["src"] == tid:
                other = edge["dst"]
            elif edge["dst"] == tid:
                other = edge["src"]
            if other is not None:
                neighbors[other] = neighbors.get(other, 0) + edge["weight"]
        ego = []
        for oid, w in sorted(neighbors.items(), key=lambda x: -x[1])[:30]:
            r = conn.execute("SELECT id, name, college FROM teachers WHERE id = ?", (oid,)).fetchone()
            if r:
                ego.append({"id": oid, "name": r["name"], "college": r["college"], "weight": w})
        item["collaborators"] = ego

        # 雷达图维度：使用百分位排名，避免极端离群值使图形失真
        def percentile(seq, value):
            if not seq:
                return 0.0
            below = sum(1 for x in seq if x <= value)
            return round(below / len(seq) * 100, 1)

        papers_all, cites_all, h_all = [], [], []
        honors_all = []
        ratings_all = []
        for r in conn.execute("SELECT paper_count, citation_count, h_index, honors FROM teachers"):
            papers_all.append(r["paper_count"] or 0)
            cites_all.append(r["citation_count"] or 0)
            if r["h_index"] is not None:
                h_all.append(r["h_index"])
            honors_all.append(len(_json(r["honors"], [])))
        for r in conn.execute(
            "SELECT teaching_score FROM processing WHERE teaching_score IS NOT NULL"
        ):
            ratings_all.append(_to_float(r["teaching_score"], 0) or 0)

        rating_val = (item.get("rating") or {}).get("avg") or 0
        item["radar"] = {
            "论文产出": percentile(papers_all, item.get("paper_count") or 0),
            "引用影响": percentile(cites_all, item.get("citation_count") or 0),
            "学术声誉": percentile(h_all, item.get("h_index") or 0),
            "荣誉头衔": percentile(honors_all, len(item.get("honors", []))),
            "教学口碑": percentile(ratings_all, rating_val),
        }

        item["score_parts"] = build_score_parts(conn, item)

        return jsonify(item)
    finally:
        conn.close()


@app.route("/api/colleges")
def api_colleges():
    conn = get_db()
    try:
        cols = [
            {"name": r["college"], "count": r["n"]}
            for r in conn.execute(
                "SELECT college, COUNT(*) AS n FROM teachers GROUP BY college ORDER BY n DESC"
            )
        ]
        return jsonify(cols)
    finally:
        conn.close()


@app.route("/api/insights")
def api_insights():
    """概况页数据：学院分布、字段覆盖率、评分分布、聚类、社区与关联规则。"""
    from collections import Counter

    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]

        colleges = [
            {"name": r["college"], "count": r["n"]}
            for r in conn.execute(
                "SELECT college, COUNT(*) AS n FROM teachers GROUP BY college ORDER BY n DESC"
            )
        ]

        coverage_fields = [
            "research_directions", "bio", "honors", "email",
            "institute", "homepage_url", "h_index", "citation_count", "paper_count",
        ]
        coverage = []
        for f in coverage_fields:
            n = conn.execute(
                f"SELECT COUNT(*) FROM teachers WHERE {f} IS NOT NULL AND {f}!='' AND {f}!='[]'"
            ).fetchone()[0]
            coverage.append({"field": f, "filled": n, "total": total,
                             "pct": round(n / total * 100, 1) if total else 0.0})

        bins = [0] * 10
        for r in conn.execute("SELECT score FROM processing WHERE score IS NOT NULL"):
            bins[min(int(r["score"] // 10), 9)] += 1

        top = [
            {"id": r["id"], "name": r["name"], "college": r["college"], "score": r["score"]}
            for r in conn.execute(
                "SELECT t.id, t.name, t.college, p.score FROM processing p "
                "JOIN teachers t ON t.id = p.teacher_id WHERE p.score IS NOT NULL "
                "ORDER BY p.score DESC LIMIT 10"
            )
        ]

        names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM teachers")}

        clusters = {}
        communities = {}
        for r in conn.execute(
            "SELECT teacher_id, cluster, community, keywords FROM processing"
        ):
            kws = _json(r["keywords"], [])
            if r["cluster"] is not None:
                c = clusters.setdefault(r["cluster"], {"members": [], "kw": Counter()})
                c["members"].append(r["teacher_id"])
                c["kw"].update(kws)
            if r["community"] is not None:
                c = communities.setdefault(r["community"], {"members": [], "kw": Counter()})
                c["members"].append(r["teacher_id"])
                c["kw"].update(kws)

        def pack(group, limit=6):
            out = []
            for gid, g in group.items():
                out.append({
                    "id": gid,
                    "size": len(g["members"]),
                    "keywords": [k for k, _ in g["kw"].most_common(limit)],
                    "sample": [names.get(t, "") for t in g["members"][:6]],
                })
            out.sort(key=lambda x: -x["size"])
            return out

        rules = []
        if os.path.exists(os.path.join(BASE, "data", "exports", "association_rules.json")):
            with open(os.path.join(BASE, "data", "exports", "association_rules.json"),
                      encoding="utf-8") as f:
                rules = json.load(f)[:12]

        teach = conn.execute(
            "SELECT COUNT(teaching_score) FROM processing WHERE teaching_score IS NOT NULL"
        ).fetchone()[0]

        return jsonify({
            "total": total,
            "teaching": {"filled": teach, "total": total,
                         "pct": round(teach / total * 100, 1) if total else 0.0},
            "colleges": colleges,
            "coverage": coverage,
            "histogram": {"bins": [f"{i * 10}-{i * 10 + 10}" for i in range(10)], "counts": bins},
            "top": top,
            "clusters": pack(clusters),
            "communities": pack(communities),
            "rules": rules,
        })
    finally:
        conn.close()


from assistant.api import register_chat

register_chat(app)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)

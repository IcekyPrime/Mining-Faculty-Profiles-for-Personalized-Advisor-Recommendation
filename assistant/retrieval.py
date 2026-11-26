# -*- coding: utf-8 -*-
"""本地教师库检索。

直接读取现有的 mentor.db，不修改其结构。
按研究方向、关键词、简介与已收录论文标题做加权匹配，
并给出可展示的匹配依据，供对话回答引用。
"""
import csv
import json
import os
import re
import sqlite3
import sys
import unicodedata

from . import nlu

BASE_DIR = (
    sys._MEIPASS if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DB_PATH = os.path.join(BASE_DIR, "data", "db", "mentor.db")

_cache = {
    "key": None,
    "teachers": [],
    "papers": {},
    "vocab": [],
}
_collab = None


def set_db_path(path):
    """让助手复用应用工厂当前数据库（测试时也能指向临时库）。"""
    global DB_PATH, _collab
    if path:
        DB_PATH = os.path.abspath(path)
    _cache.update({"key": None, "teachers": [], "papers": {}, "vocab": []})
    _collab = None


def _json_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def _to_int(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _to_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _load_teachers(conn):
    sql = """
        SELECT t.id, t.name, t.name_pinyin, t.college, t.title, t.email,
               t.research_directions, t.bio, t.institute, t.honors,
               t.h_index, t.citation_count, t.paper_count,
               t.homepage_url, t.personal_homepage,
               p.keywords, p.score, p.teaching_score, p.teaching_imputed
        FROM teachers t
        LEFT JOIN processing p ON p.teacher_id = t.id
    """
    try:
        rows = conn.execute(sql).fetchall()
    except sqlite3.Error:
        rows = conn.execute("""
            SELECT id, name, name_pinyin, college, title, email, research_directions, bio,
                   institute, honors, h_index, citation_count, paper_count,
                   homepage_url, personal_homepage
            FROM teachers
        """).fetchall()

    out = []
    for row in rows:
        d = dict(row)
        out.append({
            "id": d.get("id"),
            "name": d.get("name") or "",
            "name_pinyin": d.get("name_pinyin") or "",
            "college": d.get("college") or "",
            "title": d.get("title") or "",
            "email": d.get("email") or "",
            "directions": d.get("research_directions") or "",
            "bio": d.get("bio") or "",
            "institute": d.get("institute") or "",
            "honors": d.get("honors") or "",
            "h_index": _to_int(d.get("h_index")),
            "citation_count": _to_int(d.get("citation_count")),
            "paper_count": _to_int(d.get("paper_count")),
            "homepage_url": d.get("homepage_url") or "",
            "personal_homepage": d.get("personal_homepage") or "",
            "keywords": _json_list(d.get("keywords")),
            "score": _to_float(d.get("score")),
            "teaching": _to_float(d.get("teaching_score")),
            "teaching_imputed": bool(d.get("teaching_imputed")),
        })
    return out


def _load_papers(conn):
    try:
        rows = conn.execute(
            "SELECT teacher_id, title, year, citation_count, venue, doi FROM papers"
        ).fetchall()
    except sqlite3.Error:
        return {}
    grouped = {}
    for row in rows:
        d = dict(row)
        if not d.get("title"):
            continue
        year = _to_int(d.get("year"))
        if year is not None and (year < 1980 or year > 2100):
            year = None
        grouped.setdefault(d.get("teacher_id"), []).append({
            "title": d["title"],
            "year": year,
            "citations": _to_int(d.get("citation_count")) or 0,
            "venue": d.get("venue") or "",
            "doi": d.get("doi") or "",
        })
    return grouped


def _load():
    key = None
    if os.path.exists(DB_PATH):
        stat = os.stat(DB_PATH)
        # 使用纳秒时间戳：同一秒内写库且文件大小不变时也不会命中旧缓存。
        key = (stat.st_mtime_ns, stat.st_size)
    if _cache["key"] == key:
        return
    teachers, papers = [], {}
    if key:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                teachers = _load_teachers(conn)
                papers = _load_papers(conn)
            finally:
                conn.close()
        except sqlite3.Error:
            teachers, papers = [], {}
    _cache.update({
        "key": key,
        "teachers": teachers,
        "papers": papers,
        "vocab": _build_vocab(teachers),
    })


def _build_vocab(teachers):
    terms = set()
    for t in teachers:
        terms.update(k for k in t["keywords"] if len(k) >= 2)
        for seg in re.split(r"[、,，;；/|]+", t["directions"]):
            seg = seg.strip()
            if 2 <= len(seg) <= 14:
                terms.add(seg)
    return sorted(terms, key=len, reverse=True)


def teachers():
    _load()
    return _cache["teachers"]


def vocabulary():
    _load()
    return _cache["vocab"]


def college_names():
    return sorted({t["college"] for t in teachers() if t["college"]})


def teacher_names():
    return [t["name"] for t in teachers() if t["name"]]


def stats():
    data = teachers()
    return {
        "teachers": len(data),
        "papers": sum(len(v) for v in _cache["papers"].values()),
    }


def _surfaces(term):
    return [term] + nlu.ALIASES.get(term, [])


def _dedupe(items):
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _match_teacher(t, terms):
    score = 0.0
    dirs, kws, bios, insts = [], [], [], []
    for term in terms:
        for surface in _surfaces(term):
            weight = 1.0 if surface == term else 0.5
            if nlu._contains(t["directions"], surface):
                score += 3.0 * weight
                dirs.append(surface)
            if any(nlu._contains(k, surface) for k in t["keywords"]):
                score += 2.2 * weight
                kws.append(surface)
            if nlu._contains(t["bio"], surface):
                score += 0.8 * weight
                bios.append(surface)
            if nlu._contains(t["institute"], surface):
                score += 0.6 * weight
                insts.append(surface)

    paper_hits = []
    if terms:
        surfaces = [s for term in terms for s in _surfaces(term)]
        for p in _cache["papers"].get(t["id"], []):
            if any(nlu._contains(p["title"], s) for s in surfaces):
                paper_hits.append(p)
                if len(paper_hits) >= 8:
                    break
        score += len(paper_hits) * 0.45

    return score, _dedupe(dirs), _dedupe(kws), _dedupe(bios), _dedupe(insts), paper_hits


def search(terms, college=None, limit=5, depth=False):
    """返回候选教师及匹配依据。depth=True 时优先“持续涉及”的教师。"""
    rows = teachers()
    results = []
    for t in rows:
        if college and t["college"] != college:
            continue
        if terms:
            score, dirs, kws, bios, insts, papers = _match_teacher(t, terms)
            if score <= 0:
                continue
        else:
            score, dirs, kws, bios, insts, papers = 1.0, [], [], [], [], []
            papers = sorted(
                _cache["papers"].get(t["id"], []),
                key=lambda p: (p["year"] or 0, p["citations"]),
                reverse=True,
            )[:2]

        years = {p["year"] for p in papers if p["year"]}
        depth_score = len(papers) + 0.5 * len(years)
        results.append({
            "teacher": t,
            "match": score,
            "depth": depth_score,
            "matched_dirs": dirs[:3],
            "matched_keywords": kws[:4],
            "matched_bio": bios[:2],
            "matched_institute": insts[:2],
            "papers": papers[:2],
            "recent_year": max(years) if years else None,
        })

    if not terms:
        # 没有研究方向条件时，沿用项目现有的综合评分排序
        results.sort(key=lambda r: (-(r["teacher"]["score"] or 0),
                                    -(r["teacher"]["h_index"] or 0)))
    elif depth:
        results.sort(key=lambda r: (-r["depth"], -r["match"],
                                    -(r["teacher"]["h_index"] or 0)))
    else:
        results.sort(key=lambda r: (-r["match"], -(r["teacher"]["h_index"] or 0)))
    return results[:limit]


def _ascii_tokens(text):
    value = unicodedata.normalize("NFKD", text or "")
    value = value.encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return [x for x in value.split() if x]


def _pinyin_forms(teacher):
    tokens = _ascii_tokens(teacher.get("name_pinyin"))
    if len(tokens) < 2:
        return []
    return [" ".join(tokens), " ".join(reversed(tokens))]


def find_teacher_in_text(text):
    """从中文姓名或英文拼音句子中定位教师。"""
    raw = str(text or "")
    for t in sorted(teachers(), key=lambda x: -len(x["name"])):
        if len(t["name"]) >= 2 and t["name"] in raw:
            return t
    tokens = _ascii_tokens(raw)
    if len(tokens) < 2:
        return None
    for t in sorted(teachers(), key=lambda x: -len(x.get("name_pinyin") or "")):
        for form in _pinyin_forms(t):
            parts = form.split()
            size = len(parts)
            for i in range(len(tokens) - size + 1):
                if tokens[i:i + size] == parts:
                    return t
    return None


def resolve_teacher(name):
    """接受中文姓名、英文姓名或拼音，正反顺序均可。"""
    text = str(name or "").strip()
    if not text:
        return None
    for t in teachers():
        if t["name"] == text:
            return t
    tokens = sorted(_ascii_tokens(text))
    if len(tokens) >= 2:
        matches = [
            t for t in teachers()
            if sorted(_ascii_tokens(t.get("name_pinyin"))) == tokens
        ]
        if matches:
            return sorted(matches, key=lambda x: -(x.get("score") or 0))[0]
    return find_teacher_in_text(text)


def by_name(name):
    return resolve_teacher(name)


def profile(tid):
    for t in teachers():
        if t["id"] == tid:
            return t
    return None


def papers_for(tid, limit=3):
    items = list(_cache["papers"].get(tid, []))
    items.sort(key=lambda p: (p["year"] or 0, p["citations"]), reverse=True)
    return items[:limit]


def courses_for(tid, limit=3):
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT course_name, rating_avg, rating_count FROM courses "
            "WHERE teacher_id=? ORDER BY (rating_count>0) DESC, "
            "COALESCE(rating_avg,0) DESC, rating_count DESC LIMIT ?",
            (tid, limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out = []
    for row in rows:
        d = dict(row)
        out.append({
            "name": d.get("course_name") or "",
            "rating": _to_float(d.get("rating_avg")),
            "count": _to_int(d.get("rating_count")) or 0,
        })
    return [c for c in out if c["name"]]


def _load_collab():
    global _collab
    if _collab is not None:
        return _collab
    path = os.path.join(BASE_DIR, "data", "exports", "collab_edges.csv")
    adj = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    a = int(row["src"])
                    b = int(row["dst"])
                    w = int(row["weight"])
                except (KeyError, ValueError):
                    continue
                adj.setdefault(a, {})
                adj.setdefault(b, {})
                adj[a][b] = adj[a].get(b, 0) + w
                adj[b][a] = adj[b].get(a, 0) + w
    _collab = adj
    return adj


def lab_context(tid, limit=10):
    """实验室问题的可核验替代信息。

    数据库没有实验室成员字段，这里返回同研究所教师与合作记录，
    由回答层明确标注为推断依据。
    """
    t = profile(tid)
    if not t:
        return {"institute": "", "lab_name": "", "mates": [], "collaborators": []}

    institute = t["institute"]
    mates = []
    if institute:
        mates = [x for x in teachers() if x["id"] != tid and x["institute"] == institute]
        mates.sort(key=lambda x: (-(x["score"] or 0), -(x["h_index"] or 0)))
        mates = mates[:limit]

    collaborators = []
    for oid, weight in sorted(_load_collab().get(tid, {}).items(),
                              key=lambda kv: -kv[1])[:limit]:
        other = profile(oid)
        if other:
            collaborators.append({"teacher": other, "weight": weight})

    lab_name = ""
    match = re.search(r"([A-Za-z][A-Za-z0-9\-& ]{1,30}(?:Lab|LAB|Laboratory))", t["bio"])
    if match:
        lab_name = match.group(1).strip()

    return {
        "institute": institute,
        "lab_name": lab_name,
        "mates": mates,
        "collaborators": collaborators,
    }


def candidate_payload(item):
    t = item["teacher"]
    return {
        "id": t["id"],
        "name": t["name"],
        "college": t["college"],
        "title": t["title"],
        "directions": t["directions"],
        "h_index": t["h_index"],
        "citation_count": t["citation_count"],
        "paper_count": t["paper_count"],
        "homepage_url": t["homepage_url"],
        "personal_homepage": t["personal_homepage"],
        "matched_dirs": item["matched_dirs"],
        "matched_keywords": item["matched_keywords"],
        "papers": item["papers"],
        "recent_year": item["recent_year"],
        "rag_evidence": item.get("rag_evidence") or [],
        "graph_reason": item.get("graph_reason") or "",
        "honor_match": bool(item.get("honor_match")),
    }


def profile_payload(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "college": t["college"],
        "title": t["title"],
        "email": t.get("email") or "",
        "directions": t["directions"],
        "bio": t["bio"],
        "institute": t["institute"],
        "honors": t["honors"],
        "h_index": t["h_index"],
        "citation_count": t["citation_count"],
        "paper_count": t["paper_count"],
        "homepage_url": t["homepage_url"],
        "personal_homepage": t["personal_homepage"],
        "score": t["score"],
        "teaching": t["teaching"],
        "teaching_imputed": t["teaching_imputed"],
    }

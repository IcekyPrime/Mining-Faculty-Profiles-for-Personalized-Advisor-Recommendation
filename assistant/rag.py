# -*- coding: utf-8 -*-
"""词法 RAG + Graph RAG 检索。

在教师档案、荣誉、论文、课程上建轻量 BM25 索引；
再沿合作网络和研究所做图扩展。教师卡片仍由检索结果生成。
"""
import json
import math
import os
import re
import sqlite3
from collections import Counter, defaultdict

from . import retrieval

FIELD_BOOST = {
    "honors": 3.0,
    "directions": 3.0,
    "keywords": 2.5,
    "bio": 2.0,
    "papers": 1.2,
    "courses": 0.5,
    "institute": 0.3,
    "college": 0.2,
}

SYNONYMS = {
    "语音识别": ["语音识别", "语音", "speech", "asr", "speech recognition"],
    "语音": ["语音", "语音识别", "speech", "asr"],
    "数据挖掘": ["数据挖掘", "数据仓库", "知识发现", "data mining", "kdd"],
    "机器学习": ["机器学习", "machine learning"],
    "深度学习": ["深度学习", "deep learning", "neural network"],
    "计算机视觉": ["计算机视觉", "图像处理", "computer vision", "image processing"],
    "自然语言处理": ["自然语言处理", "nlp", "natural language processing"],
    "大模型": ["大模型", "大语言模型", "llm", "large language model"],
    "推荐系统": ["推荐系统", "推荐算法", "recommender", "recommendation"],
    "强化学习": ["强化学习", "reinforcement learning"],
    "知识图谱": ["知识图谱", "knowledge graph"],
    "图神经网络": ["图神经网络", "graph neural network", "gnn"],
    "多模态": ["多模态", "multimodal"],
    "芯片设计": ["芯片设计", "集成电路", "芯片", "vlsi", "ic design"],
    "电力系统": ["电力系统", "智能电网", "power system", "smart grid"],
    "机器人": ["机器人", "具身智能", "robotics"],
    "网络安全": ["网络安全", "信息安全", "隐私", "security", "privacy"],
}

HONOR_BOOST = {
    "ieee fellow": 40.0,
    "isca fellow": 40.0,
    "acm fellow": 40.0,
    "院士": 30.0,
    "杰青": 20.0,
    "长江学者": 20.0,
    "优青": 16.0,
    "博导": 4.0,
}

STOP = set("""
的 了 和 与 及 或 等 在 中 上 下 对 为 于 从 到 被 把 将 是 有 也 都 而 并 且
主要 研究 方向 领域 技术 方法 应用 系统 相关 基于 包括 从事 目前 负责 参与
进行 实现 提出 针对 开展 承担 主持 完成 获得 发表 论文 国际 国内 教授 研究员
副教授 讲师 博士 硕士 学位 毕业 担任 荣获 获奖 项目 课题 基金 合作 企业 成果
现任 曾任 期刊 会议 出版 国家 上海 教育部 学会 会员 杰出 优秀 人才 计划 学者 专家
作为 曾 曾获 老师 导师 教师 学生 学院 学校 哪些 哪位 什么 怎么 如何
""".split())

_jieba = None
_cache = {"key": None, "docs": [], "teachers": {}, "df": Counter(),
          "n": 0, "avgdl": 1.0, "courses": {}}


def _get_jieba():
    global _jieba
    if _jieba is None:
        try:
            import jieba
            _jieba = jieba
        except Exception:
            _jieba = False
    return _jieba


def _tokenize(text):
    text = (text or "").lower()
    jieba = _get_jieba()
    if jieba:
        words = jieba.lcut(text)
    else:
        words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fa5]{2}", text)
    out = []
    for word in words:
        word = word.strip().lower()
        if len(word) < 2 or word in STOP:
            continue
        out.append(word)
    return out


def _load_courses():
    if not os.path.exists(retrieval.DB_PATH):
        return {}
    conn = sqlite3.connect(retrieval.DB_PATH)
    try:
        rows = conn.execute(
            "SELECT teacher_id, course_name FROM courses WHERE course_name IS NOT NULL"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    grouped = defaultdict(list)
    for tid, name in rows:
        if name:
            grouped[tid].append(name)
    return grouped


def _mtime_key():
    if not os.path.exists(retrieval.DB_PATH):
        return "missing"
    stat = os.stat(retrieval.DB_PATH)
    return (int(stat.st_mtime), stat.st_size)


def _build():
    teachers = retrieval.teachers()
    papers = retrieval._cache.get("papers") or {}
    courses = _load_courses()
    docs = []

    def add(tid, field, text):
        text = (text or "").strip()
        if not text:
            return
        tokens = _tokenize(text)
        if not tokens:
            return
        docs.append({
            "tid": tid,
            "field": field,
            "text": text[:600],
            "tf": Counter(tokens),
            "len": len(tokens),
        })

    for t in teachers:
        add(t["id"], "directions", t["directions"])
        add(t["id"], "keywords", "、".join(t["keywords"]))
        add(t["id"], "honors", t["honors"])
        add(t["id"], "institute", t["institute"])
        add(t["id"], "college", t["college"])
        bio = t["bio"] or ""
        for start in range(0, min(len(bio), 900), 300):
            add(t["id"], "bio", bio[start:start + 300])
        teacher_papers = sorted(
            papers.get(t["id"], []),
            key=lambda p: (p.get("year") or 0, p.get("citations") or 0),
            reverse=True,
        )[:6]
        for p in teacher_papers:
            add(t["id"], "papers", "%s %s %s" % (
                p.get("title") or "", p.get("venue") or "", p.get("year") or ""))
        for name in courses.get(t["id"], [])[:4]:
            add(t["id"], "courses", name)

    df = Counter()
    for doc in docs:
        for token in doc["tf"]:
            df[token] += 1

    _cache.update({
        "key": _mtime_key(),
        "docs": docs,
        "teachers": {t["id"]: t for t in teachers},
        "df": df,
        "n": max(1, len(docs)),
        "avgdl": (sum(d["len"] for d in docs) / len(docs)) if docs else 1.0,
        "courses": courses,
    })


def _ensure():
    if _cache["key"] != _mtime_key():
        _build()


def _matches(term, text):
    if not term or not text:
        return False
    if term.isascii():
        pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
        return re.search(pattern, text.lower()) is not None
    return term in text


def search(terms, college=None, limit=8, depth=False):
    """返回与 retrieval.search 兼容的候选，并附带 RAG 证据与图扩展原因。"""
    _ensure()
    terms = [str(t).strip() for t in (terms or []) if str(t).strip()][:4]
    if not terms:
        return retrieval.search([], college=college, limit=limit)

    query_text = " ".join(terms).lower()
    expanded = list(terms)
    for term in terms:
        for synonym in SYNONYMS.get(term, []):
            if synonym not in expanded:
                expanded.append(synonym)
    query_tokens = _tokenize(" ".join(expanded))
    if not query_tokens:
        return retrieval.search(terms, college=college, limit=limit)

    docs = _cache["docs"]
    teachers = _cache["teachers"]
    df = _cache["df"]
    n_docs = _cache["n"]
    avgdl = _cache["avgdl"]

    teacher_scores = defaultdict(float)
    teacher_fields = defaultdict(dict)
    teacher_evidence = defaultdict(list)
    teacher_paper_hits = defaultdict(int)
    matched_dirs = defaultdict(list)
    matched_keywords = defaultdict(list)

    for doc in docs:
        tid = doc["tid"]
        if college and teachers.get(tid, {}).get("college") != college:
            continue
        score = 0.0
        for token in set(query_tokens):
            freq = doc["tf"].get(token, 0)
            if not freq:
                continue
            idf = math.log(1 + (n_docs - df[token] + 0.5) / (df[token] + 0.5))
            score += idf * (freq * 2.5) / (freq + 1.5 * (1 - 0.75 + 0.75 * doc["len"] / avgdl))
        if score <= 0:
            continue

        field = doc["field"]
        score *= FIELD_BOOST.get(field, 0.5)
        doc_low = doc["text"].lower()
        if query_text and len(query_text) >= 2 and query_text in doc_low:
            score *= 1.8
        for term in terms:
            if term and term.lower() in doc_low:
                score += 4.0 * FIELD_BOOST.get(field, 0.5)

        prev = teacher_fields[tid].get(field, 0.0)
        if score > prev:
            teacher_fields[tid][field] = score
        teacher_evidence[tid].append({
            "field": field,
            "text": doc["text"][:220],
            "score": round(score, 2),
        })
        if field == "papers":
            teacher_paper_hits[tid] += 1

        teacher = teachers.get(tid)
        if teacher:
            for term in terms:
                if _matches(term, teacher["directions"]):
                    if term not in matched_dirs[tid]:
                        matched_dirs[tid].append(term)
                if any(_matches(term, k) for k in teacher["keywords"]):
                    if term not in matched_keywords[tid]:
                        matched_keywords[tid].append(term)

    for tid, fields in teacher_fields.items():
        best = max(fields.values())
        total = best + 0.2 * (sum(fields.values()) - best)
        teacher_scores[tid] += total

    # 荣誉元数据增强：例如 IEEE Fellow 直接提高有该荣誉的教师
    for phrase, boost in HONOR_BOOST.items():
        if phrase not in query_text:
            continue
        for tid, teacher in teachers.items():
            if college and teacher["college"] != college:
                continue
            if phrase in (teacher["honors"] or "").lower():
                teacher_scores[tid] += boost

    # Graph RAG：从词法 top 教师沿合作边与研究所扩展
    adjacency = retrieval._load_collab()
    seeds = sorted(teacher_scores.items(), key=lambda kv: -kv[1])[:3]
    graph_reason = {}
    for seed_tid, seed_score in seeds:
        if seed_score <= 0:
            continue
        seed_name = teachers.get(seed_tid, {}).get("name") or ""
        for neighbor, weight in (adjacency.get(seed_tid) or {}).items():
            if neighbor not in teacher_scores or teacher_scores[neighbor] <= 0:
                continue
            if college and teachers.get(neighbor, {}).get("college") != college:
                continue
            bonus = seed_score * min(0.2, weight / 50.0)
            teacher_scores[neighbor] += bonus
            graph_reason.setdefault(neighbor, "与%s有合作关系" % seed_name)
        institute = teachers.get(seed_tid, {}).get("institute") or ""
        if institute:
            for tid, teacher in teachers.items():
                if tid == seed_tid or teacher["institute"] != institute:
                    continue
                if college and teacher["college"] != college:
                    continue
                if teacher_scores.get(tid, 0) > 0:
                    teacher_scores[tid] += seed_score * 0.03
                    graph_reason.setdefault(tid, "与%s同研究所" % seed_name)

    results = []
    for tid, score in sorted(teacher_scores.items(), key=lambda kv: -kv[1]):
        if score <= 0:
            continue
        teacher = teachers.get(tid)
        if not teacher:
            continue
        papers = sorted(
            retrieval._cache.get("papers", {}).get(tid, []),
            key=lambda p: (p.get("year") or 0, p.get("citations") or 0),
            reverse=True,
        )[:2]
        years = [p["year"] for p in papers if p.get("year")]
        evidence = sorted(teacher_evidence.get(tid, []),
                          key=lambda e: -e["score"])[:3]
        results.append({
            "teacher": teacher,
            "match": round(score, 2),
            "depth": teacher_paper_hits.get(tid, 0),
            "matched_dirs": matched_dirs.get(tid, [])[:3],
            "matched_keywords": matched_keywords.get(tid, [])[:3],
            "papers": papers,
            "recent_year": max(years) if years else None,
            "rag_evidence": evidence,
            "graph_reason": graph_reason.get(tid, ""),
            "honor_match": any(
                phrase in query_text and phrase in (teacher["honors"] or "").lower()
                for phrase in HONOR_BOOST
            ),
        })
        if len(results) >= limit:
            break

    if not results:
        return retrieval.search(terms, college=college, limit=limit, depth=depth)
    if depth:
        results.sort(key=lambda r: (-r["honor_match"], -r["depth"], -r["match"]))
    return results[:limit]

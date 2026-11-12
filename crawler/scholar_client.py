"""Semantic Scholar 学术指标客户端（替代 OpenAlex，免费额度更宽松）。

对每位导师：作者检索 -> h 指数/引用量/论文数 -> 代表论文（按被引排序）。
结果按教师名缓存到 data/raw/scholar/ 下。
"""
import json
import os
import re
import time

import requests

from . import config

try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None

API = "https://api.semanticscholar.org/graph/v1"
CACHE_DIR = os.path.join(config.RAW_DIR, "scholar")
os.makedirs(CACHE_DIR, exist_ok=True)

_SESS = None
_last_req = 0.0
_RATE_INTERVAL = 1.2  # 请求间隔（秒），规避 Semantic Scholar 限流


def _get_session():
    global _SESS
    if _SESS is None:
        _SESS = requests.Session()
        _SESS.headers.update({"User-Agent": "mentor-data-layer/1.0"})
    return _SESS


def _get(url, params=None):
    global _last_req
    # 主动限速
    wait = _RATE_INTERVAL - (time.time() - _last_req)
    if wait > 0:
        time.sleep(wait)
    r = _get_session().get(url, params=params, timeout=30)
    for backoff in (5, 10, 20, 40):
        if r.status_code != 429:
            break
        time.sleep(backoff)
        r = _get_session().get(url, params=params, timeout=30)
    r.raise_for_status()
    _last_req = time.time()
    return r.json()


def _cache_path(key):
    safe = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]", "_", key or "")
    return os.path.join(CACHE_DIR, f"scholar_{safe}.json")


def _candidate_names(teacher):
    names = []
    pinyin = (teacher.get("name_pinyin") or "").strip()
    if pinyin:
        names.append(pinyin)
    email = teacher.get("email") or ""
    if "@" in email:
        local = re.sub(r"[^a-zA-Z.\-_]", "", email.split("@")[0])
        parts = [p for p in re.split(r"[.\-_]+", local) if p]
        if len(parts) >= 2:
            names.append(" ".join(parts))
            names.append(" ".join(reversed(parts)))
        elif len(local) >= 4:
            names.append(local)
    slug = teacher.get("slug") or ""
    if not slug and teacher.get("homepage_url"):
        m = re.search(r"faculty\.sjtu\.edu\.cn/([^/]+)/", teacher["homepage_url"] or "")
        slug = m.group(1) if m else ""
    slug = re.sub(r"[^a-zA-Z]", "", slug)
    if len(slug) >= 4:
        names.append(slug)
    # 中文名转拼音（姓+名，名拼接）
    cn = teacher.get("name") or ""
    if lazy_pinyin and cn and re.search(r"[\u4e00-\u9fff]", cn):
        py = lazy_pinyin(cn)
        if len(py) >= 2:
            surname = py[0]
            given = "".join(py[1:])
            names.append(f"{given.title()} {surname.title()}")   # Binyu Zang
            names.append(f"{surname.title()} {given.title()}")   # Zang Binyu
        elif py:
            names.append(py[0].title())
    if cn:
        names.append(cn)
    out = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


def _is_sjtu(author):
    affs = author.get("affiliations") or ""
    return "Jiao Tong" in affs or "SJTU" in affs


def search_author(teacher):
    """依次检索候选名，优先上海交通大学作者；否则退回首个候选的首条结果。"""
    queries = _candidate_names(teacher)
    fallback = None
    for q in queries:
        try:
            data = _get(f"{API}/author/search",
                        {"query": q, "fields": "name,hIndex,citationCount,paperCount,affiliations"})
        except Exception:
            continue
        authors = data.get("data") or []
        for a in authors:
            if _is_sjtu(a):
                return a
        if fallback is None and authors:
            fallback = authors[0]
    return fallback


def get_author_papers(author_id, limit=5):
    data = _get(f"{API}/author/{author_id}/papers",
                {"fields": "title,year,citationCount,venue,externalIds", "limit": limit})
    papers = []
    for p in data.get("data") or []:
        ext = p.get("externalIds") or {}
        papers.append({
            "title": p.get("title"),
            "year": p.get("year"),
            "citation_count": p.get("citationCount"),
            "venue": p.get("venue"),
            "doi": ext.get("DOI"),
            "paper_id": p.get("paperId"),
        })
    return papers


def enrich_teacher(teacher, force=False):
    """为一位教师补全 Semantic Scholar 学术指标。

    默认仅在有可靠拼音名时检索（避免中文名歧义）；force=True 时用中文名转拼音兜底，
    对缺失学术数据的教师尽力检索。
    """
    if not force and not (teacher.get("name_pinyin") or "").strip():
        return {}
    cache = _cache_path(teacher.get("name"))
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    author = search_author(teacher)
    if not author:
        return {}
    result = {
        "scholar_id": author.get("authorId"),
        "scholar_name": author.get("name"),
        "paper_count": author.get("paperCount"),
        "citation_count": author.get("citationCount"),
        "h_index": author.get("hIndex"),
        "papers": get_author_papers(author.get("authorId")) if author.get("authorId") else [],
    }
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return result

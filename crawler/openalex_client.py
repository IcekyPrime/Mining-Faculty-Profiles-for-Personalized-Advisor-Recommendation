"""OpenAlex 开放学术 API 客户端。

对每位导师：检索作者 -> 获取影响力指标（引用/h指数）与研究主题 -> 拉取代表论文。
结果缓存到 data/raw/openalex/ 下，支持断点续跑。
"""
import json
import os
import re
import time

import requests

from . import config

API = "https://api.openalex.org"
CACHE_DIR = os.path.join(config.RAW_DIR, "openalex")
os.makedirs(CACHE_DIR, exist_ok=True)

_SESS = None


def _get_session():
    global _SESS
    if _SESS is None:
        _SESS = requests.Session()
        _SESS.headers.update({"User-Agent": "mentor-data-layer/1.0 (course project)"})
    return _SESS


def _get(url, params=None):
    r = _get_session().get(url, params=params, timeout=30)
    if r.status_code == 429:
        time.sleep(2)
        r = _get_session().get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _load_cache(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _save_cache(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _affiliated_with_sjtu(author):
    for inst in author.get("last_known_institutions") or []:
        if inst.get("id", "").endswith(config.SJTU_OPENALEX_ID):
            return True
    for aff in author.get("affiliations") or []:
        if aff.get("institution", {}).get("id", "").endswith(config.SJTU_OPENALEX_ID):
            return True
    return False


def _candidate_queries(teacher):
    """按可靠性生成候选检索词：拼音 > 邮箱派生 > 中文名。"""
    qs = []
    pinyin = (teacher.get("name_pinyin") or "").strip()
    email = teacher.get("email") or ""
    if pinyin:
        qs.append(pinyin)
    if "@" in email:
        local = re.sub(r"[^a-zA-Z.\-_]", "", email.split("@")[0])
        if "." in local or "-" in local or "_" in local:
            parts = [p for p in re.split(r"[.\-_]+", local) if p]
            if len(parts) >= 2:
                qs.append(" ".join(parts))
                qs.append(" ".join(reversed(parts)))
        elif len(local) >= 4:
            qs.append(local)
    if teacher.get("name"):
        qs.append(teacher.get("name"))
    # 去重保序
    seen, out = set(), []
    for q in qs:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def search_author(teacher):
    """按候选词依次检索 OpenAlex，优先上海交通大学作者；否则退回首个候选的首条结果。"""
    queries = _candidate_queries(teacher)
    fallback = None
    for q in queries:
        try:
            data = _get(f"{API}/authors", {"search": q, "per-page": 5})
        except Exception:
            continue
        results = data.get("results") or []
        for a in results:
            if _affiliated_with_sjtu(a):
                return a
        if fallback is None and results:
            fallback = results[0]
    return fallback


def get_top_works(author_id, n=5):
    """获取该作者被引最高的 n 篇代表论文。"""
    cache = os.path.join(CACHE_DIR, f"works_{author_id.split('/')[-1]}.json")
    cached = _load_cache(cache)
    if cached is not None:
        return cached
    data = _get(
        f"{API}/works",
        {"filter": f"author.id:{author_id.split('/')[-1]}",
         "sort": "cited_by_count:desc", "per-page": n},
    )
    works = []
    for w in data.get("results") or []:
        src = ((w.get("primary_location") or {}).get("source") or {})
        works.append({
            "title": w.get("title"),
            "year": w.get("publication_year"),
            "cited_by_count": w.get("cited_by_count"),
            "venue": src.get("display_name"),
            "doi": w.get("doi"),
            "openalex_work_id": w.get("id"),
        })
    _save_cache(cache, works)
    time.sleep(0.2)
    return works


def enrich_teacher(teacher):
    """为一位教师补全 OpenAlex 学术信息，返回补充字段 dict。

    结果按教师 slug 缓存到 data/raw/openalex/enrich_<slug>.json，避免重复请求
    （OpenAlex 免费额度有限，重复爬取会被限流）。
    """
    slug = teacher.get("slug")
    cache = os.path.join(CACHE_DIR, f"enrich_{slug}.json") if slug else None
    if cache:
        cached = _load_cache(cache)
        if cached is not None:
            return cached
    author = search_author(teacher)
    if not author:
        return {}
    stats = author.get("summary_stats") or {}
    topics = [t.get("display_name") for t in (author.get("topics") or [])[:8]]
    aid = author.get("id", "").split("/")[-1]
    works = get_top_works(author.get("id"), 5)
    result = {
        "openalex_id": aid,
        "openalex_name": author.get("display_name"),
        "works_count": author.get("works_count"),
        "cited_by_count": author.get("cited_by_count"),
        "h_index": stats.get("h_index"),
        "i10_index": stats.get("i10_index"),
        "research_topics": json.dumps(topics, ensure_ascii=False),
        "papers": works,
    }
    if cache:
        _save_cache(cache, result)
    return result

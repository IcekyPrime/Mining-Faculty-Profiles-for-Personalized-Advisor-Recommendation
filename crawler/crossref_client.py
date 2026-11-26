"""Crossref 开放元数据客户端。

按英文姓名检索 DOI 作品，取完整作者列表，补充非计算机学院教师的合作网络。
结果按教师 ID 缓存到 data/raw/crossref/，支持断点续跑。

用法：
    python -m crawler.crossref_client [--limit N] [--college X]
"""
import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from . import config

API = "https://api.crossref.org/works"
CACHE_DIR = os.path.join(config.RAW_DIR, "crossref")
os.makedirs(CACHE_DIR, exist_ok=True)

MAX_ROWS = 40      # 每人最多取多少条作品
WORKERS = 4        # 并发数（Crossref 限额宽松）

_SESS = requests.Session()
_SESS.headers.update({"User-Agent": "mentor-data-layer/1.0 (course project)"})


def _get(params):
    for backoff in (2, 5, 15, 30, None):
        try:
            r = _SESS.get(API, params=params, timeout=60)
        except requests.exceptions.RequestException:
            if backoff:
                time.sleep(backoff)
                continue
            return None
        if r.status_code == 200:
            return r.json()
        if backoff:
            time.sleep(backoff)
            continue
        return None
    return None


def query_name(teacher):
    """检索用英文名：拼音优先，其次邮箱前缀。"""
    py = (teacher.get("name_pinyin") or "").strip()
    if py:
        return py
    email = teacher.get("email") or ""
    if "@" in email:
        local = re.sub(r"[^a-zA-Z.\-_]", "", email.split("@")[0])
        parts = [p for p in re.split(r"[.\-_]+", local) if p]
        if len(parts) >= 2:
            return " ".join(parts)
    return ""


def norm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def fetch_works(name_en):
    """检索该作者的作品，返回 [{doi, title, year, authors, sjtu}]。"""
    data = _get({
        "query.author": name_en,
        "rows": MAX_ROWS,
        "select": "DOI,title,author,issued",
    })
    if not data:
        return []
    items = (data.get("message") or {}).get("items") or []
    forms = {norm(name_en)}
    parts = name_en.split()
    if len(parts) >= 2:
        forms.add(norm(" ".join(reversed(parts))))
    out = []
    for it in items:
        authors, sjtu, hit = [], False, False
        for a in it.get("author") or []:
            full = ((a.get("given") or "") + " " + (a.get("family") or "")).strip()
            if not full:
                continue
            authors.append(full)
            if norm(full) in forms:
                hit = True
            for aff in a.get("affiliation") or []:
                if "jiao tong" in (aff.get("name") or "").lower():
                    sjtu = True
        if not hit or len(authors) < 2:
            continue
        title = re.sub(r"\s+", " ", (it.get("title") or [""])[0] or "").strip()
        year = ((it.get("issued") or {}).get("date-parts") or [[None]])[0][0]
        out.append({"doi": it.get("DOI"), "title": title, "year": year,
                    "authors": authors, "sjtu": sjtu})
    return out


def enrich_teacher(teacher):
    """抓取（或复用缓存）某位教师的 Crossref 作品。"""
    name_en = query_name(teacher)
    if not name_en:
        return {}
    cache = os.path.join(CACHE_DIR, "%s.json" % teacher.get("id"))
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    works = fetch_works(name_en)
    result = {"name_en": name_en, "works": works}
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return result


def main():
    import sqlite3
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--college", default="")
    args = parser.parse_args()

    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM teachers WHERE college != '计算机学院'"
    params = []
    if args.college:
        sql = "SELECT * FROM teachers WHERE college = ?"
        params = [args.college]
    rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    conn.close()
    if args.limit:
        rows = rows[:args.limit]

    print("待检索教师 %d 人（Crossref 并发 %d）" % (len(rows), WORKERS))
    hit = papers = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(enrich_teacher, dict(r)): dict(r) for r in rows}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                res = fut.result()
            except Exception:
                res = {}
            n = len(res.get("works") or [])
            if n:
                hit += 1
                papers += n
            if i % 20 == 0:
                print("  %d/%d 已命中 %d 人" % (i, len(rows), hit))
    print("完成：命中 %d / %d 人，作品 %d 条，缓存目录 %s"
          % (hit, len(rows), papers, CACHE_DIR))


if __name__ == "__main__":
    main()

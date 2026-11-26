"""arXiv 开放接口客户端。

按英文姓名检索作者论文，取完整作者列表，供合作网络补充非计算机学院教师。
结果按教师 ID 缓存到 data/raw/arxiv/，支持断点续跑。

用法：
    python -m crawler.arxiv_client [--limit N]
"""
import argparse
import json
import os
import re
import time
import xml.etree.ElementTree as ET

import requests

from . import config

API = "http://export.arxiv.org/api/query"
CACHE_DIR = os.path.join(config.RAW_DIR, "arxiv")
os.makedirs(CACHE_DIR, exist_ok=True)

NS = {"atom": "http://www.w3.org/2005/Atom"}
MAX_RESULTS = 40          # 每人最多取多少篇
INTERVAL = 3.0            # arXiv 建议的请求间隔（秒）

_HEADERS = {"User-Agent": "mentor-data-layer/1.0 (course project)"}
_last_req = 0.0


def _get(params):
    global _last_req
    wait = INTERVAL - (time.time() - _last_req)
    if wait > 0:
        time.sleep(wait)
    for backoff in (5, 15, 30, None):
        try:
            r = requests.get(API, params=params, headers=_HEADERS, timeout=40)
        except requests.exceptions.RequestException:
            if backoff:
                time.sleep(backoff)
                continue
            return None
        if r.status_code == 200:
            _last_req = time.time()
            return r.text
        if backoff:
            time.sleep(backoff)
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


def _parse_entries(text):
    """解析 Atom 响应，返回 [{arxiv_id, title, year, authors}]。"""
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for e in root.findall("atom:entry", NS):
        title = (e.findtext("atom:title", default="", namespaces=NS) or "").strip()
        title = re.sub(r"\s+", " ", title)
        published = e.findtext("atom:published", default="", namespaces=NS) or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        aid = (e.findtext("atom:id", default="", namespaces=NS) or "").strip()
        authors = [(a.findtext("atom:name", default="", namespaces=NS) or "").strip()
                   for a in e.findall("atom:author", NS)]
        authors = [a for a in authors if a]
        if title and authors:
            out.append({"arxiv_id": aid.rsplit("/", 1)[-1], "title": title,
                        "year": year, "authors": authors})
    return out


def fetch_papers(name_en, max_results=MAX_RESULTS):
    """检索该作者的论文，返回 [{arxiv_id, title, year, authors}]。"""
    text = _get({
        "search_query": 'au:"%s"' % name_en,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    return _parse_entries(text)


def fetch_batch(names, max_results=150):
    """一次检索多位作者（OR 查询），用于批量补全。"""
    query = " OR ".join('au:"%s"' % n for n in names)
    text = _get({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    return _parse_entries(text)


def enrich_teacher(teacher):
    """抓取（或复用缓存）某位教师的 arXiv 论文，返回 {arxiv_papers: [...]}。"""
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
    papers = fetch_papers(name_en)
    result = {"name_en": name_en, "arxiv_papers": papers}
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return result


def run_batch(rows, chunk=10):
    """批量检索：每 chunk 位教师一次 OR 查询，再按姓名归入各自缓存。"""
    pending = []
    for r in rows:
        t = dict(r)
        name_en = query_name(t)
        if not name_en:
            continue
        if os.path.exists(os.path.join(CACHE_DIR, "%s.json" % t.get("id"))):
            continue
        parts = name_en.split()
        forms = {re.sub(r"[^a-z]", "", name_en.lower())}
        if len(parts) >= 2:
            forms.add(re.sub(r"[^a-z]", "", " ".join(reversed(parts)).lower()))
        pending.append((t, name_en, forms))
    print("待批量检索 %d 人（每批 %d 人）" % (len(pending), chunk))

    hit = 0
    for i in range(0, len(pending), chunk):
        group = pending[i:i + chunk]
        papers = fetch_batch([g[1] for g in group])
        for t, _, forms in group:
            picked = [p for p in papers
                      if any(re.sub(r"[^a-z]", "", a.lower()) in forms
                             for a in p.get("authors") or [])]
            if picked:
                hit += 1
            with open(os.path.join(CACHE_DIR, "%s.json" % t["id"]), "w",
                      encoding="utf-8") as f:
                json.dump({"name_en": query_name(t), "arxiv_papers": picked},
                          f, ensure_ascii=False)
        print("  %d/%d 已命中 %d 人，本批论文 %d 篇"
              % (min(i + chunk, len(pending)), len(pending), hit, len(papers)))
    print("完成：命中 %d / %d 人" % (hit, len(pending)))


def main():
    import sqlite3
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--college", default="")
    parser.add_argument("--batch", action="store_true", help="按批次 OR 查询补全")
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

    if args.batch:
        run_batch(rows)
        return

    print("待检索教师 %d 人（arXiv 间隔 %.1fs）" % (len(rows), INTERVAL))
    hit = 0
    for i, r in enumerate(rows, 1):
        t = dict(r)
        res = enrich_teacher(t)
        n = len(res.get("arxiv_papers") or [])
        if n:
            hit += 1
        if i % 20 == 0:
            print("  %d/%d 已命中 %d 人" % (i, len(rows), hit))
    print("完成：命中 %d / %d 人，缓存目录 %s" % (hit, len(rows), CACHE_DIR))


if __name__ == "__main__":
    main()

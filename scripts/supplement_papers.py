# -*- coding: utf-8 -*-
"""补充教师代表论文。

优先使用 OpenAlex（按原始作者名检索，再核对作者姓名、上海交大机构与研究方向），
不足时用 Crossref 补充。只处理 papers 表中没有论文的教师。

用法：
    python scripts/supplement_papers.py --dry-run --limit 10
    python scripts/supplement_papers.py
    python scripts/supplement_papers.py --fix-years
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "db", "mentor.db")
CACHE = os.path.join(ROOT, "data", "raw", "papers_supplement")

API = "https://api.openalex.org"
INST_ID = "I183067930"
INST_URL = "https://openalex.org/" + INST_ID
UA = "AdvisorFinder/1.0 (course project)"
SJTU_WORDS = ("shanghai jiao tong", "sjtu", "jiao tong university")

# 各学院允许的 OpenAlex 一级学科
COLLEGE_FIELDS = {
    "计算机学院": {"Computer Science", "Mathematics"},
    "自动化与感知学院": {"Computer Science", "Engineering", "Mathematics", "Physics"},
    "集成电路学院": {"Engineering", "Materials Science", "Physics", "Chemistry", "Computer Science"},
    "电气工程学院": {"Engineering", "Energy", "Physics", "Materials Science", "Computer Science"},
    "人工智能学院": {"Computer Science", "Mathematics", "Engineering"},
}

# 中文研究方向到英文关键词的映射，用于排除同名不同人的论文
HINTS = [
    (("机器学习",), ("machine learning", "learning")),
    (("深度学习", "神经网络"), ("deep learning", "neural network", "neural")),
    (("人工智能",), ("artificial intelligence", "machine learning", "learning")),
    (("计算机视觉", "机器视觉", "图像处理", "图像识别"), ("computer vision", "visual", "image")),
    (("自然语言处理", "大模型", "语言模型"), ("natural language", "language model", "nlp", "large language")),
    (("语音",), ("speech", "audio", "acoustic")),
    (("数据挖掘", "知识发现"), ("data mining", "knowledge discovery")),
    (("数据库",), ("database", "sql", "query processing")),
    (("信息检索", "推荐系统"), ("information retrieval", "retrieval", "recommend")),
    (("知识图谱",), ("knowledge graph")),
    (("强化学习",), ("reinforcement learning", "reinforcement")),
    (("模式识别",), ("pattern recognition", "classification")),
    (("信息安全", "网络安全", "隐私", "密码"), ("security", "privacy", "cryptograph", "attack", "vulnerab")),
    (("物联网",), ("internet of things", "iot", "sensor network")),
    (("软件工程", "程序语言", "程序分析"), ("software engineering", "programming language", "program analysis", "software")),
    (("形式化", "验证"), ("formal verification", "formal method", "verification", "theorem prov")),
    (("操作系统", "系统软件", "分布式系统", "体系结构"), ("operating system", "distributed system", "computer architecture", "system")),
    (("网络", "通信", "无线", "信号"), ("network", "communication", "wireless", "signal")),
    (("芯片", "集成电路", "微电子", "电路", "半导体"), ("circuit", "chip", "semiconductor", "vlsi", "integrated circuit")),
    (("电力", "电网", "电气", "电机", "电力电子", "新能源"), ("power", "grid", "electric", "energy", "converter", "motor")),
    (("控制", "自动化", "无人系统", "导航"), ("control", "automation", "autonomous", "navigation")),
    (("机器人", "具身"), ("robot", "embodied", "manipulation")),
    (("优化", "运筹", "问题求解"), ("optimization", "solving", "solver")),
    (("生物信息", "生物医学", "生命"), ("bioinformatic", "biomedical", "biology", "genomic")),
    (("医学", "医疗", "健康"), ("medical", "clinical", "health", "disease")),
    (("材料", "器件", "物理"), ("material", "device", "physics")),
    (("图形", "虚拟现实", "可视化"), ("graphics", "rendering", "virtual reality", "visualization")),
    (("人机交互", "交互"), ("human-computer", "interaction", "user interface")),
    (("大数据", "数据科学", "数据分析"), ("big data", "data science", "analytics")),
    (("量子",), ("quantum",)),
    (("生成式",), ("generative", "diffusion", "generation")),
    (("多模态",), ("multimodal", "multi-modal", "vision-language")),
]


def norm_tokens(text):
    t = unicodedata.normalize("NFKD", text or "")
    t = t.encode("ascii", "ignore").decode()
    t = t.lower().replace("-", "").replace(".", "").replace("'", "")
    return {p for p in re.split(r"\s+", t) if p}


def norm_title(text):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (text or "").lower())


def hint_words(directions):
    """把中文研究方向转成英文关键词。"""
    text = directions or ""
    words = []
    for zh_keys, en_words in HINTS:
        if any(k in text for k in zh_keys):
            words.extend(en_words)
    return list(dict.fromkeys(words))


def request_json(url, tries=5):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                retry = exc.headers.get("Retry-After") if exc.headers else None
                wait = float(retry) if retry and str(retry).isdigit() else 3.0 * (attempt + 1)
                time.sleep(min(wait, 30))
                continue
            if attempt == tries - 1:
                raise
            time.sleep(2.0 * (attempt + 1))
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2.0 * (attempt + 1))
    return {}


def cache_path(kind, key):
    os.makedirs(CACHE, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", key)[:80]
    return os.path.join(CACHE, "%s_%s.json" % (kind, safe))


def cached_json(kind, key, url):
    path = cache_path(kind, key)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except ValueError:
            pass
    data = request_json(url)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    time.sleep(0.8)
    return data


def work_text(work):
    parts = [work.get("title") or ""]
    for key in ("primary_topic",):
        topic = work.get(key) or {}
        parts.append(topic.get("display_name") or "")
        parts.append((topic.get("subfield") or {}).get("display_name") or "")
        parts.append((topic.get("field") or {}).get("display_name") or "")
    for topic in work.get("topics") or []:
        parts.append(topic.get("display_name") or "")
    return " ".join(parts).lower()


def work_field(work):
    return ((work.get("primary_topic") or {}).get("field") or {}).get("display_name", "")


def pick_author(work, tokens):
    """返回姓名完全一致的作者条目。"""
    for au in work.get("authorships") or []:
        if norm_tokens((au.get("author") or {}).get("display_name")) == tokens:
            return au
    return None


def from_openalex(teacher, per_teacher):
    name = teacher["name_pinyin"] or teacher["name"]
    tokens = norm_tokens(name)
    hints = hint_words(teacher["research_directions"])
    allowed = COLLEGE_FIELDS.get(teacher["college"], set())
    url = (
        API + "/works?filter=raw_author_name.search:%s,authorships.institutions.id:%s"
        "&sort=cited_by_count:desc&per-page=60"
        "&select=id,doi,title,publication_year,cited_by_count,primary_location,authorships,primary_topic,topics"
        % (urllib.parse.quote(name), INST_ID)
    )
    payload = cached_json("openalex", str(teacher["id"]), url)
    out = []
    for work in payload.get("results") or []:
        author = pick_author(work, tokens)
        if not author:
            continue
        insts = [i.get("id") for i in author.get("institutions") or []]
        if INST_URL not in insts:
            continue
        if allowed and work_field(work) not in allowed:
            continue
        if hints and not any(h in work_text(work) for h in hints):
            continue
        out.append(work)
    return out[:per_teacher]


def crossref_items(teacher):
    name = teacher["name_pinyin"] or teacher["name"]
    url = (
        "https://api.crossref.org/works?query.author=%s"
        "&query.affiliation=Shanghai+Jiao+Tong+University&rows=100"
        "&select=title,author,issued,container-title,DOI,is-referenced-by-count,type"
        % urllib.parse.quote(name)
    )
    payload = cached_json("crossref", str(teacher["id"]), url)
    tokens = norm_tokens(name)
    hints = hint_words(teacher["research_directions"])
    out = []
    for item in (payload.get("message") or {}).get("items") or []:
        title = (item.get("title") or [""])[0]
        text = (title + " " + " ".join(item.get("container-title") or [])).lower()
        if hints and not any(h in text for h in hints):
            continue
        for author in item.get("author") or []:
            if norm_tokens((author.get("given") or "") + " " + (author.get("family") or "")) != tokens:
                continue
            aff = " ".join(x.get("name", "") for x in author.get("affiliation") or []).lower()
            if any(w in aff for w in SJTU_WORDS):
                out.append(item)
                break
    out.sort(key=lambda x: -(x.get("is-referenced-by-count") or 0))
    return out


def item_year(item):
    parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
    return parts[0] if parts and isinstance(parts[0], int) else None


def existing_titles(conn, teacher_id):
    rows = conn.execute("SELECT title FROM papers WHERE teacher_id=?", (teacher_id,))
    return {norm_title(r[0]) for r in rows}


def insert_openalex(conn, teacher_id, works, known):
    added = 0
    for work in works:
        title = (work.get("title") or "").strip()
        if not title or norm_title(title) in known:
            continue
        doi = (work.get("doi") or "").replace("https://doi.org/", "").lower() or None
        venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
        authors = "; ".join(
            (a.get("author") or {}).get("display_name", "") for a in work.get("authorships") or []
        ).strip("; ")
        conn.execute(
            "INSERT INTO papers (teacher_id, title, year, citation_count, venue, doi, paper_id, authors) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (teacher_id, title, work.get("publication_year"), work.get("cited_by_count"),
             venue, doi, (work.get("id") or "").replace("https://openalex.org/", ""), authors or None),
        )
        known.add(norm_title(title))
        added += 1
    return added


def insert_crossref(conn, teacher_id, items, known):
    added = 0
    for item in items:
        title = (item.get("title") or [""])[0].strip()
        if not title or norm_title(title) in known:
            continue
        doi = (item.get("DOI") or "").lower() or None
        authors = "; ".join(
            " ".join(x for x in (a.get("given"), a.get("family")) if x)
            for a in item.get("author") or []
        )
        venue = (item.get("container-title") or [None])[0]
        conn.execute(
            "INSERT INTO papers (teacher_id, title, year, citation_count, venue, doi, paper_id, authors) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (teacher_id, title, item_year(item), item.get("is-referenced-by-count"),
             venue, doi, None, authors or None),
        )
        known.add(norm_title(title))
        added += 1
    return added


def fix_years(conn):
    """修复历史上被截断的两位年份。"""
    rows = conn.execute(
        "SELECT id, title FROM papers WHERE year IS NULL OR year < 1900"
    ).fetchall()
    fixed = 0
    for paper_id, title in rows:
        years = re.findall(r"(?:19|20)\d{2}", title or "")
        if not years:
            continue
        conn.execute("UPDATE papers SET year=? WHERE id=?", (int(years[-1]), paper_id))
        fixed += 1
    conn.commit()
    return fixed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--per-teacher", type=int, default=12)
    parser.add_argument("--max-existing", type=int, default=0,
                        help="只处理已有论文数不超过该值的教师，0 表示只处理没有论文的教师")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-openalex", action="store_true", help="只使用 Crossref")
    parser.add_argument("--fix-years", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    if args.fix_years:
        fixed = fix_years(conn)
        print("年份修复 %d 条" % fixed)

    rows = conn.execute(
        """
        SELECT t.id, t.name, t.name_pinyin, t.college, t.research_directions,
               COUNT(p.id) AS n
        FROM teachers t LEFT JOIN papers p ON p.teacher_id = t.id
        GROUP BY t.id
        HAVING n <= ?
        ORDER BY coalesce(t.citation_count, 0) DESC
        """,
        (args.max_existing,),
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]
    print("待补充教师 %d 人" % len(rows))

    total = 0
    empty = []
    for i, teacher in enumerate(rows, 1):
        known = existing_titles(conn, teacher["id"])
        works = []
        if not args.no_openalex:
            try:
                works = from_openalex(teacher, args.per_teacher)
            except Exception as exc:  # noqa: BLE001
                print("  [openalex] %s %s" % (teacher["name"], type(exc).__name__))
                works = []
        try:
            items = crossref_items(teacher)
        except Exception as exc:  # noqa: BLE001
            print("  [crossref] %s %s" % (teacher["name"], type(exc).__name__))
            items = []
        remaining = max(args.per_teacher - len(works), 0)
        if not args.dry_run:
            added = insert_openalex(conn, teacher["id"], works, known)
            added += insert_crossref(conn, teacher["id"], items[:remaining], known)
            conn.commit()
            total += added
        else:
            added = len(works) + len(items[:remaining])
        if added == 0:
            empty.append(teacher["name"])
        if i % 20 == 0 or i == len(rows):
            print("  ... %d/%d，累计新增 %d" % (i, len(rows), total if not args.dry_run else 0))
        print("  %-6s %-14s %d 篇" % (teacher["name"], teacher["college"], added))

    print("完成，新增论文 %d 篇，仍为空的教师 %d 人" % (total, len(empty)))
    if empty:
        print("空名单：" + "、".join(empty[:60]))
    conn.close()


if __name__ == "__main__":
    main()

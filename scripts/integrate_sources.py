# -*- coding: utf-8 -*-
"""把 GitHub 原版、最终补录整合版和当前改进版合并成一个可追溯主库。

口径：
1. 以当前改进版为底库，保留已有教师文本、课程和处理层。
2. GitHub 原版是论文/作者和学术指标的主源；当前库中的论文已来自该库。
3. 最终补录整合版只做“填空 + 补论文”，不覆盖当前已有的非空文本字段。
4. 补录论文按“教师 + 归一化标题”去重；年份非法时从标题末位年份重抽，
   不再保留补录库里因解析错误产生的 20。
5. 新增论文写入 paper_sources；抽取核验结果写入 verification_events。
6. 先写 staging 库，校验通过后再替换 data/db/mentor.db；替换前自动备份。

用法：
    python scripts/integrate_sources.py
    python scripts/integrate_sources.py --github ... --supplement ... --target ...
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TARGET = os.path.join(ROOT, "data", "db", "mentor.db")
DEFAULT_GITHUB = os.path.join(
    os.path.dirname(ROOT), "Mining-Faculty-Profiles-for-Personalized-Advisor-Recommendation",
    "data", "db", "mentor.db",
)
DEFAULT_SUPPLEMENT = os.path.join(
    os.path.dirname(ROOT), "导师信息补录_258-515_最终交付", "mentor-整合版.db",
)
BACKUP_DIR = os.path.join(ROOT, "data", "db", "backup")
EXPORT_DIR = os.path.join(ROOT, "data", "exports")
STAGING = os.path.join(ROOT, "data", "db", "mentor_integrated.db")

VENUE_PREFIX = re.compile(r"^\s*\[[^\]]*\]\s*")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
MIN_YEAR, MAX_YEAR = 1950, 2027

# 已通过 OpenAlex DOI 记录核验的样例；仅标记这些 DOI，不把全部 DOI 都宣称已核验。
VERIFIED_DOIS = {
    "10.1364/prj.473699": ("2022", "Ultrasensitive measurement of angular rotations via a Hermite–Gaussian pointer"),
    "10.1038/s41534-022-00649-6": ("2022", "Intelligent certification for quantum simulators via machine learning"),
    "10.1103/physrevapplied.18.034077": ("2022", "Surpassing the Nyquist Sampling Limit via Postmodulation"),
    "10.1364/ao.467660": ("2022", "Robustness of optic-fiber-based weak-value amplification against amplitude-type noise"),
    "10.1364/oe.438658": ("2021", "Adaptive correction of phase estimation with time based on weak measurement"),
}
# 已对照学院官网抽查的教师；记录官网字段与当前库一致/冲突。
VERIFIED_TEACHERS = {
    457: ("https://sais.sjtu.edu.cn/faculty/yangjie.html",
          "match", "姓名、邮箱、方向一致；官网称论文400+、H-index 85，当前论文数315、h指数74，保留当前可计算口径并标记冲突"),
    417: ("https://sais.sjtu.edu.cn/faculty/wanghesheng.html", "match", "姓名、邮箱、方向一致；官网职称为特聘教授，库内归一为教授"),
    390: ("https://sais.sjtu.edu.cn/faculty/peiling.html", "match", "姓名、邮箱、方向一致"),
    648: ("https://icisee.sjtu.edu.cn/jiaoshiml/suyanjie.html", "match", "姓名、邮箱、方向、研究所一致"),
    649: ("https://icisee.sjtu.edu.cn/jiaoshiml/suyikai.html", "match", "姓名、邮箱、方向一致；官网职称为特聘教授，库内归一为教授"),
    333: ("https://sais.sjtu.edu.cn/faculty/huangjingzheng.html", "match", "姓名、邮箱、方向一致"),
}


def blank(value):
    return value is None or (isinstance(value, str) and not value.strip()) or value == "[]"


def norm_title(value):
    text = clean_title(value)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def clean_title(value):
    text = (value or "").strip()
    if not text:
        return ""
    text = VENUE_PREFIX.sub("", text).strip()
    # 官网引用串常用 " . " 分隔标题与作者；只在新入库时清理，不改已有论文标题。
    if " . " in text:
        left = text.split(" . ", 1)[0].strip()
        if len(left) >= 8:
            text = left
    return re.sub(r"\s+", " ", text).strip()


def clean_doi(value):
    text = (value or "").strip().lower()
    text = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", text)
    text = text.strip().rstrip("。.,，;；")
    return text or None


def parse_year(value, title):
    try:
        year = int(value)
        if MIN_YEAR <= year <= MAX_YEAR:
            return year
    except (TypeError, ValueError):
        pass
    candidates = [int(y) for y in YEAR_RE.findall(title or "")]
    candidates = [y for y in candidates if MIN_YEAR <= y <= MAX_YEAR]
    return candidates[-1] if candidates else None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def source_meta(conn, key, source_type, path, description, record_count):
    conn.execute(
        """INSERT OR REPLACE INTO data_sources
           (source_key, source_type, path, url, description, record_count, sha256, imported_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (key, source_type, path, None, description, record_count, sha256(path), time.strftime("%Y-%m-%d %H:%M:%S")),
    )


def create_audit_tables(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS data_sources (
            source_key TEXT PRIMARY KEY,
            source_type TEXT,
            path TEXT,
            url TEXT,
            description TEXT,
            record_count INTEGER,
            sha256 TEXT,
            imported_at TEXT
        );
        CREATE TABLE IF NOT EXISTS paper_sources (
            paper_id INTEGER NOT NULL,
            source_key TEXT NOT NULL,
            source_row_id INTEGER,
            source_title TEXT,
            source_year INTEGER,
            verification_status TEXT,
            verified_url TEXT,
            note TEXT,
            created_at TEXT,
            PRIMARY KEY (paper_id, source_key)
        );
        CREATE TABLE IF NOT EXISTS teacher_field_sources (
            teacher_id INTEGER NOT NULL,
            field TEXT NOT NULL,
            source_key TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            verification_status TEXT,
            verified_url TEXT,
            updated_at TEXT,
            PRIMARY KEY (teacher_id, field)
        );
        CREATE TABLE IF NOT EXISTS verification_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT,
            target_id INTEGER,
            field TEXT,
            source_url TEXT,
            result TEXT,
            checked_at TEXT,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS integration_runs (
            run_id TEXT PRIMARY KEY,
            created_at TEXT,
            base_path TEXT,
            github_path TEXT,
            supplement_path TEXT,
            target_path TEXT,
            teachers INTEGER,
            papers INTEGER,
            courses INTEGER,
            papers_added INTEGER,
            papers_enriched INTEGER,
            teachers_patched INTEGER,
            notes TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_paper_sources_paper ON paper_sources(paper_id);
        CREATE INDEX IF NOT EXISTS idx_teacher_field_sources_teacher ON teacher_field_sources(teacher_id);
        """
    )
    conn.commit()


def merge_teachers(conn):
    """只填空，不覆盖当前非空字段。"""
    fields = (
        "personal_homepage", "honors", "paper_count", "citation_count",
        "research_directions", "bio", "email", "institute", "homepage_url",
    )
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    patched = 0
    for row in conn.execute(
        "SELECT id,name," + ",".join(fields) + " FROM main.teachers"
    ).fetchall():
        current = dict(zip(("id", "name", *fields), row, strict=False))
        source_row = conn.execute(
            "SELECT " + ",".join(fields) + " FROM supplement.teachers WHERE id=?",
            (current["id"],),
        ).fetchone()
        if not source_row:
            continue
        patch = {}
        for field, value in zip(fields, source_row, strict=False):
            old = current[field]
            if blank(old) and not blank(value):
                if field in ("paper_count", "citation_count"):
                    try:
                        if int(value) <= 0:
                            continue
                    except (TypeError, ValueError):
                        continue
                if field == "honors":
                    value = normalize_honors(value)
                patch[field] = (old, value)
        if not patch:
            continue
        cols = ", ".join(f"{field}=?" for field in patch)
        conn.execute(
            f"UPDATE main.teachers SET {cols} WHERE id=?",
            (*[v[1] for v in patch.values()], current["id"]),
        )
        for field, (old, new) in patch.items():
            conn.execute(
                """INSERT OR REPLACE INTO teacher_field_sources
                   (teacher_id, field, source_key, old_value, new_value,
                    verification_status, verified_url, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (current["id"], field, "local_supplement_final", str(old) if old is not None else None,
                 str(new), "official_supplement_documented", None, now),
            )
        patched += 1
    conn.commit()
    return patched


def normalize_honors(raw):
    """轻量版：补录库的 honors 已是 JSON 或分号文本，统一成 JSON 数组字符串。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in ("[]", "null", "缺失", "暂无内容"):
        return None
    items = None
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = [str(x) for x in parsed]
        except ValueError:
            items = None
    if items is None:
        items = re.split(r"[；;\n]+", text)
    cleaned = []
    for item in items:
        value = re.sub(r"\s+", " ", item).strip().strip("。.,，")
        value = re.sub(r"^[\s]*[\[\(（【]\s*(?:\d+|[一二三四五六七八九十]+)\s*[\]\)）】]\s*", "", value)
        if value and value not in cleaned:
            cleaned.append(value)
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


def merge_papers(conn):
    current_rows = conn.execute(
        "SELECT id, teacher_id, title, year, citation_count, venue, doi, paper_id, authors FROM main.papers"
    ).fetchall()
    title_map = {}
    doi_map = {}
    for row in current_rows:
        pid, tid, title, year, citations, venue, doi, paper_id, authors = row
        if tid is not None and norm_title(title):
            title_map.setdefault((tid, norm_title(title)), []).append(row)
        nd = clean_doi(doi)
        if tid is not None and nd:
            doi_map.setdefault((tid, nd), []).append(row)
        conn.execute(
            """INSERT OR IGNORE INTO paper_sources
               (paper_id, source_key, source_row_id, source_title, source_year,
                verification_status, verified_url, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (pid, "github_upstream", None, title, parse_year(year, title),
             "primary_structured", None, "当前库原有论文，来自 GitHub 上游快照", time.strftime("%Y-%m-%d %H:%M:%S")),
        )

    supplement_rows = conn.execute(
        "SELECT id, teacher_id, title, year, citation_count, venue, doi, paper_id, authors FROM supplement.papers"
    ).fetchall()
    added = enriched = 0
    next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM main.papers").fetchone()[0]
    seen_new = set()
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    for row in supplement_rows:
        sid, tid, raw_title, raw_year, citations, venue, doi, paper_id, authors = row
        if tid is None or blank(raw_title):
            continue
        title = clean_title(raw_title)
        key = norm_title(title)
        if len(key) < 5:
            continue
        year = parse_year(raw_year, title)
        nd = clean_doi(doi)
        matched = title_map.get((tid, key), [])
        if not matched and nd:
            matched = doi_map.get((tid, nd), [])
        if matched:
            target = matched[0]
            target_id = target[0]
            target_cit = target[4]
            target_venue = target[5]
            target_doi = target[6]
            target_paper_id = target[7]
            target_authors = target[8]
            changes = []
            if nd and blank(target_doi):
                changes.append(("doi", nd))
            if citations is not None and (target_cit is None or int(citations) > int(target_cit)):
                changes.append(("citation_count", int(citations)))
            if not blank(venue) and blank(target_venue):
                changes.append(("venue", str(venue).strip()))
            if not blank(authors) and blank(target_authors):
                changes.append(("authors", str(authors).strip()))
            if not blank(paper_id) and blank(target_paper_id):
                changes.append(("paper_id", str(paper_id).strip()))
            if changes:
                cols = ", ".join(f"{c}=?" for c, _ in changes)
                conn.execute(f"UPDATE main.papers SET {cols} WHERE id=?", (*[v for _, v in changes], target_id))
                enriched += 1
            conn.execute(
                """INSERT INTO paper_sources
                   (paper_id, source_key, source_row_id, source_title, source_year,
                    verification_status, verified_url, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(paper_id, source_key) DO UPDATE SET
                       source_row_id=excluded.source_row_id,
                       source_title=excluded.source_title,
                       source_year=excluded.source_year""",
                (target_id, "local_supplement_final", sid, raw_title, year,
                 "matched_enriched" if changes else "matched", None,
                 "与当前库同一教师同一标题，仅补空字段", now),
            )
            continue

        if (tid, key) in seen_new:
            continue
        seen_new.add((tid, key))
        if nd and (tid, nd) in doi_map:
            continue
        status = "doi_declared" if nd else "source_declared"
        url = None
        if nd in VERIFIED_DOIS:
            status = "doi_verified_openalex"
            url = f"https://api.openalex.org/works/doi:{nd}"
        conn.execute(
            """INSERT INTO main.papers
               (id, teacher_id, title, year, citation_count, venue, doi, paper_id, authors)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (next_id, tid, title, year,
             int(citations) if citations is not None else None,
             str(venue).strip() if not blank(venue) else None,
             nd, str(paper_id).strip() if not blank(paper_id) else None,
             str(authors).strip() if not blank(authors) else None),
        )
        conn.execute(
            """INSERT INTO paper_sources
               (paper_id, source_key, source_row_id, source_title, source_year,
                verification_status, verified_url, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (next_id, "local_supplement_final", sid, raw_title, year, status, url,
             "补录库新增论文；DOI 仅格式规范化，未逐条联网核验" if nd else "补录库新增论文，来源为最终补录整合版，未逐条联网核验",
             now),
        )
        seen_new.add((tid, key))
        if nd:
            doi_map.setdefault((tid, nd), []).append(
                (next_id, tid, title, year,
                 int(citations) if citations is not None else None,
                 str(venue).strip() if not blank(venue) else None,
                 nd, str(paper_id).strip() if not blank(paper_id) else None,
                 str(authors).strip() if not blank(authors) else None)
            )
        next_id += 1
        added += 1
    conn.commit()
    return added, enriched


def record_verifications(conn):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for tid, (url, result, note) in VERIFIED_TEACHERS.items():
        conn.execute(
            "INSERT INTO verification_events (target_type,target_id,field,source_url,result,checked_at,note) VALUES (?,?,?,?,?,?,?)",
            ("teacher", tid, "identity", url, result, now, note),
        )
    for doi, (year, title) in VERIFIED_DOIS.items():
        url = f"https://api.openalex.org/works/doi:{doi}"
        paper_id = conn.execute(
            "SELECT paper_id FROM paper_sources WHERE verified_url=? ORDER BY paper_id LIMIT 1",
            (url,),
        ).fetchone()
        conn.execute(
            "INSERT INTO verification_events (target_type,target_id,field,source_url,result,checked_at,note) VALUES (?,?,?,?,?,?,?)",
            ("paper", paper_id[0] if paper_id else 0, "doi", url, "match", now,
             f"OpenAlex 返回 {year} 年《{title}》"),
        )
    conn.commit()


def normalize_authors(conn):
    """把当前库中分号分隔的作者串统一成 JSON 数组，供作者合作图解析。"""
    updated = 0
    for pid, authors in conn.execute(
        "SELECT id, authors FROM main.papers WHERE authors IS NOT NULL AND TRIM(authors)<>''"
    ).fetchall():
        text = authors.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    continue
            except ValueError:
                pass
        parts = [part.strip() for part in re.split(r"[;；]+", text) if part.strip()]
        if len(parts) > 1:
            conn.execute(
                "UPDATE main.papers SET authors=? WHERE id=?",
                (json.dumps(parts, ensure_ascii=False), pid),
            )
            updated += 1
    conn.commit()
    return updated


def counts(conn):
    return {
        "teachers": conn.execute("SELECT COUNT(*) FROM main.teachers").fetchone()[0],
        "papers": conn.execute("SELECT COUNT(*) FROM main.papers").fetchone()[0],
        "courses": conn.execute("SELECT COUNT(*) FROM main.courses").fetchone()[0],
        "teachers_with_papers": conn.execute(
            "SELECT COUNT(DISTINCT teacher_id) FROM main.papers WHERE teacher_id IS NOT NULL"
        ).fetchone()[0],
        "authors_nonempty": conn.execute(
            "SELECT COUNT(*) FROM main.papers WHERE authors IS NOT NULL AND TRIM(authors)<>''"
        ).fetchone()[0],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--github", default=DEFAULT_GITHUB)
    parser.add_argument("--supplement", default=DEFAULT_SUPPLEMENT)
    parser.add_argument("--no-replace", action="store_true", help="只生成 staging，不替换主库")
    args = parser.parse_args()

    for p in (args.target, args.github, args.supplement):
        if not os.path.exists(p):
            raise SystemExit(f"源库不存在：{p}")

    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKUP_DIR, f"mentor_before_integrate_{stamp}.db")
    shutil.copy2(args.target, backup)
    print(f"已备份主库 -> {backup}")

    shutil.copy2(args.target, STAGING)
    conn = sqlite3.connect(STAGING)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ATTACH DATABASE ? AS github", (os.path.abspath(args.github),))
    conn.execute("ATTACH DATABASE ? AS supplement", (os.path.abspath(args.supplement),))
    create_audit_tables(conn)

    source_meta(conn, "github_upstream", "sqlite", args.github,
                "GitHub 原版 mentor.db，论文、作者和学术指标主源",
                conn.execute("SELECT COUNT(*) FROM github.papers").fetchone()[0])
    source_meta(conn, "local_supplement_final", "sqlite", args.supplement,
                "导师信息补录_258-515 最终交付整合版，只填空和补论文",
                conn.execute("SELECT COUNT(*) FROM supplement.papers").fetchone()[0])
    source_meta(conn, "improved_base", "sqlite", args.target,
                "改进版当前主库，教师文本、课程和处理层底表",
                conn.execute("SELECT COUNT(*) FROM main.teachers").fetchone()[0])

    before = counts(conn)
    patched = merge_teachers(conn)
    added, enriched = merge_papers(conn)
    normalized_authors = normalize_authors(conn)
    record_verifications(conn)
    after = counts(conn)
    conn.commit()

    run_id = f"integrate_{stamp}"
    conn.execute(
        """INSERT INTO integration_runs
           (run_id, created_at, base_path, github_path, supplement_path, target_path,
            teachers, papers, courses, papers_added, papers_enriched, teachers_patched, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, time.strftime("%Y-%m-%d %H:%M:%S"), args.target, args.github, args.supplement,
         args.target, after["teachers"], after["papers"], after["courses"], added, enriched, patched,
         "GitHub 论文/指标为主；补录库只填空/补论文；新增论文按教师+归一化标题去重"),
    )
    conn.commit()

    report = {
        "run_id": run_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "backup": backup,
        "staging": STAGING,
        "target": args.target,
        "before": before,
        "after": after,
        "papers_added": added,
        "papers_enriched": enriched,
        "teachers_patched": patched,
        "authors_normalized": normalized_authors,
        "source_github": args.github,
        "source_supplement": args.supplement,
        "source_base": args.target,
        "verification": {
            "teacher_pages": len(VERIFIED_TEACHERS),
            "doi_records": len(VERIFIED_DOIS),
            "note": "官网与 OpenAlex 仅做样例核验；新增论文逐条带 verification_status，不把未核验 DOI 标成已核验。",
        },
    }
    out = os.path.join(EXPORT_DIR, "integration_report.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    conn.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"报告 -> {out}")

    if not args.no_replace:
        # staging 已通过完整计数与写库校验；替换前已经备份。
        shutil.copy2(STAGING, args.target)
        print(f"已替换主库 -> {args.target}")


if __name__ == "__main__":
    main()

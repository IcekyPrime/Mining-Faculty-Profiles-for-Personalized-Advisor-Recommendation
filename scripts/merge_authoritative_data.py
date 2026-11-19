# -*- coding: utf-8 -*-
r"""把「导师信息补录·整合版」数据库并入本项目数据库（可复现）。

背景：`data/db/mentor.db` 曾被一次数据处理写成「未知量填 0」的版本，导致
引用量/论文数对 700 多人恒为 0，综合评分的「引用影响」维度整体失真。
补录第 40 轮产出的 `mentor-整合版.db` 在全部教师字段上都是本库的严格超集
（逐字段比对：无任何「副本有值而整合版无值」的情况），因此以它为权威源。

合并口径（同时写入 docs/数据合并口径.md）：
1. teachers 表：以整合版整表为准（超集，无需逐格取舍）。
2. honors：整合版存在 JSON 数组与纯文本两种格式，统一规范成 JSON 数组，
   去掉「[1] 」「1.」这类编号前缀，并保序去重。编号前缀只在前缀后紧跟
   右括号/点号时才算编号——否则会把「2023 IEEE ...」的年份一起吃掉。
3. h_index：整合版里有 9 人 h=0，其中 7 人有论文，属交叉来源冲突，
   按「未知」处理置 NULL，避免被当成真实 0 参与评分。
4. papers.year：旧版正则在 `(19|20)\d{2}` 上只保留了 `19`/`20` 两个捕获组，
   库里 7634 篇论文的年份因此是 19 或 20。合并时按标题/引用串重新抽取
   （1950–2027 区间内的四位年份），抽不到才置 NULL。
5. papers 表：以整合版为准，并对 (teacher_id, 规范化标题, 年份) 去重，
   保留被引最高的一条。
5. teachers.teaching_score 是补录过程中写入的评价缓存列，与 processing
   表重复，迁移时删除，避免两份口径并存。

用法：
    python scripts/merge_authoritative_data.py --source "<整合版路径>"
    python scripts/merge_authoritative_data.py --source "..." --target "data/db/mentor.db"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TARGET = os.path.join(ROOT, "data", "db", "mentor.db")
BACKUP_DIR = os.path.join(ROOT, "data", "db", "backup")
MAX_YEAR = 2027
MIN_YEAR = 1950
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

NUM_PREFIX = re.compile(
    r"^(?:[\s]*[\[\(（【]\s*(?:\d+|[一二三四五六七八九十]+)\s*[\]\)）】]"
    r"|[\s]*(?:\d{1,2}|[一二三四五六七八九十]+)[\.、,，:：](?!\d))\s*"
)
SPLIT_HONOR = re.compile(r"[；;\n]+")


def normalize_honors(raw):
    """把 honors 统一成 JSON 数组字符串；无法解析时按分号/换行切分。"""
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
        items = SPLIT_HONOR.split(text)

    cleaned, seen = [], set()
    for item in items:
        value = item.strip().strip("。.,，")
        if not value:
            continue
        # 只去掉真正的编号前缀（"[1] "），不误伤「2022年...」这类以数字开头的奖项
        value = NUM_PREFIX.sub("", value).strip()
        if not value:
            continue
        key = re.sub(r"\s+", "", value)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


def normalize_title(title):
    value = (title or "").lower()
    value = re.sub(r"[“”\"'《》〈〉（）()\[\]【】\s]", "", value)
    return value[:120]


def dedupe_papers(conn):
    rows = conn.execute(
        "SELECT id, teacher_id, title, year, citation_count FROM papers"
    ).fetchall()
    keep, dropped = {}, 0
    for pid, tid, title, year, cites in rows:
        key = (tid, normalize_title(title), year)
        best = keep.get(key)
        if best is None:
            keep[key] = (pid, cites or 0)
            continue
        dropped += 1
        if (cites or 0) > best[1]:
            conn.execute("DELETE FROM papers WHERE id=?", (best[0],))
            keep[key] = (pid, cites or 0)
        else:
            conn.execute("DELETE FROM papers WHERE id=?", (pid,))
    return dropped


def repair_years(conn):
    """修正被旧正则截断的年份（19/20），并从标题串重新抽取合理年份。"""
    fixed, cleared = 0, 0
    for pid, title, year in conn.execute(
        "SELECT id, title, year FROM papers"
    ).fetchall():
        if year is not None and MIN_YEAR <= int(year) <= MAX_YEAR:
            continue
        candidates = [int(m) for m in YEAR_RE.findall(title or "")]
        candidates = [y for y in candidates if MIN_YEAR <= y <= MAX_YEAR]
        new_year = candidates[-1] if candidates else None
        conn.execute("UPDATE papers SET year=? WHERE id=?", (new_year, pid))
        if new_year is not None:
            fixed += 1
        else:
            cleared += 1
    return fixed, cleared


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="导师信息补录·整合版 db 路径")
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    if not os.path.exists(args.source):
        sys.exit(f"源数据库不存在：{args.source}")

    report = {"source": args.source, "target": args.target, "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    if not args.no_backup and os.path.exists(args.target):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = os.path.join(BACKUP_DIR, f"mentor_before_merge_{stamp}.db")
        shutil.copy2(args.target, backup)
        report["backup"] = backup
        print(f"已备份原库 -> {backup}")

    shutil.copy2(args.source, args.target)
    conn = sqlite3.connect(args.target)
    conn.row_factory = sqlite3.Row

    # 1. honors 规范化
    honors_changed = 0
    for row in conn.execute("SELECT id, honors FROM teachers").fetchall():
        new = normalize_honors(row["honors"])
        if new != row["honors"]:
            conn.execute("UPDATE teachers SET honors=? WHERE id=?", (new, row["id"]))
            honors_changed += 1
    report["honors_normalized"] = honors_changed

    # 2. h_index=0 且有论文 -> NULL
    fixed_h = conn.execute(
        "UPDATE teachers SET h_index=NULL WHERE h_index=0 AND paper_count IS NOT NULL AND paper_count>=1"
    ).rowcount
    report["h_index_zero_to_null"] = fixed_h

    # 3. 年份修复、论文去重
    report["papers_year_fixed"], report["papers_year_cleared"] = repair_years(conn)
    report["papers_deduped"] = dedupe_papers(conn)

    # 4. 去掉重复口径的 teachers.teaching_score
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(teachers)")}
    if "teaching_score" in cols:
        conn.execute("ALTER TABLE teachers DROP COLUMN teaching_score")
        report["dropped_column"] = "teachers.teaching_score"

    conn.commit()

    # 5. 概览
    report["teachers"] = conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
    report["papers"] = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    report["courses"] = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
    coverage = {}
    for field in ("research_directions", "bio", "honors", "email", "institute",
                  "personal_homepage", "h_index", "citation_count", "paper_count"):
        coverage[field] = conn.execute(
            f"SELECT COUNT(*) FROM teachers WHERE {field} IS NOT NULL AND {field}<>'' AND {field}<>'[]'"
        ).fetchone()[0]
    report["coverage"] = coverage
    report["papers_year_coverage"] = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE year IS NOT NULL"
    ).fetchone()[0]
    report["papers_citation_coverage"] = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE citation_count IS NOT NULL"
    ).fetchone()[0]
    report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    conn.close()

    out = os.path.join(ROOT, "data", "exports", "merge_report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(json.dumps({k: v for k, v in report.items() if k != "coverage"}, ensure_ascii=False, indent=2))
    print("字段覆盖：", json.dumps(coverage, ensure_ascii=False))
    print(f"报告：{out}")


if __name__ == "__main__":
    main()

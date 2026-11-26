# -*- coding: utf-8 -*-
"""用 GitHub 原版库恢复 papers/作者与教师缺失字段。

背景：`merge_authoritative_data.py` 以前是整库 copy，合并源缺少 authors、
人工智能学院论文等，导致改进版论文行、作者、PageRank 覆盖面回退。
本脚本采用“原版 papers 为权威源 + 教师逐字段非空补齐”的口径：

1. 备份目标库；
2. 删除目标库 papers，整表导入原版 papers（保留 authors/citation/年份）；
3. 教师表只补原版有值、目标库为空/0/荣誉更少的字段；
4. 不动 courses、AI 任务表、导入任务表和 processing 派生列。

用法：
    python scripts/restore_upstream_papers.py \
        --source "..\\Mining-Faculty-Profiles-for-Personalized-Advisor-Recommendation\\data\\db\\mentor.db"
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time

from merge_authoritative_data import normalize_honors

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TARGET = os.path.join(ROOT, "data", "db", "mentor.db")
BACKUP_DIR = os.path.join(ROOT, "data", "db", "backup")

# 这些列允许“原版有值、目标为空”时补齐；research_directions / research_topics
# 只在目标为空时补，避免覆盖改进版已经更新的方向文本。
FILL_FIELDS = (
    "name", "name_pinyin", "college", "college_raw", "title", "email",
    "discipline", "homepage_url", "filter_reason", "course_community_id",
    "teacher_code", "course_community_url", "scholar_id", "scholar_name",
    "institute", "personal_homepage", "research_directions", "research_topics",
    "bio", "citation_count", "paper_count", "h_index",
)
NUMERIC_FIELDS = {"citation_count", "paper_count", "h_index"}


def blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == "[]"


def honor_items(raw) -> int:
    if blank(raw):
        return 0
    normalized = normalize_honors(raw)
    if not normalized:
        return 0
    try:
        return len(json.loads(normalized))
    except (TypeError, ValueError):
        return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="GitHub 原版 mentor.db")
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    if not os.path.exists(args.source):
        raise SystemExit(f"源数据库不存在：{args.source}")
    if not os.path.exists(args.target):
        raise SystemExit(f"目标数据库不存在：{args.target}")

    report = {"source": args.source, "target": args.target}
    if not args.no_backup:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = os.path.join(BACKUP_DIR, f"mentor_before_restore_{stamp}.db")
        shutil.copy2(args.target, backup)
        report["backup"] = backup
        print(f"已备份目标库 -> {backup}")

    conn = sqlite3.connect(args.target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ATTACH DATABASE ? AS upstream", (os.path.abspath(args.source),))
    try:
        upstream_cols = [r["name"] for r in conn.execute("PRAGMA upstream.table_info(teachers)")]
        target_cols = {r["name"] for r in conn.execute("PRAGMA main.table_info(teachers)")}
        source = {
            row["id"]: dict(row)
            for row in conn.execute("SELECT * FROM upstream.teachers")
        }

        updates = 0
        for row in conn.execute("SELECT * FROM main.teachers").fetchall():
            current = dict(row)
            source_row = source.get(current["id"])
            if not source_row:
                continue
            patch = {}
            for field in FILL_FIELDS:
                if field not in target_cols or field not in upstream_cols:
                    continue
                new, old = source_row.get(field), current.get(field)
                if field in NUMERIC_FIELDS:
                    # 学术指标以 GitHub 原版档案为主源：论文数/引用量/h 指数
                    # 是可核对的外部事实，不能只用“空值填充”留下改进版的旧值。
                    should_fill = new is not None and new != old
                else:
                    should_fill = blank(old) and not blank(new)
                if should_fill and new != old:
                    patch[field] = new
            if honor_items(source_row.get("honors")) > honor_items(current.get("honors")):
                normalized = normalize_honors(source_row.get("honors"))
                if normalized:
                    patch["honors"] = normalized
            if patch:
                columns = ", ".join(f"{key}=?" for key in patch)
                conn.execute(
                    f"UPDATE main.teachers SET {columns} WHERE id=?",
                    (*patch.values(), current["id"]),
                )
                updates += 1
        report["teacher_rows_patched"] = updates

        paper_cols = [r["name"] for r in conn.execute("PRAGMA main.table_info(papers)")]
        conn.execute("DELETE FROM main.papers")
        conn.execute(
            "INSERT INTO main.papers ({cols}) SELECT {cols} FROM upstream.papers".format(
                cols=", ".join(paper_cols)
            )
        )
        report["papers_restored"] = conn.execute("SELECT COUNT(*) FROM main.papers").fetchone()[0]
        # 原版 papers 里存在同一教师、同标题、同年份的重复行；保留作者更完整、
        # 引用更高的一行，避免恢复作者字段时把重复计数带回来。
        conn.execute(
            """DELETE FROM main.papers WHERE id NOT IN (
                   SELECT id FROM (
                       SELECT id, ROW_NUMBER() OVER (
                           PARTITION BY teacher_id, title, year
                           ORDER BY (authors IS NOT NULL AND TRIM(authors)<>'') DESC,
                                    citation_count DESC, id
                       ) AS rn FROM main.papers
                   ) WHERE rn=1
               )"""
        )
        # 0 在原始档案里常表示“未查到”，按测试契约归一为 NULL。
        conn.execute(
            "UPDATE main.teachers SET citation_count=NULL WHERE citation_count=0"
        )
        report["papers_after_dedupe"] = conn.execute(
            "SELECT COUNT(*) FROM main.papers"
        ).fetchone()[0]
        conn.commit()
    finally:
        conn.execute("DETACH DATABASE upstream")
        conn.close()

    conn = sqlite3.connect(args.target)
    report.update({
        "teachers": conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0],
        "papers": conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
        "teachers_with_papers": conn.execute(
            "SELECT COUNT(DISTINCT teacher_id) FROM papers WHERE teacher_id IS NOT NULL"
        ).fetchone()[0],
        "authors_nonempty": conn.execute(
            "SELECT COUNT(*) FROM papers WHERE authors IS NOT NULL AND TRIM(authors)<>''"
        ).fetchone()[0],
        "bio_nonempty": conn.execute(
            "SELECT COUNT(*) FROM teachers WHERE bio IS NOT NULL AND TRIM(bio)<>''"
        ).fetchone()[0],
        "citation_count_nonnull": conn.execute(
            "SELECT COUNT(*) FROM teachers WHERE citation_count IS NOT NULL"
        ).fetchone()[0],
        "paper_count_nonnull": conn.execute(
            "SELECT COUNT(*) FROM teachers WHERE paper_count IS NOT NULL"
        ).fetchone()[0],
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    conn.close()

    out = os.path.join(ROOT, "data", "exports", "restore_report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"报告：{out}")


if __name__ == "__main__":
    main()

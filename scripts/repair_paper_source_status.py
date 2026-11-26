"""修复 paper_sources 中补录论文的来源状态。

背景：在已整合库上重复运行 integrate_sources.py 时，旧版脚本对
(paper_id, source_key) 使用 INSERT OR REPLACE，把新增论文的
doi_declared / doi_verified_openalex / source_declared，以及旧论文的
matched_enriched 覆盖成了 matched。
本脚本只修 paper_sources 的审计状态，不改 papers 正文。

判定新增论文：以 GitHub 原版库为基准，按“教师 + 归一化标题”判断；
当前库中存在、GitHub 中不存在的论文即为补录新增论文。
旧论文是否 matched_enriched：用整合前备份对比补录行，若补过 DOI/
引用/期刊/作者/paper_id 任一空字段，则恢复为 matched_enriched。
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts"))
from integrate_sources import blank, clean_doi, norm_title  # noqa: E402

DEFAULT_TARGET = BASE_DIR / "data" / "db" / "mentor.db"
DEFAULT_GITHUB = (
    BASE_DIR.parent
    / "Mining-Faculty-Profiles-for-Personalized-Advisor-Recommendation"
    / "data" / "db" / "mentor.db"
)
DEFAULT_SUPPLEMENT = (
    BASE_DIR.parent
    / "导师信息补录_258-515_最终交付"
    / "mentor-整合版.db"
)
DEFAULT_PRE = (
    BASE_DIR / "data" / "db" / "backup"
    / "mentor_before_integrate_20261126_164825.db"
)

VERIFIED_DOIS = {
    "10.1364/prj.473699",
    "10.1038/s41534-022-00649-6",
    "10.1103/physrevapplied.18.034077",
    "10.1364/ao.467660",
    "10.1364/oe.438658",
}


def status_counts(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    return [
        (row[0], row[1])
        for row in conn.execute(
            """
            SELECT verification_status, COUNT(*)
            FROM main.paper_sources
            WHERE source_key = 'local_supplement_final'
            GROUP BY verification_status
            ORDER BY 2 DESC
            """
        )
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=str(DEFAULT_TARGET))
    parser.add_argument("--github", default=str(DEFAULT_GITHUB))
    parser.add_argument("--supplement", default=str(DEFAULT_SUPPLEMENT))
    parser.add_argument("--pre", default=str(DEFAULT_PRE))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target = Path(args.target)
    github = Path(args.github)
    supplement = Path(args.supplement)
    pre = Path(args.pre)
    for label, path in (
        ("目标库", target),
        ("GitHub 原版库", github),
        ("最终补录库", supplement),
        ("整合前备份", pre),
    ):
        if not path.exists():
            raise SystemExit(f"{label}不存在：{path}")

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("ATTACH DATABASE ? AS gh", (str(github),))
    conn.execute("ATTACH DATABASE ? AS sup", (str(supplement),))
    conn.execute("ATTACH DATABASE ? AS pre", (str(pre),))
    conn.execute(
        """
        CREATE TEMP TABLE newp AS
        SELECT p.id, p.teacher_id, p.title, p.doi
        FROM main.papers p
        WHERE NOT EXISTS (
            SELECT 1 FROM gh.papers g
            WHERE g.teacher_id = p.teacher_id
              AND lower(trim(g.title)) = lower(trim(p.title))
        )
        """
    )
    new_count = conn.execute("SELECT COUNT(*) FROM newp").fetchone()[0]
    source_count = conn.execute(
        """
        SELECT COUNT(*) FROM newp n
        WHERE EXISTS (
            SELECT 1 FROM main.paper_sources ps
            WHERE ps.paper_id = n.id
              AND ps.source_key = 'local_supplement_final'
        )
        """
    ).fetchone()[0]
    print(f"新增论文：{new_count}，其中有补录来源行：{source_count}")
    if new_count != source_count:
        raise SystemExit("新增论文与补录来源行数量不一致，停止修复")

    print("修复前状态：", status_counts(conn))

    # 1. 新增论文：按当前 DOI 恢复 doi_verified_openalex / doi_declared / source_declared。
    new_statuses = {"doi_verified_openalex": 0, "doi_declared": 0, "source_declared": 0}
    updates: list[tuple[str, str | None, str, int]] = []
    for row in conn.execute("SELECT id, doi FROM newp ORDER BY id"):
        doi = (row["doi"] or "").strip().lower()
        if doi in VERIFIED_DOIS:
            status = "doi_verified_openalex"
            url = f"https://api.openalex.org/works/doi:{doi}"
            note = "补录库新增论文；OpenAlex 已验证 DOI、标题与年份"
        elif doi:
            status = "doi_declared"
            url = None
            note = "补录库新增论文；DOI 仅格式规范化，未逐条联网核验"
        else:
            status = "source_declared"
            url = None
            note = "补录库新增论文，来源为最终补录整合版，未逐条联网核验"
        new_statuses[status] += 1
        updates.append((status, url, note, row["id"]))

    # 2. 旧论文：用整合前备份判断是否补过空字段，恢复 matched_enriched。
    pre_map = {}
    for row in conn.execute(
        "SELECT id, teacher_id, title, doi, citation_count, venue, authors, paper_id FROM pre.papers"
    ):
        pre_map[(row["teacher_id"], norm_title(row["title"]))] = row
    sup_map = {
        row["id"]: row
        for row in conn.execute(
            "SELECT id, teacher_id, title, doi, citation_count, venue, authors, paper_id FROM sup.papers"
        )
    }

    old_statuses = {"matched_enriched": 0, "matched": 0}
    missing_pre = 0
    for row in conn.execute(
        """
        SELECT ps.paper_id, ps.source_row_id, p.teacher_id, p.title
        FROM main.paper_sources ps
        JOIN main.papers p ON p.id = ps.paper_id
        WHERE ps.source_key = 'local_supplement_final'
          AND ps.paper_id NOT IN (SELECT id FROM newp)
        """
    ):
        source = sup_map.get(row["source_row_id"])
        if source is None:
            missing_pre += 1
            continue
        old = pre_map.get((source["teacher_id"], norm_title(source["title"])))
        if old is None:
            old = pre_map.get((row["teacher_id"], norm_title(row["title"])))
        if old is None:
            missing_pre += 1
            continue

        nd = clean_doi(source["doi"])
        changes = bool(nd and blank(old["doi"]))
        try:
            citation = int(source["citation_count"]) if source["citation_count"] is not None else None
        except (TypeError, ValueError):
            citation = None
        if citation is not None and (
            old["citation_count"] is None or citation > int(old["citation_count"])
        ):
            changes = True
        if not blank(source["venue"]) and blank(old["venue"]):
            changes = True
        if not blank(source["authors"]) and blank(old["authors"]):
            changes = True
        if not blank(source["paper_id"]) and blank(old["paper_id"]):
            changes = True

        status = "matched_enriched" if changes else "matched"
        old_statuses[status] += 1
        updates.append(
            (status, None, "与当前库同一教师同一标题，仅补空字段", row["paper_id"])
        )

    print("新增论文应恢复状态：", new_statuses)
    print("旧论文应恢复状态：", old_statuses, "缺整合前记录：", missing_pre)
    if missing_pre:
        raise SystemExit("有旧论文无法在整合前备份中定位，停止修复")

    if args.dry_run:
        print("dry-run，不写入")
        conn.close()
        return

    backup_dir = target.parent / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"mentor_before_audit_repair_{time.strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(target, backup)
    print("已备份：", backup)

    with conn:
        conn.executemany(
            """
            UPDATE main.paper_sources
            SET verification_status = ?, verified_url = ?, note = ?
            WHERE paper_id = ? AND source_key = 'local_supplement_final'
            """,
            updates,
        )

    print("修复后状态：", status_counts(conn))
    print("完整性检查：", conn.execute("PRAGMA integrity_check").fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()

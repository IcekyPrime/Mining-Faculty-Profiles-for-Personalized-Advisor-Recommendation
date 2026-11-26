# -*- coding: utf-8 -*-
"""生成数据质量报告：字段覆盖、缺口、异常与评分分布。

输出：
    data/exports/data_quality.json
    docs/数据质量报告.md
"""
import json
import os
import sqlite3
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "db", "mentor.db")
EXP = os.path.join(ROOT, "data", "exports")
DOCS = os.path.join(ROOT, "docs")

FIELDS = [
    ("name_pinyin", "拼音"),
    ("title", "职称"),
    ("email", "邮箱"),
    ("research_directions", "研究方向"),
    ("bio", "简介"),
    ("institute", "研究所"),
    ("honors", "荣誉"),
    ("personal_homepage", "个人主页"),
    ("h_index", "h 指数"),
    ("citation_count", "引用量"),
    ("paper_count", "论文数"),
    ("course_community_id", "选课社区条目"),
]

PROCESSING_FIELDS = [
    ("keywords", "关键词"),
    ("cluster", "聚类簇"),
    ("community", "研究社区"),
    ("pagerank", "PageRank"),
    ("hits_authority", "HITS 权威值"),
    ("teaching_score", "教学评分"),
    ("score", "综合评分"),
]


def present(value):
    return value is not None and str(value).strip() not in ("", "[]", "缺失", "暂无内容")


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
    report = {"总人数": total}

    colleges = [
        {"name": r["college"], "count": r["n"]}
        for r in conn.execute(
            "SELECT college, COUNT(*) AS n FROM teachers GROUP BY college ORDER BY n DESC"
        )
    ]
    report["学院分布"] = colleges

    coverage = {}
    for field, label in FIELDS:
        n = sum(1 for r in conn.execute(f"SELECT {field} AS v FROM teachers") if present(r["v"]))
        coverage[label] = {"覆盖": n, "比例": round(n / total * 100, 1)}
    report["教师字段覆盖"] = coverage

    proc_coverage = {}
    proc_total = conn.execute("SELECT COUNT(*) FROM processing").fetchone()[0]
    for field, label in PROCESSING_FIELDS:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(processing)")}
        if field not in cols:
            continue
        n = sum(1 for r in conn.execute(f"SELECT {field} AS v FROM processing") if present(r["v"]))
        proc_coverage[label] = {
            "覆盖": n,
            "比例": round(n / max(proc_total, 1) * 100, 1),
        }
    report["处理层字段覆盖"] = proc_coverage

    papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    papers_year = conn.execute("SELECT COUNT(*) FROM papers WHERE year IS NOT NULL").fetchone()[0]
    papers_cite = conn.execute("SELECT COUNT(*) FROM papers WHERE citation_count IS NOT NULL").fetchone()[0]
    papers_doi = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE COALESCE(doi, '') <> ''"
    ).fetchone()[0]
    papers_venue = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE COALESCE(venue, '') <> ''"
    ).fetchone()[0]
    report["论文"] = {
        "总数": papers,
        "有年份": papers_year,
        "有引用量": papers_cite,
        "有 DOI": papers_doi,
        "有会议/期刊": papers_venue,
    }

    # 异常检查
    anomalies = {}
    anomalies["h指数为0但有论文"] = conn.execute(
        "SELECT COUNT(*) FROM teachers WHERE h_index=0 AND paper_count>=1"
    ).fetchone()[0]
    anomalies["h指数大于论文总数"] = conn.execute(
        "SELECT COUNT(*) FROM teachers WHERE h_index IS NOT NULL AND paper_count IS NOT NULL AND h_index>paper_count"
    ).fetchone()[0]
    anomalies["同姓名多条记录"] = sum(
        v - 1 for v in Counter(
            r["name"] for r in conn.execute("SELECT name FROM teachers")
        ).values() if v > 1
    )
    anomalies["论文年份缺失"] = papers - papers_year
    anomalies["论文 DOI 缺失"] = papers - papers_doi
    anomalies["论文会议/期刊缺失"] = papers - papers_venue
    anomalies["有论文数但无论文记录"] = conn.execute(
        "SELECT COUNT(*) FROM teachers t LEFT JOIN papers p ON p.teacher_id=t.id "
        "WHERE p.id IS NULL AND COALESCE(t.paper_count, 0) > 0"
    ).fetchone()[0]
    anomalies["有论文记录但论文数为 0"] = conn.execute(
        "SELECT COUNT(*) FROM teachers t WHERE EXISTS("
        "SELECT 1 FROM papers p WHERE p.teacher_id=t.id"
        ") AND COALESCE(t.paper_count, 0) = 0"
    ).fetchone()[0]
    anomalies["课程无评分"] = conn.execute(
        "SELECT COUNT(*) FROM courses WHERE COALESCE(rating_count, 0) = 0"
    ).fetchone()[0]
    report["异常"] = anomalies

    scores = [r["score"] for r in conn.execute("SELECT score FROM processing WHERE score IS NOT NULL ORDER BY score")]
    if scores:
        report["综合评分分布"] = {
            "人数": len(scores),
            "最小值": scores[0],
            "P25": scores[len(scores) // 4],
            "中位数": scores[len(scores) // 2],
            "P75": scores[len(scores) * 3 // 4],
            "最大值": scores[-1],
        }
    coverages = [r["score_coverage"] for r in conn.execute(
        "SELECT score_coverage FROM processing WHERE score_coverage IS NOT NULL"
    )]
    if coverages:
        buckets = Counter()
        for c in coverages:
            if c >= 0.8:
                buckets["≥0.8（信息充分）"] += 1
            elif c >= 0.5:
                buckets["0.5–0.8"] += 1
            else:
                buckets["<0.5（信息不足）"] += 1
        report["评分覆盖度分布"] = dict(buckets)

    conn.close()

    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(EXP, "data_quality.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    lines = ["# 数据质量报告", "", "> 由 `scripts/data_quality_report.py` 自动生成，随数据库更新重跑。", ""]
    lines.append(f"- 教师总人数：**{total}**")
    lines.append(f"- 论文记录：**{papers}**（有年份 {papers_year}，有引用量 {papers_cite}，"
                 f"有 DOI {papers_doi}，有会议/期刊 {papers_venue}）")
    lines.append("")
    lines.append("## 学院分布")
    lines.append("")
    lines.append("| 学院 | 人数 |")
    lines.append("|---|---|")
    for c in colleges:
        lines.append(f"| {c['name']} | {c['count']} |")
    lines.append("")
    lines.append("## 教师字段覆盖")
    lines.append("")
    lines.append("| 字段 | 覆盖人数 | 覆盖比例 |")
    lines.append("|---|---|---|")
    for label, item in coverage.items():
        lines.append(f"| {label} | {item['覆盖']} | {item['比例']}% |")
    lines.append("")
    lines.append("## 处理层字段覆盖")
    lines.append("")
    lines.append("| 字段 | 覆盖人数 | 覆盖比例 |")
    lines.append("|---|---|---|")
    for label, item in proc_coverage.items():
        lines.append(f"| {label} | {item['覆盖']} | {item['比例']}% |")
    lines.append("")
    lines.append("## 异常与缺口")
    lines.append("")
    for key, value in anomalies.items():
        lines.append(f"- {key}：**{value}**")
    lines.append("")
    if "综合评分分布" in report:
        dist = report["综合评分分布"]
        lines.append("## 综合评分分布")
        lines.append("")
        lines.append(f"- 参与评分：{dist['人数']} 人")
        lines.append(f"- 最小 {dist['最小值']} / P25 {dist['P25']} / 中位 {dist['中位数']} / P75 {dist['P75']} / 最大 {dist['最大值']}")
        lines.append("")
    if "评分覆盖度分布" in report:
        lines.append("## 评分覆盖度（可用维度占比）")
        lines.append("")
        for key, value in report["评分覆盖度分布"].items():
            lines.append(f"- {key}：{value} 人")
        lines.append("")
    lines.append("## 已知数据限制")
    lines.append("")
    lines.append("- 合作网络（PageRank/HITS）只覆盖计算机学院：只有该学院教师页公开完整作者列表，其余学院只能看到代表论文标题。")
    lines.append("- 引用量与论文总数来自 AMiner 个人学术页，未覆盖到的教师按「未知」处理（NULL），不参与综合评分。")
    lines.append("- 教学评分只统计选课社区有点评的课程，未开课或无人点评的教师没有该维度。")
    lines.append("")

    with open(os.path.join(DOCS, "数据质量报告.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n已写入 docs/数据质量报告.md 与 data/exports/data_quality.json")


if __name__ == "__main__":
    main()

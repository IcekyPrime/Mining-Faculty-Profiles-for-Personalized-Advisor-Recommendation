# -*- coding: utf-8 -*-
"""教师画像分析扩展：异常检测 / FWCI 归一化 / 时间衰减。

合并了原 ext_04、ext_05、ext_07 三个独立扩展脚本。
只读原 DB，不修改任何原有文件；结果写入 docs/eval/extensions/。

运行方式（项目根目录）：
    python scripts/teacher_analytics.py --anomaly --fwci --time-decay
"""
from __future__ import annotations

import argparse
import bisect
import datetime
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats as sps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "db" / "mentor.db"
OUT_DIR = ROOT / "docs" / "eval" / "extensions"


# ---------------------------------------------------------------------------
# 共享工具
# ---------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_out_dir():
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def dump_json(obj, name):
    path = OUT_DIR / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"已写入 {path}")


def dump_md(text, name):
    path = OUT_DIR / name
    path.write_text(text, encoding="utf-8")
    print(f"已写入 {path}")


# ===========================================================================
# 1. IsolationForest 异常检测（原 ext_04）
# ===========================================================================

LOG_FEATURES = {"citation_count", "paper_count"}
FEATURES = [
    "paper_count", "citation_count", "h_index", "honor_count",
    "course_count", "avg_rating", "rating_count", "paper_citations_per_paper",
    "is_advisor", "is_phd_advisor", "processing_score", "teaching_score",
    "recent_papers_5y",
]


def _honor_count(honors_raw):
    if not honors_raw:
        return 0
    try:
        v = json.loads(honors_raw)
        return len(v) if isinstance(v, list) else 0
    except Exception:
        return 0


def build_feature_matrix(conn):
    rows = conn.execute(
        """SELECT id, name, college, paper_count, citation_count, h_index,
                  honors, is_advisor, is_phd_advisor
           FROM teachers ORDER BY id"""
    ).fetchall()
    course_stats = {}
    for r in conn.execute(
        """SELECT teacher_id, COUNT(*) AS n, AVG(rating_avg) AS avg_rating,
                  SUM(rating_count) AS rating_count
           FROM courses GROUP BY teacher_id"""
    ):
        course_stats[r["teacher_id"]] = {
            "n": r["n"] or 0,
            "avg_rating": r["avg_rating"] or 0.0,
            "rating_count": r["rating_count"] or 0,
        }
    current_year = datetime.date.today().year
    recent_cutoff = current_year - 4
    recent_map = {}
    for r in conn.execute(
        "SELECT teacher_id, COUNT(*) AS n FROM papers WHERE year >= ? GROUP BY teacher_id",
        (recent_cutoff,),
    ):
        recent_map[r["teacher_id"]] = r["n"]
    proc_map = {}
    for r in conn.execute("SELECT teacher_id, score, teaching_score FROM processing"):
        proc_map[r["teacher_id"]] = {
            "score": r["score"] if r["score"] is not None else 0.0,
            "teaching_score": r["teaching_score"] if r["teaching_score"] is not None else 0.0,
        }
    records = []
    for t in rows:
        tid = t["id"]
        cs = course_stats.get(tid, {"n": 0, "avg_rating": 0.0, "rating_count": 0})
        pr = proc_map.get(tid, {"score": 0.0, "teaching_score": 0.0})
        paper_count = t["paper_count"] or 0
        citation_count = t["citation_count"] or 0
        h_index = t["h_index"] or 0
        feat = {
            "paper_count": float(paper_count),
            "citation_count": float(citation_count),
            "h_index": float(h_index),
            "honor_count": float(_honor_count(t["honors"])),
            "course_count": float(cs["n"]),
            "avg_rating": float(cs["avg_rating"]),
            "rating_count": float(cs["rating_count"]),
            "paper_citations_per_paper": citation_count / max(1, paper_count),
            "is_advisor": float(t["is_advisor"] or 0),
            "is_phd_advisor": float(t["is_phd_advisor"] or 0),
            "processing_score": float(pr["score"]),
            "teaching_score": float(pr["teaching_score"]),
            "recent_papers_5y": float(recent_map.get(tid, 0)),
        }
        records.append({
            "teacher_id": tid,
            "name": t["name"],
            "college": t["college"],
            "features": feat,
        })
    X = np.array([[r["features"][name] for name in FEATURES] for r in records], dtype=float)
    return records, X


def preprocess(X):
    X = X.copy()
    for i, name in enumerate(FEATURES):
        if name in LOG_FEATURES:
            col = X[:, i]
            X[:, i] = np.where(col > 1, np.log1p(col), col)
    lo = np.percentile(X, 5, axis=0)
    hi = np.percentile(X, 95, axis=0)
    X = np.clip(X, lo, hi)
    lo2 = X.min(axis=0)
    hi2 = X.max(axis=0)
    denom = hi2 - lo2
    denom[denom < 1e-9] = 1.0
    X = (X - lo2) / denom
    return X


def explain_anomaly(feat_raw: dict) -> list[str]:
    reasons = []
    pc = feat_raw["paper_count"]
    cc = feat_raw["citation_count"]
    h = feat_raw["h_index"]
    hc = feat_raw["honor_count"]
    nc = feat_raw["course_count"]
    rc = feat_raw["rating_count"]
    recent = feat_raw["recent_papers_5y"]
    if cc > 10000:
        reasons.append(f"citation_count 极高（{int(cc)}）")
    elif cc > 1000:
        reasons.append(f"citation_count 很高（{int(cc)}）")
    if h > 80:
        reasons.append(f"h_index 极高（{int(h)}）")
    elif h > 40:
        reasons.append(f"h_index 很高（{int(h)}）")
    if pc > 300:
        reasons.append(f"paper_count 极高（{int(pc)}）")
    elif pc > 100:
        reasons.append(f"paper_count 较高（{int(pc)}）")
    if hc > 5:
        reasons.append(f"honor_count 很多（{int(hc)}）")
    if pc == 0 and (cc > 0 or h > 0):
        reasons.append("paper_count=0 但存在引用/h_index（数据不一致）")
    if pc > 0 and recent == 0:
        reasons.append("近 5 年无论文（可能为早期入库或爬取不全）")
    if nc == 0:
        if pc > 50 or cc > 1000:
            reasons.append("无课程记录但学术产出高（课程数据可能缺失）")
        else:
            reasons.append("无课程记录")
    if rc == 0 and nc > 0:
        reasons.append("有课程但无评分（教学口碑数据缺失）")
    if not reasons:
        reasons.append("组合特征偏离主流分布（各维度非极端但综合异常）")
    return reasons


def run_anomaly_detection():
    from sklearn.ensemble import IsolationForest
    ensure_out_dir()
    conn = get_conn()
    records, X_raw = build_feature_matrix(conn)
    conn.close()
    n = len(records)
    print(f"教师总数: {n}")
    X = preprocess(X_raw)
    model = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
    model.fit(X)
    labels = model.predict(X)
    scores = model.score_samples(X)
    mean = X_raw.mean(axis=0)
    std = X_raw.std(axis=0)
    std[std < 1e-9] = 1.0
    Z = (X_raw - mean) / std
    anomaly_idx = np.where(labels == -1)[0]
    order = anomaly_idx[np.argsort(scores[anomaly_idx])]
    top20 = order[:20]
    anomaly_count = len(order) if len(order) else 1
    contribution = {f: 0 for f in FEATURES}
    for idx in order:
        z_abs = np.abs(Z[idx])
        top3 = set(np.argsort(-z_abs)[:3])
        for j, f in enumerate(FEATURES):
            if z_abs[j] > 2 and j in top3:
                contribution[f] += 1
    contribution_frac = {f: round(c / anomaly_count, 4) for f, c in contribution.items()}
    anomaly_list = []
    for idx in top20:
        rec = records[idx]
        reasons = explain_anomaly(rec["features"])
        z_abs = np.abs(Z[idx])
        top3 = [FEATURES[j] for j in np.argsort(-z_abs)[:3]]
        anomaly_list.append({
            "teacher_id": rec["teacher_id"],
            "name": rec["name"],
            "college": rec["college"],
            "score": round(float(scores[idx]), 4),
            "top_extreme_features": top3,
            "features": {
                k: (round(float(v), 4) if isinstance(v, float) else v)
                for k, v in rec["features"].items()
            },
            "reasons": reasons,
        })
    dump_json(anomaly_list, "ext_anomalies.json")
    lines = []
    lines.append("# 教师画像异常检测（IsolationForest）\n")
    lines.append("## 方法说明\n")
    lines.append(
        "使用 **IsolationForest（孤立森林）** 对每位教师的多维画像进行无监督异常检测，"
        "目的有二：(1) 发现**数据质量问题**（如字段缺失、爬取不全导致的组合异常）；"
        "(2) 识别**真正 exceptional** 的教师（学术产出、引用、荣誉等维度极端）。\n"
    )
    lines.append("### 特征（13 维，缺失值按 0 处理）\n")
    for f in FEATURES:
        lines.append(f"- `{f}`")
    lines.append("")
    lines.append(
        "### 预处理\n"
        "1. 对 `citation_count`、`paper_count` 做 log1p 变换（值 >1 时），缓解右偏；\n"
        "2. 对所有特征做 **5-95 分位裁剪**（与原版 `score.py` 的 normalize 一致）；\n"
        "3. min-max 归一化到 [0,1]。\n"
    )
    lines.append(
        "### 模型参数\n"
        "`IsolationForest(n_estimators=200, contamination=0.05, random_state=42)`\n"
    )
    lines.append("\n## Top-20 异常教师\n")
    lines.append(
        "| # | 姓名 | 学院 | paper_count | citation_count | h_index | honor_count | 异常分数 | 主要原因 |"
    )
    lines.append("|---|------|------|-------------|----------------|---------|-------------|----------|----------|")
    for i, a in enumerate(anomaly_list, 1):
        f = a["features"]
        reason = a["reasons"][0] if a["reasons"] else ""
        lines.append(
            f"| {i} | {a['name']} | {a['college'] or '-'} "
            f"| {int(f['paper_count'])} | {int(f['citation_count'])} | {int(f['h_index'])} "
            f"| {int(f['honor_count'])} | {a['score']} | {reason} |"
        )
    lines.append("")
    lines.append("## 特征贡献分析\n")
    lines.append(
        "统计：在全部异常样本中，某特征 |z-score|>2 **且** 位列该样本 top-3 极端特征的占比。\n"
    )
    lines.append("| 特征 | 贡献占比 |")
    lines.append("|------|----------|")
    for f in sorted(contribution_frac, key=lambda k: -contribution_frac[k]):
        lines.append(f"| `{f}` | {contribution_frac[f]:.2%} |")
    lines.append("")
    reason_keywords = {
        "citation_count 极高": 0, "citation_count 很高": 0,
        "h_index 极高": 0, "h_index 很高": 0,
        "paper_count 极高": 0, "paper_count 较高": 0,
        "honor_count 很多": 0,
        "paper_count=0 但存在引用/h_index（数据不一致）": 0,
        "近 5 年无论文（可能为早期入库或爬取不全）": 0,
        "无课程记录但学术产出高（课程数据可能缺失）": 0,
        "无课程记录": 0,
        "有课程但无评分（教学口碑数据缺失）": 0,
        "组合特征偏离主流分布（各维度非极端但综合异常）": 0,
    }
    for a in anomaly_list:
        for r in a["reasons"]:
            for key in reason_keywords:
                if r.startswith(key):
                    reason_keywords[key] += 1
                    break
    lines.append("## 分析\n")
    lines.append(
        f"IsolationForest 共标记 **{len(order)}** 名教师为异常（约 "
        f"{len(order) / n:.1%}，与 contamination=0.05 设定一致）。\n"
    )
    if reason_keywords.get("citation_count 极高") or reason_keywords.get("citation_count 很高"):
        lines.append("- **学术产出/引用极高**：属于真正 exceptional 的教师，并非数据问题。\n")
    if reason_keywords.get("paper_count=0 但存在引用/h_index（数据不一致）"):
        lines.append("- **数据不一致**：`paper_count=0` 但引用/h_index 非 0，属于数据质量问题。\n")
    if reason_keywords.get("无课程记录") or reason_keywords.get("无课程记录但学术产出高（课程数据可能缺失）"):
        lines.append("- **课程数据缺失**：部分学术产出高的教师没有课程记录。\n")
    if reason_keywords.get("有课程但无评分（教学口碑数据缺失）"):
        lines.append("- **教学口碑缺失**：有课程但无评分记录。\n")
    if reason_keywords.get("近 5 年无论文（可能为早期入库或爬取不全）"):
        lines.append("- **近 5 年无论文**：可能是早期入库/退休教师。\n")
    lines.append(
        "\n综合来看，异常画像主要由两类构成：**真正 exceptional 的教师**"
        "与**数据质量/覆盖问题**。IsolationForest 的价值在于无需人工设定阈值即可自动圈出"
        "「组合维度上偏离主流」的样本。"
    )
    lines.append("")
    dump_md("\n".join(lines), "ext_isolation_forest_report.md")
    print(f"标记异常: {len(order)} 人 (占比 {len(order) / n:.1%})")
    print("Top-10 异常教师：")
    for i, a in enumerate(anomaly_list[:10], 1):
        f = a["features"]
        print(
            f"  {i}. {a['name']} ({a['college'] or '-'}) "
            f"papers={int(f['paper_count'])} cites={int(f['citation_count'])} "
            f"h={int(f['h_index'])} score={a['score']} | {a['reasons'][0]}"
        )
    print("特征贡献 Top-5：")
    for f in sorted(contribution_frac, key=lambda k: -contribution_frac[k])[:5]:
        print(f"  {f}: {contribution_frac[f]:.2%}")


# ===========================================================================
# 2. FWCI 归一化（原 ext_05）
# ===========================================================================

MIN_PAPERS_FOR_COLLEGE = 5


def _fmt(x, nd=3):
    if x is None:
        return "-"
    return f"{x:.{nd}f}"


def compute_college_baselines(conn) -> dict:
    overall = conn.execute(
        "SELECT COUNT(*) AS n, SUM(citation_count) AS s "
        "FROM papers WHERE citation_count IS NOT NULL"
    ).fetchone()
    overall_n = overall["n"] or 0
    overall_s = overall["s"] or 0
    overall_mean = (overall_s / overall_n) if overall_n > 0 else 0.0
    baselines = {
        "__overall__": {
            "n_papers": overall_n,
            "total_citations": overall_s,
            "mean_citations": overall_mean,
            "fallback": False,
        }
    }
    for row in conn.execute(
        """SELECT t.college AS college, COUNT(p.id) AS n, SUM(p.citation_count) AS s
           FROM papers p JOIN teachers t ON t.id = p.teacher_id
           WHERE p.citation_count IS NOT NULL GROUP BY t.college"""
    ):
        college = row["college"] or "(未知学院)"
        n_p = row["n"] or 0
        s = row["s"] or 0
        if n_p < MIN_PAPERS_FOR_COLLEGE:
            baselines[college] = {
                "n_papers": n_p, "total_citations": s,
                "mean_citations": overall_mean, "fallback": True,
            }
        else:
            baselines[college] = {
                "n_papers": n_p, "total_citations": s,
                "mean_citations": (s / n_p) if n_p > 0 else 0.0, "fallback": False,
            }
    return baselines


def compute_teacher_fwci(conn, baselines: dict) -> list[dict]:
    teachers = conn.execute("SELECT id, name, college FROM teachers ORDER BY id").fetchall()
    cite_map = {}
    for row in conn.execute(
        "SELECT teacher_id, COUNT(*) AS n, SUM(citation_count) AS s "
        "FROM papers WHERE citation_count IS NOT NULL GROUP BY teacher_id"
    ):
        cite_map[row["teacher_id"]] = (row["n"] or 0, row["s"] or 0)
    results = []
    for t in teachers:
        college = t["college"] or "(未知学院)"
        baseline = baselines.get(college, baselines["__overall__"])
        mean_base = baseline["mean_citations"]
        n_p, s = cite_map.get(t["id"], (0, 0))
        raw_citations = s
        expected = n_p * mean_base
        fwci = (raw_citations / expected) if expected > 0 else None
        results.append({
            "teacher_id": t["id"],
            "name": t["name"],
            "college": college,
            "raw_citations": raw_citations,
            "paper_count_with_cites": n_p,
            "expected_citations": expected,
            "fwci": fwci,
            "baseline_source": college if not baseline["fallback"] else "__overall__",
        })
    return results


def _rank_desc(values: dict, key=lambda v: v) -> dict:
    valid = {k: key(v) for k, v in values.items() if v is not None and v > 0}
    if not valid:
        return {k: None for k in values}
    ordered = sorted(valid.items(), key=lambda kv: -kv[1])
    ranks = {}
    prev_val = None
    prev_rank = None
    for rank, (k, v) in enumerate(ordered, 1):
        if prev_val is not None and abs(v - prev_val) < 1e-9:
            ranks[k] = prev_rank
        else:
            ranks[k] = rank
            prev_rank = rank
            prev_val = v
    for k in values:
        if k not in ranks:
            ranks[k] = None
    return ranks


def _percentile_rank_sorted(sorted_vals: list, n: int) -> list:
    res = [0.0] * n
    if n == 0:
        return res
    for i, v in enumerate(sorted_vals):
        lo = bisect.bisect_left(sorted_vals, v)
        hi = bisect.bisect_right(sorted_vals, v)
        res[i] = (lo + 0.5 * (hi - lo)) / n * 100.0
    return res


def run_fwci():
    ensure_out_dir()
    conn = get_conn()
    baselines = compute_college_baselines(conn)
    overall = baselines["__overall__"]
    records = compute_teacher_fwci(conn, baselines)
    conn.close()
    n = len(records)
    print(f"教师总数: {n}")
    print(f"全校基准: 论文 {overall['n_papers']} 篇, 篇均引用 {overall['mean_citations']:.3f}")
    raw_rank = _rank_desc({r["teacher_id"]: r["raw_citations"] for r in records})
    fwci_rank = _rank_desc({r["teacher_id"]: r["fwci"] for r in records})
    raw_sorted = sorted(r["raw_citations"] for r in records)
    raw_pct = _percentile_rank_sorted(raw_sorted, n)
    order_by_raw = sorted(range(n), key=lambda i: records[i]["raw_citations"])
    raw_pct_map = {records[order_by_raw[i]]["teacher_id"]: raw_pct[i] for i in range(n)}
    for r in records:
        r["raw_rank"] = raw_rank[r["teacher_id"]]
        r["fwci_rank"] = fwci_rank[r["teacher_id"]]
        r["raw_citation_percentile"] = raw_pct_map[r["teacher_id"]]
    college_stats = {}
    for c in [c for c in baselines if c != "__overall__"]:
        fwci_vals = [r["fwci"] for r in records if r["college"] == c and r["fwci"] is not None]
        if fwci_vals:
            fwci_vals_sorted = sorted(fwci_vals)
            m = len(fwci_vals_sorted)
            mid = m // 2
            median = (
                fwci_vals_sorted[mid]
                if m % 2
                else (fwci_vals_sorted[mid - 1] + fwci_vals_sorted[mid]) / 2
            )
        else:
            median = None
        college_stats[c] = {
            "n_teachers": sum(1 for r in records if r["college"] == c),
            "n_with_fwci": len(fwci_vals),
            "mean_fwci": (sum(fwci_vals) / len(fwci_vals)) if fwci_vals else None,
            "median_fwci": median,
            "n_above_field_avg": sum(1 for v in fwci_vals if v > 1.0),
            "n_below_field_avg": sum(1 for v in fwci_vals if v < 1.0),
            "baseline_mean_citations": baselines[c]["mean_citations"],
            "fallback": baselines[c]["fallback"],
        }
    ranked = [r for r in records if r["fwci_rank"] is not None and r["raw_rank"] is not None]
    total_r = len(ranked)

    def rank_pct(rank, total):
        return (rank - 1) / max(1, total - 1)

    cross_stars = []
    for r in ranked:
        fwci_p = rank_pct(r["fwci_rank"], total_r)
        raw_p = rank_pct(r["raw_rank"], total_r)
        gap = raw_p - fwci_p
        cross_stars.append({
            "teacher_id": r["teacher_id"],
            "name": r["name"],
            "college": r["college"],
            "fwci": round(r["fwci"], 4),
            "fwci_rank": r["fwci_rank"],
            "raw_citations": r["raw_citations"],
            "raw_rank": r["raw_rank"],
            "gap": round(gap, 4),
        })
    undervalued = sorted(cross_stars, key=lambda x: -x["gap"])[:15]
    overvalued = sorted(cross_stars, key=lambda x: x["gap"])[:15]
    by_fwci = sorted([r for r in records if r["fwci"] is not None], key=lambda r: -r["fwci"])
    by_raw = sorted([r for r in records if r["raw_citations"] > 0], key=lambda r: -r["raw_citations"])
    top15_fwci = by_fwci[:15]
    top15_raw = by_raw[:15]
    scores_json = {
        str(r["teacher_id"]): {
            "name": r["name"],
            "college": r["college"],
            "fwci": (round(r["fwci"], 4) if r["fwci"] is not None else None),
            "raw_citations": r["raw_citations"],
            "expected_citations": round(r["expected_citations"], 3),
            "paper_count_with_cites": r["paper_count_with_cites"],
            "raw_rank": r["raw_rank"],
            "fwci_rank": r["fwci_rank"],
            "raw_citation_percentile": round(r["raw_citation_percentile"], 2),
            "baseline_source": r["baseline_source"],
        }
        for r in records
    }
    dump_json(scores_json, "ext_fwci_scores.json")
    lines = []
    lines.append("# FWCI 学院内引用归一化\n")
    lines.append("## 方法说明\n")
    lines.append(
        "**FWCI（Field-Weighted Citation Impact）** = 实际引用数 / 领域平均预期引用数。\n"
        "FWCI = 1.0 表示恰好处于所属领域平均水平；> 1.0 高于平均；< 1.0 低于平均。\n"
        "本扩展用**学院内论文篇均引用**近似领域基准。\n"
    )
    lines.append(
        f"**全校基准**：{overall['n_papers']} 篇有引用论文，篇均引用 {overall['mean_citations']:.3f}。\n"
    )
    lines.append("")
    lines.append("## 学院级基准与 FWCI 分布\n")
    lines.append(
        "| 学院 | 教师数 | 有引用论文数 | 篇均基准 | 平均FWCI | 中位FWCI | 高于领域平均 | 低于领域平均 | 回退全校 |"
    )
    lines.append("|------|--------|--------------|----------|----------|----------|--------------|--------------|----------|")
    for c, st in sorted(college_stats.items(), key=lambda kv: -(kv[1]["mean_fwci"] or 0)):
        b = baselines[c]
        lines.append(
            f"| {c} | {st['n_teachers']} | {b['n_papers']} "
            f"| {b['mean_citations']:.2f} "
            f"| {_fmt(st['mean_fwci'])} | {_fmt(st['median_fwci'])} "
            f"| {st['n_above_field_avg']} | {st['n_below_field_avg']} "
            f"| {'是' if st['fallback'] else '否'} |"
        )
    lines.append("")
    lines.append("## Top-15 FWCI（归一化后）\n")
    lines.append("| # | 姓名 | 学院 | FWCI | 原始引用 | 原始引用排名 | 有引用论文数 |")
    lines.append("|---|------|------|------|----------|--------------|--------------|")
    for i, r in enumerate(top15_fwci, 1):
        lines.append(
            f"| {i} | {r['name']} | {r['college']} | {r['fwci']:.3f} "
            f"| {r['raw_citations']} | {r['raw_rank']} | {r['paper_count_with_cites']} |"
        )
    lines.append("")
    lines.append("## Top-15 原始引用（未归一化）\n")
    lines.append("| # | 姓名 | 学院 | 原始引用 | FWCI | FWCI排名 |")
    lines.append("|---|------|------|----------|------|----------|")
    for i, r in enumerate(top15_raw, 1):
        lines.append(
            f"| {i} | {r['name']} | {r['college']} | {r['raw_citations']} "
            f"| {_fmt(r['fwci'])} | {r['fwci_rank']} |"
        )
    lines.append("")
    top15_fwci_ids = {r["teacher_id"] for r in top15_fwci}
    top15_raw_ids = {r["teacher_id"] for r in top15_raw}
    only_fwci = top15_fwci_ids - top15_raw_ids
    only_raw = top15_raw_ids - top15_fwci_ids
    lines.append("## 两种排序的差异\n")
    lines.append(
        f"FWCI Top-15 中有 **{len(only_fwci)}** 人不在原始引用 Top-15 中"
        f"（归一化后被「提升」），而原始引用 Top-15 中有 **{len(only_raw)}** 人"
        f"不在 FWCI Top-15 中（归一化后被「拉低」）。\n"
    )
    if only_fwci:
        lines.append("### 归一化后进入 Top-15 的教师\n")
        for r in sorted([r for r in top15_fwci if r["teacher_id"] in only_fwci], key=lambda x: -x["fwci"]):
            lines.append(
                f"- **{r['name']}**（{r['college']}）：FWCI={r['fwci']:.3f}，"
                f"但原始引用 {r['raw_citations']} 仅排 {r['raw_rank']} 位。"
            )
        lines.append("")
    if only_raw:
        lines.append("### 原始引用进入 Top-15 但归一化后掉出的教师\n")
        for r in sorted([r for r in top15_raw if r["teacher_id"] in only_raw], key=lambda x: -x["raw_citations"]):
            lines.append(
                f"- **{r['name']}**（{r['college']}）：原始引用 {r['raw_citations']}（排名 "
                f"{r['raw_rank']}），但 FWCI 仅 {_fmt(r['fwci'])}。"
            )
        lines.append("")
    lines.append("## 交叉学科明星（排名反差）\n")
    lines.append("### 被低估的明星\n")
    lines.append("| 姓名 | 学院 | FWCI | FWCI排名 | 原始引用 | 原始引用排名 | gap |")
    lines.append("|------|------|------|----------|----------|--------------|-----|")
    for r in undervalued:
        lines.append(
            f"| {r['name']} | {r['college']} | {r['fwci']:.3f} | {r['fwci_rank']} "
            f"| {r['raw_citations']} | {r['raw_rank']} | {r['gap']:+.3f} |"
        )
    lines.append("")
    lines.append("### 被高估的明星\n")
    lines.append("| 姓名 | 学院 | 原始引用 | 原始引用排名 | FWCI | FWCI排名 | gap |")
    lines.append("|------|------|----------|--------------|------|----------|-----|")
    for r in overvalued:
        lines.append(
            f"| {r['name']} | {r['college']} | {r['raw_citations']} | {r['raw_rank']} "
            f"| {_fmt(r['fwci'])} | {r['fwci_rank']} | {r['gap']:+.3f} |"
        )
    lines.append("")
    lines.append("## 局限\n")
    lines.append(
        "1. **学院 ≠ 学科**：用 college 近似领域，学院内多个研究方向的引用基准差异被抹平。\n"
        "2. **基准稳定性**：篇均引用受少量高被引论文拉动（长尾分布）。\n"
        "3. **引用缺失**：约 70% 论文 citation_count 为 NULL，可能低估真实产出。\n"
        "4. **样本量差异**：小样本学院的篇均基准方差更大。\n"
        "5. **未考虑时间因素**：近年论文引用尚在累积中。\n"
        "6. **循环性风险**：用同一批教师的论文估计基准、再对这些教师计算 FWCI。\n"
    )
    lines.append("")
    dump_md("\n".join(lines), "ext_fwci_report.md")
    print(f"\nFWCI 摘要:")
    print(f"  有 FWCI 的教师: {sum(1 for r in records if r['fwci'] is not None)} / {n}")
    for c, st in sorted(college_stats.items(), key=lambda kv: -(kv[1]["mean_fwci"] or 0)):
        b = baselines[c]
        print(
            f"    {c:<12} 篇均基准={b['mean_citations']:>8.2f}  "
            f"平均FWCI={_fmt(st['mean_fwci']):>6}  (教师 {st['n_teachers']})"
        )
    print(f"  Top-15 差异: 归一化提升 {len(only_fwci)} 人, 拉低 {len(only_raw)} 人")


# ===========================================================================
# 3. 时间衰减分析（原 ext_07）
# ===========================================================================

CURRENT_YEAR = 2026
HALF_LIVES = [2, 5, 10, 20]


def decay_weight(year: int, half_life: int) -> float:
    age = max(CURRENT_YEAR - year, 0)
    return 0.5 ** (age / half_life)


def normalize_td(vals: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(vals, [5, 95])
    if hi <= lo:
        return np.zeros_like(vals)
    return np.clip((vals - lo) / (hi - lo), 0, 1)


def rank_array(values: np.ndarray) -> np.ndarray:
    order = np.argsort(-values, kind="stable")
    ranks = np.empty_like(order)
    ranks[order] = np.arange(1, len(values) + 1)
    return ranks


def kendall_tau(a, b) -> float:
    if len(a) < 2:
        return 0.0
    tau, _ = sps.kendalltau(a, b)
    return float(tau) if not np.isnan(tau) else 0.0


def spearman_rho(a, b) -> float:
    if len(a) < 2:
        return 0.0
    rho, _ = sps.spearmanr(a, b)
    return float(rho) if not np.isnan(rho) else 0.0


def run_time_decay():
    ensure_out_dir()
    conn = get_conn()
    teachers = conn.execute("SELECT id, name, college FROM teachers ORDER BY id").fetchall()
    teacher_ids = [t["id"] for t in teachers]
    id2name = {t["id"]: t["name"] for t in teachers}
    id2college = {t["id"]: t["college"] for t in teachers}
    n = len(teacher_ids)
    print(f"评分对象 {n} 人")
    papers = conn.execute("SELECT teacher_id, year, citation_count FROM papers").fetchall()
    agg = defaultdict(lambda: {
        "raw": 0.0,
        "decayed": {hl: 0.0 for hl in HALF_LIVES},
        "recent_5y": 0, "recent_3y": 0,
        "recent_5y_cites": 0.0, "total_cites": 0.0,
    })
    for p in papers:
        tid = p["teacher_id"]
        if tid is None or tid not in id2name:
            continue
        year = p["year"]
        cites = p["citation_count"] or 0
        a = agg[tid]
        a["raw"] += cites
        a["total_cites"] += cites
        if year is not None:
            if year >= CURRENT_YEAR - 5:
                a["recent_5y"] += 1
                a["recent_5y_cites"] += cites
            if year >= CURRENT_YEAR - 3:
                a["recent_3y"] += 1
            for hl in HALF_LIVES:
                a["decayed"][hl] += cites * decay_weight(year, hl)
        else:
            for hl in HALF_LIVES:
                a["decayed"][hl] += cites * 0.5
    conn.close()
    raw = np.array([agg.get(tid, {"raw": 0.0})["raw"] for tid in teacher_ids], dtype=float)
    recent5 = np.array([agg.get(tid, {"recent_5y": 0})["recent_5y"] for tid in teacher_ids], dtype=float)
    recent3 = np.array([agg.get(tid, {"recent_3y": 0})["recent_3y"] for tid in teacher_ids], dtype=float)
    recency_ratio = np.zeros(n)
    for i, tid in enumerate(teacher_ids):
        a = agg.get(tid)
        if a:
            total = a["total_cites"]
            recent_cites = a["recent_5y_cites"]
            recency_ratio[i] = recent_cites / total if total > 0 else 0.0
    decayed = {}
    for hl in HALF_LIVES:
        decayed[hl] = np.array(
            [agg.get(tid, {"decayed": {}}).get("decayed", {}).get(hl, 0.0) for tid in teacher_ids],
            dtype=float,
        )
    raw_norm = normalize_td(raw)
    decayed_norm = {hl: normalize_td(decayed[hl]) for hl in HALF_LIVES}
    raw_ranks = rank_array(raw)
    decayed_ranks = {hl: rank_array(decayed[hl]) for hl in HALF_LIVES}
    recent5_ranks = rank_array(recent5)
    rank_change_hl5 = raw_ranks - decayed_ranks[5]
    risers_idx = np.argsort(-rank_change_hl5)
    fallers_idx = np.argsort(rank_change_hl5)
    risers = []
    for idx in risers_idx:
        if rank_change_hl5[idx] > 0:
            risers.append(int(idx))
        if len(risers) >= 20:
            break
    fallers = []
    for idx in fallers_idx:
        if rank_change_hl5[idx] < 0:
            fallers.append(int(idx))
        if len(fallers) >= 20:
            break
    sensitivity = []
    for hl in HALF_LIVES:
        rc = raw_ranks - decayed_ranks[hl]
        sensitivity.append({
            "half_life": hl,
            "mean_rank_change": float(np.mean(rc)),
            "max_rank_change": float(np.max(np.abs(rc))),
            "kendall_tau": kendall_tau(raw_ranks, decayed_ranks[hl]),
            "spearman_rho": spearman_rho(raw_ranks, decayed_ranks[hl]),
        })
    scores_out = {}
    for i, tid in enumerate(teacher_ids):
        scores_out[str(tid)] = {
            "name": id2name[tid],
            "college": id2college[tid],
            "raw_citations": float(raw[i]),
            "decayed": {str(hl): float(decayed[hl][i]) for hl in HALF_LIVES},
            "recent_5y": int(recent5[i]),
            "recent_3y": int(recent3[i]),
            "recency_ratio": float(recency_ratio[i]),
            "raw_rank": int(raw_ranks[i]),
            "decayed_rank_hl5": int(decayed_ranks[5][i]),
            "rank_change": int(rank_change_hl5[i]),
        }
    dump_json(scores_out, "ext_time_decay_scores.json")
    lines = []
    lines.append("# 论文引用时间衰减分析\n")
    lines.append("## 方法描述\n")
    lines.append("对论文引用数施加指数时间衰减：`weight(t) = 0.5 ^ ((current_year - t) / half_life)`\n")
    lines.append(f"current_year = {CURRENT_YEAR}，half_life 取 {HALF_LIVES} 年。\n")
    lines.append("year=None 的论文给中性权重 0.5。\n")
    lines.append("## 敏感性分析\n")
    lines.append("| half_life | 平均排名变化 | 最大排名变化 | Kendall τ | Spearman ρ |")
    lines.append("|-----------|:-----------:|:-----------:|:---------:|:----------:|")
    lines.append("| ∞ (无衰减) | 0.0 | 0.0 | 1.0000 | 1.0000 |")
    for s in sensitivity:
        lines.append(
            f"| {s['half_life']} | {s['mean_rank_change']:.2f} "
            f"| {s['max_rank_change']:.0f} "
            f"| {s['kendall_tau']:.4f} | {s['spearman_rho']:.4f} |"
        )
    lines.append("\n> 半衰期越短，排名扰动越大。\n")
    lines.append("## Top-10 上升者（时间衰减后排名大幅上升）\n")
    lines.append("| 姓名 | 学院 | 原始排名 | 衰后排名(hl=5) | 排名变化 | 近5年论文数 |")
    lines.append("|------|------|:-------:|:-------------:|:-------:|:---------:|")
    for idx in risers[:10]:
        tid = teacher_ids[idx]
        lines.append(
            f"| {id2name[tid]} | {id2college[tid] or '-'} "
            f"| {raw_ranks[idx]} | {decayed_ranks[5][idx]} "
            f"| +{rank_change_hl5[idx]} | {recent5[idx]:.0f} |"
        )
    lines.append("")
    lines.append("## Top-10 下降者（时间衰减后排名大幅下降）\n")
    lines.append("| 姓名 | 学院 | 原始排名 | 衰后排名(hl=5) | 排名变化 | 近5年论文数 |")
    lines.append("|------|------|:-------:|:-------------:|:-------:|:---------:|")
    for idx in fallers[:10]:
        tid = teacher_ids[idx]
        lines.append(
            f"| {id2name[tid]} | {id2college[tid] or '-'} "
            f"| {raw_ranks[idx]} | {decayed_ranks[5][idx]} "
            f"| {rank_change_hl5[idx]} | {recent5[idx]:.0f} |"
        )
    lines.append("")
    lines.append("## 分析\n")
    risers_with_recent = sum(1 for i in risers[:10] if recent5[i] >= 3)
    fallers_with_low_recent = sum(1 for i in fallers[:10] if recent5[i] <= 1)
    lines.append(f"### 上升者特征\n- Top-10 上升者中有 **{risers_with_recent} 人**近 5 年发表论文 ≥ 3 篇。\n")
    lines.append(f"### 下降者特征\n- Top-10 下降者中有 **{fallers_with_low_recent} 人**近 5 年发表论文 ≤ 1 篇。\n")
    lines.append("### 结论\n")
    lines.append("1. **hl=5 是合理的默认值**，与学术界 5 年考核周期一致。")
    lines.append("2. **新兴研究者 vs 资深学者**：时间衰减有利于近年高产的新兴研究者。")
    lines.append("3. **recency_ratio**：近 5 年引用占总引用比例可衡量科研「新鲜度」。\n")
    lines.append("")
    dump_md("\n".join(lines), "ext_time_decay_report.md")
    print(f"\n时间衰减摘要 (hl=5 为推荐值):")
    for s in sensitivity:
        print(f"  hl={s['half_life']:>3}: Kendall τ={s['kendall_tau']:.4f}, "
              f"Spearman ρ={s['spearman_rho']:.4f}, max|Δrank|={s['max_rank_change']:.0f}")
    print("Top-5 上升者:")
    for idx in risers[:5]:
        tid = teacher_ids[idx]
        print(f"  {id2name[tid]}: rank {raw_ranks[idx]} → {decayed_ranks[5][idx]} (+{rank_change_hl5[idx]})")
    print("Top-5 下降者:")
    for idx in fallers[:5]:
        tid = teacher_ids[idx]
        print(f"  {id2name[tid]}: rank {raw_ranks[idx]} → {decayed_ranks[5][idx]} ({rank_change_hl5[idx]})")


# ===========================================================================
# main
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="教师画像分析扩展")
    parser.add_argument("--anomaly", action="store_true", help="IsolationForest 异常检测")
    parser.add_argument("--fwci", action="store_true", help="FWCI 学院内归一化")
    parser.add_argument("--time-decay", action="store_true", help="论文引用时间衰减")
    args = parser.parse_args()

    if not args.anomaly and not args.fwci and not args.time_decay:
        parser.print_help()
        sys.exit(0)

    if args.anomaly:
        print("\n===== IsolationForest 异常检测 =====")
        run_anomaly_detection()
    if args.fwci:
        print("\n===== FWCI 归一化 =====")
        run_fwci()
    if args.time_decay:
        print("\n===== 时间衰减分析 =====")
        run_time_decay()
    print("\n全部完成。")


if __name__ == "__main__":
    main()

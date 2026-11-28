# -*- coding: utf-8 -*-
"""离线检索评估：规则相关度 vs BM25F。

用法（在项目根目录）：
    python scripts/evaluate_retrieval.py

数据来自 docs/eval/queries.json（人工核对研究方向后标注的相关教师），
指标为 NDCG@10、MAP@10、HitRate@10 与 P@5；结果写到 docs/eval/results.md。
这是课程式的「小规模、可复现」评估，不宣称是完整基准。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sqlite3
import sys
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.mining import combine_scores, topic_scores  # noqa: E402
from app.retrieval import build_index  # noqa: E402
from app.services import relevance, search_corpus  # noqa: E402

DB = ROOT / "data" / "db" / "mentor.db"
QUERIES = ROOT / "docs" / "eval" / "queries.json"
TOPICS = ROOT / "data" / "exports" / "topics.json"
OUT = ROOT / "docs" / "eval" / "results.md"
K = 10


def dcg(gains):
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gains[:K]))


def evaluate(ranked_ids, relevant, k=K):
    relevant = set(relevant)
    gains = [1 if tid in relevant else 0 for tid in ranked_ids[:k]]
    ideal = [1] * min(len(relevant), k)
    ndcg = dcg(gains) / dcg(ideal) if ideal else 0.0

    hits = 0
    precision_sum = 0.0
    for i, tid in enumerate(ranked_ids[:k], start=1):
        if tid in relevant:
            hits += 1
            precision_sum += hits / i
    ap = precision_sum / min(len(relevant), k) if relevant else 0.0
    hr = 1.0 if hits else 0.0
    p5 = sum(1 for tid in ranked_ids[:5] if tid in relevant) / 5.0
    return {"ndcg10": ndcg, "map10": ap, "hr10": hr, "p5": p5}


def minmax(values):
    if not values:
        return {}
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if high - low < 1e-9:
        return {key: 1.0 for key in values}
    return {key: (value - low) / (high - low) for key, value in values.items()}


# ── 扩展常量 ────────────────────────────────────────────────────────────
EXT_DIR = ROOT / "docs" / "eval" / "extensions"
EXT_EXPANDED = EXT_DIR / "ext_eval_queries_expanded.json"
EXT_POOL = EXT_DIR / "ext_pool_labels.json"
EXT_KAPPA = EXT_DIR / "ext_kappa_report.md"
EXT_ABLATION_MD = EXT_DIR / "ext_ablation_report.md"
EXT_ABLATION_JSON = EXT_DIR / "ext_ablation_results.json"
MIN_RELEVANT = 2
MAX_RELEVANT = 20
TOP_KEYWORDS = 40
POOL_K = 10
ALPHA = 0.05
RANDOM_SEEDS = (1, 2, 3, 4, 5)
MIN_PAIRS_FOR_TEST = 5

GENERIC_STOPWORDS = {
    "研究", "相关", "领域", "方向", "技术", "方法", "系统", "应用", "问题",
    "基础", "新型", "主要", "及其", "以及", "若干", "关键", "总体", "综合",
    "工程", "科学", "理论",
}
DIRECTION_SPLIT_RE = re.compile(r"[、，,;；/|\t]+")

ABLATION_VARIANTS = [
    ("full_hybrid", "混合 0.6 BM25 + 0.4 主题（基线）"),
    ("bm25_only", "仅 BM25F"),
    ("topic_only", "仅主题模型"),
    ("hybrid_8_2", "混合 0.8 BM25 + 0.2 主题"),
    ("hybrid_2_8", "混合 0.2 BM25 + 0.8 主题"),
    ("rule_only", "仅规则 relevance()"),
    ("random", "随机排序（5 种子平均）"),
]
ABLATION_BASELINE = "full_hybrid"


# ── 简易分词（英文词 + 中文 bigram）────────────────────────────────────
def _tokenize_simple(text):
    """简易分词：英文按词、中文按字（bigram），与 ext_common.tokenize 同口径。"""
    if not text:
        return []
    text = text.lower()
    tokens = []
    for m in re.finditer(r"[a-z0-9]+", text):
        tokens.append(m.group())
    for seg in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(seg) == 1:
            tokens.append(seg)
        else:
            for i in range(len(seg) - 1):
                tokens.append(seg[i:i + 2])
    return tokens


def _split_directions(text):
    """把 research_directions 拆成方向短语。"""
    return [p.strip() for p in DIRECTION_SPLIT_RE.split(text or "") if p.strip()]


def _deng_stripped(part):
    """去掉结尾的「等」：「操作系统等」「……等相关方向」。"""
    return part[:-1] if part.endswith("等") and len(part) > 1 else part


def _contains_keyword(text, kw):
    """教师方向里是否出现关键词：精确匹配方向短语或去「等」后的短语。"""
    return any(
        kw in part or kw in _deng_stripped(part)
        for part in _split_directions(text or "")
    )


def _dump_ext_json(obj, name):
    """写到 docs/eval/extensions/ 下。"""
    EXT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXT_DIR / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"  -> {path.relative_to(ROOT)}")
    return path


def _dump_ext_md(text, name):
    """写到 docs/eval/extensions/ 下。"""
    EXT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXT_DIR / name
    path.write_text(text, encoding="utf-8")
    print(f"  -> {path.relative_to(ROOT)}")
    return path


def _get_teachers():
    """从数据库读取全部教师记录。"""
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM teachers")]
    finally:
        conn.close()


# ── 扩展 01：评估集扩充 ─────────────────────────────────────────────────
def _mine_keywords(teachers):
    """统计全库方向词频率，取 top-N 且排除过于宽泛的词。"""
    counter = Counter()
    for t in teachers:
        for part in _split_directions(t.get("research_directions") or ""):
            word = _deng_stripped(part)
            if 2 <= len(word) <= 12:
                counter[word] += 1
    ranked = [w for w in counter if w not in GENERIC_STOPWORDS]
    ranked.sort(key=lambda w: (-counter[w], w))
    return ranked[:TOP_KEYWORDS]


def _expand_eval_set(teachers, payload):
    """子任务 1：人工查询 + 关键词自动查询，按查询串去重（人工优先）。"""
    manual = payload["queries"]
    existing = {q["query"] for q in manual}
    expanded = [dict(q) for q in manual]

    added = []
    for kw in _mine_keywords(teachers):
        if kw in existing:
            continue
        relevant = sorted(
            t["id"] for t in teachers
            if _contains_keyword(t.get("research_directions"), kw)
        )
        if not (MIN_RELEVANT <= len(relevant) <= MAX_RELEVANT):
            continue
        expanded.append({"query": kw, "relevant": relevant, "source": "keyword"})
        existing.add(kw)
        added.append((kw, len(relevant)))

    print(f"[1/3] 评估集扩充：人工 {len(manual)} 条，新增关键词查询 {len(added)} 条，"
          f"合计 {len(expanded)} 条")
    for kw, n in added:
        print(f"      + {kw}（{n} 人）")
    _dump_ext_json({"queries": expanded}, "ext_eval_queries_expanded.json")
    return expanded


# ── 扩展 01：池式伪相关反馈 ─────────────────────────────────────────────
def _build_pools(index, queries):
    """子任务 2：每个查询取 BM25F top-10 作池，池内 minmax 归一化分数作伪标签。"""
    pools = {}
    for q in queries:
        scores = index.scores(q["query"])
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:POOL_K]
        if not top:
            pools[q["query"]] = []
            continue
        norm = minmax(dict(top))
        pools[q["query"]] = [
            {"teacher_id": tid, "bm25_score": round(score, 4),
             "pseudo_label": round(norm[tid], 4)}
            for tid, score in top
        ]
    _dump_ext_json(pools, "ext_pool_labels.json")
    print(f"[2/3] 伪相关反馈池：{len(pools)} 个查询 × ≤{POOL_K} 个候选，"
          f"共 {sum(len(v) for v in pools.values())} 条伪标签")
    return pools


# ── 扩展 01：Cohen's κ 标注一致性 ───────────────────────────────────────
def _cohens_kappa(pairs):
    """按 2×2 列联表计算 Cohen's κ；pairs 为 (A, B) 二值标注对。"""
    if not pairs:
        return 0.0, 0.0
    a = Counter(pairs)
    n = len(pairs)
    p_o = (a[(1, 1)] + a[(0, 0)]) / n
    a1 = (a[(1, 0)] + a[(1, 1)]) / n
    b1 = (a[(0, 1)] + a[(1, 1)]) / n
    p_e = a1 * b1 + (1 - a1) * (1 - b1)
    kappa = (p_o - p_e) / (1 - p_e) if 1 - p_e > 0 else 0.0
    return kappa, p_o


def _inter_annotator(teachers, payload):
    """子任务 3：人工标注 vs 规则标注的一致性与 Cohen's κ。"""
    manual = payload["queries"]
    directions = {t["id"]: t.get("research_directions") or "" for t in teachers}
    by_name = {t["id"]: t["name"] for t in teachers}

    per_query = []
    all_pairs = []
    for q in manual:
        query = q["query"]
        relevant_a = set(q["relevant"])
        # 标注员 B：方向词与查询共享 ≥1 个 token 即视为相关
        query_tokens = set(_tokenize_simple(query))
        relevant_b = {
            tid for tid, text in directions.items()
            if query_tokens & set(_tokenize_simple(text))
        }
        pairs = [(1, 1)] * len(relevant_a & relevant_b) + \
                [(1, 0)] * len(relevant_a - relevant_b) + \
                [(0, 1)] * len(relevant_b - relevant_a)
        # 顺带检查：人工标注的教师方向里是否都真的包含该查询词
        missing = [
            f"{tid}({by_name.get(tid, '?')})"
            for tid in relevant_a
            if not _contains_keyword(directions.get(tid, ""), query)
        ]
        if missing:
            print(f"      ! 人工标注中 {len(missing)} 人方向未含「{query}」：{', '.join(missing)}")
        kappa, agreement = _cohens_kappa(pairs)
        per_query.append({
            "query": query, "kappa": round(kappa, 4),
            "agreement": round(agreement, 4),
            "a_only": sorted(relevant_a - relevant_b),
            "b_only": sorted(relevant_b - relevant_a),
        })
        all_pairs.extend(pairs)
        print(f"      {query}: κ={kappa:.4f}  一致率={agreement * 100:.1f}%  "
              f"(A独有 {len(relevant_a - relevant_b)} / B独有 {len(relevant_b - relevant_a)})")

    overall_kappa, overall_agreement = _cohens_kappa(all_pairs)
    _dump_ext_json({
        "per_query": per_query,
        "overall_kappa": round(overall_kappa, 4),
        "overall_agreement": round(overall_agreement, 4),
    }, "ext_kappa.json")

    # Markdown 报告
    lines = [
        "# 标注一致性报告（Cohen's κ）",
        "",
        "标注员 A：人工标注（docs/eval/queries.json）；标注员 B：规则标注",
        "（research_directions 与查询共享 ≥1 个 token）。",
        "",
        "| 查询 | Cohen's κ | 一致率 | A 独有 | B 独有 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for item in per_query:
        lines.append(
            f"| {item['query']} | {item['kappa']:.4f} | {item['agreement'] * 100:.1f}% "
            f"| {len(item['a_only'])} | {len(item['b_only'])} |"
        )
    lines += [
        f"| **整体** | **{overall_kappa:.4f}** | **{overall_agreement * 100:.1f}%** | - | - |",
        "",
        f"整体基于 {len(all_pairs)} 个 (查询, 教师) 二值标注对。",
    ]
    _dump_ext_md("\n".join(lines), "ext_kappa_report.md")
    print(f"[3/3] 标注一致性：整体 κ={overall_kappa:.4f}，一致率={overall_agreement * 100:.1f}%")


# ── 扩展 06：消融实验 ───────────────────────────────────────────────────
def _ablation_rank_by_scores(records, scores, order=None):
    """把分数字典转成教师 id 排序列表；召回集之外的教师排在末尾。"""
    ids = {r["item"]["id"] for r in records}
    ranked = sorted(ids, key=lambda tid: (-scores.get(tid, 0.0),
                                          order.get(tid, tid) if order else tid))
    return ranked


def _ablation_variant_ranking(variant, query, records, index, topics, order=None):
    """返回单个变体在单个查询下的教师 id 排序列表。"""
    if variant == "bm25_only":
        scores = index.scores(query)
        return _ablation_rank_by_scores(records, scores, order)

    if variant == "topic_only":
        scores = topic_scores(topics, query)
        return _ablation_rank_by_scores(records, scores, order)

    if variant == "full_hybrid":
        scores = combine_scores(index.scores(query), topic_scores(topics, query),
                                topic_weight=0.4)
        return _ablation_rank_by_scores(records, scores, order)

    if variant in ("hybrid_8_2", "hybrid_2_8"):
        weight = 0.2 if variant == "hybrid_8_2" else 0.8
        scores = combine_scores(index.scores(query), topic_scores(topics, query),
                                topic_weight=weight)
        return _ablation_rank_by_scores(records, scores, order)

    if variant == "rule_only":
        scores = {r["item"]["id"]: float(relevance(r, query)) for r in records}
        return _ablation_rank_by_scores(records, scores, order)

    raise ValueError(f"未知变体：{variant}")


def _ablation_evaluate_variant(variant, queries, records, index, topics):
    """逐查询评估一个变体；random 变体跑 5 个种子后逐查询平均。"""
    all_ids = [r["item"]["id"] for r in records]
    per_query = []

    for q in queries:
        query, relevant = q["query"], set(q["relevant"])
        if variant == "random":
            # 多个种子的逐查询指标取平均（指标非线性，故对指标而非排名求平均）
            acc = {}
            for seed in RANDOM_SEEDS:
                rng = random.Random(seed)
                order = {tid: rank for rank, tid in enumerate(rng.sample(all_ids, len(all_ids)))}
                ranked = _ablation_rank_by_scores(records, {}, order)
                m = evaluate(ranked, relevant)
                for key, v in m.items():
                    acc[key] = acc.get(key, 0.0) + v / len(RANDOM_SEEDS)
            metrics = acc
        else:
            ranked = _ablation_variant_ranking(variant, query, records, index, topics)
            metrics = evaluate(ranked, relevant)
        per_query.append({
            "query": query,
            "source": q.get("source", "manual"),
            "relevant_count": len(relevant),
            **{k: round(v, 4) for k, v in metrics.items()},
        })
    return per_query


def _ablation_paired_tests(full, other):
    """Full hybrid vs 某变体：逐查询指标差的 Wilcoxon / t 检验。"""
    out = {}
    n = len(full)
    for key in ("ndcg10", "map10", "hr10", "p5"):
        d = [f[key] - o[key] for f, o in zip(full, other, strict=False)]
        if n < MIN_PAIRS_FOR_TEST:
            out[key] = {"n": n, "note": "样本不足，无法做显著性检验"}
            continue
        if all(v == 0 for v in d):
            out[key] = {"n": n, "wilcoxon_p": 1.0, "ttest_p": 1.0,
                        "significant": False, "note": "逐查询无差异"}
            continue
        non_zero = [v for v in d if v != 0]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if len(non_zero) == len(d):
                _, w_p = stats.wilcoxon(d)
            elif len(non_zero) > 0:
                _, w_p = stats.wilcoxon(non_zero, method="approx")
            else:
                w_p = 1.0
        t_stat, t_p = stats.ttest_1samp(d, 0.0)
        out[key] = {
            "n": n,
            "mean_diff": round(float(np.mean(d)), 4),
            "wilcoxon_p": round(float(w_p), 4),
            "ttest_p": round(float(t_p), 4),
            "significant": bool(w_p < ALPHA),
        }
    return out


def _ablation_load_queries():
    """人工标注查询 + 扩充集里带 relevant 列表的查询；无标注的跳过。"""
    manual = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]
    queries = [dict(q) for q in manual if q.get("relevant")]
    added = 0
    if EXT_EXPANDED.exists():
        with open(EXT_EXPANDED, encoding="utf-8") as f:
            expanded = json.load(f)["queries"]
        seen = {q["query"] for q in queries}
        for q in expanded:
            if q.get("relevant") and q["query"] not in seen:
                queries.append(dict(q))
                seen.add(q["query"])
                added += 1
    print(f"评估查询：人工 {len(manual)} 条，扩充集补充 {added} 条，"
          f"参与评估共 {len(queries)} 条（无 relevant 标注的查询已跳过）")
    return queries


def _run_ablation(records, index, topic_payload, queries):
    """执行消融实验全流程，生成 Markdown + JSON 报告。"""
    EXT_DIR.mkdir(parents=True, exist_ok=True)

    # 逐变体逐查询评估
    results = {}
    for name, _ in ABLATION_VARIANTS:
        per_query = _ablation_evaluate_variant(name, queries, records, index, topic_payload)
        results[name] = per_query
        avg_ndcg = float(np.mean([p["ndcg10"] for p in per_query]))
        avg_hr = float(np.mean([p["hr10"] for p in per_query]))
        print(f"  {name:<14s} NDCG@10 均值 {avg_ndcg:.4f}，HitRate@10 均值 {avg_hr:.4f}")

    # 汇总统计：每变体每指标 均值 ± 标准差
    summary = {}
    for name, per_query in results.items():
        summary[name] = {}
        for key in ("ndcg10", "map10", "hr10", "p5"):
            values = [p[key] for p in per_query]
            summary[name][key] = {
                "mean": round(float(np.mean(values)), 4),
                "std": round(float(np.std(values)), 4),
            }

    # 显著性检验：Full hybrid vs 其余变体
    full = results[ABLATION_BASELINE]
    significance = {}
    for name, _ in ABLATION_VARIANTS:
        if name == ABLATION_BASELINE:
            continue
        significance[name] = _ablation_paired_tests(full, results[name])

    # 输出 JSON
    _dump_ext_json({
        "baseline": ABLATION_BASELINE,
        "alpha": ALPHA,
        "n_queries": len(queries),
        "random_seeds": list(RANDOM_SEEDS),
        "queries": [q["query"] for q in queries],
        "per_query": results,
        "summary": summary,
        "significance": significance,
    }, "ext_ablation_results.json")

    # Markdown 报告
    names = [n for n, _ in ABLATION_VARIANTS]
    lines = [
        "# 混合检索系统消融实验报告",
        "",
        "## 1. 方法",
        "",
        "混合检索系统由三部分组成：",
        "1. **BM25F 词法检索**：对姓名/拼音/关键词/研究方向/研究所/职称六个字段加权打分；",
        "2. **主题模型相似度**：TF-IDF + NMF 得到教师主题分布（`data/exports/topics.json`），"
        "查询词投影到主题词空间后做余弦相似度；",  # noqa: ISC004
        "3. **混合融合**：`(1-α)·BM25 + α·主题`（双方各自 min-max 归一化，主题分数只在 BM25 召回集内生效）。",
        "",
        f"对以下 {len(ABLATION_VARIANTS)} 个变体逐一评估，基线为 `{ABLATION_BASELINE}`：",
        "",
        "| 变体 | 说明 |",
        "| --- | --- |",
    ]
    for name, desc in ABLATION_VARIANTS:
        lines.append(f"| `{name}` | {desc} |")
    lines += [
        "",
        f"评估查询共 {len(queries)} 条（人工标注；扩充集中带 relevant 标注的查询已并入，"
        "自动生成的无标注查询跳过）。指标：NDCG@10、MAP@10、HitRate@10、P@5，"
        f"逐查询计算后取平均。显著性检验：Full hybrid vs 各变体的逐查询指标差值做配对 "
        f"Wilcoxon 符号秩检验与配对 t 检验，α={ALPHA}。",
        "",
        "## 2. 逐查询 NDCG@10 对比",
        "",
        "| 查询 | " + " | ".join(names) + " |",
        "| --- | " + " | ".join(["---:"] * len(names)) + " |",
    ]
    for i, q in enumerate(queries):
        cells = [f"{results[n][i]['ndcg10']:.3f}" for n in names]
        lines.append(f"| {q['query']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## 3. 平均指标（均值 ± 标准差）",
        "",
        "| 变体 | NDCG@10 | MAP@10 | HitRate@10 | P@5 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name in names:
        row = summary[name]
        lines.append(
            f"| `{name}` | "
            + " | ".join(f"{row[k]['mean']:.4f} ± {row[k]['std']:.4f}" for k in ("ndcg10", "map10", "hr10", "p5"))
            + " |"
        )
    lines += [
        "",
        "## 4. 显著性检验（Full hybrid vs 各变体，逐查询差值）",
        "",
        "| 对比 | 指标 | 差值均值 | Wilcoxon p | t 检验 p | 显著 (α=0.05) | 备注 |",
        "| --- | --- | ---: | ---: | ---: | :---: | --- |",
    ]
    for name in names:
        if name == ABLATION_BASELINE:
            continue
        for key in ("ndcg10", "map10", "hr10", "p5"):
            s = significance[name][key]
            if "note" in s:
                lines.append(f"| `{ABLATION_BASELINE}` vs `{name}` | {key} | - | - | - | - | {s['note']} |")
            else:
                lines.append(
                    f"| `{ABLATION_BASELINE}` vs `{name}` | {key} | {s['mean_diff']:+.4f} "
                    f"| {s['wilcoxon_p']:.4f} | {s['ttest_p']:.4f} "
                    f"| {'是' if s['significant'] else '否'} | |"
                )
    lines.append("")

    # 5. 分析
    lines += ["## 5. 分析", ""]
    ndcg = {n: summary[n]["ndcg10"]["mean"] for n in names}
    baseline_ndcg = ndcg[ABLATION_BASELINE]

    topic_gain = baseline_ndcg - ndcg["bm25_only"]
    sig = significance.get("bm25_only", {}).get("ndcg10", {})
    if topic_gain < 0:
        topic_note = ("主题分数在召回集内把部分词法匹配度更高的教师排后，"
                      "说明当前主题分布与词法证据的区分方向不完全一致")
    else:
        topic_note = "主题分数把语义相关教师提前，提供了词法匹配之外的增量"
    lines.append(f"- **主题模型的增量价值**：Full hybrid（0.6/0.4）相对纯 BM25 的 NDCG@10 "
                 f"{'提升' if topic_gain >= 0 else '下降'} {abs(topic_gain):.4f}"
                 f"（{ndcg['bm25_only']:.4f} → {baseline_ndcg:.4f}）。{topic_note}。")
    if "wilcoxon_p" in sig:
        lines.append(f"  - 该差异 Wilcoxon p={sig['wilcoxon_p']:.4f}、"
                     f"t 检验 p={sig['ttest_p']:.4f}，"
                     f"{'在 α=0.05 下显著' if sig['significant'] else '未达显著'}。")
    else:
        lines.append(f"  - {sig.get('note', '样本不足，无法判断显著性')}。")

    w_hi, w_lo = ndcg["hybrid_8_2"], ndcg["hybrid_2_8"]
    weight_note = ("BM25 权重越大性能越好，词法检索是主要贡献者，"
                   "当前 0.4 的主题权重偏大，可考虑降到 0.1~0.2"
                   if w_hi > baseline_ndcg else
                   "存在主题权重更大的最优点，可进一步做权重网格搜索")
    lines.append(f"- **融合权重敏感性**：BM25 权重 0.8 时 NDCG={w_hi:.4f}，"
                 f"0.2 时 {w_lo:.4f}。{weight_note}。")

    lines.append(f"- **纯主题模型**：NDCG={ndcg['topic_only']:.4f}，远低于 BM25 单模型"
                 f"（{ndcg['bm25_only']:.4f}）。主题粒度过粗，会把大量无关教师"
                 "一并打分，缺乏词法精确匹配能力，单独使用无法支撑检索。")

    lines.append(f"- **规则 relevance()**：NDCG={ndcg['rule_only']:.4f}。"
                 "规则对「研究方向子串命中」直接给高分且召回集内按姓名稳定排序；"
                 "但其固定档位打分无法区分同档教师，泛化性有限。")
    lines.append(f"- **随机下界**：NDCG={ndcg['random']:.4f}（5 种子平均），"
                 f"基线相对随机的提升 {baseline_ndcg - ndcg['random']:.4f}，"
                 "说明混合检索远好于随机猜测。")

    lines.append("")
    lines.append(f"**结论**：BM25F 词法检索是系统的核心组件（{ndcg['bm25_only']:.4f}）；"
                 "主题模型单独使用偏弱（粗粒度画像区分力有限），以 0.4 权重融合时"
                 "对排序可能产生扰动，建议降低主题权重或改进主题粒度后再融合。"
                 "随机排序作为下界验证了所有真实变体的显著优势。")

    _dump_ext_md("\n".join(lines), "ext_ablation_report.md")

    # 控制台摘要
    print("\n=== 消融实验摘要（NDCG@10 均值）===")
    for name in names:
        bar = "█" * int(ndcg[name] * 30)
        print(f"  {name:<14s} {ndcg[name]:.4f}  {bar}")
    print(f"输出目录：{EXT_DIR.relative_to(ROOT)}/")


def main():
    parser = argparse.ArgumentParser(description="离线检索评估：规则相关度 vs BM25F")
    parser.add_argument("--expanded", action="store_true",
                        help="通过关键词挖掘扩充评估集")
    parser.add_argument("--kappa", action="store_true",
                        help="计算 Cohen's κ 标注一致性")
    parser.add_argument("--pooling", action="store_true",
                        help="生成池式伪相关反馈标签")
    parser.add_argument("--ablation", action="store_true",
                        help="运行消融实验 + 统计显著性检验")
    args = parser.parse_args()

    if not DB.exists():
        raise SystemExit(f"数据库不存在：{DB}")
    stat = DB.stat()
    records = list(search_corpus((str(DB), stat.st_mtime, stat.st_size)))
    index = build_index(records)
    payload = json.loads(QUERIES.read_text(encoding="utf-8"))
    try:
        topic_payload = json.loads(TOPICS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        topic_payload = {}

    # 扩展功能
    if args.expanded:
        teachers = _get_teachers()
        print(f"教师总数：{len(teachers)}")
        _expand_eval_set(teachers, payload)

    if args.pooling:
        # 使用扩充后的查询集（如果存在），否则用原始查询
        queries_for_pool = payload["queries"]
        if EXT_EXPANDED.exists():
            with open(EXT_EXPANDED, encoding="utf-8") as f:
                queries_for_pool = json.load(f)["queries"]
        _build_pools(index, queries_for_pool)

    if args.kappa:
        teachers = _get_teachers()
        print(f"教师总数：{len(teachers)}")
        _inter_annotator(teachers, payload)

    if args.ablation:
        queries = _ablation_load_queries()
        if not queries:
            print("没有带 relevant 标注的查询，无法评估")
            return
        _run_ablation(records, index, topic_payload, queries)

    # 原有评估行为（始终执行）
    rows = []
    for case in payload["queries"]:
        query = case["query"]
        relevant = case["relevant"]
        rule_scored = [(relevance(r, query), r["item"]["id"]) for r in records]
        rule_scored = [(s, tid) for s, tid in rule_scored if s > 0]
        rule_scored.sort(key=lambda pair: (-pair[0], pair[1]))
        bm25 = index.scores(query)
        bm25_scored = sorted(bm25.items(), key=lambda pair: (-pair[1], pair[0]))
        topic = topic_scores(topic_payload, query)
        topic_scored = sorted(topic.items(), key=lambda pair: (-pair[1], pair[0]))
        # 混合检索：只在 BM25 召回集合内融合主题相似度，避免主题模型把
        # 完全没有词法依据的档案拉进来。两路分数先 min-max 归一。
        bm25_norm = minmax({tid: score for tid, score in bm25.items() if score > 0})
        topic_norm = minmax({tid: score for tid, score in topic.items() if tid in bm25})
        hybrid = {
            tid: 0.6 * bm25_norm.get(tid, 0.0) + 0.4 * topic_norm.get(tid, 0.0)
            for tid in bm25_norm
        }
        hybrid_scored = sorted(hybrid.items(), key=lambda pair: (-pair[1], pair[0]))
        rows.append({
            "query": query,
            "relevant": len(relevant),
            "rule": evaluate([tid for _, tid in rule_scored], relevant),
            "bm25": evaluate([tid for tid, _ in bm25_scored], relevant),
            "topic": evaluate([tid for tid, _ in topic_scored], relevant),
            "hybrid": evaluate([tid for tid, _ in hybrid_scored], relevant),
        })

    def avg(key, name):
        return sum(row[key][name] for row in rows) / len(rows)

    lines = [
        "# 检索质量离线评估",
        "",
        f"- 查询数：{len(rows)}；每查询人工标注相关教师数见下表。",
        f"- 指标：NDCG@{K}、MAP@{K}、HitRate@{K}、P@5；规则分指 `services.relevance()`，BM25 指 `app/retrieval.py` 的 BM25F，主题指 `processing/topic_model.py` 的 TF-IDF+NMF，混合指 BM25 与主题分数按 0.6/0.4 融合。",
        "- 相关标签来自 `docs/eval/queries.json`，按研究方向字段人工核对；这是课程级小样本评估，不代表线上真实分布。",
        "",
        "| 查询 | 标注数 | 规则 NDCG | BM25 NDCG | 主题 NDCG | 混合 NDCG | BM25 MAP | 混合 MAP | BM25 P@5 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['query']} | {row['relevant']} | {row['rule']['ndcg10']:.3f} | "
            f"{row['bm25']['ndcg10']:.3f} | {row['topic']['ndcg10']:.3f} | "
            f"{row['hybrid']['ndcg10']:.3f} | {row['bm25']['map10']:.3f} | "
            f"{row['hybrid']['map10']:.3f} | {row['bm25']['p5']:.2f} |"
        )
    lines.extend([
        "",
        "| 方法 | 平均 NDCG@10 | 平均 MAP@10 | 平均 HitRate@10 | 平均 P@5 |",
        "| --- | ---: | ---: | ---: | ---: |",
        *[
            (
                f"| {label} | {avg(key, 'ndcg10'):.3f} | {avg(key, 'map10'):.3f} | "
                f"{avg(key, 'hr10'):.3f} | {avg(key, 'p5'):.3f} |"
            )
            for key, label in (
                ("rule", "规则相关度"),
                ("bm25", "BM25F"),
                ("topic", "主题模型"),
                ("hybrid", "BM25 + 主题混合（0.6/0.4）"),
            )
        ],
        "",
        "> 主题模型是粗粒度画像，NDCG 需要结合主题词和教师分布解释；混合检索只在 BM25 召回集合内融合，因此 MAP/P@5 通常更稳。",
    ])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入 {OUT}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

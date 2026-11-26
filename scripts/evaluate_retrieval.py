# -*- coding: utf-8 -*-
"""离线检索评估：规则相关度 vs BM25F。

用法（在项目根目录）：
    python scripts/evaluate_retrieval.py

数据来自 docs/eval/queries.json（人工核对研究方向后标注的相关教师），
指标为 NDCG@10、MAP@10、HitRate@10 与 P@5；结果写到 docs/eval/results.md。
这是课程式的「小规模、可复现」评估，不宣称是完整基准。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.mining import topic_scores  # noqa: E402
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


def main():
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

"""合并脚本：LambdaMART 学习排序 + 学生画像个性化推荐。

用法（项目根目录）：
    python scripts/recommendation_extensions.py --ltr
    python scripts/recommendation_extensions.py --student-profile
    python scripts/recommendation_extensions.py --student-profile --profile my_profile.json

输出（docs/eval/extensions/）：
    LTR: ltr_model.txt, ext_ltr_importance.json, ext_ltr_report.md
    Student: ext_student_profiles_results.json, ext_student_profile_report.md
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sqlite3
import sys
from pathlib import Path

# 确保能从项目根目录导入 app 包
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "db" / "mentor.db"
OUT_DIR = ROOT / "docs" / "eval" / "extensions"
QUERIES_FILE = ROOT / "docs" / "eval" / "queries.json"

import lightgbm as lgb
import numpy as np

from app.retrieval import build_index
from app.services import search_corpus

# ---------------------------------------------------------------------------
# 共享工具函数（内联，避免依赖 extensions/ 目录）
# ---------------------------------------------------------------------------

# 简易中文分词：按字/词切分，用于文本相似度
_STOP_RE = re.compile(r"[\s,，。.;；:：、!！?？()（）\[\]【】\"'`~@#\$%\^&\*\+=\-\_\\\|/\\{}]")


def tokenize(text: str) -> list[str]:
    """简易分词：英文按词、中文按字（bigram），去停用符。"""
    if not text:
        return []
    text = text.lower()
    tokens = []
    # 英文单词
    for m in re.finditer(r"[a-z0-9]+", text):
        tokens.append(m.group())
    # 中文 bigram
    cn = re.findall(r"[\u4e00-\u9fff]+", text)
    for seg in cn:
        if len(seg) == 1:
            tokens.append(seg)
        else:
            for i in range(len(seg) - 1):
                tokens.append(seg[i:i+2])
    return tokens


def minmax(values: dict) -> dict:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi - lo < 1e-9:
        return {k: 1.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def ndcg(reanked, relevant: set, k: int = 10) -> float:
    gains = [1.0 if t in relevant else 0.0 for t in reanked[:k]]
    dcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))
    ideal_n = min(len(relevant), k)
    idcg = sum((2**1 - 1) / math.log2(i + 2) for i in range(ideal_n))
    return dcg / idcg if idcg else 0.0


def map_at_k(reanked, relevant: set, k: int = 10) -> float:
    hits = 0
    psum = 0.0
    for i, t in enumerate(reanked[:k], 1):
        if t in relevant:
            hits += 1
            psum += hits / i
    return psum / min(len(relevant), k) if relevant else 0.0


def hit_rate(reanked, relevant: set, k: int = 10) -> float:
    return 1.0 if any(t in relevant for t in reanked[:k]) else 0.0


def precision_at_k(reanked, relevant: set, k: int = 5) -> float:
    return sum(1 for t in reanked[:k] if t in relevant) / k


def evaluate_ranking(reanked, relevant: set, k: int = 10) -> dict:
    return {
        "ndcg": ndcg(reanked, relevant, k),
        "map": map_at_k(reanked, relevant, k),
        "hr": hit_rate(reanked, relevant, k),
        "p5": precision_at_k(reanked, relevant, 5),
    }


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def load_queries() -> list[dict]:
    with open(QUERIES_FILE, encoding="utf-8") as f:
        return json.load(f)["queries"]


def ensure_out_dir():
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def dump_json(obj, name: str):
    """写到 docs/eval/extensions/ 下。"""
    ensure_out_dir()
    path = OUT_DIR / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"  -> {path.relative_to(ROOT)}")
    return path


def dump_md(text: str, name: str):
    ensure_out_dir()
    path = OUT_DIR / name
    path.write_text(text, encoding="utf-8")
    print(f"  -> {path.relative_to(ROOT)}")
    return path


# ---------------------------------------------------------------------------
# LTR（LambdaMART）常量
# ---------------------------------------------------------------------------
CANDIDATE_TOP_K = 50   # 每条查询取 BM25 前 50 作为候选集
RANDOM_STATE = 42
TRAIN_RATIO = 0.8

FEATURE_NAMES = [
    "bm25_score",
    "bm25_rank_inv",
    "token_overlap",
    "token_overlap_kw",
    "token_overlap_institute",
    "title_match",
    "name_match",
    "h_index_norm",
    "citation_norm",
    "paper_count_norm",
    "processing_score_norm",
    "teaching_norm",
    "is_phd_advisor",
    "honor_count",
]


# ---------------------------------------------------------------------------
# LTR 数据加载
# ---------------------------------------------------------------------------
def load_expanded_queries() -> list[dict]:
    """优先加载 ext_01 生成的扩展查询集，否则回退到原始 10 条。"""
    expanded_path = OUT_DIR / "ext_eval_queries_expanded.json"
    if expanded_path.exists():
        with open(expanded_path, encoding="utf-8") as f:
            data = json.load(f)
        # 兼容两种格式：{"queries": [...]} 或 直接 [...]
        if isinstance(data, dict) and "queries" in data:
            return data["queries"]
        return data
    print("[info] 未找到 ext_eval_queries_expanded.json，使用原始 queries.json")
    return load_queries()


def load_pool_labels() -> dict:
    """加载 ext_01 生成的 pool 伪标签（query → {teacher_id: pseudo_label}）。"""
    pool_path = OUT_DIR / "ext_pool_labels.json"
    if pool_path.exists():
        with open(pool_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def build_records() -> list[dict]:
    """加载检索语料（与 services.search_corpus 一致）。"""
    st = os.stat(str(DB_PATH))
    stamp = (str(DB_PATH), st.st_mtime, st.st_size)
    return list(search_corpus(stamp))


# ---------------------------------------------------------------------------
# LTR 特征提取
# ---------------------------------------------------------------------------
def compute_global_stats(records: list[dict]) -> dict:
    """计算全局归一化用的极值。"""
    max_h, max_cite, max_paper, max_score, max_teaching = 0, 0, 0, 0, 0
    for rec in records:
        item = rec["item"]
        max_h = max(max_h, item.get("h_index") or 0)
        max_cite = max(max_cite, item.get("citation_count") or 0)
        max_paper = max(max_paper, item.get("paper_count") or 0)
        max_score = max(max_score, item.get("score") or 0)
        max_teaching = max(max_teaching, (item.get("rating") or {}).get("avg") or 0)
    return {
        "max_h": max_h or 1,
        "max_cite": max_cite or 1,
        "max_paper": max_paper or 1,
        "max_score": max_score or 1,
        "max_teaching": max_teaching or 1,
    }


def extract_features(
    query: str,
    rec: dict,
    bm25_scores: dict,
    bm25_rank: dict,
    q_tokens: set,
    global_stats: dict,
) -> list:
    """为 (query, teacher) 对提取 14 维特征向量。"""
    item = rec["item"]
    tid = item["id"]

    # --- BM25 相关 ---
    bs = float(bm25_scores.get(tid, 0.0))
    b_rank = bm25_rank.get(tid)
    bm25_rank_inv = 1.0 / (1 + b_rank) if b_rank is not None else 0.0

    # --- token 重叠 ---
    def _overlap(field_text: str) -> float:
        if not q_tokens or not field_text:
            return 0.0
        field_tokens = set(tokenize(field_text))
        if not field_tokens:
            return 0.0
        inter = q_tokens & field_tokens
        return len(inter) / len(q_tokens)

    directions = item.get("research_directions") or ""
    keywords = item.get("keywords") or []
    keywords_text = " ".join(str(k) for k in keywords)
    institute = item.get("institute") or ""

    token_overlap = _overlap(directions)
    token_overlap_kw = _overlap(keywords_text) / max(1, len(q_tokens)) if q_tokens else 0.0
    token_overlap_institute = _overlap(institute) / max(1, len(q_tokens)) if q_tokens else 0.0

    # --- 标题 / 姓名匹配 ---
    title_lower = (item.get("title") or "").lower()
    title_match = 1.0 if query.lower() in title_lower else 0.0

    name = item.get("name") or ""
    name_match = 1.0 if any(tok in name for tok in q_tokens) else 0.0

    # --- 学术指标归一化 ---
    h = item.get("h_index") or 0
    c = item.get("citation_count") or 0
    p = item.get("paper_count") or 0
    s = item.get("score") or 0
    t = (item.get("rating") or {}).get("avg") or 0

    h_norm = h / global_stats["max_h"]
    cite_norm = math.log1p(c) / math.log1p(global_stats["max_cite"])
    paper_norm = p / global_stats["max_paper"]
    score_norm = s / global_stats["max_score"]
    teaching_norm = t / global_stats["max_teaching"]

    # --- 其他 ---
    is_phd = 1.0 if item.get("is_phd_advisor") else 0.0
    honors = item.get("honors") or []
    honor_count = float(len(honors))

    return [
        bs, bm25_rank_inv,
        token_overlap, token_overlap_kw, token_overlap_institute,
        title_match, name_match,
        h_norm, cite_norm, paper_norm, score_norm, teaching_norm,
        is_phd, honor_count,
    ]


# ---------------------------------------------------------------------------
# LTR 相关性标签
# ---------------------------------------------------------------------------
def get_relevant_set(q: dict, bm25_ranked: list, pool_labels: dict) -> set:
    """
    确定一条查询的 relevant 教师 ID 集合：
    - 有人工标注 → 直接用
    - 有 pool 伪标签 → 取 pseudo_label > median 的
    - 兜底 → BM25 top-10
    """
    relevant = set(q.get("relevant", []))
    if relevant:
        return relevant

    query_text = q["query"]
    pseudo = pool_labels.get(query_text, {})
    if pseudo:
        pseudo_vals = [pseudo[tid] for tid, _ in bm25_ranked if tid in pseudo]
        if pseudo_vals:
            median_val = float(np.median(pseudo_vals))
            return {tid for tid, _ in bm25_ranked if pseudo.get(tid, 0) > median_val}

    # BM25 rank 兜底：top-10
    return {tid for tid, _ in bm25_ranked[:10]}


# ---------------------------------------------------------------------------
# LTR 训练数据构建
# ---------------------------------------------------------------------------
def build_training_data(
    queries: list,
    records: list,
    bm25_idx,
    pool_labels: dict,
    global_stats: dict,
) -> tuple:
    """
    返回 (X_flat, labels, group_sizes, query_meta)。
    每条查询取 BM25 top-50 作为候选集。
    query_meta: [(query_dict, candidate_tids, relevant_set), ...]
    """
    rec_map = {r["item"]["id"]: r for r in records}
    X_flat = []
    labels = []
    group_sizes = []
    query_meta = []

    for q in queries:
        query_text = q["query"]
        q_tokens = set(tokenize(query_text))

        # BM25 打分 + top-50
        bm25_scores = bm25_idx.scores(query_text)
        ranked = sorted(bm25_scores.items(), key=lambda x: -x[1])[:CANDIDATE_TOP_K]
        if not ranked:
            continue
        bm25_rank = {tid: i for i, (tid, _) in enumerate(ranked, start=1)}

        # 确定 relevant set（用于标签和后续评估）
        relevant = get_relevant_set(q, ranked, pool_labels)

        # 计算 pool 伪标签中位数（用于二值化）
        pseudo = pool_labels.get(query_text, {})
        pseudo_vals = [pseudo[tid] for tid, _ in ranked if tid in pseudo]
        median_val = float(np.median(pseudo_vals)) if pseudo_vals else None

        group_feats = []
        for tid, _ in ranked:
            rec = rec_map.get(tid)
            if rec is None:
                continue
            feats = extract_features(query_text, rec, bm25_scores, bm25_rank, q_tokens, global_stats)

            # 相关性标签
            if q.get("relevant"):
                # 有人工标注：good=2, bad=0
                label = 2 if tid in relevant else 0
            elif median_val is not None:
                # pool 伪标签二值化
                label = 1 if pseudo[tid] > median_val else 0
            else:
                # BM25 rank 兜底
                label = 1 if bm25_rank[tid] <= 10 else 0

            group_feats.append(feats)
            labels.append(label)

        if not group_feats:
            continue

        X_flat.extend(group_feats)
        group_sizes.append(len(group_feats))
        query_meta.append((q, [tid for tid, _ in ranked], relevant))

    return X_flat, labels, group_sizes, query_meta


# ---------------------------------------------------------------------------
# LTR 评估
# ---------------------------------------------------------------------------
def ranking_metrics(order: list, relevant: set) -> dict:
    """对给定排序计算 NDCG/MAP/HR/P@5 指标。"""
    if not relevant:
        return {"ndcg1": 0.0, "ndcg5": 0.0, "ndcg10": 0.0,
                "map10": 0.0, "hr10": 0.0, "p5": 0.0}
    return {
        "ndcg1": ndcg(order, relevant, k=1),
        "ndcg5": ndcg(order, relevant, k=5),
        "ndcg10": ndcg(order, relevant, k=10),
        "map10": map_at_k(order, relevant, k=10),
        "hr10": hit_rate(order, relevant, k=10),
        "p5": precision_at_k(order, relevant, k=5),
    }


# ---------------------------------------------------------------------------
# LTR 主流程
# ---------------------------------------------------------------------------
def run_ltr():
    print("=" * 60)
    print("LambdaMART 学习排序")
    print("=" * 60)

    ensure_out_dir()

    # 1. 加载数据
    print("\n[1/6] 加载数据...")
    queries = load_expanded_queries()
    print(f"  查询数量: {len(queries)}")

    records = build_records()
    print(f"  教师记录数: {len(records)}")

    pool_labels = load_pool_labels()
    if pool_labels:
        print(f"  Pool 伪标签: {len(pool_labels)} 条查询")

    # 2. 构建 BM25 索引
    print("\n[2/6] 构建 BM25 索引...")
    bm25_idx = build_index(records)
    print("  完成")

    # 3. 全局统计
    global_stats = compute_global_stats(records)
    print(f"  max_h={global_stats['max_h']}, max_cite={global_stats['max_cite']}, "
          f"max_paper={global_stats['max_paper']}, max_score={global_stats['max_score']}")

    # 4. 构建训练数据
    print("\n[3/6] 构建训练数据...")
    X_flat, labels, group_sizes, query_meta = build_training_data(
        queries, records, bm25_idx, pool_labels, global_stats
    )
    n_samples = len(labels)
    n_queries = len(group_sizes)
    print(f"  样本数: {n_samples}, 查询组数: {n_queries}")
    label_dist = {i: labels.count(i) for i in sorted(set(labels))}
    print(f"  标签分布: {label_dist}")

    if n_samples == 0:
        print("[error] 无有效训练样本，退出")
        return

    X = np.array(X_flat, dtype=np.float32).reshape(n_samples, -1)
    y = np.array(labels, dtype=np.float32)

    # 5. 划分 train/test（按查询组）
    print("\n[4/6] 划分训练/测试集...")
    all_idx = list(range(n_queries))
    random.seed(RANDOM_STATE)
    random.shuffle(all_idx)

    n_train = max(1, int(n_queries * TRAIN_RATIO))
    train_query_idx = all_idx[:n_train]
    test_query_idx = all_idx[n_train:]

    use_all_for_train = len(test_query_idx) < 2
    if use_all_for_train:
        print(f"  [note] 测试集仅 {len(test_query_idx)} 条查询（<2），使用全部查询训练")
        train_query_idx = list(range(n_queries))
        test_query_idx = list(range(n_queries))

    def _flatten(query_idx_list):
        """将查询索引列表展平为 (样本索引列表, 组大小列表)。"""
        sample_idx = []
        groups = []
        for qi in query_idx_list:
            offset = sum(group_sizes[:qi])
            sample_idx.extend(range(offset, offset + group_sizes[qi]))
            groups.append(group_sizes[qi])
        return sample_idx, groups

    train_samples, train_groups = _flatten(train_query_idx)
    test_samples, test_groups = _flatten(test_query_idx)

    X_train = X[train_samples]
    y_train = y[train_samples]
    X_test = X[test_samples] if test_samples else X_train
    y_test = y[test_samples] if test_samples else y_train
    eval_groups = test_groups if test_samples else train_groups

    print(f"  训练: {len(train_samples)} 样本 / {len(train_groups)} 查询")
    print(f"  测试: {len(test_samples)} 样本 / {len(test_groups)} 查询")

    # 6. 训练 LambdaMART
    print("\n[5/6] 训练 LightGBM LambdaMART...")
    model = lgb.LGBMRanker(
        objective="lambdarank",
        metric="ndcg",
        ndcg_eval_at=[1, 5, 10],
        learning_rate=0.05,
        n_estimators=200,
        num_leaves=31,
        min_child_samples=5,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=RANDOM_STATE,
        verbose=-1,
    )
    model.fit(
        X_train,
        y_train,
        group=train_groups,
        eval_set=[(X_test, y_test)],
        eval_group=[eval_groups],
        callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False)],
    )
    best_iter = model.best_iteration_ if model.best_iteration_ > 0 else model.n_estimators_
    print(f"  最佳迭代: {best_iter}")

    # 特征重要性
    importance = dict(zip(FEATURE_NAMES, model.feature_importances_.tolist()))
    importance_sorted = sorted(importance.items(), key=lambda x: -x[1])
    print("\n  特征重要性 (top 5):")
    for name, imp in importance_sorted[:5]:
        print(f"    {name:25s} {imp:.0f}")

    # 7. 评估
    print("\n[6/6] 评估...")
    rec_map = {r["item"]["id"]: r for r in records}
    per_query_results = []

    for qi in test_query_idx:
        q, candidate_tids, relevant = query_meta[qi]
        query_text = q["query"]
        q_tokens = set(tokenize(query_text))

        # BM25 打分（重新计算以获取完整分数）
        bm25_scores = bm25_idx.scores(query_text)
        bm25_rank = {tid: i for i, tid in enumerate(candidate_tids, start=1)}

        # 提取特征并 LTR 打分
        feats_list = []
        valid_tids = []
        for tid in candidate_tids:
            rec = rec_map.get(tid)
            if rec is None:
                continue
            feats = extract_features(query_text, rec, bm25_scores, bm25_rank, q_tokens, global_stats)
            feats_list.append(feats)
            valid_tids.append(tid)

        if not feats_list:
            continue

        X_q = np.array(feats_list, dtype=np.float32)
        ltr_preds = model.predict(X_q)

        # LTR 排序（按预测分降序）
        ltr_order = [tid for tid, _ in sorted(zip(valid_tids, ltr_preds), key=lambda x: -x[1])]
        # BM25 排序（候选集本身已按 BM25 降序）
        bm25_order = valid_tids

        bm25_m = ranking_metrics(bm25_order, relevant)
        ltr_m = ranking_metrics(ltr_order, relevant)

        per_query_results.append({
            "query": query_text,
            "n_candidates": len(valid_tids),
            "bm25": bm25_m,
            "ltr": ltr_m,
            "delta_ndcg10": round(ltr_m["ndcg10"] - bm25_m["ndcg10"], 4),
        })

    # 汇总平均指标
    metric_keys = ["ndcg1", "ndcg5", "ndcg10", "map10", "hr10", "p5"]
    if per_query_results:
        avg_bm25 = {k: float(np.mean([r["bm25"][k] for r in per_query_results])) for k in metric_keys}
        avg_ltr = {k: float(np.mean([r["ltr"][k] for r in per_query_results])) for k in metric_keys}
    else:
        avg_bm25 = {k: 0.0 for k in metric_keys}
        avg_ltr = {k: 0.0 for k in metric_keys}

    # -----------------------------------------------------------------------
    # 输出
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("评估结果")
    print("=" * 60)
    print(f"\n{'查询':<12} {'BM25 NDCG@10':>12} {'LTR NDCG@10':>12} {'Delta':>8}")
    print("-" * 50)
    for r in per_query_results:
        print(f"{r['query']:<12} {r['bm25']['ndcg10']:>12.4f} {r['ltr']['ndcg10']:>12.4f} {r['delta_ndcg10']:>+8.4f}")

    print(f"\n{'指标':<12} {'BM25':>10} {'LambdaMART':>12}")
    print("-" * 36)
    for k in metric_keys:
        print(f"{k:<12} {avg_bm25[k]:>10.4f} {avg_ltr[k]:>12.4f}")

    # 保存特征重要性
    dump_json(importance_sorted, "ext_ltr_importance.json")

    # 生成报告
    report_lines = [
        "# LambdaMART 学习排序报告",
        "",
        "## 实验设置",
        f"- 查询数量: {len(queries)}（训练 {n_train} / 测试 {n_queries - n_train}）",
        f"- 候选集: 每条查询 BM25 top-{CANDIDATE_TOP_K}",
        f"- 总样本数: {n_samples}",
        f"- 特征维度: {len(FEATURE_NAMES)}",
        f"- 超参数: lr=0.05, n_estimators=200, num_leaves=31, min_child_samples=5, "
        f"subsample=0.8, colsample_bytree=0.8",
        "",
        "## 特征重要性 (Top 10)",
        "",
        "| 排名 | 特征 | 重要性 |",
        "|------|------|--------|",
    ]
    for i, (name, imp) in enumerate(importance_sorted[:10], 1):
        report_lines.append(f"| {i} | {name} | {imp:.0f} |")

    report_lines += [
        "",
        "## 逐查询对比",
        "",
        "| 查询 | BM25 NDCG@10 | LTR NDCG@10 | Delta |",
        "|------|--------------|-------------|-------|",
    ]
    for r in per_query_results:
        report_lines.append(
            f"| {r['query']} | {r['bm25']['ndcg10']:.4f} "
            f"| {r['ltr']['ndcg10']:.4f} | {r['delta_ndcg10']:+.4f} |"
        )

    report_lines += [
        "",
        "## 平均指标对比",
        "",
        "| 指标 | BM25 | LambdaMART | Delta |",
        "|------|------|------------|-------|",
    ]
    for k in metric_keys:
        delta = avg_ltr[k] - avg_bm25[k]
        report_lines.append(f"| {k} | {avg_bm25[k]:.4f} | {avg_ltr[k]:.4f} | {delta:+.4f} |")

    # 简要分析
    improved = sum(1 for r in per_query_results if r["delta_ndcg10"] > 0)
    degraded = sum(1 for r in per_query_results if r["delta_ndcg10"] < 0)
    delta_avg = avg_ltr["ndcg10"] - avg_bm25["ndcg10"]
    report_lines += [
        "",
        "## 分析",
        "",
        f"在 {len(per_query_results)} 条测试查询中，LambdaMART 在 {improved} 条上优于 BM25，"
        f"在 {degraded} 条上劣于 BM25。",
        f"平均 NDCG@10 变化: {delta_avg:+.4f}。",
    ]
    if delta_avg > 0:
        report_lines.append(
            "LambdaMART 通过融合 BM25 分数与学术指标（h-index、引用数、论文数等），"
            "在学术相关度排序上有一定提升，说明教师学术影响力特征对检索排序有正向贡献。"
        )
    elif delta_avg < 0:
        report_lines.append(
            "LambdaMART 在本次实验中未优于 BM25 基线，可能原因包括：训练数据量较小、"
            "伪标签噪声较大、或学术指标与查询相关度之间缺乏强相关性。"
        )
    else:
        report_lines.append("两种方法表现相当，学术指标特征未带来显著增益。")

    dump_md("\n".join(report_lines), "ext_ltr_report.md")

    # 最后保存模型（LightGBM C API 写文件，沙箱可能阻止，已 try 保护）
    model_path = OUT_DIR / "ltr_model.txt"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        model.booster_.save_model(str(model_path))
        print(f"  -> 模型已保存: {model_path.relative_to(ROOT)}")
    except Exception as e:
        print(f"  [warn] 模型保存失败（沙箱写入限制）: {e}")

    print("\n[done] 全部完成")


# ===========================================================================
# 学生画像 → 个性化导师推荐（基于内容的协同过滤）
# ===========================================================================

# ---------------------------------------------------------------------------
# 学生画像定义
# ---------------------------------------------------------------------------
DEFAULT_PROFILE = {
    "research_interests": ["计算机视觉", "深度学习"],
    "preferred_college": None,
    "preferred_institute": None,
    "wants_phd_advisor": False,
    "weight_academic": 0.5,
    "weight_teaching": 0.3,
    "weight_research_match": 0.2,
}


def normalize_profile(p: dict) -> dict:
    """补全缺失字段，返回完整画像。"""
    merged = dict(DEFAULT_PROFILE)
    merged.update(p)
    # 权重归一化（保持比例不变，总和为 1）
    w = merged["weight_academic"] + merged["weight_teaching"] + merged["weight_research_match"]
    if w <= 0:
        merged["weight_academic"] = 0.5
        merged["weight_teaching"] = 0.3
        merged["weight_research_match"] = 0.2
    else:
        merged["weight_academic"] /= w
        merged["weight_teaching"] /= w
        merged["weight_research_match"] /= w
    return merged


# ---------------------------------------------------------------------------
# 核心推荐函数
# ---------------------------------------------------------------------------
def recommend(student_profile: dict, conn: sqlite3.Connection) -> list[dict]:
    """基于学生画像，返回按最终分数降序排列的导师推荐列表。

    每个元素：
        {
          "id", "name", "college", "institute",
          "research_match", "academic", "teaching", "final_score",
          "score_parts": {...}
        }
    """
    profile = normalize_profile(student_profile)
    cur = conn.cursor()

    # ---- 1. 拉取全部教师 + 处理表数据 ------------------------------------
    cur.execute(
        """
        SELECT t.id, t.name, t.college, t.institute, t.research_directions,
               t.is_phd_advisor,
               p.score, p.teaching_score, p.keywords
        FROM teachers t
        LEFT JOIN processing p ON p.teacher_id = t.id
        """
    )
    rows = cur.fetchall()

    # ---- 2. 硬过滤 --------------------------------------------------------
    filtered = []
    for row in rows:
        tid, name, college, institute, directions, is_phd, score, tscore, keywords_json = row
        # 博导过滤
        if profile["wants_phd_advisor"] and not is_phd:
            continue
        # 学院过滤
        if profile["preferred_college"] and college != profile["preferred_college"]:
            continue
        # 研究所过滤
        if profile["preferred_institute"] and institute != profile["preferred_institute"]:
            continue
        filtered.append(
            {
                "id": tid,
                "name": name,
                "college": college,
                "institute": institute,
                "research_directions": directions or "",
                "score": score or 0.0,
                "teaching_score": tscore or 0.0,
                "keywords": _parse_keywords(keywords_json),
            }
        )

    if not filtered:
        return []

    # ---- 3. 计算归一化分数 ------------------------------------------------
    # 学术分：minmax(processing.score)
    academic_raw = {t["id"]: t["score"] for t in filtered}
    academic_norm = minmax(academic_raw)
    # 教学分：minmax(processing.teaching_score)
    teaching_raw = {t["id"]: t["teaching_score"] for t in filtered}
    teaching_norm = minmax(teaching_raw)

    # 学生研究兴趣 token
    interest_text = " ".join(profile["research_interests"])
    student_tokens = set(tokenize(interest_text))

    # ---- 4. 计算每位教师的三维分数 ----------------------------------------
    results = []
    for t in filtered:
        # 研究匹配分：|∩| / max(1, |student_tokens|)
        teacher_tokens = set()
        teacher_tokens.update(tokenize(t["research_directions"]))
        teacher_tokens.update(tokenize(" ".join(t["keywords"])))
        if student_tokens:
            inter = student_tokens & teacher_tokens
            research_match = len(inter) / max(1, len(student_tokens))
        else:
            research_match = 0.0

        academic = academic_norm.get(t["id"], 0.0)
        teaching = teaching_norm.get(t["id"], 0.0)

        final = (
            profile["weight_research_match"] * research_match
            + profile["weight_academic"] * academic
            + profile["weight_teaching"] * teaching
        )

        results.append(
            {
                "id": t["id"],
                "name": t["name"],
                "college": t["college"],
                "institute": t["institute"] or "",
                "research_match": round(research_match, 4),
                "academic": round(academic, 4),
                "teaching": round(teaching, 4),
                "final_score": round(final, 4),
                "score_parts": {
                    "research_match_weight": profile["weight_research_match"],
                    "academic_weight": profile["weight_academic"],
                    "teaching_weight": profile["weight_teaching"],
                },
            }
        )

    # ---- 5. 排序（降序）--------------------------------------------------
    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results


def _parse_keywords(raw: str | None) -> list[str]:
    """把 processing.keywords（JSON 数组字符串）解析为 list[str]。"""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# 评估：构造 ground truth 并计算 NDCG@10 / HitRate@10
# ---------------------------------------------------------------------------
def build_ground_truth(profile: dict, conn: sqlite3.Connection) -> set[int]:
    """构造 ground truth：research_directions 的 token 与学生兴趣 token 有交集的教师 ID 集合。"""
    profile = normalize_profile(profile)
    interest_text = " ".join(profile["research_interests"])
    student_tokens = set(tokenize(interest_text))
    if not student_tokens:
        return set()

    cur = conn.cursor()
    cur.execute("SELECT id, research_directions FROM teachers")
    relevant = set()
    for tid, directions in cur.fetchall():
        t_tokens = set(tokenize(directions or ""))
        if student_tokens & t_tokens:
            relevant.add(tid)
    return relevant


def evaluate_profile(profile: dict, conn: sqlite3.Connection) -> dict:
    """对单个画像计算 NDCG@10 和 HitRate@10。"""
    ranking = recommend(profile, conn)
    ranked_ids = [r["id"] for r in ranking]
    gt = build_ground_truth(profile, conn)
    metrics = evaluate_ranking(ranked_ids, gt, k=10)
    return {
        "ndcg10": round(metrics["ndcg"], 4),
        "hit_rate10": round(metrics["hr"], 4),
        "map10": round(metrics["map"], 4),
        "p5": round(metrics["p5"], 4),
        "n_relevant": len(gt),
        "n_ranked": len(ranked_ids),
    }


# ---------------------------------------------------------------------------
# 演示画像
# ---------------------------------------------------------------------------
DEMO_PROFILES: list[dict] = [
    {
        "label": "P1 计算机视觉+深度学习（要博导，学术导向）",
        "profile": {
            "research_interests": ["计算机视觉", "深度学习", "图像处理"],
            "preferred_college": "计算机学院",
            "preferred_institute": None,
            "wants_phd_advisor": True,
            "weight_academic": 0.6,
            "weight_teaching": 0.2,
            "weight_research_match": 0.2,
        },
    },
    {
        "label": "P2 NLP+大语言模型（均衡权重）",
        "profile": {
            "research_interests": ["自然语言处理", "大语言模型", "NLP"],
            "preferred_college": None,
            "preferred_institute": None,
            "wants_phd_advisor": False,
            "weight_academic": 0.4,
            "weight_teaching": 0.3,
            "weight_research_match": 0.3,
        },
    },
    {
        "label": "P3 芯片设计/硬件（不要博导）",
        "profile": {
            "research_interests": ["芯片设计", "集成电路", "硬件设计", "EDA"],
            "preferred_college": None,
            "preferred_institute": None,
            "wants_phd_advisor": False,
            "weight_academic": 0.4,
            "weight_teaching": 0.4,
            "weight_research_match": 0.2,
        },
    },
    {
        "label": "P4 医学影像+AI（偏好特定学院）",
        "profile": {
            "research_interests": ["医学影像", "人工智能", "深度学习"],
            "preferred_college": "人工智能学院",
            "preferred_institute": None,
            "wants_phd_advisor": True,
            "weight_academic": 0.5,
            "weight_teaching": 0.2,
            "weight_research_match": 0.3,
        },
    },
    {
        "label": "P5 机器人+控制系统（教学权重高）",
        "profile": {
            "research_interests": ["机器人", "控制系统", "自动导航"],
            "preferred_college": None,
            "preferred_institute": None,
            "wants_phd_advisor": False,
            "weight_academic": 0.2,
            "weight_teaching": 0.5,
            "weight_research_match": 0.3,
        },
    },
]


# ---------------------------------------------------------------------------
# 学生画像输出辅助
# ---------------------------------------------------------------------------
def print_top5(label: str, ranking: list[dict]):
    """在终端打印某画像的 Top-5 推荐。"""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    if not ranking:
        print("  （无符合条件的导师）")
        return
    print(f"  {'#':<3}{'姓名':<8}{'学院':<12}{'研究所':<20}{'研究匹配':>8}{'学术':>8}{'教学':>8}{'总分':>8}")
    print(f"  {'-'*68}")
    for i, r in enumerate(ranking[:5], 1):
        inst = (r["institute"] or "—")[:18]
        print(
            f"  {i:<3}{r['name']:<8}{r['college'] or '—':<12}{inst:<20}"
            f"{r['research_match']:>8.3f}{r['academic']:>8.3f}{r['teaching']:>8.3f}{r['final_score']:>8.4f}"
        )


def build_report(demo_results: list[dict], all_metrics: list[dict]) -> str:
    """生成 Markdown 报告。"""
    lines: list[str] = []
    lines.append("# 学生画像 → 个性化导师推荐\n")
    lines.append("## 方法说明\n")
    lines.append(
        "本实验采用**基于内容的过滤（Content-Based Filtering）**方法，"
        "根据学生画像中的研究兴趣、学院偏好和权重设置，对库内 773 位教师进行个性化排序。\n"
    )
    lines.append("**评分组成：**\n")
    lines.append("| 维度 | 来源 | 说明 |")
    lines.append("|---|---|---|")
    lines.append("| 研究匹配 | `research_directions` + `keywords` 与学生兴趣 token 的 Jaccard | 值域 [0, 1]，越大表示方向越贴合 |")
    lines.append("| 学术能力 | `processing.score`（min-max 归一化） | 论文数、引用数、h 指数、荣誉的综合评分 |")
    lines.append("| 教学口碑 | `processing.teaching_score`（min-max 归一化） | 选课社区课程评分 |")
    lines.append("")
    lines.append("**最终分数** = `w_research × 研究匹配` + `w_academic × 学术能力` + `w_teaching × 教学口碑`\n")
    lines.append("**硬过滤**：`wants_phd_advisor=True` 时只保留博导；指定学院/研究所时进一步过滤。\n")
    lines.append("## 各画像 Top-5 推荐\n")
    for dr in demo_results:
        lines.append(f"### {dr['label']}\n")
        lines.append(f"**画像参数**：兴趣={dr['profile']['research_interests']}，学院={dr['profile']['preferred_college'] or '不限'}，博导={dr['profile']['wants_phd_advisor']}，权重(研/学/教)={dr['profile']['weight_research_match']:.2f}/{dr['profile']['weight_academic']:.2f}/{dr['profile']['weight_teaching']:.2f}\n")
        lines.append("| # | 姓名 | 学院 | 研究所 | 研究匹配 | 学术 | 教学 | 总分 |")
        lines.append("|---|---|---|---|---:|---:|---:|---:|")
        for i, r in enumerate(dr["top5"], 1):
            lines.append(
                f"| {i} | {r['name']} | {r['college'] or '—'} | {r['institute'] or '—'} "
                f"| {r['research_match']:.3f} | {r['academic']:.3f} | {r['teaching']:.3f} | {r['final_score']:.4f} |"
            )
        lines.append("")
    lines.append("## 评估指标\n")
    lines.append("Ground Truth：教师 `research_directions` 的 token 与学生兴趣 token 有交集的集合。\n")
    lines.append("| 画像 | NDCG@10 | HitRate@10 | MAP@10 | P@5 | 相关教师数 | 排名数 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for dr, m in zip(demo_results, all_metrics):
        lines.append(
            f"| {dr['label']} | {m['ndcg10']:.4f} | {m['hit_rate10']:.4f} | {m['map10']:.4f} | {m['p5']:.4f} | {m['n_relevant']} | {m['n_ranked']} |"
        )
    lines.append("")
    lines.append("## 权重敏感性分析\n")
    lines.append(
        "从五个演示画像可以观察以下规律：\n"
    )
    lines.append(
        "1. **研究匹配权重（w_research）**：当学生兴趣方向明确（如 CV、芯片），"
        "提高 w_research 能让方向高度吻合的教师排名上升；但 Jaccard 分母是学生 token 数，"
        "如果兴趣描述过于宽泛（如只写'智能'），几乎所有教师都会拿到较高分，区分度下降。\n"
    )
    lines.append(
        "2. **学术权重（w_academic）**：学术分来自综合评分（论文、引用、h 指数、荣誉），"
        "提高此权重会让高引用、高 h 指数的资深教师排名靠前，适合科研导向的学生。\n"
    )
    lines.append(
        "3. **教学权重（w_teaching）**：教学分只覆盖选课社区有点评的约 498 位教师，"
        "其余教师教学分为 0（min-max 后偏低）。提高此权重适合本科/硕士阶段、重视课堂体验的学生；"
        "但需注意数据覆盖不全可能带来的偏差。\n"
    )
    lines.append(
        "4. **硬过滤的影响**：`wants_phd_advisor=True` 会把候选池从 773 人缩小到 151 人（博导），"
        "候选池变小后 min-max 归一化的分数分布会变化，可能导致同一教师在'有博导/无博导'两种模式下的排名不同。\n"
    )
    lines.append("")
    lines.append("## 局限性\n")
    lines.append(
        "- Jaccard 匹配基于中文 bigram 分词，同义词（如'深度学习'与'神经网络'）无法自动关联；\n"
        "- 教学评分覆盖率约 64%，缺失教师的 min-max 分偏低；\n"
        "- Ground Truth 同样基于 token 交集，与真实相关性存在偏差；\n"
        "- 未考虑师生比、招生名额、经费等实际选导师因素。\n"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 学生画像主流程
# ---------------------------------------------------------------------------
def run_student_profile(profile_path: str | None = None):
    conn = get_conn()
    try:
        if profile_path:
            # ---- 自定义画像模式 -------------------------------------------
            with open(profile_path, encoding="utf-8") as f:
                custom = json.load(f)
            label = custom.get("label", "自定义画像")
            profile = custom.get("profile", custom)
            print(f"加载自定义画像：{label}")
            ranking = recommend(profile, conn)
            metrics = evaluate_profile(profile, conn)
            print_top5(label, ranking)
            print(f"\n  NDCG@10={metrics['ndcg10']:.4f}  HitRate@10={metrics['hit_rate10']:.4f}  MAP@10={metrics['map10']:.4f}")
            result = {
                "label": label,
                "profile": profile,
                "top5": ranking[:5],
                "metrics": metrics,
            }
            dump_json([result], "ext_student_profiles_results.json")
            report = build_report([result], [metrics])
            dump_md(report, "ext_student_profile_report.md")
        else:
            # ---- 5 个演示画像 ---------------------------------------------
            print("运行 5 个演示画像……")
            demo_results: list[dict] = []
            all_metrics: list[dict] = []

            for demo in DEMO_PROFILES:
                ranking = recommend(demo["profile"], conn)
                metrics = evaluate_profile(demo["profile"], conn)
                print_top5(demo["label"], ranking)
                demo_results.append(
                    {
                        "label": demo["label"],
                        "profile": demo["profile"],
                        "top5": ranking[:5],
                        "metrics": metrics,
                    }
                )
                all_metrics.append(metrics)

            # 保存 JSON
            dump_json(demo_results, "ext_student_profiles_results.json")
            # 生成 Markdown 报告
            report = build_report(demo_results, all_metrics)
            dump_md(report, "ext_student_profile_report.md")

            # 终端汇总
            print(f"\n{'='*70}")
            print("  评估汇总")
            print(f"{'='*70}")
            print(f"  {'画像':<50}{'NDCG@10':>10}{'HR@10':>10}{'MAP@10':>10}")
            print(f"  {'-'*78}")
            for dr, m in zip(demo_results, all_metrics):
                print(f"  {dr['label']:<50}{m['ndcg10']:>10.4f}{m['hit_rate10']:>10.4f}{m['map10']:>10.4f}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="推荐扩展实验（LambdaMART + 学生画像推荐）"
    )
    parser.add_argument("--ltr", action="store_true", help="运行 LambdaMART 学习排序")
    parser.add_argument("--student-profile", action="store_true", help="运行学生画像推荐演示")
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="自定义画像 JSON 文件路径（用于 student-profile 模式）",
    )
    args = parser.parse_args()

    if not args.ltr and not args.student_profile:
        parser.print_help()
        print("\n请指定 --ltr 或 --student-profile。")
        sys.exit(0)

    if args.ltr:
        run_ltr()

    if args.student_profile:
        run_student_profile(args.profile)


if __name__ == "__main__":
    main()

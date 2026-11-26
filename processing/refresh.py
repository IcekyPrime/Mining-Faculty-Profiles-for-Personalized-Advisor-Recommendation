# -*- coding: utf-8 -*-
"""处理层刷新：AI 补全写入后，按依赖顺序重跑轻量脚本，不抓取、不重建库。

用法：
    python processing/refresh.py
    python processing/refresh.py --from similarity_index

说明：这是 `run_pipeline.py` 的“只重算处理层”版本；它不会访问网络，也不会
调用 `db.reset()`，因此适合在 Web 应用里对单条补全做增量刷新。
"""
import argparse
import os
import subprocess
import sys
import time

STEPS = (
    ("keyword_extract", "关键词抽取（jieba + TF-IDF）"),
    ("topic_model", "主题模型（TF-IDF + NMF）"),
    ("similarity_index", "相似导师（MinHash + LSH）"),
    ("ranking", "合作网络（PageRank + HITS）"),
    ("community", "社区发现（Louvain）"),
    ("clustering", "方向聚类（SVD + K-means 自动 K）"),
    ("association", "关联规则（Apriori）"),
    ("score", "原始综合评分 v1"),
    ("score_v2", "改进评分 v2"),
)

HERE = os.path.dirname(os.path.abspath(__file__))


def run(only_from=None):
    names = [name for name, _ in STEPS]
    start = names.index(only_from) if only_from in names else 0
    results = []
    for name, label in STEPS[start:]:
        started = time.perf_counter()
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, f"{name}.py")],
            cwd=HERE,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        results.append({
            "name": name,
            "label": label,
            "ok": proc.returncode == 0,
            "took_ms": round((time.perf_counter() - started) * 1000, 1),
            "output": (proc.stdout or "")[-600:],
            "error": (proc.stderr or "")[-600:] if proc.returncode else "",
        })
        print(f"[{ 'OK' if proc.returncode == 0 else 'FAIL' }] {label}")
        if proc.returncode != 0:
            print((proc.stderr or proc.stdout or "")[-1200:])
            break
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="only_from", choices=[name for name, _ in STEPS])
    args = parser.parse_args()
    results = run(args.only_from)
    failed = [item for item in results if not item["ok"]]
    if failed:
        sys.exit(1)
    print("处理层刷新完成。")


if __name__ == "__main__":
    main()

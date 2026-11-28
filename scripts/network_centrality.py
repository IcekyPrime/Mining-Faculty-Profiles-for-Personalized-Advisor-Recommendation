# -*- coding: utf-8 -*-
"""协作网络中心性分析：度中心性、介数中心性、PageRank、接近中心性。

在已有 Louvain 社区检测和 PageRank/HITS 基础上，补充多种中心性指标，
识别"桥梁型"教师和"核心枢纽"教师，支撑跨方向导师推荐。

只读原 DB 与 collab_edges.csv，不修改任何原有文件；结果写入 docs/eval/extensions/。

运行方式（项目根目录）：
    python scripts/network_centrality.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "db" / "mentor.db"
COLLAB_CSV = ROOT / "data" / "exports" / "collab_edges.csv"
OUT_DIR = ROOT / "docs" / "eval" / "extensions"


def load_graph():
    """从 collab_edges.csv 构建加权无向图。"""
    G = nx.Graph()
    with open(COLLAB_CSV, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("src,"):
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            src, dst, weight = int(parts[0]), int(parts[1]), int(parts[2])
            if G.has_edge(src, dst):
                G[src][dst]["weight"] += weight
            else:
                G.add_edge(src, dst, weight=weight)
    return G


def load_names():
    """从 DB 读取教师姓名和学院。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, name, college FROM teachers").fetchall()
    conn.close()
    return {r["id"]: {"name": r["name"], "college": r["college"] or ""} for r in rows}


def compute_centrality(G):
    """计算四种中心性指标。"""
    results = {}
    results["degree"] = nx.degree_centrality(G)
    results["betweenness"] = nx.betweenness_centrality(G)
    results["pagerank"] = nx.pagerank(G, alpha=0.85, max_iter=200)
    results["closeness"] = nx.closeness_centrality(G)
    return results


def top_n(metrics, n=15):
    """返回指标最高的前 n 个节点。"""
    return sorted(metrics.items(), key=lambda x: -x[1])[:n]


def find_bridges(G, betweenness, n=15):
    """识别桥梁型教师：介数中心性最高且连接多个社区。"""
    community = nx.algorithms.community.louvain_communities(G, weight="weight", seed=42)
    node_community = {}
    for i, comm in enumerate(community):
        for node in comm:
            node_community[node] = i

    bridge_scores = []
    for node in G.nodes():
        neighbors = list(G.neighbors(node))
        communities = set(node_community.get(nb, -1) for nb in neighbors)
        n_communities = len(communities)
        bridge_scores.append((node, betweenness[node], n_communities))

    bridge_scores.sort(key=lambda x: (-x[1], -x[2]))
    return bridge_scores[:n], node_community, len(community)


def save_results(G, centrality, bridges, node_community, n_communities, names):
    """保存 JSON 结果和可视化图。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON 结果
    result = {
        "graph": {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "density": round(nx.density(G), 4),
            "average_degree": round(2 * G.number_of_edges() / G.number_of_nodes(), 2),
            "connected_components": nx.number_connected_components(G),
        },
        "top15_degree": [
            {"id": nid, "name": names.get(nid, {}).get("name", f"#{nid}"),
             "college": names.get(nid, {}).get("college", ""),
             "score": round(score, 4)}
            for nid, score in top_n(centrality["degree"])
        ],
        "top15_betweenness": [
            {"id": nid, "name": names.get(nid, {}).get("name", f"#{nid}"),
             "college": names.get(nid, {}).get("college", ""),
             "score": round(score, 4)}
            for nid, score in top_n(centrality["betweenness"])
        ],
        "top15_pagerank": [
            {"id": nid, "name": names.get(nid, {}).get("name", f"#{nid}"),
             "college": names.get(nid, {}).get("college", ""),
             "score": round(score, 4)}
            for nid, score in top_n(centrality["pagerank"])
        ],
        "top15_closeness": [
            {"id": nid, "name": names.get(nid, {}).get("name", f"#{nid}"),
             "college": names.get(nid, {}).get("college", ""),
             "score": round(score, 4)}
            for nid, score in top_n(centrality["closeness"])
        ],
        "bridges": [
            {"id": nid, "name": names.get(nid, {}).get("name", f"#{nid}"),
             "college": names.get(nid, {}).get("college", ""),
             "betweenness": round(score, 4),
             "n_communities": n_comm}
            for nid, score, n_comm in bridges
        ],
        "communities": n_communities,
    }

    out_json = OUT_DIR / "network_centrality.json"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {out_json}")

    # 可视化：2x2 子图
    fig, axes = plt.subplots(2, 2, figsize=(16, 14))
    fig.suptitle("Collaboration Network Centrality Analysis", fontsize=14, fontweight="bold")

    for ax, (label, metrics) in zip(
        axes.flat,
        [
            ("Degree Centrality", centrality["degree"]),
            ("Betweenness Centrality", centrality["betweenness"]),
            ("PageRank", centrality["pagerank"]),
            ("Closeness Centrality", centrality["closeness"]),
        ],
    ):
        pos = nx.spring_layout(G, seed=42, k=1.5 / np.sqrt(G.number_of_nodes()))
        node_sizes = [
            50 + 400 * metrics[n] / max(metrics.values()) for n in G.nodes()
        ]
        ax.scatter(
            [pos[n][0] for n in G.nodes()],
            [pos[n][1] for n in G.nodes()],
            s=node_sizes,
            alpha=0.6,
            c="steelblue",
            edgecolors="navy",
            linewidths=0.3,
        )
        edge_x = []
        edge_y = []
        for u, v in G.edges():
            edge_x.extend([pos[u][0], pos[v][0], None])
            edge_y.extend([pos[u][1], pos[v][1], None])
        ax.plot(edge_x, edge_y, "k-", alpha=0.08, linewidth=0.3)
        ax.set_title(label, fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_facecolor("#f8f9fa")

    # 高亮 Top-10 节点名称
    for ax, (label, metrics) in zip(
        axes.flat,
        [
            ("Degree", centrality["degree"]),
            ("Betweenness", centrality["betweenness"]),
            ("PageRank", centrality["pagerank"]),
            ("Closeness", centrality["closeness"]),
        ],
    ):
        pos = nx.spring_layout(G, seed=42, k=1.5 / np.sqrt(G.number_of_nodes()))
        for nid, _ in top_n(metrics, 5):
            name = names.get(nid, {}).get("name", str(nid))
            ax.annotate(
                name,
                (pos[nid][0], pos[nid][1]),
                fontsize=6,
                xytext=(5, 5),
                textcoords="offset points",
                color="darkred",
            )

    plt.tight_layout()
    out_png = OUT_DIR / "network_centrality.png"
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"已写入 {out_png}")


def write_report(result, names):
    """生成 Markdown 报告。"""
    lines = [
        "# 协作网络中心性分析",
        "",
        "## 方法",
        "",
        "在已有 Louvain 社区检测和 PageRank/HITS 基础上，补充多种中心性指标：",
        "",
        "| 指标 | 公式/含义 | 识别对象 |",
        "|------|----------|---------|",
        "| 度中心性 | deg(v) / (n-1) | 合作最广的教师（枢纽） |",
        "| 介数中心性 | 最短路径经过 v 的比例 | 连接不同社区的桥梁教师 |",
        "| PageRank | 迭代加权的入链重要性 | 综合影响力（考虑邻居质量） |",
        "| 接近中心性 | (n-1) / Σ d(v,u) | 信息传播最快的教师 |",
        "",
        "参考：UCSD CSE 291-F Graph Mining, Brin & Page (1998) PageRank 论文。",
        "",
        "## 网络规模",
        "",
        f"- 节点数：{result['graph']['nodes']} 位有合作边的教师",
        f"- 边数：{result['graph']['edges']} 条合作边",
        f"- 密度：{result['graph']['density']}",
        f"- 平均度：{result['graph']['average_degree']}",
        f"- 连通分量：{result['graph']['connected_components']}",
        f"- Louvain 社区数：{result['communities']}",
        "",
        "## Top-15 中心性排名",
        "",
        "### 度中心性（合作广度）",
        "",
        "| 排名 | 姓名 | 学院 | 度中心性 |",
        "|------|------|------|---------|",
    ]
    for i, item in enumerate(result["top15_degree"], 1):
        lines.append(f"| {i} | {item['name']} | {item['college']} | {item['score']} |")

    lines.extend([
        "",
        "### 介数中心性（桥梁效应）",
        "",
        "| 排名 | 姓名 | 学院 | 介数中心性 |",
        "|------|------|------|-----------|",
    ])
    for i, item in enumerate(result["top15_betweenness"], 1):
        lines.append(f"| {i} | {item['name']} | {item['college']} | {item['score']} |")

    lines.extend([
        "",
        "### PageRank（综合影响力）",
        "",
        "| 排名 | 姓名 | 学院 | PageRank |",
        "|------|------|------|---------|",
    ])
    for i, item in enumerate(result["top15_pagerank"], 1):
        lines.append(f"| {i} | {item['name']} | {item['college']} | {item['score']} |")

    lines.extend([
        "",
        "### 接近中心性（信息传播速度）",
        "",
        "| 排名 | 姓名 | 学院 | 接近中心性 |",
        "|------|------|------|-----------|",
    ])
    for i, item in enumerate(result["top15_closeness"], 1):
        lines.append(f"| {i} | {item['name']} | {item['college']} | {item['score']} |")

    lines.extend([
        "",
        "## 桥梁型教师（跨社区连接）",
        "",
        "介数中心性高且邻居分布在多个 Louvain 社区中的教师：",
        "",
        "| 姓名 | 学院 | 介数中心性 | 连接社区数 |",
        "|------|------|-----------|-----------|",
    ])
    for item in result["bridges"][:10]:
        lines.append(f"| {item['name']} | {item['college']} | {item['betweenness']} | {item['n_communities']} |")

    lines.extend([
        "",
        "## 分析结论",
        "",
        "1. **枢纽教师**（度中心性 Top）：合作网络中最活跃，是资源汇聚点；推荐时适合需要广泛合作资源的学生。",
        "2. **桥梁教师**（介数中心性 Top）：连接不同研究方向/社区，适合希望跨方向拓展的学生。",
        "3. **影响力教师**（PageRank Top）：不仅自身合作多，且合作的对象本身也重要，综合学术影响力强。",
        "4. **高效传播教师**（接近中心性 Top）：在合作网络中距离其他人最近，信息/资源流通效率高。",
        "",
        "## 可视化",
        "",
        "![网络中心性](network_centrality.png)",
    ])

    out = OUT_DIR / "network_centrality_report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入 {out}")


def main():
    print("加载协作图...")
    G = load_graph()
    names = load_names()
    print(f"  {G.number_of_nodes()} 节点, {G.number_of_edges()} 边")

    print("计算中心性指标...")
    centrality = compute_centrality(G)

    print("识别桥梁型教师...")
    bridges, node_community, n_communities = find_bridges(G, centrality["betweenness"])

    print("保存结果...")
    save_results(G, centrality, bridges, node_community, n_communities, names)
    # 读取 save_results 写入的完整 JSON（含 top15 列表）
    full_result = json.loads((OUT_DIR / "network_centrality.json").read_text(encoding="utf-8"))
    write_report(full_result, names)

    # 打印摘要
    print(f"\n=== 中心性分析摘要 ===")
    print(f"Top-5 度中心性: ", end="")
    for nid, s in top_n(centrality["degree"], 5):
        print(f"{names.get(nid, {}).get('name', nid)}({s:.3f})", end="  ")
    print()
    print(f"Top-5 介数中心性: ", end="")
    for nid, s in top_n(centrality["betweenness"], 5):
        print(f"{names.get(nid, {}).get('name', nid)}({s:.3f})", end="  ")
    print()
    print(f"Top-5 PageRank: ", end="")
    for nid, s in top_n(centrality["pagerank"], 5):
        print(f"{names.get(nid, {}).get('name', nid)}({s:.3f})", end="  ")
    print()
    print(f"Top-5 桥梁教师: ", end="")
    for nid, s, nc in bridges[:5]:
        print(f"{names.get(nid, {}).get('name', nid)}(b={s:.3f},c={nc})", end="  ")
    print()


if __name__ == "__main__":
    main()

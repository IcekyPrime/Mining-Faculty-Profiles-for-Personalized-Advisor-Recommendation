"""处理层 · 社区发现：在研究方向相似图上运行 Louvain（模块度），识别研究社群。"""
import sqlite3, json, os
import networkx as nx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')
KNN = 5


def jaccard(a, b):
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS processing (teacher_id INTEGER PRIMARY KEY, keywords TEXT, cluster INTEGER, community INTEGER, pagerank REAL, hits_authority REAL, hits_hub REAL, score REAL)")
    rows = conn.execute("SELECT teacher_id, keywords FROM processing WHERE keywords IS NOT NULL").fetchall()
    data = {r['teacher_id']: set(json.loads(r['keywords'])) for r in rows}
    tids = list(data.keys())
    print(f'参与社区发现的教师 {len(tids)} 人')

    # kNN 相似图（每个教师连相似度最高的 K 个）
    G = nx.Graph()
    G.add_nodes_from(tids)
    for i, a in enumerate(tids):
        sims = sorted(((jaccard(data[a], data[b]), b) for b in tids if b != a), reverse=True)[:KNN]
        for s, b in sims:
            if s > 0:
                G.add_edge(a, b, weight=s)
    print(f'相似图：{G.number_of_nodes()} 节点，{G.number_of_edges()} 边')

    # networkx 内置 Louvain
    communities = nx.community.louvain_communities(G, weight='weight', seed=42, resolution=1.0)
    partition = {}
    for cid, members in enumerate(communities):
        for tid in members:
            partition[tid] = cid
    n_comm = len(communities)
    print(f'Louvain 社区数：{n_comm}')
    mod = nx.community.modularity(G, communities, weight='weight')
    print(f'模块度：{mod:.4f}')

    for tid, c in partition.items():
        conn.execute("UPDATE processing SET community=? WHERE teacher_id=?", (c, tid))
    conn.commit()

    # 社区概况
    name_map = {r['id']: r['name'] for r in conn.execute("SELECT id, name FROM teachers").fetchall()}
    comm_groups = {}
    for tid, c in partition.items():
        comm_groups.setdefault(c, []).append(tid)
    print('\n社区概况（Top 6 社区，按人数）：')
    for c, members in sorted(comm_groups.items(), key=lambda x: -len(x[1]))[:6]:
        names = [name_map.get(t, '?') for t in members[:8]]
        print(f"  社区{c} ({len(members)}人): {', '.join(names)}{'...' if len(members) > 8 else ''}")

    with open(os.path.join(EXP, 'communities.json'), 'w', encoding='utf-8') as f:
        json.dump({str(k): v for k, v in partition.items()}, f)
    conn.close()


if __name__ == '__main__':
    main()

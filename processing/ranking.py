"""处理层 · 学术影响力排名：基于合作网络的 PageRank 与 HITS（Hub/Authority）。"""
import sqlite3, os, csv
import networkx as nx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS processing (teacher_id INTEGER PRIMARY KEY, keywords TEXT, cluster INTEGER, community INTEGER, pagerank REAL, hits_authority REAL, hits_hub REAL, score REAL)")

    G = nx.Graph()
    with open(os.path.join(EXP, 'collab_edges.csv'), encoding='utf-8') as f:
        rd = csv.DictReader(f)
        for row in rd:
            G.add_edge(int(row['src']), int(row['dst']), weight=int(row['weight']))
    print(f'合作网络：{G.number_of_nodes()} 节点，{G.number_of_edges()} 边')

    pr = nx.pagerank(G, weight='weight', alpha=0.85)

    # HITS 需有向图：将合作边按 h 指数定向（影响力流向更资深/高产的协作者），
    # 从而区分「领域枢纽 Hub（连接多位权威者）」与「权威产出 Authority（被多位协作者指向）」。
    hmap = {r['id']: (r['h_index'] or 0) for r in conn.execute("SELECT id, h_index FROM teachers").fetchall()}
    D = nx.DiGraph()
    for a, b, d in G.edges(data=True):
        ha, hb = hmap.get(a, 0), hmap.get(b, 0)
        if ha > hb:
            D.add_edge(b, a, weight=d['weight'])
        elif hb > ha:
            D.add_edge(a, b, weight=d['weight'])
        else:
            D.add_edge(a, b, weight=d['weight'])
            D.add_edge(b, a, weight=d['weight'])
    hubs, auth = nx.hits(D, max_iter=300, normalized=True)

    for tid in G.nodes():
        conn.execute("""UPDATE processing SET pagerank=?, hits_authority=?, hits_hub=?
                        WHERE teacher_id=?""", (pr[tid], auth[tid], hubs[tid], tid))
    conn.commit()

    name_map = dict(conn.execute("SELECT id, name FROM teachers").fetchall())
    top_pr = sorted(pr.items(), key=lambda x: -x[1])[:10]
    print('\nPageRank Top10：')
    for tid, v in top_pr:
        print(f"  {name_map.get(tid)}: {v:.6f}")
    top_auth = sorted(auth.items(), key=lambda x: -x[1])[:5]
    print('\nHITS Authority Top5（权威产出）：')
    for tid, v in top_auth:
        print(f"  {name_map.get(tid)}: {v:.4f}")
    top_hub = sorted(hubs.items(), key=lambda x: -x[1])[:5]
    print('\nHITS Hub Top5（领域枢纽）：')
    for tid, v in top_hub:
        print(f"  {name_map.get(tid)}: {v:.4f}")
    conn.close()


if __name__ == '__main__':
    main()

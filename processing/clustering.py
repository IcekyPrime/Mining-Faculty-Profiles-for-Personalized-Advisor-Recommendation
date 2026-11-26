"""处理层 · 研究方向聚类：TF-IDF 向量 + K-means，轮廓系数自动选择簇数。

K 不再写死为 8：在 4–8 之间用轮廓系数选择，换一批规模/领域不同的数据
也能得到一个相对合理的 K；上限可用 MENTOR_CLUSTER_MAX 调整。
"""
import json
import os
import sqlite3
import sys

from sklearn.feature_extraction.text import TfidfVectorizer
from text_utils import clean_text, strip_career, tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.mining import cluster_with_auto_k  # noqa: E402

DB = os.environ.get('MENTOR_DB_PATH') or os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')
MAX_TEXT = 240


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS processing (teacher_id INTEGER PRIMARY KEY, keywords TEXT, cluster INTEGER, community INTEGER, pagerank REAL, hits_authority REAL, hits_hub REAL, score REAL)")
    rows = conn.execute("SELECT id, research_directions, bio FROM teachers").fetchall()
    corpus, tids = [], []
    for r in rows:
        # 只用研究方向聚类：简介里的教育/任职经历会把「上海交通大学」这类词
        # 抬成簇中心词，掩盖真正的学科差异。缺研究方向时才退回简介。
        text = clean_text(strip_career(r['research_directions'] or r['bio'] or ''), max_len=MAX_TEXT)
        if text:
            corpus.append(text)
            tids.append(r['id'])
    vec = TfidfVectorizer(tokenizer=tokenize, lowercase=False, min_df=2, max_df=0.85)
    X = vec.fit_transform(corpus)
    feat = vec.get_feature_names_out()
    print(f'聚类样本 {len(corpus)} 人，词表 {len(feat)}')

    # 轮廓系数在 4–8 簇中自动选择；数据量很小/特征很少时自动收缩范围。
    k_max = int(os.environ.get("MENTOR_CLUSTER_MAX", "8"))
    labels, K, silhouette = cluster_with_auto_k(X, k_min=4, k_max=max(2, k_max))
    print(f'自动选 K={K}，轮廓系数={silhouette:.3f}')
    for tid, lab in zip(tids, labels, strict=True):
        conn.execute("UPDATE processing SET cluster=? WHERE teacher_id=?", (int(lab), tid))
    conn.commit()

    # 每个簇的 top 关键词：取簇内 TF-IDF 均值最高的词，而不是只看中心向量，
    # 避免 K-means 中心受长文本影响。
    name_map = {r['id']: r['name'] for r in conn.execute("SELECT id, name FROM teachers").fetchall()}
    print(f'\nK-means 聚类结果（{K} 簇，轮廓系数 {silhouette:.3f}）：')
    for k in range(K):
        members = [tids[i] for i in range(len(tids)) if labels[i] == k]
        if not members:
            continue
        mean = X[[tids.index(t) for t in members]].mean(axis=0).A1
        top = [feat[j] for j in mean.argsort()[::-1][:6]]
        sample = [name_map.get(t, '?') for t in members[:5]]
        print(f"  簇{k} ({len(members)}人) 关键词: {'/'.join(top)}")
        print(f"       代表: {', '.join(sample)}")

    with open(os.path.join(EXP, 'clusters.json'), 'w', encoding='utf-8') as f:
        json.dump({str(t): int(label) for t, label in zip(tids, labels, strict=True)}, f)
    with open(os.path.join(EXP, 'cluster_meta.json'), 'w', encoding='utf-8') as f:
        json.dump({"k": K, "silhouette": silhouette, "samples": len(corpus)}, f)
    conn.close()


if __name__ == '__main__':
    main()

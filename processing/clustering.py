"""处理层 · 研究方向聚类：TF-IDF 向量 + K-means，将导师聚为若干主题簇。"""
import json
import os
import sqlite3

from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from text_utils import clean_text, strip_career, tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'db', 'mentor.db')
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

    K = 8
    km = KMeans(n_clusters=K, random_state=42, n_init=10)
    labels = km.fit_predict(X)
    for tid, lab in zip(tids, labels, strict=True):
        conn.execute("UPDATE processing SET cluster=? WHERE teacher_id=?", (int(lab), tid))
    conn.commit()

    # 每个簇的 top 关键词
    centers = km.cluster_centers_
    name_map = {r['id']: r['name'] for r in conn.execute("SELECT id, name FROM teachers").fetchall()}
    print('\nK-means 聚类结果（8 簇）：')
    for k in range(K):
        top = [feat[j] for j in centers[k].argsort()[::-1][:6]]
        members = [tids[i] for i in range(len(tids)) if labels[i] == k]
        sample = [name_map.get(t, '?') for t in members[:5]]
        print(f"  簇{k} ({len(members)}人) 关键词: {'/'.join(top)}")
        print(f"       代表: {', '.join(sample)}")

    with open(os.path.join(EXP, 'clusters.json'), 'w', encoding='utf-8') as f:
        json.dump({str(t): int(label) for t, label in zip(tids, labels, strict=True)}, f)
    conn.close()


if __name__ == '__main__':
    main()

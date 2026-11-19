"""处理层 · 关键词抽取：jieba 分词 + TF-IDF，生成每位教师的研究方向关键词。"""
import json
import os
import sqlite3

from sklearn.feature_extraction.text import TfidfVectorizer
from text_utils import clean_text, strip_career, tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')
MAX_TEXT = 240   # 简介常含整段履历/获奖清单，截断后研究方向权重才不会被稀释


def main():
    os.makedirs(EXP, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, research_directions, bio FROM teachers").fetchall()
    corpus, tids = [], []
    for r in rows:
        # 研究方向优先；缺失时才退回简介，且截断掉履历段
        text = clean_text(strip_career(r['research_directions'] or r['bio'] or ''), max_len=MAX_TEXT)
        if text:
            corpus.append(text)
            tids.append(r['id'])
    print(f'有文本的教师 {len(corpus)} 人')

    vec = TfidfVectorizer(tokenizer=tokenize, lowercase=False, min_df=2, max_df=0.85)
    X = vec.fit_transform(corpus)
    feat = vec.get_feature_names_out()
    print(f'词表大小 {len(feat)}，TF-IDF 矩阵 {X.shape}')

    conn.execute("CREATE TABLE IF NOT EXISTS processing (teacher_id INTEGER PRIMARY KEY, keywords TEXT, cluster INTEGER, community INTEGER, pagerank REAL, hits_authority REAL, hits_hub REAL, score REAL)")
    for i, tid in enumerate(tids):
        row = X[i].toarray().ravel()
        idx = row.argsort()[::-1][:12]
        kws = [feat[j] for j in idx if row[j] > 0]
        conn.execute("""INSERT INTO processing (teacher_id, keywords) VALUES (?,?)
                        ON CONFLICT(teacher_id) DO UPDATE SET keywords=excluded.keywords""",
                     (tid, json.dumps(kws, ensure_ascii=False)))
    conn.commit()

    with open(os.path.join(EXP, 'keywords.json'), 'w', encoding='utf-8') as f:
        json.dump({str(t): json.loads(conn.execute("SELECT keywords FROM processing WHERE teacher_id=?", (t,)).fetchone()[0])
                   for t in tids}, f, ensure_ascii=False)
    # 输出几个示例
    print('\n关键词抽取示例：')
    name_map = dict(conn.execute("SELECT id, name FROM teachers").fetchall())
    for tid in tids[:6]:
        kws = json.loads(conn.execute("SELECT keywords FROM processing WHERE teacher_id=?", (tid,)).fetchone()[0])
        print(f"  {name_map[tid]}: {', '.join(kws[:6])}")
    conn.close()


if __name__ == '__main__':
    main()

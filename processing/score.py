"""处理层 · 综合评分：融合学术产出、引用影响、荣誉与教学口碑，输出可解释的导师能力分。"""
import sqlite3, json, os
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')

# 人才称号权重（叠加）
HONOR_W = {"院士": 5.0, "杰青": 4.0, "长江": 3.5, "万人计划": 3.5, "优青": 3.0,
           "国家级高层次人才": 3.0, "海外高层次": 3.0, "国家级青年人才": 2.5,
           "IEEE Fellow": 2.5, "Fellow": 2.0, "ACM Fellow": 2.5, "CCF Fellow": 2.0,
           "博导": 1.0, "国家级人才": 3.0, "青年长江": 3.0}


def normalize(vals):
    vals = np.array(vals, dtype=float)
    lo, hi = np.percentile(vals, [5, 95])
    if hi <= lo:
        return np.zeros_like(vals)
    return np.clip((vals - lo) / (hi - lo), 0, 1)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS processing (teacher_id INTEGER PRIMARY KEY, keywords TEXT, cluster INTEGER, community INTEGER, pagerank REAL, hits_authority REAL, hits_hub REAL, score REAL)")
    cols = {r['name'] for r in conn.execute("PRAGMA table_info(processing)")}
    if 'teaching_score' not in cols:
        conn.execute("ALTER TABLE processing ADD COLUMN teaching_score REAL")
    if 'teaching_count' not in cols:
        conn.execute("ALTER TABLE processing ADD COLUMN teaching_count INTEGER")
    conn.commit()
    rows = conn.execute("""SELECT id, h_index, citation_count, paper_count, honors, title FROM teachers""").fetchall()
    print(f'评分对象 {len(rows)} 人')

    ids = [r['id'] for r in rows]
    h = normalize([r['h_index'] or 0 for r in rows])
    cites = normalize([r['citation_count'] or 0 for r in rows])
    papers = normalize([r['paper_count'] or 0 for r in rows])

    honor_score = []
    for r in rows:
        try:
            hs = json.loads(r['honors'] or '[]')
        except Exception:
            hs = []
        s = sum(HONOR_W.get(x, 0) for x in hs)
        # 职称基准
        t = r['title'] or ''
        if '院士' in t:
            s += 5
        elif '教授' in t and '副' not in t:
            s += 1.0
        honor_score.append(s)
    honor_norm = normalize(honor_score)

    # 教学口碑：按评分人数加权的课程评分（排除无评分课程）
    teaching_score = []
    teaching_count = []
    for rid in ids:
        r = conn.execute(
            "SELECT SUM(rating_avg*rating_count) ws, SUM(rating_count) wc "
            "FROM courses WHERE teacher_id=? AND rating_count>0 AND rating_avg IS NOT NULL",
            (rid,)).fetchone()
        wc = r['wc'] or 0
        ws = r['ws'] or 0.0
        teaching_count.append(wc)
        teaching_score.append((ws / wc) if wc > 0 else None)
    rating_vals = [x if x is not None else 0.0 for x in teaching_score]
    rating_norm = normalize(rating_vals)

    # 综合分 = 学术产出 0.25 + 引用影响 0.25 + 荣誉 0.25 + 教学 0.25（可解释）
    W = (0.25, 0.25, 0.25, 0.25)
    scores = W[0]*papers + W[1]*cites + W[2]*honor_norm + W[3]*rating_norm
    scores = np.round(scores * 100, 1)

    for rid, s, ts, tc in zip(ids, scores, teaching_score, teaching_count):
        conn.execute(
            "INSERT INTO processing(teacher_id, score, teaching_score, teaching_count) VALUES(?,?,?,?) "
            "ON CONFLICT(teacher_id) DO UPDATE SET score=excluded.score, "
            "teaching_score=excluded.teaching_score, teaching_count=excluded.teaching_count",
            (rid, float(s), ts, tc))
    conn.commit()

    name_map = {r['id']: r['name'] for r in conn.execute("SELECT id, name FROM teachers").fetchall()}
    college_map = {r['id']: r['college'] for r in conn.execute("SELECT id, college FROM teachers").fetchall()}
    order = sorted(zip(ids, scores), key=lambda x: -x[1])
    print('\n综合评分 Top15：')
    for rid, s in order[:15]:
        print(f"  {name_map.get(rid)} ({college_map.get(rid)}): {s}")

    with open(os.path.join(EXP, 'scores.json'), 'w', encoding='utf-8') as f:
        json.dump({str(rid): s for rid, s in zip(ids, scores)}, f, ensure_ascii=False)
    conn.close()


if __name__ == '__main__':
    main()

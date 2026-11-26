# -*- coding: utf-8 -*-
"""处理层 · 改进版综合评分（v2，新增脚本）。

原始 `score.py` 的论文 0.10 / 引用 0.20 / 荣誉 0.35 / 教学 0.25 + 5%–95% 截断算法保持不变，继续写
`processing.score`；本脚本只**新增**三列：`score_v2`（改进分）、
`score_parts`（五维分项）、`score_coverage`（数据完整度），不改动原列。

设计要点（对应 docs/改进说明.md 第 2 节）：
1. 未知 ≠ 0：`paper_count` / `citation_count` / `h_index` 为空表示「没查到」，
   该维度不参与计算，而不是当作 0 拉低分数。
2. 权重按可用维度重新归一：某位教师只有 h 指数与教学评分时，分数由这两项
   按 0.25:0.15 归一得出，避免「缺数据 = 能力差」。
3. 归一化改用分位数排名（percentile rank），对长尾引用量更稳健，也比
   5%–95% 截断更容易解释。
4. 每个维度都落库（score_parts），应用层可以直接展示「这个分怎么来的」。
5. 覆盖度低时向中位数收缩（类似贝叶斯收缩）：只有一个维度有值的教师，
   不会因为「该项恰好排第一」就拿到接近满分的分数。
6. 荣誉时效：能解析出年份的称号按「0.75 下限 + 10 年半衰期」温和衰减；
   无年份的条目不衰减，避免把资料缺失误判成荣誉陈旧。
"""
import datetime
import json
import os
import re
import sqlite3
from bisect import bisect_right

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get('MENTOR_DB_PATH') or os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')

PROCESSING_SCHEMA = """CREATE TABLE IF NOT EXISTS processing (
    teacher_id INTEGER PRIMARY KEY,
    keywords TEXT, cluster INTEGER, community INTEGER,
    pagerank REAL, hits_authority REAL, hits_hub REAL,
    score REAL, teaching_score REAL, teaching_count INTEGER,
    score_v2 REAL, score_coverage REAL, score_parts TEXT
)"""

# 维度权重（可用维度会重新归一）
WEIGHTS = {
    'papers': 0.20,      # 论文产出
    'citations': 0.25,   # 引用影响
    'h_index': 0.25,     # 学术声誉
    'honors': 0.15,      # 荣誉头衔
    'teaching': 0.15,    # 教学口碑
}

# 覆盖度不足时的收缩先验：PRIOR_W 相当于「凭空多出一个权重、分数为 PRIOR_SCORE
# 的维度」，使单维度教师的高分被拉回中位，而不是直接封顶。
PRIOR_W = 0.30
PRIOR_SCORE = 50.0

# 荣誉识别规则：(维度标签, 关键词组, 权重)；同一维度取命中最大值
HONOR_RULES = [
    ('院士', ('院士',), 5.0),
    ('杰青', ('杰青', '杰出青年'), 4.0),
    ('长江学者', ('长江学者', '长江特聘', '长江讲座'), 3.5),
    ('万人计划', ('万人计划', '青年拔尖'), 3.5),
    ('国家级高层次人才', ('国家级高层次人才', '国家级领军人才'), 3.0),
    ('优青', ('优青', '优秀青年'), 3.0),
    ('国家级青年人才', ('国家级青年人才',), 2.5),
    ('IEEE Fellow', ('IEEE Fellow',), 2.5),
    ('ACM Fellow', ('ACM Fellow',), 2.5),
    ('CCF Fellow', ('CCF Fellow',), 2.0),
    ('Fellow', ('Fellow',), 2.0),
    ('博导', ('博导', '博士生导师'), 1.0),
]

SPECIFIC_FELLOWS = ('IEEE Fellow', 'ACM Fellow', 'CCF Fellow')

# 荣誉时效：参考 AVRD 等工作的“时间衰减”思路，只对**已解析出年份**的称号生效。
# 采用温和衰减（0.75 下限 + 半衰期 10 年），避免把早年杰青/院士直接判为无效。
HONOR_YEAR_RE = re.compile(r'(?:19|20)\d{2}')
HONOR_RECENCY_HALF_LIFE = 10.0
HONOR_RECENCY_FLOOR = 0.75
CURRENT_YEAR = int(os.environ.get('MENTOR_SCORE_YEAR') or datetime.date.today().year)


def honor_year(value):
    """取荣誉文本里的第一个年份；用于时效特征，找不到返回 None。"""
    match = HONOR_YEAR_RE.search(str(value or ''))
    return int(match.group()) if match else None


def honor_recency_weight(year, current_year=None):
    """年份越新权重越接近 1；无年份时由调用方按 1.0 处理。"""
    if year is None:
        return 1.0
    age = max(0, int(current_year or CURRENT_YEAR) - int(year))
    return round(
        HONOR_RECENCY_FLOOR
        + (1.0 - HONOR_RECENCY_FLOOR) * (0.5 ** (age / HONOR_RECENCY_HALF_LIFE)),
        3,
    )


def _honor_items(honors_json):
    try:
        items = json.loads(honors_json or '[]')
    except (ValueError, TypeError):
        items = []
    if not isinstance(items, list):
        items = [str(items)]
    return [str(x) for x in items]


def honor_points(honors_json, current_year=None):
    """把荣誉数组映射成可加的分值；同一荣誉称号重复出现只计一次。

    若某条称号带年份，按年份给一个温和的时效系数；没有年份的条目保持原权重，
    避免把「资料没写年份」误判成「荣誉很旧」。
    """
    items = _honor_items(honors_json)
    points, hits = 0.0, []
    for label, keywords, weight in HONOR_RULES:
        # 通用「Fellow」不再对 IEEE/ACM/CCF Fellow 重复计分
        if label == 'Fellow' and any(h in SPECIFIC_FELLOWS for h in hits):
            continue
        matched = [item for item in items if any(k in item for k in keywords)]
        if matched:
            years = [honor_year(item) for item in matched]
            years = [year for year in years if year]
            factor = honor_recency_weight(max(years), current_year) if years else 1.0
            points += weight * factor
            hits.append(label)
    return round(points, 3), hits


def percentile_ranker(values):
    """返回 (排序后的序列, 映射函数)：pct = 小于等于该值的样本占比 × 100。"""
    known = sorted(v for v in values if v is not None)
    if not known:
        return known, lambda _v: None

    def rank(value):
        if value is None:
            return None
        return round(bisect_right(known, value) / len(known) * 100, 1)

    return known, rank


def teaching_scores(conn, ids):
    """按点评人数加权平均课程评分；无点评数据返回 (None, 0)。"""
    out = {}
    for tid in ids:
        row = conn.execute(
            "SELECT SUM(rating_avg*rating_count) AS ws, SUM(rating_count) AS wc "
            "FROM courses WHERE teacher_id=? AND rating_count>0 AND rating_avg IS NOT NULL",
            (tid,),
        ).fetchone()
        wc = row['wc'] or 0
        out[tid] = ((row['ws'] or 0.0) / wc, wc) if wc > 0 else (None, 0)
    return out


def ensure_columns(conn):
    conn.execute(PROCESSING_SCHEMA)
    cols = {r[1] for r in conn.execute('PRAGMA table_info(processing)')}
    for name, ddl in (('score_v2', 'REAL'), ('score_coverage', 'REAL'), ('score_parts', 'TEXT')):
        if name not in cols:
            conn.execute(f'ALTER TABLE processing ADD COLUMN {name} {ddl}')
    conn.commit()


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    rows = conn.execute(
        'SELECT id, name, title, honors, paper_count, citation_count, h_index FROM teachers'
    ).fetchall()
    ids = [r['id'] for r in rows]
    print(f'评分对象 {len(ids)} 人')

    raw = {k: [] for k in WEIGHTS}
    honor_detail = {}
    for r in rows:
        raw['papers'].append(r['paper_count'])
        raw['citations'].append(r['citation_count'])
        raw['h_index'].append(r['h_index'])
        points, hits = honor_points(r['honors'])
        title = r['title'] or ''
        if '院士' in title:
            points += 5
        elif '教授' in title and '副' not in title:
            points += 1.0
        years = [honor_year(item) for item in _honor_items(r['honors'])]
        latest_year = max((year for year in years if year), default=None)
        honor_detail[r['id']] = {
            'points': points, 'labels': hits, 'latest_year': latest_year,
        }
        raw['honors'].append(points)

    teach = teaching_scores(conn, ids)
    raw['teaching'] = [teach[t][0] for t in ids]

    rankers = {k: percentile_ranker(v)[1] for k, v in raw.items()}
    values = {k: {ids[i]: raw[k][i] for i in range(len(ids))} for k in raw}

    coverage_stats = {k: sum(1 for v in values[k].values() if v is not None) for k in WEIGHTS}
    print('各维度可用人数：', coverage_stats)

    results = {}
    for tid in ids:
        parts, total_w, total = {}, 0.0, 0.0
        for dim, weight in WEIGHTS.items():
            value = values[dim].get(tid)
            pct = rankers[dim](value)
            if pct is None:
                parts[dim] = {'value': None, 'pct': None, 'weight': weight, 'used': False}
                continue
            parts[dim] = {'value': value, 'pct': pct, 'weight': weight, 'used': True}
            total += weight * pct
            total_w += weight
        score = None
        if total_w:
            score = round((total + PRIOR_W * PRIOR_SCORE) / (total_w + PRIOR_W), 1)
        if tid in honor_detail:
            parts['honors']['labels'] = honor_detail[tid]['labels']
            parts['honors']['latest_year'] = honor_detail[tid]['latest_year']
        results[tid] = (score, round(total_w, 2), parts)

    for tid, (score, coverage, parts) in results.items():
        conn.execute(
            """INSERT INTO processing (teacher_id, score_v2, score_coverage, score_parts)
               VALUES (?,?,?,?)
               ON CONFLICT(teacher_id) DO UPDATE SET
                 score_v2=excluded.score_v2,
                 score_coverage=excluded.score_coverage,
                 score_parts=excluded.score_parts""",
            (tid, score,
             round(coverage / sum(WEIGHTS.values()), 3),
             json.dumps(parts, ensure_ascii=False)),
        )
    for tid in ids:
        ts, tc = teach[tid]
        conn.execute(
            'UPDATE processing SET teaching_score=?, teaching_count=? WHERE teacher_id=?',
            (ts, tc, tid),
        )
    conn.commit()

    name_map = {r['id']: r['name'] for r in rows}
    college_map = {row[0]: row[1] for row in conn.execute('SELECT id, college FROM teachers')}
    ranked = sorted(((v[0] if v[0] is not None else -1), tid) for tid, v in results.items())
    print('\n改进评分 v2 Top15：')
    for score, tid in reversed(ranked[-15:]):
        print(f'  {name_map.get(tid)} ({college_map.get(tid)}): {score}  覆盖={results[tid][1]:.2f}')
    print('\n改进评分 v2 Bottom5：')
    for score, tid in ranked[:5]:
        print(f'  {name_map.get(tid)} ({college_map.get(tid)}): {score}')

    with open(os.path.join(EXP, 'scores_v2.json'), 'w', encoding='utf-8') as f:
        json.dump({str(t): v[0] for t, v in results.items()}, f, ensure_ascii=False)
    with open(os.path.join(EXP, 'score_breakdown.json'), 'w', encoding='utf-8') as f:
        json.dump({str(t): {'score': v[0], 'coverage': v[1], 'parts': v[2]}
                   for t, v in results.items()}, f, ensure_ascii=False, indent=1)
    print(f'\n已写入 {EXP}')
    conn.close()


if __name__ == '__main__':
    main()

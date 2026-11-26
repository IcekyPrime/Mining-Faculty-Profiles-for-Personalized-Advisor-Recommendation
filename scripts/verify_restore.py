# -*- coding: utf-8 -*-
"""审计修复后的数据一致性：论文覆盖、作者、PageRank、评分、社区、聚类。"""
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("MENTOR_DB_PATH") or os.path.join(ROOT, "data", "db", "mentor.db")
EXP = os.path.join(ROOT, "data", "exports")
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

stats = {}
for table in ("teachers", "papers", "courses"):
    stats[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
stats["teachers_with_papers"] = conn.execute(
    "SELECT COUNT(DISTINCT teacher_id) FROM papers WHERE teacher_id IS NOT NULL"
).fetchone()[0]
stats["authors_nonempty"] = conn.execute(
    "SELECT COUNT(*) FROM papers WHERE authors IS NOT NULL AND TRIM(authors)<>''"
).fetchone()[0]
stats["pagerank_nonnull"] = conn.execute(
    "SELECT COUNT(*) FROM processing WHERE pagerank IS NOT NULL"
).fetchone()[0]
stats["hits_nonnull"] = conn.execute(
    "SELECT COUNT(*) FROM processing WHERE hits_authority IS NOT NULL"
).fetchone()[0]
stats["teaching_imputed"] = conn.execute(
    "SELECT COUNT(*) FROM processing WHERE teaching_imputed=1"
).fetchone()[0]
stats["paper_count_missing"] = conn.execute(
    "SELECT COUNT(*) FROM teachers WHERE paper_count IS NULL OR paper_count=0"
).fetchone()[0]
stats["local_papers_but_no_count"] = conn.execute(
    """SELECT COUNT(*) FROM (SELECT p.teacher_id FROM papers p
       LEFT JOIN teachers t ON t.id=p.teacher_id
       WHERE p.teacher_id IS NOT NULL AND (t.paper_count IS NULL OR t.paper_count=0)
       GROUP BY p.teacher_id)"""
).fetchone()[0]
stats["count_but_no_local_papers"] = conn.execute(
    """SELECT COUNT(*) FROM teachers t WHERE t.paper_count>0 AND NOT EXISTS
       (SELECT 1 FROM papers p WHERE p.teacher_id=t.id)"""
).fetchone()[0]
stats["h_gt_paper_count"] = conn.execute(
    "SELECT COUNT(*) FROM teachers WHERE h_index IS NOT NULL AND paper_count IS NOT NULL AND h_index>paper_count"
).fetchone()[0]
stats["ai_papers"] = conn.execute(
    "SELECT COUNT(*) FROM papers p JOIN teachers t ON t.id=p.teacher_id WHERE t.college LIKE '%人工智能%'"
).fetchone()[0]

for name in ("沈红斌", "俞勇", "程浩忠"):
    row = conn.execute(
        """SELECT t.name,t.paper_count,t.citation_count,t.h_index,p.score,p.score_v2,
                  p.teaching_score,p.teaching_imputed,
                  (SELECT COUNT(*) FROM papers WHERE teacher_id=t.id) local_papers
           FROM teachers t LEFT JOIN processing p ON p.teacher_id=t.id WHERE t.name=?""",
        (name,),
    ).fetchone()
    if row:
        stats.setdefault("people", {})[name] = dict(row)

with open(os.path.join(EXP, "cluster_meta.json"), encoding="utf-8") as handle:
    stats["cluster_meta"] = json.load(handle)
with open(os.path.join(EXP, "communities.json"), encoding="utf-8") as handle:
    stats["communities"] = len(json.load(handle))
with open(os.path.join(EXP, "collab_edges.csv"), encoding="utf-8") as handle:
    stats["collab_edges"] = sum(1 for _ in handle) - 1
with open(os.path.join(EXP, "similar_pairs.json"), encoding="utf-8") as handle:
    stats["similar_pairs"] = len(json.load(handle))

print(json.dumps(stats, ensure_ascii=False, indent=2))
conn.close()

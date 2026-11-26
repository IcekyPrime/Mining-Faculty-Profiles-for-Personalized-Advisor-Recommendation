"""处理层 · 主题模型：TF-IDF + NMF，输出教师-主题分布。

这是新增步骤，不替代关键词抽取/聚类/关联规则：
- 输入：研究方向的文本优先，缺失时用研究主题/简介；
- 主题数：优先读 `MENTOR_TOPIC_K`，否则用轮廓系数在 4–10 中自动选择；
- 输出：processing.topic_primary / topic_distribution / topic_label，
  以及 data/exports/topics.json，供 /api/search?sort=topic 与洞察页使用。

算法只依赖当前语料，不新增教师、论文或外部 ID；换一批领域文本后重新运行
本脚本即可得到新的主题空间。
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.mining import build_topic_model, load_lexicon, serialize_topic_model  # noqa: E402

DB = os.environ.get("MENTOR_DB_PATH") or os.path.join(ROOT, "data", "db", "mentor.db")
EXP = os.path.join(ROOT, "data", "exports")
MAX_TEXT = 360


def ensure_columns(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS processing (
        teacher_id INTEGER PRIMARY KEY, keywords TEXT, cluster INTEGER, community INTEGER,
        pagerank REAL, hits_authority REAL, hits_hub REAL, score REAL,
        teaching_score REAL, teaching_count INTEGER, score_v2 REAL,
        score_coverage REAL, score_parts TEXT, topic_primary INTEGER,
        topic_distribution TEXT, topic_label TEXT)"""
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(processing)")}
    for name, ddl in (
        ("topic_primary", "INTEGER"),
        ("topic_distribution", "TEXT"),
        ("topic_label", "TEXT"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE processing ADD COLUMN {name} {ddl}")
    conn.commit()


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)
    rows = conn.execute(
        "SELECT id, name, research_directions, research_topics, bio FROM teachers"
    ).fetchall()
    ids, texts = [], []
    for row in rows:
        raw = row["research_directions"] or row["research_topics"] or row["bio"] or ""
        text = " ".join(str(raw).split())[:MAX_TEXT]
        if text:
            ids.append(int(row["id"]))
            texts.append(text)
    print(f"主题模型语料 {len(texts)} 人")

    if not texts:
        print("没有可建模的文本，跳过")
        conn.close()
        return

    env_k = os.environ.get("MENTOR_TOPIC_K")
    n_topics = int(env_k) if env_k and env_k.isdigit() else None
    model = build_topic_model(texts, n_topics=n_topics, lexicon=load_lexicon())
    if not model.get("k"):
        print("词表或主题数不足，跳过")
        conn.close()
        return

    serialized = serialize_topic_model(model, ids)
    serialized["generated_at"] = datetime.now().isoformat(timespec="seconds")
    serialized["source"] = os.path.basename(DB)
    os.makedirs(EXP, exist_ok=True)
    with open(os.path.join(EXP, "topics.json"), "w", encoding="utf-8") as handle:
        json.dump(serialized, handle, ensure_ascii=False, indent=1)

    for tid, row in zip(ids, model["doc_topic"], strict=False):
        values = row.tolist()
        primary = int(max(range(len(values)), key=lambda i: values[i])) if values else None
        top = sorted(
            ({"id": i, "weight": round(float(value), 4)} for i, value in enumerate(values)),
            key=lambda item: -item["weight"],
        )[:3]
        label = ""
        for topic in serialized["topics"]:
            if topic["id"] == primary:
                label = topic["label"]
                break
        conn.execute(
            """UPDATE processing
               SET topic_primary=?, topic_distribution=?, topic_label=?
               WHERE teacher_id=?""",
            (primary, json.dumps(top, ensure_ascii=False), label, tid),
        )
    conn.commit()

    print(f"主题数 K={serialized['k']}，词表 {serialized['vocabulary']}")
    for topic in serialized["topics"]:
        print(f"  主题{topic['id']}: {topic['label']}")
    print(f"已写入 {os.path.join(EXP, 'topics.json')}")
    conn.close()


if __name__ == "__main__":
    main()

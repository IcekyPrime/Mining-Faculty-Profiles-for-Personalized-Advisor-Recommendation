"""处理层 · 关联规则：以研究文本中的多项共现为事务，挖掘 Apriori 规则。

项集不再写死在脚本里：
- 优先读取 `data/mining/lexicon.json` 的 `areas`，可在不改代码的情况下换领域；
- 没有配置项集时，用当前语料的 TF-IDF 高频词自动生成项集；
- 支持度阈值可用 `MENTOR_RULE_SUPPORT` 覆盖，适配大小不同的数据集。
"""
import json
import os
import sqlite3
import sys

import pandas as pd
from mlxtend.frequent_patterns import apriori, association_rules
from sklearn.feature_extraction.text import TfidfVectorizer
from text_utils import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.mining import load_lexicon, normalise  # noqa: E402

DB = os.environ.get('MENTOR_DB_PATH') or os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')
MAX_TEXT = 400


def configured_areas():
    return load_lexicon().get('areas') or []


def mined_areas(texts, top_n=60):
    """无配置词典时，从语料中挖掘高频词作为项集，保证换数据仍能跑。"""
    if not texts:
        return []
    vectorizer = TfidfVectorizer(
        tokenizer=tokenize, lowercase=False, min_df=1 if len(texts) < 20 else 2,
        max_df=0.7, max_features=top_n,
    )
    matrix = vectorizer.fit_transform(texts)
    names = vectorizer.get_feature_names_out()
    mean = matrix.mean(axis=0).A1
    return [str(names[idx]) for idx in mean.argsort()[::-1] if mean[idx] > 0]


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, research_directions, research_topics, bio FROM teachers").fetchall()
    print(f'教师数 {len(rows)}')

    texts = []
    for r in rows:
        raw = " ".join([
            str(r['research_directions'] or ''),
            str(r['research_topics'] or ''),
            str(r['bio'] or ''),
        ])
        text = normalise(raw)[:MAX_TEXT]
        if text:
            texts.append(text)
    areas = configured_areas()
    source = "lexicon"
    if not areas:
        areas = mined_areas(texts)
        source = "corpus-tfidf"
    areas = list(dict.fromkeys(areas))
    print(f'项集来源={source}，项数={len(areas)}')

    transactions = []
    for text in texts:
        items = {a for a in areas if a in text}
        if items:
            transactions.append(items)
    print(f'有研究方向的教师 {len(transactions)} 人')
    if not transactions or not areas:
        print('没有可用事务，跳过关联规则')
        conn.close()
        return

    support = float(os.environ.get("MENTOR_RULE_SUPPORT") or max(0.02, 3 / len(transactions)))
    oh = pd.DataFrame([{a: (a in t) for a in areas} for t in transactions], dtype=bool)
    freq = apriori(oh, min_support=support, use_colnames=True)
    freq2 = freq[freq['itemsets'].map(len) >= 2]
    print(f'频繁项集（≥2项）{len(freq2)} 个（min_support={support:.3f}）')

    if len(freq2) == 0:
        print('无 2 项频繁项集，可降低 MENTOR_RULE_SUPPORT')
        conn.close()
        return
    # 需传入完整频繁项集（含单项集）以计算支持度
    rules = association_rules(freq, metric='confidence', min_threshold=0.3)
    rules = rules[rules['antecedents'].map(len) >= 1]
    rules = rules.sort_values('lift', ascending=False)
    print(f'关联规则 {len(rules)} 条（min_conf=0.3）')

    out = []
    for _, r in rules.head(40).iterrows():
        ant = '、'.join(sorted(r['antecedents']))
        con = '、'.join(sorted(r['consequents']))
        out.append({'antecedent': ant, 'consequent': con,
                    'support': round(float(r['support']), 3),
                    'confidence': round(float(r['confidence']), 3),
                    'lift': round(float(r['lift']), 3)})
        print(f"  {{{ant}}} => {{{con}}}  支持度={r['support']:.3f} 置信度={r['confidence']:.3f} 提升度={r['lift']:.2f}")

    with open(os.path.join(EXP, 'association_rules.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open(os.path.join(EXP, 'association_meta.json'), 'w', encoding='utf-8') as f:
        json.dump({"source": source, "items": len(areas), "transactions": len(transactions),
                   "min_support": round(support, 4), "rules": len(out)}, f, ensure_ascii=False, indent=1)
    conn.close()


if __name__ == '__main__':
    main()

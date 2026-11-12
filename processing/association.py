"""处理层 · 关联规则：以规范研究方向为项集，挖掘研究方向共现规则（Apriori）。"""
import sqlite3, json, os
import pandas as pd
from mlxtend.frequent_patterns import apriori, association_rules

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')

# 规范研究方向（作为项集）
AREAS = [
    "操作系统", "分布式系统", "体系结构", "编译优化", "存储系统", "系统软件", "虚拟化",
    "计算机视觉", "自然语言处理", "机器学习", "深度学习", "强化学习", "知识图谱", "大语言模型",
    "数据挖掘", "数据库", "计算机网络", "网络安全", "信息安全", "密码学", "隐私计算",
    "集成电路", "芯片设计", "微电子", "半导体", "射频", "模拟电路",
    "控制理论", "机器人", "智能控制", "模式识别", "信号处理", "图像处理", "多智能体",
    "电力系统", "电力电子", "电机", "新能源", "智能电网", "高电压",
    "人工智能", "边缘计算", "物联网", "云计算", "区块链", "联邦学习", "图神经网络",
    "脑机接口", "语音识别", "无人系统", "传感器", "信息融合", "医学影像",
]


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, research_directions, bio FROM teachers").fetchall()
    print(f'教师数 {len(rows)}')

    transactions = []
    for r in rows:
        text = (r['research_directions'] or '') + ' ' + (r['bio'] or '')
        items = {a for a in AREAS if a in text}
        if items:
            transactions.append(items)
    print(f'有研究方向的教师 {len(transactions)} 人')

    oh = pd.DataFrame([{a: (a in t) for a in AREAS} for t in transactions], dtype=bool)
    freq = apriori(oh, min_support=0.02, use_colnames=True)
    freq2 = freq[freq['itemsets'].map(len) >= 2]
    print(f'频繁项集（≥2项）{len(freq2)} 个')

    if len(freq2) == 0:
        print('无 2 项频繁项集，降低 min_support')
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
    conn.close()


if __name__ == '__main__':
    main()

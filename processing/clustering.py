"""处理层 · 研究方向聚类：TF-IDF 向量 + K-means，将导师聚为若干主题簇。"""
import sqlite3, json, os, re
import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'db', 'mentor.db')
EXP = os.path.join(ROOT, 'data', 'exports')

DOMAIN_TERMS = [
    "操作系统", "分布式系统", "系统软件", "虚拟化", "体系结构", "编译优化", "存储系统",
    "计算机视觉", "自然语言处理", "机器学习", "深度学习", "强化学习", "知识图谱", "大语言模型",
    "数据挖掘", "数据库", "计算机网络", "网络安全", "信息安全", "密码学", "隐私计算",
    "集成电路", "芯片设计", "微电子", "射频", "模拟电路", "数字电路", "半导体",
    "自动化", "控制理论", "机器人", "智能控制", "模式识别", "信号处理", "图像处理",
    "电力系统", "电力电子", "电机", "电气工程", "新能源", "智能电网", "高电压",
    "人工智能", "边缘计算", "物联网", "云计算", "区块链", "联邦学习", "图神经网络",
    "多智能体", "感知", "传感器", "信息融合", "无人系统", "脑机接口", "语音识别",
]
for t in DOMAIN_TERMS:
    jieba.add_word(t)
STOPWORDS = set("""的 了 和 与 及 或 等 在 中 上 下 对 为 于 从 到 被 把 将 是 有 也 都 而 并 且 及其 以及 主要 研究 方向 领域 技术 方法 应用 系统 相关 基于 包括 从事 目前 负责 参与 进行 实现 提出 针对 开展 承担 主持 完成 获得 发表 论文 国际 国内 主席 委员 编委 教授 研究员 副教授 讲师 博士 硕士 学位 毕业 担任 荣获 获奖 一等奖 二等奖 三等奖 科学奖 技术奖 项目 课题 基金 合作 企业 成果 现任 曾任 期刊 会议 出版 国家 上海 教育部 学会 会员 杰出 优秀 人才 计划 学者 专家 作为 曾 曾获""".split())
ACRONYMS = {'acm','ieee','ccf','sig','sosp','osdi','eurosys','asplos','usenix','vldb','icml',
            'neurips','nips','cvpr','iccv','aaai','ijcai','acl','emnlp','iclr','sigmod','sigcomm',
            'tocs','toc','tcad','tifs','tdsc','iot','sigops','sigarch','atc','fast','nsdi'}
EN_STOP = {'and','the','for','of','in','on','with','using','based','from','to','an','is','are',
           'was','were','university','shanghai','jiao','tong','systems','system','learning',
           'towards','via','by','at','their','its','his','her','our','we','as','this','that'}


def tokenize(s):
    out = []
    for w in jieba.lcut(re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', ' ', s or '')):
        w = w.strip().lower()
        if len(w) < 2 or w in STOPWORDS:
            continue
        if re.fullmatch(r'\d+', w):
            continue
        if re.fullmatch(r'[a-z]+', w) and (len(w) <= 2 or w in ACRONYMS or w in EN_STOP):
            continue
        out.append(w)
    return out


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS processing (teacher_id INTEGER PRIMARY KEY, keywords TEXT, cluster INTEGER, community INTEGER, pagerank REAL, hits_authority REAL, hits_hub REAL, score REAL)")
    rows = conn.execute("SELECT id, research_directions, bio FROM teachers").fetchall()
    corpus, tids = [], []
    for r in rows:
        t = (r['research_directions'] or '') + ' ' + (r['bio'] or '')
        if t.strip():
            corpus.append(t)
            tids.append(r['id'])
    vec = TfidfVectorizer(tokenizer=tokenize, lowercase=False, min_df=2, max_df=0.85)
    X = vec.fit_transform(corpus)
    feat = vec.get_feature_names_out()
    print(f'聚类样本 {len(corpus)} 人，词表 {len(feat)}')

    K = 8
    km = KMeans(n_clusters=K, random_state=42, n_init=10)
    labels = km.fit_predict(X)
    for tid, lab in zip(tids, labels):
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
        json.dump({str(t): int(l) for t, l in zip(tids, labels)}, f)
    conn.close()


if __name__ == '__main__':
    main()

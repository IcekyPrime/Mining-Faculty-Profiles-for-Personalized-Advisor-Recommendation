# 处理层说明（Processing Layer）

对数据层 SQLite 数据库（`data/db/mentor.db`）做数据挖掘处理，对应课程知识点（相似检索、链接分析、社区发现、聚类、关联规则等）。结果写入数据库 `processing` 表及 `data/exports/` 目录。

## 运行顺序

```powershell
cd processing
python preprocess.py        # 1. 拼音索引 + 论文年份 + 合作网络
python keyword_extract.py   # 2. jieba + TF-IDF 关键词
python similarity_index.py  # 3. MinHash + LSH
python ranking.py           # 4. PageRank + HITS
python community.py         # 5. Louvain 社区发现
python clustering.py        # 6. K-means 聚类
python association.py       # 7. Apriori 关联规则
python score.py             # 8. 综合评分
```

## 模块与课程知识点对应

| 模块 | 算法 | 课程知识点 | 产出 |
|---|---|---|---|
| `preprocess.py` | 拼音姓名索引、作者抽取 | 数据清洗/集成 | `exports/pinyin_index.json`、`collab_edges.csv`、论文年份 |
| `keyword_extract.py` | jieba 分词 + TF-IDF | 文本知识抽取、向量化 | `processing.keywords` |
| `similarity_index.py` | Shingling + MinHash + LSH | 相似检索（similar.pdf） | `exports/similar_pairs.json` |
| `ranking.py` | PageRank + HITS | 链接分析（link.pdf） | `processing.pagerank/hits_*` |
| `community.py` | Louvain（模块度） | 社区发现（community.pdf） | `processing.community`、`exports/communities.json` |
| `clustering.py` | K-means | 聚类（community.pdf） | `processing.cluster`、`exports/clusters.json` |
| `association.py` | Apriori + 关联规则 | 频繁项集/关联规则 | `exports/association_rules.json` |
| `score.py` | 多指标加权归一化 | 综合评分 | `processing.score`、`exports/scores.json` |

## 处理结果概况

- 关键词抽取：746 人（有研究方向/简介文本）。
- 合作网络：167 条边、127 位教师（仅计算机学院，因其论文含英文作者列表）。
- Louvain：12 个研究社区，模块度 0.65。
- K-means：8 个主题簇（大致对应操作系统/集成电路/电力系统/机器人/安全等方向）。
- 关联规则：12 条（如 {新能源}→{电力电子}、{深度学习}→{人工智能}）。
- 综合评分：746 人（融合论文产出、引用影响、荣誉、教学口碑，0–100 分）。

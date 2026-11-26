# 处理层说明（Processing Layer）

对数据层 SQLite 数据库（`data/db/mentor.db`）做数据挖掘处理，覆盖文本特征、相似检索、
链接分析、社区发现、主题模型、聚类、关联规则与综合评分。结果写入 `processing` 表及
`data/exports/` 目录。

## 运行顺序

```powershell
cd processing
python preprocess.py        # 1. 拼音索引 + 论文年份 + 合作网络
python keyword_extract.py   # 2. jieba + TF-IDF 关键词
python topic_model.py       # 3. TF-IDF + NMF 主题模型（新增）
python similarity_index.py  # 4. MinHash + LSH
python ranking.py           # 5. PageRank + HITS
python community.py         # 6. Louvain 社区发现
python clustering.py        # 7. SVD + K-means 自动选 K
python association.py       # 8. Apriori 关联规则（词典/语料动态项集）
python score.py             # 9. 综合评分
python score_v2.py          # 10. 改进评分 v2
python refresh.py           # 11. 只重算处理层（不抓取、不重建库）
```

AI 联网补全或数据工坊应用后，服务端会按 `refresh.py` 的顺序重跑处理层；`refresh.py` 默认
使用 `data/db/mentor.db`，也可用 `MENTOR_DB_PATH` 指向其他数据库。它只更新处理列，
不会调用 `db.reset()` 或删除教师/论文/课程。

## 模块与课程知识点对应

| 模块 | 算法 | 课程知识点 | 产出 |
|---|---|---|---|
| `preprocess.py` | 拼音姓名索引、作者抽取 | 数据清洗/集成 | `exports/pinyin_index.json`、`collab_edges.csv`、论文年份 |
| `keyword_extract.py` | jieba 分词 + TF-IDF | 文本知识抽取、向量化 | `processing.keywords` |
| `topic_model.py` | TF-IDF + NMF、主题数自动选择 | 主题模型、降维 | `processing.topic_primary/topic_distribution/topic_label`、`exports/topics.json` |
| `similarity_index.py` | Shingling + MinHash + LSH | 相似检索 | `exports/similar_pairs.json` |
| `ranking.py` | PageRank + HITS | 链接分析 | `processing.pagerank/hits_*` |
| `community.py` | Louvain（模块度） | 社区发现 | `processing.community`、`exports/communities.json` |
| `clustering.py` | TruncatedSVD + K-means + 轮廓系数 | 降维、聚类 | `processing.cluster`、`exports/clusters.json`、`cluster_meta.json` |
| `association.py` | Apriori + support/confidence/lift | 频繁项集/关联规则 | `exports/association_rules.json`、`association_meta.json` |
| `score.py` | 多指标加权归一化 | 综合评分 | `processing.score`、`exports/scores.json` |
| `score_v2.py` | 分位数 + 缺失感知 + 收缩先验 | 评分改进 | `processing.score_v2/score_parts/score_coverage` |
| `refresh.py` | 顺序调度上述脚本 | 处理层增量刷新 | 处理列与 exports |

## 当前结果（2026-11-24）

- 关键词抽取：771 人（有研究方向/研究主题/简介文本）。
- 主题模型：771 篇文档、词表 1,304、自动 K=8；主题标签见 `data/exports/topics.json`。
- 合作网络：2751 条边、127 位教师（仅计算机学院，因其论文含英文作者列表）。
- 相似导师：72 对（MinHash + LSH + Jaccard ≥ 0.25）。
- Louvain：23 个研究社区，模块度约 0.69。
- 聚类：SVD 50 维 + K-means，自动 K=8，轮廓系数 0.0754。
- 关联规则：5 条；项集来自 `data/mining/lexicon.json`（53 项、577 位有方向教师、support 0.02）。
- 综合评分：773 人（融合论文产出、引用影响、荣誉、教学口碑，0–100 分）。

## 换一批数据时

1. 新数据库放到 `data/db/`，用 `MENTOR_DB_PATH` 指向它；
2. 换学科时改 `data/mining/lexicon.json` 的 `aliases` 与 `areas`，或设置 `MENTOR_LEXICON_PATH`；
3. 重新跑 `topic_model.py`、`clustering.py`、`association.py`；
4. 主题数默认按语料规模 + 轮廓系数选，可用 `MENTOR_TOPIC_K` 固定；
5. 关联规则支持度可用 `MENTOR_RULE_SUPPORT` 调整；规则变少通常意味着项集/支持度口径变严。

已知边界：字段语义仍是“教师画像”；中文专业新词需补进 `areas`；教师文本过短时主题数会下降。
详细的公式、参数与评估见 [`docs/数据挖掘-算法与泛化说明.md`](../docs/数据挖掘-算法与泛化说明.md)。

# -*- coding: utf-8 -*-
"""通用数据挖掘组件（不依赖 Flask，可复用到其它文档/教师库）。

本模块解决的问题不是“再补一批教师数据”，而是把当前项目里的算法改成
**对数据规模和领域都可配置、可从语料自学习** 的版本：

1. 领域词典外置：`data/mining/lexicon.json`，查询别名和关联规则项集都能替换；
2. 语料自学习：从“中文（英文缩写）”这类写法自动学习缩写，不写死 ML/CV；
3. 主题模型：TF-IDF + NMF，自动选择主题数，输出教师-主题分布；
4. 聚类：TF-IDF + K-means，轮廓系数自动选 K；
5. 主题检索：把查询词投影到主题词空间，计算教师主题分布与查询的余弦相似度。

这些函数不读写固定数据库，输入是通用文本/记录列表，便于换学院、换学校、
甚至换成一批评委/论文/课程数据后继续使用。
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
ASCII_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#._/-]*")
ACRONYM_PATTERNS = (
    # 机器学习（ML） / 机器学习 (Machine Learning)
    (re.compile(r"([\u4e00-\u9fff]{2,20})\s*[（(]\s*([A-Za-z][A-Za-z0-9+.#/_-]{1,16})\s*[）)]"), 1, 2),
    # ML（机器学习） / Machine Learning (机器学习)
    (re.compile(r"([A-Za-z][A-Za-z0-9+.#/_-]{1,16})\s*[（(]\s*([\u4e00-\u9fff]{2,20})\s*[）)]"), 2, 1),
)
STOP_TERMS = set("""
的 了 和 与 及 或 等 在 中 上 下 对 为 于 从 到 被 把 将 是 有 也 都 而 并 且 及其 以及
主要 研究 方向 领域 技术 方法 应用 系统 相关 基于 包括 从事 目前 负责 参与 进行 实现
提出 针对 开展 承担 主持 完成 获得 发表 论文 国际 国内 主席 委员 编委 教授 研究员
副教授 讲师 博士 硕士 学位 毕业 担任 荣获 获奖 项目 课题 基金 合作 企业 成果 现任
曾任 期刊 会议 出版 国家 上海 教育部 学会 会员 杰出 优秀 人才 计划 学者 专家 作为
学院 学校 大学 系 所 实验室 中心 团队 招生 联系 欢迎 同学 本科生 研究生 博士后
""".split())
NOISE_TERMS = ("大学", "学院", "学校", "实验室", "研究中心", "委员会", "公司", "集团")


def normalise(text) -> str:
    """NFKC + 折叠空白 + 去掉控制字符，适合中英文混合文本。"""
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return " ".join(value.split()).strip()


def _get_jieba():
    try:
        import jieba  # type: ignore
        return jieba
    except ImportError:  # pragma: no cover - 无 jieba 时退化为正则
        return None


_JIEBA = _get_jieba()
_JIEBA_WORDS: set[str] = set()


def add_domain_terms(items) -> None:
    """把外部词典中的词加入 jieba，避免“计算机视觉”被切成两个词。"""
    if _JIEBA is None:
        return
    for item in items or []:
        word = normalise(item)
        if word and word not in _JIEBA_WORDS:
            _JIEBA.add_word(word)
            _JIEBA_WORDS.add(word)


def terms(text) -> list[str]:
    """通用分词：中文词 + 英文词；没有 jieba 时退化为 CJK 二元组。"""
    text = normalise(text).lower()
    if not text:
        return []
    words = _JIEBA.lcut(text) if _JIEBA else []
    if not words:
        words = CJK_RE.findall(text) + ASCII_RE.findall(text)
        # 没有分词器时，CJK 连续串再补二元组，保证中文可检索。
        cjk_words = []
        for run in CJK_RE.findall(text):
            cjk_words.extend(run[i:i + 2] for i in range(len(run) - 1))
        words.extend(cjk_words)
    out = []
    for word in words:
        word = normalise(word).lower()
        if len(word) < 2 or word in STOP_TERMS:
            continue
        if re.fullmatch(r"\d+", word):
            continue
        out.append(word)
    return out


def _alias_hit(query_lower: str, alias: str) -> bool:
    """短英文别名按词边界匹配，避免 html 命中 ml、said 命中 ai。"""
    if alias.isascii():
        return re.search(
            r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])",
            query_lower,
        ) is not None
    return alias in query_lower


def default_lexicon_path() -> str:
    env = os.environ.get("MENTOR_LEXICON_PATH")
    if env:
        return env
    return str(Path(__file__).resolve().parents[1] / "data" / "mining" / "lexicon.json")


def load_lexicon(path=None) -> dict:
    """读取外置词典；缺失或损坏时返回空词典，不影响主流程。"""
    path = path or default_lexicon_path()
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            return {"aliases": {}, "areas": []}
    except (OSError, ValueError, TypeError):
        return {"aliases": {}, "areas": []}
    aliases = payload.get("aliases") or {}
    if not isinstance(aliases, dict):
        aliases = {}
    areas = payload.get("areas") or []
    if not isinstance(areas, list):
        areas = []
    return {
        "version": payload.get("version", 1),
        "aliases": {
            str(key).lower(): list(value) if isinstance(value, (list, tuple))
            else [str(value)]
            for key, value in aliases.items()
            if key and value
        },
        "areas": [str(item) for item in areas if str(item).strip()],
    }


def learn_acronyms(documents, min_count=None, max_pairs=200) -> dict[str, str]:
    """从语料自动学习“中文全称（英文缩写）”映射。

    `min_count=None` 时：小语料（< 50 篇）允许出现 1 次，大语料要求 2 次，
    避免一次性出现的机构缩写污染查询扩展。
    """
    docs = [normalise(doc) for doc in documents or [] if normalise(doc)]
    if min_count is None:
        min_count = 1 if len(docs) < 50 else 2
    counts = Counter()
    for doc in docs:
        for pattern, zh_group, en_group in ACRONYM_PATTERNS:
            for match in pattern.finditer(doc):
                zh = match.group(zh_group).strip()
                en = match.group(en_group).strip().lower()
                if len(zh) < 2 or len(en) < 2:
                    continue
                if any(word in zh for word in NOISE_TERMS):
                    continue
                if not re.search(r"[\u4e00-\u9fff]", zh):
                    continue
                counts[(en, zh)] += 1
    learned = {}
    for (en, zh), count in counts.most_common(max_pairs):
        if count >= min_count:
            learned.setdefault(en, zh)
    return learned


class QueryExpander:
    """查询扩展器：外部词典 + 当前语料自动学习，二者都不绑定具体数据集。"""

    def __init__(self, aliases=None, learned=None):
        self.aliases = {}
        for alias, expansions in (aliases or {}).items():
            key = normalise(alias).lower()
            if not key:
                continue
            values = expansions if isinstance(expansions, (list, tuple)) else [expansions]
            self.aliases[key] = [normalise(value) for value in values if normalise(value)]
        for alias, canonical in (learned or {}).items():
            self.aliases.setdefault(normalise(alias).lower(), [normalise(canonical)])

    @classmethod
    def from_records(cls, records, lexicon=None):
        docs = [corpus_text(record) for record in records or []]
        lex = lexicon if isinstance(lexicon, dict) else load_lexicon()
        add_domain_terms(lex.get("areas") or [])
        return cls(lex.get("aliases") or {}, learn_acronyms(docs))

    def expand(self, query) -> str:
        query = normalise(query)
        if not query:
            return ""
        lower = query.lower()
        additions = []
        for alias, expansions in self.aliases.items():
            if not _alias_hit(lower, alias):
                continue
            for expansion in expansions:
                if expansion and expansion.lower() not in lower:
                    additions.append(expansion)
        if not additions:
            return query
        return query + " " + " ".join(dict.fromkeys(additions))


def corpus_text(record) -> str:
    """从通用记录里拼出用于主题/缩写的文本；字段缺失时自动跳过。"""
    item = record.get("item") if isinstance(record, dict) else {}
    item = item or {}
    fields = (
        item.get("name"),
        item.get("name_pinyin"),
        item.get("research_topics"),
        item.get("research_directions"),
        " ".join(str(k) for k in (item.get("keywords") or [])),
        item.get("institute"),
        item.get("title"),
    )
    return normalise(" ".join(str(value) for value in fields if value))


def choose_topic_k(X, k_min=4, k_max=10, random_state=42) -> int:
    """用轮廓系数在候选主题数中选 K；小语料自动收缩范围。"""
    from sklearn.decomposition import NMF
    from sklearn.metrics import silhouette_score

    n_samples = getattr(X, "shape", (0, 0))[0]
    if n_samples <= 2:
        return 1
    upper = min(k_max, n_samples - 1)
    if upper < 1:
        return 1
    lower = max(2, min(k_min, upper))
    # 主题数下界随语料规模增长（约为 sqrt(N)/3.5），再用轮廓系数在候选区间内选；
    # 这比固定 K=8 更适配小数据集，也避免大语料只得到 3–4 个过宽主题。
    scaled = int(round(math.sqrt(n_samples) / 3.5))
    lower = max(lower, min(upper, scaled))
    best_k, best_score = lower, -1.0
    for k in range(lower, upper + 1):
        model = NMF(
            n_components=k,
            init="nndsvda",
            random_state=random_state,
            max_iter=400,
        )
        weights = model.fit_transform(X)
        labels = weights.argmax(axis=1)
        unique = len(set(labels.tolist()))
        if unique < 2:
            continue
        sample_size = min(n_samples, 2000)
        score = silhouette_score(
            weights, labels, sample_size=sample_size, random_state=random_state
        )
        # 轮廓系数相近时偏向更小的 K，主题更稳、更易解释。
        if score > best_score + 1e-9:
            best_k, best_score = k, float(score)
    return best_k


def build_topic_model(texts, n_topics=None, lexicon=None, max_features=3000, random_state=42) -> dict:
    """TF-IDF + NMF 主题模型；返回词表、主题词分布与教师-主题分布。"""
    from sklearn.decomposition import NMF
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    lex = lexicon if isinstance(lexicon, dict) else load_lexicon()
    add_domain_terms((lex.get("areas") or []) + list((lex.get("aliases") or {}).keys()))
    corpus = [normalise(text) for text in texts or [] if normalise(text)]
    if not corpus:
        return {"k": 0, "topics": [], "doc_topic": [], "documents": [], "vocabulary": 0}
    min_df = 1 if len(corpus) < 20 else 2
    vectorizer = TfidfVectorizer(
        tokenizer=terms,
        token_pattern=None,
        lowercase=False,
        min_df=min_df,
        max_df=0.70,
        max_features=max_features,
    )
    matrix = vectorizer.fit_transform(corpus)
    if matrix.shape[1] < 2:
        return {"k": 0, "topics": [], "doc_topic": [], "documents": corpus,
                "vocabulary": int(matrix.shape[1])}
    upper = min(matrix.shape[0] - 1, matrix.shape[1] - 1, 20)
    if upper < 1:
        return {"k": 0, "topics": [], "doc_topic": [], "documents": corpus,
                "vocabulary": int(matrix.shape[1])}
    k = int(n_topics) if n_topics else choose_topic_k(matrix, k_max=min(10, upper))
    k = max(1, min(k, upper))
    model = NMF(
        n_components=k,
        init="nndsvda",
        random_state=random_state,
        max_iter=500,
    )
    weights = model.fit_transform(matrix)
    doc_topic = normalize(weights, norm="l1")
    names = vectorizer.get_feature_names_out()
    topics = []
    for topic_id, component in enumerate(model.components_):
        indexes = component.argsort()[::-1][:20]
        topic_terms = [
            {"term": str(names[idx]), "weight": round(float(component[idx]), 5)}
            for idx in indexes if component[idx] > 0
        ][:15]
        label = " / ".join(item["term"] for item in topic_terms[:3]) or f"主题{topic_id}"
        topics.append({"id": topic_id, "label": label, "terms": topic_terms})
    return {
        "k": k,
        "topics": topics,
        "doc_topic": doc_topic,
        "documents": corpus,
        "vocabulary": int(matrix.shape[1]),
        "method": "TF-IDF + NMF",
    }


def serialize_topic_model(model, ids) -> dict:
    """把模型输出为可持久化 JSON；只保留概率大于 1% 的主题，控制体积。"""
    topics = model.get("topics") or []
    distributions = {}
    doc_topic = model.get("doc_topic")
    if doc_topic is None:
        doc_topic = []
    for tid, row in zip(ids, doc_topic, strict=False):
        values = [
            {"id": index, "weight": round(float(weight), 4)}
            for index, weight in enumerate(row.tolist())
            if float(weight) >= 0.01
        ]
        distributions[str(tid)] = values
    return {
        "method": model.get("method", "TF-IDF + NMF"),
        "k": int(model.get("k") or 0),
        "document_count": len(model.get("documents") or []),
        "vocabulary": int(model.get("vocabulary") or 0),
        "topics": topics,
        "doc_topics": distributions,
    }


def topic_scores(payload, query) -> dict[int, float]:
    """把查询词映射到主题词空间，再与教师主题分布做余弦相似度。

    这里不依赖保存 sklearn 模型对象：持久化 JSON 里保存主题词权重，
    查询侧用同一套通用分词做“主题词投影”，因此可直接用于新数据集。
    纯主题分数是粗粒度画像，应用层用 ``combine_scores`` 把它和 BM25 融合。
    """
    if not isinstance(payload, dict) or not payload.get("topics"):
        return {}
    query_terms = set(terms(query))
    if not query_terms:
        return {}
    query_vector = {}
    for topic in payload["topics"]:
        weight = sum(
            float(item.get("weight") or 0)
            for item in topic.get("terms") or []
            if item.get("term") in query_terms
        )
        if weight > 0:
            query_vector[int(topic["id"])] = weight
    if not query_vector:
        return {}
    norm_q = math.sqrt(sum(value * value for value in query_vector.values())) or 1.0
    scores = {}
    for tid, items in (payload.get("doc_topics") or {}).items():
        dot = 0.0
        norm_d = 0.0
        for item in items or []:
            weight = float(item.get("weight") or 0)
            topic_id = int(item.get("id") or 0)
            dot += weight * query_vector.get(topic_id, 0.0)
            norm_d += weight * weight
        if dot <= 0:
            continue
        score = dot / (norm_q * (math.sqrt(norm_d) or 1.0))
        if score > 0:
            scores[int(tid)] = round(score, 4)
    return scores


def normalize_scores(scores) -> dict[int, float]:
    """把任意非负分数缩放到 [0,1]，空集合返回空字典。"""
    if not scores:
        return {}
    low = min(scores.values())
    high = max(scores.values())
    if high - low < 1e-9:
        return {int(key): 1.0 for key in scores}
    return {int(key): (float(value) - low) / (high - low) for key, value in scores.items()}


def combine_scores(bm25_scores, topic_scores_map, topic_weight=0.4) -> dict[int, float]:
    """BM25 召回集内融合主题分数。

    只在 BM25 已召回的文档上融合，避免主题模型把完全没有词法依据的档案
    拉进来；0.4 是当前 10 条标注查询上 NDCG 较好的权重，可通过参数覆盖。
    """
    base = {int(key): float(value) for key, value in (bm25_scores or {}).items() if value > 0}
    if not base:
        return {}
    base_norm = normalize_scores(base)
    topic_norm = normalize_scores({
        int(key): float(value)
        for key, value in (topic_scores_map or {}).items()
        if key in base and value > 0
    })
    weight = max(0.0, min(1.0, float(topic_weight)))
    return {
        tid: round((1.0 - weight) * value + weight * topic_norm.get(tid, 0.0), 6)
        for tid, value in base_norm.items()
    }


def cluster_with_auto_k(matrix, k_min=4, k_max=8, random_state=42) -> tuple[list[int], int, float]:
    """TF-IDF 矩阵上先做 TruncatedSVD 降维，再用 K-means + 轮廓系数选 K。

    高维稀疏文本直接算欧氏距离容易受维度诅咒影响；先用 SVD 保留主要语义，
    再做聚类，是课程里常见的“降维 + 聚类”组合。
    """
    from sklearn.cluster import KMeans
    from sklearn.decomposition import TruncatedSVD
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import normalize

    n_samples, n_features = getattr(matrix, "shape", (0, 0))
    working = matrix
    if n_features > 60 and n_samples > 10:
        components = min(50, n_features - 1, n_samples - 1)
        svd = TruncatedSVD(n_components=components, random_state=random_state)
        working = normalize(svd.fit_transform(matrix))
    if n_samples <= 1:
        return [0] * n_samples, min(1, n_samples), 0.0
    upper = min(k_max, n_samples - 1)
    lower = max(2, min(k_min, upper))
    best = (None, lower, -1.0)
    for k in range(lower, upper + 1):
        model = KMeans(n_clusters=k, random_state=random_state, n_init=10)
        labels = model.fit_predict(working)
        if len(set(labels.tolist())) < 2:
            continue
        score = float(silhouette_score(
            working, labels, sample_size=min(n_samples, 2000), random_state=random_state
        ))
        if score > best[2] + 1e-9:
            best = (labels, k, score)
    if best[0] is None:
        model = KMeans(n_clusters=min(2, n_samples), random_state=random_state, n_init=10)
        labels = model.fit_predict(working)
        return labels.tolist(), len(set(labels.tolist())), 0.0
    return best[0].tolist(), int(best[1]), round(float(best[2]), 4)

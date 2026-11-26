# -*- coding: utf-8 -*-
"""BM25F 检索打分（可选的第二种相关度排序）。

为什么单独一个模块：
- 原 `services.relevance()` 是人工分层规则，可解释但忽略词频、文档长度和
  全库稀有度；BM25 是信息检索的经典基线，适合在课程里做对照实验。
- 这里不改动任何已有评分权重，只在 `sort=bm25` 时生效，旧接口行为不变。

实现要点：
- 中文按「相邻二元组」切分，不再使用单字；英文/数字按单词切分；
- 教师姓名、拼音、关键词、研究方向、研究所、职称分别给不同字段权重
  （BM25F 的简化版），避免长简介把短姓名淹没；
- 查询别名扩展：缩写与中文写法来自外置词典 `data/mining/lexicon.json`，
  同时从当前语料的“中文（英文缩写）”写法自动学习；不写死某几个词，
  换学科/换语料后仍可工作；
- IDF 使用 `log(1 + (N - df + 0.5) / (df + 0.5))`，负 IDF 截断为 0。
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .mining import QueryExpander, load_lexicon
from .mining import terms as mining_terms

CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
ASCII_WORD = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9+#._-]*")

# 字段权重：姓名/拼音最重要，研究方向与关键词次之，职称/研究所只作补充。
FIELD_WEIGHTS = {
    "name": 4.0,
    "pinyin": 2.5,
    "keywords": 2.0,
    "directions": 2.0,
    "institute": 1.0,
    "title": 1.0,
}

K1 = 1.5
B = 0.75


def expand_query(query: str, expander: QueryExpander | None = None) -> str:
    """用外置词典扩展查询；传入 expander 时可叠加当前语料自学习缩写。"""
    query = str(query or "").strip()
    if not query:
        return ""
    expander = expander or QueryExpander(load_lexicon().get("aliases") or {})
    return expander.expand(query)


def tokenize(text: str) -> list[str]:
    """轻量中英文分词：jieba 词 + 中文二元组 + 英文/数字单词。

    不保留中文单字：单字会把「机/器/学/习」这类常见字变成弱命中，
    让“机器学习”召回大量只沾一个字的档案。jieba 词保证“机器人”“计算机视觉”
    这类完整术语可命中，二元组兜底未登录词与新领域词。
    """
    if not text:
        return []
    text = str(text).lower()
    tokens = mining_terms(text)
    for run in CJK_RUN.findall(text):
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    for word in ASCII_WORD.findall(text):
        if len(word) >= 2:
            tokens.append(word)
    return tokens


def _document(record: dict) -> dict[str, Counter]:
    item = record.get("item") or {}
    return {
        "name": Counter(tokenize(record.get("name") or item.get("name") or "")),
        "pinyin": Counter(tokenize(item.get("name_pinyin") or "")),
        "keywords": Counter(tokenize(" ".join(str(k) for k in item.get("keywords") or []))),
        "directions": Counter(tokenize(item.get("research_directions") or "")),
        "institute": Counter(tokenize(item.get("institute") or "")),
        "title": Counter(tokenize(item.get("title") or "")),
    }


class BM25Index:
    """对一组教师记录建立内存索引；773 条规模下构建耗时通常低于 50ms。"""

    def __init__(self, records):
        self.records = list(records)
        self.expander = QueryExpander.from_records(self.records)
        self.docs = []
        self.doc_len = []
        self.df = Counter()
        for record in self.records:
            fields = _document(record)
            weighted_len = sum(
                sum(counts.values()) * FIELD_WEIGHTS[name] for name, counts in fields.items()
            )
            self.docs.append(fields)
            self.doc_len.append(weighted_len or 1.0)
            # df 必须按“文档”去重：同一词同时出现在姓名、关键词、方向等字段时
            # 只能算一次；按字段累加会让 IDF 偏低、常见词权重被高估。
            doc_terms = {term for counts in fields.values() for term in counts}
            for term in doc_terms:
                self.df[term] += 1
        self.n = len(self.docs)
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.idf = {
            term: max(0.0, math.log(1.0 + (self.n - freq + 0.5) / (freq + 0.5)))
            for term, freq in self.df.items()
        }

    def scores(self, query: str) -> dict[int, float]:
        terms = tokenize(self.expander.expand(query))
        if not terms or not self.n:
            return {}
        unique = list(dict.fromkeys(terms))
        result: dict[int, float] = {}
        for idx, fields in enumerate(self.docs):
            dl = self.doc_len[idx]
            score = 0.0
            for term in unique:
                if term not in self.idf:
                    continue
                tf = sum(counts.get(term, 0) * FIELD_WEIGHTS[name] for name, counts in fields.items())
                if not tf:
                    continue
                score += self.idf[term] * tf * (K1 + 1.0) / (
                    tf + K1 * (1.0 - B + B * dl / (self.avgdl or 1.0))
                )
            if score > 0:
                result[self.records[idx]["item"]["id"]] = round(score, 4)
        return result


def build_index(records) -> BM25Index:
    return BM25Index(records)

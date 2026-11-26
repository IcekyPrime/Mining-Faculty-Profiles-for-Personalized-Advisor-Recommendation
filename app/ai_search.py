# -*- coding: utf-8 -*-
"""AI 自然语言检索：模型只负责“理解意图”和“解释结果”，真正的候选排序仍
由本地 SQLite 语料与既有 relevance 规则完成，避免模型直接编造教师。
"""
import json

from .ai_client import AIError, chat_json, is_local_base
from .db import connect, db_stamp
from .services import SORTS, relevance, search_corpus, sort_records

PARSE_SYSTEM = """你是导师检索意图解析器。把用户的中文自然语言需求解析为 JSON，
不要解释，不要编造教师姓名。只返回一个 JSON 对象：
{
  "keywords": ["用于匹配姓名/研究方向/关键词的词，最多 8 个"],
  "college": "用户明确提到的学院；未提到填空字符串",
  "title": "用户明确要求的职称，如 教授/副教授；未提到填空字符串",
  "phd_only": true/false,
  "sort": "score|score2|academic|teaching|relevance",
  "summary": "一句话概括用户真正想找什么"
}

规则：
- 不要凭空扩展用户没有提到的方向；可以把同义词放进 keywords。
- 用户说“学术强/论文多/引用高”时 sort=academic；说“讲课好/口碑好”时 sort=teaching；
  说“方向匹配/相关”时 sort=relevance；默认 score。
- 只输出 JSON。"""

REASON_SYSTEM = """你是导师推荐解释助手。根据给定候选教师的公开档案，为每位教师写一句
不超过 40 字的中文推荐理由。只能依据提供的字段，不能编造论文、奖项或联系方式。
返回 JSON：{"summary":"整体推荐说明，80字以内","reasons":{"教师id":"理由"}}
不要输出 Markdown。"""


def _allowed_colleges(db_path):
    conn = connect(db_path, readonly=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT college FROM teachers WHERE college IS NOT NULL AND college <> ''"
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def _parse_intent(config, query, colleges):
    raw = chat_json(
        config,
        PARSE_SYSTEM,
        f"可选学院：{json.dumps(colleges, ensure_ascii=False)}\n用户需求：{query}",
        temperature=0.1,
        max_tokens=650,
    )
    keywords = raw.get("keywords") if isinstance(raw.get("keywords"), list) else []
    keywords = [str(item).strip() for item in keywords if str(item).strip()][:8]
    if not keywords:
        keywords = [query]
    college = str(raw.get("college") or "").strip()
    if college not in colleges:
        college = ""
    title = str(raw.get("title") or "").strip()[:30]
    sort = str(raw.get("sort") or "score").strip()
    if sort not in SORTS:
        sort = "score"
    return {
        "keywords": keywords,
        "college": college,
        "title": title,
        "phd_only": bool(raw.get("phd_only")),
        "sort": sort,
        "summary": str(raw.get("summary") or "").strip()[:200],
    }


def _score_record(record, keywords):
    return sum(relevance(record, keyword) for keyword in keywords)


def _candidate_text(item):
    return " | ".join([
        str(item.get("name") or ""),
        str(item.get("title") or ""),
        str(item.get("college") or ""),
        str(item.get("institute") or ""),
        str(item.get("research_directions") or "")[:120],
        "、".join(item.get("keywords") or [])[:80],
    ])


def _reason(config, query, intent, items):
    payload = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "college": item.get("college"),
            "title": item.get("title"),
            "directions": (item.get("research_directions") or "")[:120],
            "score": item.get("score"),
            "score_v2": item.get("score_v2"),
            "h_index": item.get("h_index"),
        }
        for item in items[:8]
    ]
    raw = chat_json(
        config,
        REASON_SYSTEM,
        f"用户需求：{query}\n解析意图：{json.dumps(intent, ensure_ascii=False)}\n"
        f"候选教师：{json.dumps(payload, ensure_ascii=False)}",
        temperature=0.2,
        max_tokens=1000,
    )
    reasons = raw.get("reasons") if isinstance(raw.get("reasons"), dict) else {}
    return str(raw.get("summary") or "").strip()[:240], {
        str(key): str(value)[:80] for key, value in reasons.items()
    }


def ai_search(db_path, config, query, college="", sort="", page=1, size=20):
    query = (query or "").strip()
    if not query:
        raise AIError("请输入自然语言检索需求。", code="empty_query", status=400)
    if len(query) > 300:
        raise AIError("检索需求过长，请控制在 300 字以内。", code="query_too_long", status=400)
    if (
        not config.get("enabled")
        or not config.get("model")
        or not config.get("api_base")
        or (not config.get("api_key") and not is_local_base(config.get("api_base")))
    ):
        raise AIError("AI 尚未启用，请先在设置中配置模型。", code="ai_not_configured", status=400)

    colleges = _allowed_colleges(db_path)
    intent = _parse_intent(config, query, colleges)
    if college and college in colleges:
        intent["college"] = college
    if sort in SORTS:
        intent["sort"] = sort

    records = list(search_corpus(db_stamp(db_path)))
    target_college = intent["college"]
    if target_college:
        records = [r for r in records if r["item"].get("college") == target_college]
    if intent["title"]:
        title = intent["title"]
        records = [r for r in records if title in str(r["item"].get("title") or "")]
    if intent["phd_only"]:
        records = [r for r in records if r["item"].get("is_phd_advisor")]

    scored = [( _score_record(record, intent["keywords"]), record) for record in records]
    matched = [(score, record) for score, record in scored if score > 0]
    note = ""
    if not matched:
        matched = scored
        note = "没有命中具体关键词，已按你选择的排序展示全部候选。"
    if intent["sort"] == "relevance":
        matched.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
    else:
        matched_records = [record for _, record in matched]
        sort_records(matched_records, intent["sort"])
        matched = [(0, record) for record in matched_records]

    total = len(matched)
    pages = max(1, (total + size - 1) // size)
    start = (page - 1) * size
    selected = [dict(record["item"]) for _, record in matched[start:start + size]]
    for item in selected:
        item["ai_score"] = next(
            (score for score, record in matched if record["item"].get("id") == item.get("id")), 0
        )
    reason_summary, reasons = "", {}
    reason_error = ""
    if selected:
        try:
            reason_summary, reasons = _reason(config, query, intent, selected)
        except AIError as exc:
            reason_error = exc.message
    for item in selected:
        item["ai_reason"] = reasons.get(str(item.get("id")))

    return {
        "query": query,
        "items": selected,
        "results": selected,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
        "ai": {
            "model": config.get("model") or "",
            "summary": reason_summary or intent["summary"],
            "intent_summary": intent["summary"],
            "keywords": intent["keywords"],
            "filters": {
                "college": intent["college"],
                "title": intent["title"],
                "phd_only": intent["phd_only"],
                "sort": intent["sort"],
            },
            "note": note,
            "reason_error": reason_error,
        },
    }

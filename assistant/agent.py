# -*- coding: utf-8 -*-
"""API 主导的导师检索代理。

流程：模型理解意图 → 选择并调用本地/联网工具 → 模型总结。
教师卡片与来源由工具结果生成；正文不再套用固定模板。
"""
import json
import re

from . import answer, llm, rag, retrieval, tools

TOOL_SPECS = [
    {
        "name": "search_teachers",
        "description": "按研究方向或关键词检索本地导师，可限定学院",
        "args": {"terms": ["数据挖掘"], "college": "", "limit": 5,
                 "depth": False, "exclude": []},
    },
    {
        "name": "get_teacher",
        "description": "获取某位教师的档案、论文和课程",
        "args": {"name": "教师姓名"},
    },
    {
        "name": "get_lab",
        "description": "获取某位教师所在研究所、同研究所教师和合作记录",
        "args": {"name": "教师姓名"},
    },
    {
        "name": "compare_teachers",
        "description": "比较两位教师",
        "args": {"names": ["教师A", "教师B"]},
    },
    {
        "name": "list_college",
        "description": "列出某学院教师",
        "args": {"college": "学院名", "limit": 5},
    },
    {
        "name": "search_online",
        "description": "联网检索 arXiv、Crossref 和 Acemap，仅在用户要最新成果或本地不足时使用",
        "args": {"query": "English search terms"},
    },
]

SUGGEST_INTENT = {
    "teacher": "teacher",
    "recent": "teacher",
    "recommend": "recommend",
    "experts": "experts",
    "lab": "teacher",
    "compare": "teacher",
    "list": "recommend",
    "online": "experts",
    "chat": "greeting",
    "refusal": "clarify",
}


def _parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None


def _plan(question, lang, context):
    spec = json.dumps(TOOL_SPECS, ensure_ascii=False, indent=2)
    context = context or {}
    compact = {
        "last_intent": context.get("intent"),
        "last_terms": (context.get("slots") or {}).get("terms") or [],
        "last_college": (context.get("slots") or {}).get("college") or "",
        "last_cards": [c.get("name") for c in context.get("cards") or [] if c.get("name")],
        "force_online": bool(context.get("force_online")),
    }
    ctx = json.dumps(compact, ensure_ascii=False)[:1500]
    system = (
        "你是“交我导”的检索规划器。先理解用户问题，再选择工具。"
        "只输出 JSON 对象，不要 Markdown。"
        "格式：{\"intent\":\"teacher|recommend|lab|compare|list|online|chat|refusal\","
        "\"tools\":[{\"tool\":\"工具名\",\"args\":{...}}],"
        "\"reply\":\"当 tools 为空时给用户的回答\"}。"
        "规则：最多 2 个工具，只能使用给定工具；追问时结合 context 的 "
        "last_terms、last_college、last_cards。"
        "问某位教师信息用 get_teacher；问实验室或同事用 get_lab；"
        "比较两人用 compare_teachers；按方向推荐用 search_teachers；"
        "只问学院名单用 list_college；要最新论文或外部成果用 search_online。"
        "薪资、招生名额、主观人品评价等工具无法提供的，tools 为空，"
        "在 reply 中说明并给出替代检索建议。不要编造教师姓名。"
        "用户要求评价某位教师时，先调用 get_teacher 获取公开档案，不要直接拒绝；"
        "总结时说明只提供公开信息，不做主观评价。"
        "再推荐几位、还有别的、更多：terms 沿用 context.last_terms，"
        "exclude 填 context.last_cards 的姓名，limit 可设 6。"
        "如果上下文 context.force_online 为 true，优先调用 search_online。"
    )
    user = "可用工具：\n%s\n\n上下文：%s\n\n用户问题：%s" % (spec, ctx, question)
    raw = llm.chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], max_tokens=420, temperature=0.1, json_mode=True)
    plan = _parse_json(raw)
    if not isinstance(plan, dict):
        return None
    if not isinstance(plan.get("tools"), list):
        plan["tools"] = []
    if plan.get("tool"):
        plan["tools"] = [{"tool": plan.get("tool"), "args": plan.get("args") or {}}]
    plan["tools"] = plan["tools"][:2]
    return plan


def _execute(call):
    if not isinstance(call, dict):
        return None
    name = str(call.get("tool") or "").strip()
    args = call.get("args") if isinstance(call.get("args"), dict) else {}

    if name == "search_teachers":
        terms = [str(t).strip() for t in (args.get("terms") or []) if str(t).strip()][:4]
        college = str(args.get("college") or "").strip()
        try:
            limit = int(args.get("limit") or 5)
        except (ValueError, TypeError):
            limit = 5
        limit = min(8, max(1, limit))
        depth = bool(args.get("depth"))
        exclude = [str(x).strip() for x in (args.get("exclude") or []) if str(x).strip()][:8]
        fetch = min(24, limit + len(exclude) + 2)
        results = rag.search(terms, college=college or None,
                             limit=fetch, depth=depth)
        if exclude:
            blocked = set(exclude)
            results = [r for r in results if r["teacher"]["name"] not in blocked]
        results = results[:limit]
        return {
            "tool": name,
            "terms": terms,
            "college": college,
            "exclude": exclude,
            "candidates": [retrieval.candidate_payload(r) for r in results],
        }

    if name == "get_teacher":
        teacher_name = str(args.get("name") or "").strip()
        teacher = retrieval.by_name(teacher_name) if teacher_name else None
        if not teacher:
            return {"tool": name, "name": teacher_name, "teacher": None}
        return {
            "tool": name,
            "name": teacher_name,
            "teacher": retrieval.profile_payload(teacher),
            "papers": retrieval.papers_for(teacher["id"], 5),
            "courses": retrieval.courses_for(teacher["id"], 3),
        }

    if name == "get_lab":
        teacher_name = str(args.get("name") or "").strip()
        teacher = retrieval.by_name(teacher_name) if teacher_name else None
        if not teacher:
            return {"tool": name, "name": teacher_name, "teacher": None}
        lab = retrieval.lab_context(teacher["id"])
        mates = [{
            "id": m["id"], "name": m["name"], "college": m["college"],
            "title": m["title"], "directions": m["directions"],
            "homepage_url": m["homepage_url"], "personal_homepage": m["personal_homepage"],
        } for m in lab["mates"]]
        collabs = [{
            "id": c["teacher"]["id"], "name": c["teacher"]["name"],
            "college": c["teacher"]["college"], "title": c["teacher"]["title"],
            "homepage_url": c["teacher"]["homepage_url"],
            "personal_homepage": c["teacher"]["personal_homepage"],
            "weight": c["weight"],
        } for c in lab["collaborators"]]
        return {
            "tool": name,
            "name": teacher_name,
            "teacher": retrieval.profile_payload(teacher),
            "lab_name": lab["lab_name"],
            "institute": lab["institute"],
            "mates": mates,
            "collaborators": collabs,
        }

    if name == "compare_teachers":
        names = [str(n).strip() for n in (args.get("names") or []) if str(n).strip()][:2]
        profiles = []
        for teacher_name in names:
            teacher = retrieval.by_name(teacher_name)
            if teacher:
                profiles.append(retrieval.profile_payload(teacher))
        return {"tool": name, "names": names, "profiles": profiles}

    if name == "list_college":
        college = str(args.get("college") or "").strip()
        try:
            limit = int(args.get("limit") or 5)
        except (ValueError, TypeError):
            limit = 5
        limit = min(8, max(1, limit))
        results = retrieval.search([], college=college or None, limit=limit)
        return {
            "tool": name,
            "college": college,
            "candidates": [retrieval.candidate_payload(r) for r in results],
        }

    if name == "search_online":
        query = str(args.get("query") or "").strip()
        if not query:
            return None
        items, notes = tools.gather(query, teacher=None, want_recent=True)
        return {
            "tool": name,
            "query": query,
            "items": items[:8],
            "notes": [list(n) for n in notes],
        }

    return None


def _summarize(question, lang, plan, results):
    payload = json.dumps(results, ensure_ascii=False)[:7000]
    system = (
        "你是“交我导”的导师助手。根据工具结果回答用户问题。"
        "可以自由组织语言，也可以做比较和建议，但教师姓名、论文、指标、研究所"
        "必须来自工具结果，不能编造。不要做主观人品评价；"
        "工具结果为空时直接说明没有找到，并给出下一步建议。"
        "不要使用 Markdown 语法：不要加粗、表格或代码块；"
        "用纯文本短段落和以“- ”开头的简单列表。"
        "如果使用 get_lab：mates 是同研究所教师，collaborators 是合作记录，"
        "二者不等于实验室成员；必须说明这一依据和局限，不能声称他们都是同一实验室成员。"
        "用中文回答，除非用户使用英文；简洁自然。"
    )
    user = "用户问题：%s\n\n规划意图：%s\n\n工具结果：\n%s" % (
        question, plan.get("intent") or "", payload)
    text = llm.chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], max_tokens=900, temperature=0.4)
    text = (text or "").strip().replace("```", "").replace("**", "").strip()
    return text[:2500] if text else None


def _records(results):
    records = []
    for r in results:
        tool = r.get("tool")
        if tool in ("search_teachers", "list_college"):
            records.extend(r.get("candidates") or [])
        elif tool == "get_teacher":
            if r.get("teacher"):
                records.append(r["teacher"])
        elif tool == "get_lab":
            records.extend(r.get("mates") or [])
            records.extend(r.get("collaborators") or [])
        elif tool == "compare_teachers":
            records.extend(r.get("profiles") or [])
    return records


def _cards(results):
    seen, out = set(), []
    for record in _records(results):
        tid = record.get("id")
        if tid is None or tid in seen:
            continue
        seen.add(tid)
        out.append({
            "id": tid,
            "name": record.get("name") or "",
            "college": record.get("college") or "",
            "title": record.get("title") or "",
        })
    return out[:6]


def _sources(results, lang):
    online = []
    for r in results:
        if r.get("tool") == "search_online":
            online.extend(r.get("items") or [])
    local = answer._local_sources(_records(results), lang)
    return answer._dedupe_sources(local + answer._online_sources(online, lang))


def _notes(results, lang):
    notes = []
    for r in results:
        if r.get("tool") == "search_online":
            notes.extend(answer._online_notes(
                r.get("items") or [], [tuple(n) for n in r.get("notes") or []], lang))
    return notes


def _slots(results, intent, cards):
    terms, college = [], ""
    for r in results:
        tool = r.get("tool")
        if tool == "search_teachers":
            terms = r.get("terms") or []
            college = r.get("college") or ""
            break
        if tool == "list_college":
            college = r.get("college") or ""
            break
        if tool in ("get_teacher", "get_lab") and r.get("teacher"):
            directions = r["teacher"].get("directions") or ""
            terms = [s.strip() for s in re.split(r"[、,，;；/|]+", directions) if s.strip()][:1]
            break
    return {"intent": intent, "terms": terms, "college": college,
            "cards": cards[:2]}


def _pack(reply, cards, sources, intent, used_online, status, notes, lang):
    return {
        "ok": True,
        "reply": reply,
        "intent": intent,
        "cards": cards,
        "sources": sources,
        "suggestions": answer._suggestions(SUGGEST_INTENT.get(intent, "recommend"), lang),
        "notes": notes,
        "engine": {
            "mode": "api",
            "name": status.get("name") or "",
            "preset": status.get("preset") or "",
            "base_url": status.get("base_url") or "",
        },
        "used_online": bool(used_online),
    }


def _apply_context(question, calls, context):
    """把追问所需的上一轮条件补进工具参数，避免模型漏填。"""
    slots = (context or {}).get("slots") or {}
    last_terms = slots.get("terms") or []
    last_college = slots.get("college") or ""
    last_cards = [c.get("name") for c in (context or {}).get("cards") or [] if c.get("name")]
    follow = any(w in question for w in ("再推荐", "更多", "还有别的", "其他", "换几"))

    for call in calls:
        if not isinstance(call, dict) or call.get("tool") != "search_teachers":
            continue
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        if not args.get("terms") and last_terms:
            args["terms"] = last_terms
        if not args.get("college") and last_college:
            args["college"] = last_college
        if follow and last_cards:
            merged = list(args.get("exclude") or []) + last_cards
            args["exclude"] = list(dict.fromkeys(merged))
        call["args"] = args
    return calls


def run(question, lang, context):
    """返回 (result, slots)；API 未启用或规划失败时返回 None。"""
    status = llm.status()
    if status.get("mode") != "api":
        return None

    plan = _plan(question, lang, context)
    if not plan:
        return None

    intent = str(plan.get("intent") or "chat").strip()
    calls = _apply_context(question, plan.get("tools") or [], context)
    results = []
    for call in calls:
        try:
            executed = _execute(call)
        except Exception:
            executed = None
        if executed:
            results.append(executed)

    if not results:
        reply = str(plan.get("reply") or "").strip()
        if not reply:
            return None
        cards, sources = [], []
        result = _pack(reply, cards, sources, intent, False, status, [], lang)
        return result, {"intent": intent, "terms": [], "college": "", "cards": []}

    reply = _summarize(question, lang, plan, results)
    if not reply:
        return None

    cards = _cards(results)
    sources = _sources(results, lang)
    used_online = any(r.get("tool") == "search_online" for r in results)
    notes = _notes(results, lang)
    result = _pack(reply, cards, sources, intent, used_online, status, notes, lang)
    return result, _slots(results, intent, cards)

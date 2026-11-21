# -*- coding: utf-8 -*-
"""对话接口：本地优先的检索编排与历史记录。"""
import re
import uuid

from flask import jsonify, request

from . import agent, answer, llm, nlu, rag, retrieval, store, tools

COOKIE_NAME = "jiaowodao_cid"
CID_RE = re.compile(r"^[0-9a-f]{32}$")
FALLBACK = {
    "zh": "抱歉，本次检索出现异常，请稍后再试。",
    "en": "Sorry, the search failed. Please try again.",
}


def _client_id():
    """优先使用前端 localStorage 生成的客户端 ID，Cookie 作为兜底。"""
    header = request.headers.get("X-Client-Id") or ""
    if CID_RE.match(header):
        return header, False
    cid = request.cookies.get(COOKIE_NAME) or ""
    if CID_RE.match(cid):
        return cid, False
    return uuid.uuid4().hex, True


def _finish(resp, cid, is_new):
    if is_new:
        resp.set_cookie(
            COOKIE_NAME, cid,
            max_age=63072000, httponly=True, samesite="Lax",
        )
    return resp


def _should_online(intent, slots, data, forced):
    if forced or slots.get("wants_online"):
        return True
    if intent in ("recommend", "experts", "search"):
        return bool(slots.get("terms")) and len(data["candidates"]) < 3
    return intent == "recent"


def _handle_rules(message, lang, forced_online, context):
    slots = nlu.parse(
        message, lang,
        retrieval.vocabulary(),
        retrieval.college_names(),
        retrieval.teacher_names(),
        context,
    )
    intent = slots["intent"]
    data = {
        "intent": intent,
        "slots": slots,
        "lang": lang,
        "total": retrieval.stats()["teachers"],
        "candidates": [],
        "profiles": [],
        "teacher": None,
        "papers": [],
        "online": [],
        "online_notes": [],
    }

    if intent == "career":
        role = slots.get("target_role")
        if role:
            fields = list(nlu.ROLE_MAP[role][1])
            slots["terms"] = fields
            results = rag.search(
                fields, college=slots.get("college"), limit=slots["top_k"]
            )
            data["candidates"] = [retrieval.candidate_payload(r) for r in results]
    elif intent == "compare":
        profiles = []
        for name in slots["names"][:2]:
            teacher = retrieval.by_name(name)
            if teacher:
                profiles.append(retrieval.profile_payload(teacher))
        data["profiles"] = profiles
    elif intent in ("teacher", "recent", "lab"):
        name = slots["names"][0] if slots["names"] else ""
        teacher = retrieval.by_name(name) if name else None
        if teacher:
            data["teacher"] = retrieval.profile_payload(teacher)
            data["papers"] = retrieval.papers_for(teacher["id"], 3)
            data["courses"] = retrieval.courses_for(teacher["id"], 3)
            if intent == "lab":
                data["lab"] = retrieval.lab_context(teacher["id"])
            if not slots["terms"]:
                take = 1 if intent == "lab" else 2
                keywords = [k for k in teacher["keywords"] if k not in nlu.GENERIC][:take]
                if not keywords and teacher["directions"]:
                    keywords = [teacher["directions"].split("、")[0].split("，")[0].strip()]
                slots["terms"] = keywords
    elif intent != "greeting":
        if slots["terms"]:
            results = rag.search(
                slots["terms"], college=slots.get("college"),
                limit=slots["top_k"], depth=(intent == "experts"),
            )
            data["candidates"] = [retrieval.candidate_payload(r) for r in results]
        elif slots.get("college"):
            results = retrieval.search([], college=slots["college"],
                                       limit=slots["top_k"])
            data["candidates"] = [retrieval.candidate_payload(r) for r in results]

    if _should_online(intent, slots, data, forced_online):
        term = (slots.get("terms") or [""])[0]
        teacher = data.get("teacher")
        items, notes = tools.gather(
            nlu.english_term(term) if term else "",
            teacher=teacher if intent == "recent" else None,
            want_recent=(intent == "recent"),
        )
        data["online"] = items
        data["online_notes"] = notes

    result = answer.compose(data)

    engine = {"mode": "rule", "name": ""}

    result.update({
        "ok": True,
        "intent": intent,
        "engine": engine,
        "used_online": bool(data["online"]),
    })
    return result, slots


def _handle(message, lang, forced_online, context):
    """API 模式走“理解意图 + 调用工具 + 总结”；失败时回退本地规则。"""
    if llm.status().get("mode") == "api":
        try:
            packed = agent.run(message, lang, context)
        except Exception:
            packed = None
        if packed:
            return packed
    return _handle_rules(message, lang, forced_online, context)


def register_chat(app):
    @app.route("/api/chat/status")
    def _chat_status():
        return jsonify({
            "ok": True,
            "engine": llm.status(),
            "online_tools": ["official", "arxiv", "crossref", "acemap"],
            "teachers": retrieval.stats()["teachers"],
        })

    @app.route("/api/chat/settings", methods=["GET"])
    def _chat_settings_get():
        return jsonify({
            "ok": True,
            "settings": llm.public_settings(),
            "status": llm.status(),
        })

    @app.route("/api/chat/settings", methods=["POST"])
    def _chat_settings_save():
        payload = request.get_json(silent=True) or {}
        return jsonify({
            "ok": True,
            "settings": llm.save_settings(payload),
            "status": llm.status(),
        })

    @app.route("/api/chat/test", methods=["POST"])
    def _chat_test():
        return jsonify(llm.test_connection())

    @app.route("/api/chat/history")
    def _chat_history():
        cid, is_new = _client_id()
        limit = request.args.get("limit", 40, type=int) or 40
        resp = jsonify({"ok": True, "messages": store.history(cid, limit)})
        return _finish(resp, cid, is_new)

    @app.route("/api/chat", methods=["POST"])
    def _chat_send():
        cid, is_new = _client_id()
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message") or "").strip()
        lang = "en" if payload.get("lang") == "en" else "zh"
        if not message:
            return _finish(jsonify({"ok": False, "error": "empty message"}), cid, is_new), 400
        message = message[:800]

        store.add(cid, "user", message)
        try:
            context = store.last_meta(cid)
            if payload.get("online"):
                context = dict(context or {})
                context["force_online"] = True
            result, slots = _handle(message, lang, bool(payload.get("online")), context)
        except Exception:
            app.logger.exception("chat failed")
            result = {
                "ok": False,
                "error": "internal error",
                "reply": FALLBACK["en" if lang == "en" else "zh"],
                "intent": "error",
                "cards": [],
                "sources": [],
                "suggestions": [],
                "notes": [],
                "engine": {"mode": "rule", "name": ""},
                "used_online": False,
            }
            slots = {"terms": [], "college": None}

        store.add(cid, "assistant", result["reply"], {
            "intent": result.get("intent"),
            "slots": {"terms": slots.get("terms") or [],
                      "college": slots.get("college")},
            "cards": result.get("cards") or [],
            "sources": result.get("sources") or [],
            "suggestions": result.get("suggestions") or [],
            "notes": result.get("notes") or [],
            "engine": result.get("engine") or {},
        })
        return _finish(jsonify(result), cid, is_new)

    @app.route("/api/chat/clear", methods=["POST"])
    def _chat_clear():
        cid, is_new = _client_id()
        store.clear(cid)
        return _finish(jsonify({"ok": True}), cid, is_new)

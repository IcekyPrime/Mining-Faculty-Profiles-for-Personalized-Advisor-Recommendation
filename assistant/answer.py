# -*- coding: utf-8 -*-
"""根据本地检索结果组织回答。

回答只陈述数据库字段与公开来源中确实存在的内容，
并在结尾说明证据边界。
"""


def _truncate(text, size):
    text = (text or "").strip()
    return text if len(text) <= size else text[:size].rstrip() + "…"


def _cards(items, limit=6):
    out = []
    for item in items[:limit]:
        out.append({
            "id": item.get("id"),
            "name": item.get("name") or "",
            "college": item.get("college") or "",
            "title": item.get("title") or "",
        })
    return out


def _entry(index, cand, lang):
    name = cand.get("name") or ""
    college = cand.get("college") or ""
    title = cand.get("title") or ""
    head = "%d. %s" % (index, name)
    separator = " · " if lang == "en" else " ｜ "
    meta = separator.join(x for x in (college, title) if x)
    if meta:
        head += separator + meta

    dirs = _truncate(cand.get("directions") or "", 70)
    lines = [head]
    if dirs:
        lines.append(("   方向：" if lang != "en" else "   Areas: ") + dirs)

    parts = []
    if cand.get("matched_dirs"):
        joined = "、".join(cand["matched_dirs"][:2])
        parts.append((f"研究方向命中「{joined}」") if lang != "en"
                     else f'research area matches "{joined}"')
    if cand.get("matched_keywords"):
        joined = "、".join(cand["matched_keywords"][:3])
        parts.append((f"关键词命中「{joined}」") if lang != "en"
                     else f'keywords match "{joined}"')
    if cand.get("honor_match"):
        parts.append("荣誉记录命中" if lang != "en" else "honor record matches")
    if cand.get("graph_reason"):
        parts.append(cand["graph_reason"])
    if cand.get("papers"):
        paper = cand["papers"][0]
        year = "（{}）".format(paper["year"]) if paper.get("year") else ""
        if lang == "en":
            parts.append("related paper: {}{}".format(_truncate(paper["title"], 56), year))
        else:
            parts.append("相关论文：{}{}".format(_truncate(paper["title"], 56), year))
    if parts:
        lines.append(("   依据：" if lang != "en" else "   Evidence: ") + "；".join(parts))
    return "\n".join(lines)


def _local_sources(cands, lang):
    out = []
    for c in cands[:3]:
        if not c.get("id"):
            continue
        out.append({
            "type": "local",
            "label": ("{} · 教师档案".format(c["name"])) if lang != "en" else ("{} · profile".format(c["name"])),
            "url": "/api/teacher/%d" % c["id"],
        })
    for c in cands[:2]:
        url = c.get("personal_homepage") or c.get("homepage_url")
        if url:
            out.append({
                "type": "official",
                "label": ("{} · 主页".format(c["name"])) if lang != "en" else ("{} · homepage".format(c["name"])),
                "url": url,
            })
    return out


def _online_sources(items, lang):
    out = []
    for item in items or []:
        url = item.get("url")
        if not url:
            continue
        kind = item.get("type")
        if kind == "arxiv":
            label = "arXiv · " + _truncate(item.get("title") or "", 44)
        elif kind == "crossref":
            label = "Crossref · " + _truncate(item.get("title") or "", 44)
        elif kind == "acemap":
            label = "Acemap 检索入口" if lang != "en" else "Acemap search"
        elif kind == "official":
            label = "官方主页" if lang != "en" else "Official page"
        else:
            label = _truncate(item.get("title") or url, 44)
        out.append({"type": kind, "label": label, "url": url})
    return out


def _dedupe_sources(sources):
    seen, out = set(), []
    for s in sources:
        url = s.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(s)
    return out[:8]


def _online_notes(items, failed, lang):
    notes = []
    zh = lang != "en"
    failed_names = {value for kind, value in failed if kind == "source_failed"}
    if "arxiv" in failed_names:
        notes.append("arXiv 本次不可用，仅使用本地与其他来源。" if zh
                     else "arXiv was unavailable; local and other sources were used.")
    if "crossref" in failed_names:
        notes.append("Crossref 本次不可用，仅使用本地与其他来源。" if zh
                     else "Crossref was unavailable; local and other sources were used.")
    for kind, value in failed:
        if kind == "official_failed":
            notes.append((f"未能读取{value}的官方主页。") if zh
                         else f"Could not read the official page of {value}.")
        elif kind == "official_empty":
            notes.append((f"{value}的官方主页没有可提取的文本。") if zh
                         else f"No readable text on the official page of {value}.")
    if any(i.get("link_only") for i in items or []):
        notes.append("Acemap 未提供公开查询 API，列表中只给出人工核验入口。" if zh
                     else "Acemap has no public query API here; only a manual search link is provided.")
    return notes


def _suggestions(intent, lang):
    data = {
        "zh": {
            "recommend": ["只看计算机学院", "再推荐几位", "这位导师最近有什么成果"],
            "experts": ["只看计算机学院", "再推荐几位", "这些方向有哪些代表论文"],
            "teacher": ["这位老师最近在做什么", "再推荐几位同方向的导师"],
            "recent": ["这位老师的主页", "还推荐几位同方向的导师"],
            "career": ["算法研发", "芯片设计", "软件开发", "电力系统"],
            "clarify": ["数据挖掘", "计算机视觉", "芯片设计", "计算机学院有哪些导师"],
            "greeting": ["我喜欢数据挖掘，推荐几位导师", "哪些导师深耕图像处理", "计算机学院有哪些导师"],
        },
        "en": {
            "recommend": ["Only the School of Computer Science", "Show more",
                          "What has this professor published recently"],
            "experts": ["Only the School of Computer Science", "Show more", "Representative papers in this area"],
            "teacher": ["What is this professor working on now", "More advisors in the same area"],
            "recent": ["This professor's homepage", "More advisors in the same area"],
            "career": ["Algorithm R&D", "Chip design", "Software development", "Power systems"],
            "clarify": ["Data mining", "Computer vision", "Chip design", "Faculty in Computer Science"],
            "greeting": ["I like data mining, recommend advisors",
                         "Who works deeply on image processing",
                         "Faculty in the School of Computer Science"],
        },
    }
    lang_key = "en" if lang == "en" else "zh"
    return data[lang_key].get(intent) or data[lang_key]["recommend"]


def _greeting(lang):
    if lang == "en":
        text = ("Hello, I am the advisor search assistant. Describe your need in one sentence; "
                "I search the local faculty database first and only query public academic "
                "sources when needed.")
    else:
        text = ("你好，我是交我导的导师检索助手。你可以直接用一句话描述需求，"
                "我会先在本地教师库中检索，必要时再补充公开学术来源。")
    return {
        "reply": text,
        "cards": [],
        "sources": [],
        "suggestions": _suggestions("greeting", lang),
        "notes": [],
    }


def _clarify(lang, message=None):
    if lang == "en":
        text = message or ("I could not identify a specific research area. Try a field such as "
                           "data mining, computer vision or chip design, or add a school name.")
    else:
        text = message or ("我还没有识别出具体的研究方向。你可以直接说一个领域，例如"
                           "“数据挖掘”“计算机视觉”“芯片设计”，也可以加上学院限制。")
    return {
        "reply": text,
        "cards": [],
        "sources": [],
        "suggestions": _suggestions("clarify", lang),
        "notes": [],
    }


def _career(slots, cands, lang):
    role = slots.get("target_role")
    zh = lang != "en"
    role_text = {
        "算法研发": "algorithm R&D",
        "软件开发": "software development",
        "芯片设计": "chip design",
        "电力系统": "power systems",
        "机器人": "robotics",
    }.get(role, role) if not zh else role
    if not role:
        if zh:
            text = ("本地库没有毕业生薪资、去向或收入数据，所以无法判断哪位导师"
                    "“毕业薪资更高”。论文数、引用量也不能当作薪资证据。\n\n"
                    "如果你愿意，我可以按目标岗位方向筛选导师：算法研发、软件开发、"
                    "芯片设计、电力系统、机器人。告诉我方向后，我再给出候选；"
                    "这不构成任何薪资承诺。")
        else:
            text = ("The local database has no graduate salary, destination or income data, "
                    "so it cannot rank advisors by expected salary. Paper counts and citations "
                    "are not salary evidence.\n\n"
                    "I can instead filter advisors by your target role: algorithm R&D, software "
                    "development, chip design, power systems or robotics. Tell me a direction and "
                    "I will show candidates; this is not a salary promise.")
        return {
            "reply": text,
            "cards": [],
            "sources": [],
            "suggestions": _suggestions("career", lang),
            "notes": ["本地数据不含薪资或毕业去向字段。" if zh
                      else "The local database has no salary or destination fields."],
        }

    if not cands:
        return _clarify(lang)

    if zh:
        head = ("按你选择的方向“%s”，我筛出 %d 位研究领域相关的导师。"
                "再次说明：本地数据不含薪资，以下只是方向匹配。") % (role_text, len(cands))
    else:
        head = ("For your target role \"%s\", I found %d advisors whose research areas are "
                "related. Again, the local data has no salary information; this is only a "
                "research-area match.") % (role_text, len(cands))
    body = "\n\n".join(_entry(i + 1, c, lang) for i, c in enumerate(cands))
    return {
        "reply": head + "\n\n" + body,
        "cards": _cards(cands),
        "sources": _dedupe_sources(_local_sources(cands, lang)),
        "suggestions": _suggestions("recommend", lang),
        "notes": ["岗位方向与导师研究领域是软映射，不代表就业结果。" if zh
                  else "Role-to-field mapping is indicative, not an employment outcome."],
    }


def _compare(profiles, lang):
    if len(profiles) < 2:
        return _clarify(lang, "我需要两位教师的姓名才能比较。"
                              if lang != "en" else "I need two faculty names to compare.")

    zh = lang != "en"
    blocks = []
    for p in profiles[:2]:
        lines = ["{} ｜ {} ｜ {}".format(p["name"], p.get("college") or "", p.get("title") or "")]
        if p.get("directions"):
            lines.append(("  方向：" if zh else "  Areas: ") + _truncate(p["directions"], 90))
        metrics = []
        if p.get("h_index") is not None:
            metrics.append(("h 指数 {}".format(p["h_index"])) if zh else ("h-index {}".format(p["h_index"])))
        if p.get("citation_count") is not None:
            metrics.append(("总引用 {}".format(p["citation_count"])) if zh else ("{} citations".format(p["citation_count"])))
        if p.get("paper_count") is not None:
            metrics.append(("收录论文 {} 篇".format(p["paper_count"])) if zh else ("{} papers".format(p["paper_count"])))
        if metrics:
            lines.append(("  指标：" if zh else "  Metrics: ") + "，".join(metrics))
        blocks.append("\n".join(lines))

    def _terms(text):
        parts = []
        for seg in (text or "").replace("；", "、").replace(";", "、").split("、"):
            seg = seg.strip()
            if len(seg) >= 2:
                parts.append(seg)
        return set(parts)

    shared = sorted(_terms(profiles[0].get("directions")) & _terms(profiles[1].get("directions")))
    tail = ""
    if shared:
        tail = ("\n\n共同出现的方向词：{}。".format("、".join(shared[:6]))) if zh else \
               ("\n\nShared area terms: {}.".format(", ".join(shared[:6])))
    note = ("\n\n以上只比较公开档案字段，不代表指导质量、招生意愿或团队氛围。"
            if zh else "\n\nThis compares public profile fields only, not advising quality, "
                       "admission willingness or team culture.")
    return {
        "reply": "\n\n".join(blocks) + tail + note,
        "cards": _cards(profiles, 2),
        "sources": _dedupe_sources(_local_sources(profiles, lang)),
        "suggestions": _suggestions("teacher", lang),
        "notes": [],
    }


def _teacher(profile, papers, online, lang, courses=None):
    zh = lang != "en"
    separator = " · " if lang == "en" else " ｜ "
    lines = [separator.join(x for x in (profile["name"], profile.get("college") or "",
                                        profile.get("title") or "") if x)]
    if profile.get("directions"):
        lines.append(("研究方向：" if zh else "Research areas: ") + profile["directions"])
    if profile.get("institute"):
        lines.append(("所在单位：" if zh else "Institute: ") + profile["institute"])

    metrics = []
    if profile.get("h_index") is not None:
        metrics.append(("h 指数 {}".format(profile["h_index"])) if zh else ("h-index {}".format(profile["h_index"])))
    if profile.get("citation_count") is not None:
        metrics.append(("总引用 {}".format(profile["citation_count"])) if zh else ("{} citations".format(profile["citation_count"])))
    if profile.get("paper_count") is not None:
        metrics.append(("收录论文 {} 篇".format(profile["paper_count"])) if zh else ("{} papers".format(profile["paper_count"])))
    if metrics:
        lines.append(("学术指标：" if zh else "Metrics: ") + "，".join(metrics))

    if profile.get("email"):
        lines.append(("邮箱：" if zh else "Email: ") + profile["email"])
    homepage = profile.get("personal_homepage") or profile.get("homepage_url")
    if homepage:
        lines.append(("主页：" if zh else "Homepage: ") + homepage)

    if courses:
        lines.append("讲授课程：" if zh else "Courses: ")
        for course in courses[:3]:
            suffix = ""
            if course.get("rating") and course.get("count"):
                suffix = ("（%.1f 分 / %d 条评价）" % (course["rating"], course["count"])
                          if zh else
                          " (%.1f / %d reviews)" % (course["rating"], course["count"]))
            lines.append("· " + course["name"] + suffix)

    if papers:
        lines.append("代表论文：" if zh else "Recent papers: ")
        for p in papers[:2]:
            year = "（{}）".format(p["year"]) if p.get("year") else ""
            lines.append("· {}{}".format(_truncate(p["title"], 70), year))

    excerpt = next((i for i in online or [] if i.get("type") == "official"), None)
    if excerpt and excerpt.get("excerpt"):
        lines.append(("官方主页可见内容：" if zh else "Official page excerpt: ")
                     + _truncate(excerpt["excerpt"], 220))

    return {
        "reply": "\n".join(lines),
        "cards": _cards([profile], 1),
        "sources": _dedupe_sources(_local_sources([profile], lang) + _online_sources(online, lang)),
        "suggestions": _suggestions("teacher", lang),
        "notes": [],
    }


def _lab(profile, lab, lang):
    """实验室问题的回答：明确说明数据边界，再给出研究所与合作记录。"""
    zh = lang != "en"
    institute = lab.get("institute") or ""
    lab_name = lab.get("lab_name") or ""
    mates = lab.get("mates") or []
    collabs = lab.get("collaborators") or []

    separator = " · " if lang == "en" else " ｜ "
    lines = [separator.join(x for x in (profile["name"], profile.get("college") or "",
                                        profile.get("title") or "") if x)]
    if lab_name:
        lines.append(("简介中提到的实验室：" if zh else "Lab mentioned in the bio: ") + lab_name)
    if institute:
        lines.append(("所在单位：" if zh else "Institute: ") + institute)
    else:
        lines.append("本地库没有该教师的研究所信息。" if zh
                      else "No institute is recorded for this faculty member.")

    if mates:
        names = "、".join(m["name"] for m in mates[:10])
        lines.append(("同研究所教师（%d 位）：" % len(mates) if zh
                      else "Faculty in the same institute (%d): " % len(mates)) + names)

    if collabs:
        parts = []
        for c in collabs[:6]:
            name = c["teacher"]["name"]
            college = c["teacher"].get("college") or ""
            if zh:
                label = name + ("（{}，权重 {}）".format(college, c["weight"]) if college
                                else "（权重 {}）".format(c["weight"]))
            else:
                label = name + (" ({}, weight {})".format(college, c["weight"]) if college
                                else " (weight {})".format(c["weight"]))
            parts.append(label)
        lines.append(("有合作记录的教师：" if zh else "Recorded collaborators: ") + "、".join(parts))

    if not institute and not collabs:
        lines.append("本地库没有可用于推断同实验室教师的研究所或合作记录。" if zh
                      else "The local database has no institute or collaboration records to infer lab members.")
    else:
        lines.append("说明：本地教师库没有“实验室成员”字段，以上按研究所与合作记录推断，"
                      "不等于实验室完整名单；具体成员请以官方主页为准。" if zh else
                      "Note: the local database has no lab-membership field. The lists above are "
                      "inferred from institute and collaboration records, not a complete roster; "
                      "verify on the official page.")

    card_items, seen = [], set()
    for t in list(mates) + [c["teacher"] for c in collabs]:
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        card_items.append(t)

    return {
        "reply": "\n".join(lines),
        "cards": _cards(card_items, 6),
        "sources": _dedupe_sources(_local_sources(card_items, lang)),
        "suggestions": _suggestions("teacher", lang),
        "notes": [],
    }


def _recent(profile, papers, online, lang):
    zh = lang != "en"
    if papers:
        latest = papers[0]
        year = latest.get("year")
        if zh:
            head = "在本地已收录资料中，{}最近的论文是《{}》{}。".format(
                profile["name"], _truncate(latest["title"], 70),
                f"（{year}）" if year else "")
        else:
            head = ("In the local records, the most recent paper by {} is \"{}\"{}.".format(profile["name"], _truncate(latest["title"], 70),
                       f" ({year})" if year else ""))
    else:
        head = ("本地资料中没有{}的论文年份记录。".format(profile["name"])) if zh else \
               ("The local records contain no dated papers for {}.".format(profile["name"]))

    extra = []
    if not papers:
        if profile.get("directions"):
            extra.append(("研究方向：" if zh else "Research areas: ") + profile["directions"])
        if profile.get("bio"):
            extra.append(("简介：" if zh else "Bio: ") + _truncate(profile["bio"], 180))
    official = next((i for i in online or [] if i.get("type") == "official"), None)
    if official and official.get("excerpt"):
        extra.append(("官方主页当前可见内容：" if zh else "Official page excerpt: ")
                     + _truncate(official["excerpt"], 220))
    if papers and len(papers) > 1:
        others = "；".join(_truncate(p["title"], 40) for p in papers[1:3])
        extra.append(("其他已收录论文：" if zh else "Other recorded papers: ") + others)

    tail = ("\n\n本地论文收录可能不完整，建议结合官方主页核验。"
            if zh else "\n\nThe local paper records may be incomplete; verify on the official page.")
    return {
        "reply": head + ("\n\n" + "\n".join(extra) if extra else "") + tail,
        "cards": _cards([profile], 1),
        "sources": _dedupe_sources(_local_sources([profile], lang) + _online_sources(online, lang)),
        "suggestions": _suggestions("recent", lang),
        "notes": [],
    }


def compose(ctx):
    lang = "en" if ctx.get("lang") == "en" else "zh"
    intent = ctx.get("intent")
    slots = ctx.get("slots") or {}
    cands = ctx.get("candidates") or []
    profiles = ctx.get("profiles") or []
    online = ctx.get("online") or []
    failed = ctx.get("online_notes") or []
    total = ctx.get("total") or 0

    notes = list(ctx.get("notes") or [])
    notes.extend(_online_notes(online, failed, lang))

    if intent == "greeting":
        result = _greeting(lang)
    elif intent == "career":
        result = _career(slots, cands, lang)
    elif intent == "compare":
        result = _compare(profiles, lang)
    elif intent == "lab":
        profile = ctx.get("teacher")
        if not profile:
            result = _clarify(lang, "没有在本地库中找到这位教师。"
                                    if lang != "en" else "I could not find that faculty member locally.")
        else:
            result = _lab(profile, ctx.get("lab") or {}, lang)
    elif intent in ("teacher", "recent"):
        profile = ctx.get("teacher")
        if not profile:
            result = _clarify(lang, "没有在本地库中找到这位教师。"
                                    if lang != "en" else "I could not find that faculty member locally.")
        elif intent == "recent":
            result = _recent(profile, ctx.get("papers") or [], online, lang)
        else:
            result = _teacher(profile, ctx.get("papers") or [], online, lang,
                              ctx.get("courses") or [])
            raw = slots.get("raw") or ""
            if "评价" in raw:
                result["reply"] += (
                    "\n\n这里只提供公开档案中的研究方向、指标和课程信息，不做主观评价。"
                    if lang != "en" else
                    "\n\nThis only reports public profile fields; it does not offer a subjective evaluation.")
            if "课程" in raw and not (ctx.get("courses") or []):
                result["reply"] += ("\n\n本地库没有收录该教师的课程记录。"
                                    if lang != "en" else "\n\nNo course records are available locally.")
            if "邮箱" in raw and not profile.get("email"):
                result["reply"] += ("\n\n本地库没有收录该教师的邮箱。"
                                    if lang != "en" else "\n\nNo email is recorded locally.")
            if "主页" in raw and not (profile.get("personal_homepage")
                                      or profile.get("homepage_url")):
                result["reply"] += ("\n\n本地库没有收录该教师的主页。"
                                    if lang != "en" else "\n\nNo homepage is recorded locally.")
            if any(word in raw for word in ("招生", "名额", "招几个", "博士名额")):
                result["reply"] += (
                    "\n\n本地库没有招生名额信息，请以教师主页或学院通知为准。"
                    if lang != "en" else
                    "\n\nThe local database has no admission-quota information; "
                    "check the official page or school notice.")
    elif not cands:
        if slots.get("college"):
            result = _clarify(lang, ("{} 本地库中没有可展示的教师记录。".format(slots["college"])) if lang != "en"
                              else "No faculty records to show for {}.".format(slots["college"]))
        else:
            result = _clarify(lang)
    else:
        zh = lang != "en"
        terms = "、".join(slots.get("terms") or []) or ("该方向" if zh else "that area")
        scope = ""
        if slots.get("college"):
            scope = ("（限定 {}）".format(slots["college"])) if zh else (" in {}".format(slots["college"]))

        if not (slots.get("terms") or []):
            if zh:
                head = "在“%s”中，我按现有综合评分列出 %d 位教师。" % (
                    slots.get("college") or "本地教师库", len(cands))
            else:
                head = "Here are %d faculty members%s, ordered by the existing overall score." % (
                    len(cands), (" in {}".format(slots["college"])) if slots.get("college") else "")
        elif intent == "experts":
            if zh:
                head = ("在已收录资料中，有 %d 位教师持续涉及“%s”%s。"
                        "这里的“持续”按研究方向、关键词和已收录论文综合判断，"
                        "不代表完整统计。") % (len(cands), terms, scope)
            else:
                head = ("The local records show %d faculty members with sustained work related "
                        "to \"%s\"%s. This combines research areas, keywords and recorded papers; "
                        "it is not a complete census.") % (len(cands), terms, scope)
        else:
            if zh:
                head = ("根据你提到的“%s”，我在本地教师库中筛出 %d 位方向较接近的导师%s。"
                        "匹配依据只来自公开档案与已收录论文。") % (terms, len(cands), scope)
            else:
                head = ("For \"%s\", I found %d advisors with related research areas%s. "
                        "The match uses public profiles and recorded papers only.") % (
                            terms, len(cands), scope)

        body = "\n\n".join(_entry(i + 1, c, lang) for i, c in enumerate(cands))
        tail = ("\n\n以上是信息匹配结果，不代表导师的招生意愿、指导风格或录取难度。"
                if zh else "\n\nThese are information matches, not admission willingness, "
                           "advising style or acceptance odds.")
        external = [i for i in online if i.get("type") in ("arxiv", "crossref")]
        if external:
            tail += ("\n\n另补充了 %d 条公开学术来源，可在下方来源中核验。" % len(external)
                     if zh else "\n\n%d public academic sources were added; check the links below."
                     % len(external))
        result = {
            "reply": head + "\n\n" + body + tail,
            "cards": _cards(cands),
            "sources": _dedupe_sources(_local_sources(cands, lang) + _online_sources(online, lang)),
            "suggestions": _suggestions(intent if intent in ("experts",) else "recommend", lang),
            "notes": [],
        }

    if total:
        notes.insert(0, ("本地教师库共 %d 人。" % total) if lang != "en"
                     else "%d faculty records in the local database." % total)
    result["notes"] = notes[:5]
    return result

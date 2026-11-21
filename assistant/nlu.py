# -*- coding: utf-8 -*-
"""自然语言需求解析（本地规则引擎）。

不依赖在线模型：把一句中文或英文需求解析成
意图、研究兴趣、学院、教师姓名与结果数量，
供本地检索和回答层使用。
"""
import re

# 研究方向的同义表达。键为统一名称，值为可识别的写法。
# 检索时会用同一组词做权重较低的扩展匹配，避免只认字面完全一致。
ALIASES = {
    "数据挖掘": ["数据挖掘", "数据仓库", "知识发现", "data mining", "kdd"],
    "机器学习": ["机器学习", "machine learning", "统计学习"],
    "深度学习": ["深度学习", "deep learning", "神经网络", "neural network"],
    "人工智能": ["人工智能", "artificial intelligence"],
    "计算机视觉": ["计算机视觉", "图像处理", "图像识别", "图像分割", "视觉感知",
                   "computer vision", "image processing"],
    "自然语言处理": ["自然语言处理", "自然语言", "nlp", "语言模型", "大语言模型", "大模型"],
    "语音识别": ["语音识别", "语音", "speech", "asr", "speech recognition"],
    "推荐系统": ["推荐系统", "推荐算法", "个性化推荐", "recommender system"],
    "强化学习": ["强化学习", "reinforcement learning"],
    "知识图谱": ["知识图谱", "knowledge graph"],
    "图神经网络": ["图神经网络", "graph neural network", "gnn"],
    "芯片设计": ["芯片设计", "集成电路设计", "微电子", "芯片", "ic design", "vlsi"],
    "电力系统": ["电力系统", "智能电网", "电网", "power system", "smart grid"],
    "机器人": ["机器人", "具身智能", "robotics"],
    "操作系统": ["操作系统", "operating system", "系统软件"],
    "网络与信息安全": ["网络安全", "信息安全", "隐私保护", "ai安全", "人工智能安全",
                       "security", "privacy"],
    "软件工程": ["软件工程", "software engineering", "程序分析", "代码分析"],
    "控制理论": ["控制理论", "自动控制", "control theory"],
    "通信与信号处理": ["通信", "无线通信", "信号处理", "communication", "signal processing"],
    "数据库": ["数据库", "database", "数据管理"],
    "多模态": ["多模态", "multimodal", "跨模态"],
}

# 学院简称。只收录不容易和其他词冲突的写法。
COLLEGE_SHORT = {
    "计算机学院": ["计算机学院", "计算机系", "计算机科学与技术学院"],
    "自动化与感知学院": ["自动化与感知学院", "自动化系", "自动化学院"],
    "集成电路学院": ["集成电路学院", "微电子学院", "微电子系"],
    "电气工程学院": ["电气工程学院", "电气学院", "电气系"],
    "人工智能学院": ["人工智能学院", "人工智能研究院"],
}

GENERIC = {
    "老师", "导师", "教师", "教授", "学生", "学院", "学校", "方向", "领域",
    "研究", "工作", "系统", "技术", "方法", "应用", "问题", "相关", "方面",
    "专业", "学科", "成果", "论文", "情况", "信息",
    "实验室", "课题组", "团队", "研究所", "组里", "同组", "同事",
    "推荐", "邮箱", "课程", "授课", "处理", "几位", "评价",
    "the", "and", "for", "with", "advisor", "professor", "research", "student",
}

# 兜底切词时需要先去掉的口语成分。
STOP_PHRASES = [
    "我是一个", "我是一名", "我是", "一个", "一名", "喜欢", "希望", "想要",
    "想让你", "想找", "想学", "请你", "帮我", "帮忙", "推荐一下", "推荐",
    "一下", "导师", "老师", "教授", "学生", "毕业", "薪资", "很高", "比较",
    "介绍一下", "介绍", "哪些", "哪位", "什么", "怎么样", "如何", "可以",
    "能不能", "是否", "有没有", "深耕于", "深耕", "从事", "主要研究",
    "专注于", "擅长", "做", "搞", "学习", "了解", "领域", "方向", "方面",
    "相关", "的", "在", "我", "你", "他", "她", "们",
    "邮箱是", "带哪些课程", "哪些课程", "上什么课", "教什么",
    "干什么", "做什么", "干嘛", "研究什么", "做什么的", "搞什么",
    "评价一下", "评价",
]

SALARY_CUES = [
    "薪资", "工资", "薪水", "年薪", "收入", "待遇", "毕业去向", "就业",
    "找工作", "高薪", "salary", "income", "pay", "job", "career",
    "employment", "compensation",
]
COMPARE_CUES = [
    "比较", "对比", "区别", "差异", "不同", "相比", "vs", "compare",
    "comparison", "difference", "versus", "哪个更", "谁更", "更适合",
    "哪个好", "选谁",
]
RECENT_CUES = [
    "最近", "近年", "近期", "最新", "这几年", "目前", "现在",
    "recent", "latest", "now", "current",
]
LOOKUP_CUES = [
    "介绍", "是谁", "怎么样", "主页", "邮箱", "联系方式", "详情", "档案",
    "研究方向", "方向是什么", "h指数", "h 指数", "h-index", "h index",
    "职称", "头衔", "哪个学院", "哪个系", "什么学院", "学院",
    "课程", "带哪些课", "上什么课", "教什么",
    "招生", "名额", "招几个", "招收", "博士",
    "干什么", "做什么", "干嘛", "研究什么", "做什么的", "搞什么",
    "评价",
    "info", "profile", "email", "homepage", "who is",
]
DEPTH_CUES = [
    "深耕", "擅长", "专长", "主要研究", "长期", "专注", "专家", "权威",
    "领先", "leading", "expert", "specializ", "focus on", "works on", "strong",
]
RECOMMEND_CUES = [
    "推荐", "适合", "想找", "希望", "喜欢", "想学", "方向", "导师", "老师",
    "advisor", "recommend", "suggest", "looking for", "interested",
]
LAB_CUES = [
    "实验室", "课题组", "团队", "组里", "同组", "同事", "研究所", "实验组",
    "同一个实验室", "lab", "group", "team", "colleague",
]
COURSE_CUES = ["课程", "带哪些课", "上什么课", "教什么", "授课", "课程评价"]
GREETINGS = ["你好", "您好", "hi", "hello", "hey", "在吗"]
MORE_CUES = ["更多", "再推荐", "还有", "其他", "再给", "more", "another", "others"]
# 已限定学院时，这些词不再作为研究方向，否则会把全院教师都当成命中。
TOO_BROAD = {"计算机", "人工智能", "电子信息", "自动化", "电气", "软件", "通信", "电子"}
PRONOUN_CUES = ["这位", "那位", "该老师", "该导师", "他们", "她们", "这些导师",
                "this professor", "that professor", "this advisor"]

# 就业方向到研究领域的软映射。仅用于按岗位方向筛选，
# 不能反过来当作薪资证据。
ROLE_MAP = {
    "算法研发": (["算法", "建模", "机器学习", "人工智能", "algorithm"], ["机器学习", "数据挖掘",
                                                "人工智能", "计算机视觉", "自然语言处理", "推荐系统"]),
    "软件开发": (["开发", "软件", "后端", "前端", "工程", "software", "developer"],
                 ["软件工程", "操作系统", "数据库"]),
    "芯片设计": (["芯片", "集成电路", "微电子", "硬件", "chip", "hardware"],
                 ["芯片设计", "集成电路", "微电子"]),
    "电力系统": (["电力", "电网", "电气", "power"], ["电力系统"]),
    "机器人": (["机器人", "具身", "控制", "robot", "robotics"], ["机器人", "控制理论"]),
}

CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _normalize(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _contains(hay, needle):
    """中文直接包含匹配；英文按词边界匹配，避免 ai 命中 said。"""
    if not hay or not needle:
        return False
    hay = hay.lower()
    needle = needle.lower()
    if needle.isascii():
        pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
        return re.search(pattern, hay) is not None
    return needle in hay


def _has_any(text, words):
    return any(_contains(text, w) for w in words)


def _find_names(text, names):
    found = []
    for name in sorted(names or [], key=len, reverse=True):
        if len(name) < 2:
            continue
        if name in text and not any(name in f for f in found):
            found.append(name)
    return found[:3]


def _find_college(text, colleges):
    for c in colleges or []:
        if c and c in text:
            return c
    for full, shorts in COLLEGE_SHORT.items():
        if full not in (colleges or []):
            continue
        for s in shorts:
            if s in text:
                return full
    return None


def _valid_term(term):
    if not term:
        return False
    t = term.strip()
    if len(t) < 2 or len(t) > 14:
        return False
    return t.lower() not in GENERIC


def _fallback_terms(body):
    s = body
    for p in sorted(STOP_PHRASES, key=len, reverse=True):
        s = s.replace(p, " ")
    s = re.sub(r"[，。！？、,.!?；;：:\"'“”‘’（）()\[\]【】]", " ", s)
    out = []
    for chunk in s.split():
        chunk = chunk.strip()
        if _valid_term(chunk) and chunk not in out:
            out.append(chunk)
    return out[:2]


def _find_terms(raw, vocab, names):
    out = []
    for canonical, surfaces in ALIASES.items():
        if any(_contains(raw, s) for s in surfaces):
            out.append(canonical)

    body = raw
    for n in names:
        body = body.replace(n, " ")

    # 数据库里出现过的真实方向词优先，长词在前。
    for term in vocab or []:
        if len(out) >= 4:
            break
        if not _valid_term(term):
            continue
        if any(term in o or o in term for o in out):
            continue
        if term in body:
            out.append(term)

    if len(out) < 2:
        for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z+#]{2,14}?)(?:领域|方向|方面)", body):
            cand = m.group(1).strip()
            if _valid_term(cand) and not any(cand in o or o in cand for o in out):
                out.append(cand)

    if not out:
        out = [t for t in _fallback_terms(body) if _valid_term(t)]

    return out[:4]


def _find_role(text):
    for role, (cues, _fields) in ROLE_MAP.items():
        if _has_any(text, cues):
            return role
    return None


def _top_k(text):
    m = re.search(r"(?:前|top\s*|头)\s*(\d+)", text.lower())
    if m:
        return max(3, min(8, int(m.group(1))))
    m = re.search(r"([一二两三四五六七八九十])\s*(?:位|个|名)", text)
    if m:
        return max(3, min(8, CN_NUM.get(m.group(1), 5)))
    return 5


def _pick_intent(raw, terms, names, college, context):
    low = raw.lower()
    ctx_cards = (context or {}).get("cards") or []

    if len(raw) <= 14 and _has_any(low, GREETINGS):
        return "greeting"
    if _has_any(low, SALARY_CUES):
        return "career"
    # 薪资澄清后，用户直接回复岗位方向
    if (context or {}).get("intent") == "career" and _find_role(raw):
        return "career"
    # 先识别“某老师实验室/课题组里还有谁”，避免把“实验室”当成研究方向
    if names and _has_any(low, LAB_CUES) and not _has_any(low, COMPARE_CUES):
        return "lab"
    if _has_any(low, COMPARE_CUES) and (len(names) >= 2 or (names and len(ctx_cards) >= 2)):
        return "compare"
    if names and _has_any(low, RECENT_CUES):
        return "recent"
    if names and _has_any(low, COURSE_CUES):
        return "teacher"
    if names and _has_any(low, LOOKUP_CUES + DEPTH_CUES):
        return "teacher"
    if _has_any(low, DEPTH_CUES):
        return "experts"
    if terms or college or _has_any(low, RECOMMEND_CUES):
        return "recommend"
    return "search"


def english_term(term):
    """给 arXiv/Crossref 用的英文检索词；没有对应写法时原样返回。"""
    for surface in ALIASES.get(term, []):
        if surface.isascii() and len(surface) > 2:
            return surface
    return term


def parse(text, lang="zh", vocab=None, colleges=None, names=None, context=None):
    """解析一句自然语言需求，返回结构化条件。

    context 为上一条助手消息的 meta，用于“再推荐几位”“比较前两位”
    这类省略式追问。
    """
    raw = _normalize(text)
    terms = _find_terms(raw, vocab, names or [])
    found_names = _find_names(raw, names or [])
    college = _find_college(raw, colleges or [])
    if college and terms:
        terms = [t for t in terms if t not in TOO_BROAD]
    if not found_names and context and _has_any(raw.lower(), PRONOUN_CUES):
        cards = context.get("cards") or []
        found_names = [c.get("name") for c in cards[:2] if c.get("name")]
    intent = _pick_intent(raw, terms, found_names, college, context)
    if intent in ("teacher", "recent", "lab"):
        # 个人查询词不作为研究方向；后续追问由回答层从该教师关键词补全
        terms = []

    ctx_slots = (context or {}).get("slots") or {}
    wants_more = (
        _has_any(raw.lower(), MORE_CUES)
        and not re.search(r"还有(?:哪些|什么|谁|哪|多少)", raw)
    )
    if wants_more and ctx_slots.get("terms"):
        terms = list(ctx_slots.get("terms") or [])
    elif not terms and ctx_slots.get("terms") and (college or intent in ("recommend", "experts")):
        terms = list(ctx_slots.get("terms") or [])
    if not college and ctx_slots.get("college") and intent in ("recommend", "experts") and wants_more:
        college = ctx_slots.get("college")
    if intent == "compare" and len(found_names) < 2:
        cards = (context or {}).get("cards") or []
        found_names = [c.get("name") for c in cards[:2] if c.get("name")]

    return {
        "raw": raw,
        "lang": "en" if lang == "en" else "zh",
        "intent": intent,
        "terms": terms,
        "names": found_names,
        "college": college,
        "target_role": _find_role(raw),
        "wants_more": wants_more,
        "wants_online": _has_any(raw.lower(), ["联网", "在线", "网上", "最新文献", "arxiv"]),
        "top_k": min(8, _top_k(raw) + (3 if wants_more else 0)),
    }

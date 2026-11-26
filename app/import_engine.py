# -*- coding: utf-8 -*-
"""数据工坊 · 导入引擎。

数据挖掘视角的职责划分：
1. 数据接入：CSV / JSON / XLSX，统一转为「原始行 + 表头」；
2. 数据理解：按字段证据识别实体类型（教师 / 论文 / 课程）；
3. 数据清洗：空值与占位符、全半角、空白、列表分隔、邮箱、URL、数值、年份；
4. 数据质量：必填、类型、范围、缺失率、行级 issue 与质量分；
5. 去重：文件内重复 + 与现有库的实体键比对；
6. 受控入库：预览确认后事务写入，支持 skip / update_empty / update_all。

这个模块只做确定性规则；AI 辅助在 ``import_ai.py`` 中，处理结果仍回到这里重新校验。
"""
import contextlib
import csv
import io
import json
import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime
from urllib.parse import quote

try:
    from pypinyin import lazy_pinyin
except ImportError:  # pragma: no cover - 依赖缺失时仍可导入
    lazy_pinyin = None

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ROWS = 20000


def format_file_size(limit):
    """把字节上限格式化成界面可读的 KB/MB，避免 1024 字节显示成 0 MB。"""
    limit = int(limit)
    if limit >= 1024 * 1024:
        return f"{limit / (1024 * 1024):g} MB"
    return f"{max(1, round(limit / 1024))} KB"
MAX_STRING = 6000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL_RE = re.compile(r"^(http://|https://)[^\s]+$", re.I)
NULL_TEXTS = {
    "", "-", "--", "—", "–", "null", "none", "nan", "n/a", "na", "undefined",
    "未知", "暂无", "无", "空", "待补充", "待定", "不详", "未提供",
}

ENTITY_LABELS = {
    "teacher": "教师",
    "paper": "论文",
    "course": "课程",
    "unknown": "待识别",
}

# 规范字段 -> 常见表头别名。比较前会做 NFKC、去空白、去下划线/连字符、转小写。
HEADER_ALIASES = {
    "name": ["姓名", "教师姓名", "导师姓名", "老师姓名", "name", "teachername",
             "teacher_name", "faculty_name", "faculty", "full_name", "fullname"],
    "name_pinyin": ["拼音", "姓名拼音", "教师拼音", "name_pinyin", "pinyin"],
    "college": ["学院", "所属学院", "院系", "所在学院", "college", "school",
                "department", "dept", "faculty_school"],
    "college_raw": ["学院原文", "院系原文", "college_raw", "raw_college"],
    "title": ["职称", "教师职称", "岗位", "职位", "professional_title", "job_title",
              "position", "rank", "academic_title"],
    "title_generic": ["标题", "题目", "title", "heading"],
    "email": ["邮箱", "电子邮箱", "邮件", "email", "e_mail", "mail", "email_address"],
    "discipline": ["学科", "一级学科", "专业", "discipline", "subject", "major"],
    "research_directions": ["研究方向", "研究领域", "研究兴趣", "方向", "research_directions",
                            "research_direction", "research_area", "research_areas",
                            "research_interests", "interests", "keywords", "关键词"],
    "bio": ["简介", "个人简介", "教师简介", "biography", "bio", "profile", "introduction",
            "个人介绍"],
    "homepage_url": ["教师主页", "主页", "学院主页", "homepage", "homepage_url",
                     "faculty_homepage", "profile_url", "url", "link"],
    "personal_homepage": ["个人主页", "personal_homepage", "personal_website", "website"],
    "is_advisor": ["是否导师", "硕导", "是否硕导", "is_advisor", "master_advisor"],
    "is_phd_advisor": ["是否博导", "博导", "is_phd_advisor", "phd_advisor", "doctoral_advisor"],
    "honors": ["荣誉", "获奖", "人才称号", "honors", "awards", "honor"],
    "teacher_code": ["教师工号", "工号", "teacher_code", "faculty_id", "teacher_id"],
    "scholar_id": ["scholar_id", "scholarid", "谷歌学术id"],
    "scholar_name": ["scholar_name", "谷歌学术姓名"],
    "paper_count": ["论文数", "论文数量", "paper_count", "publication_count"],
    "citation_count": ["引用数", "总引用", "citation_count", "citations", "cited_by"],
    "h_index": ["h指数", "h_index", "hindex"],
    "research_topics": ["研究主题", "research_topics", "topics"],
    "institute": ["研究所", "系所", "单位", "institute", "department_unit"],
    "teacher_name": ["教师姓名", "导师姓名", "教师", "导师", "teacher_name", "advisor_name",
                     "mentor_name"],
    "teacher_link_id": ["教师id", "教师编号", "teacher_id", "advisor_id", "mentor_id"],
    "paper_title": ["论文标题", "文章标题", "论文题目", "文献标题", "paper_title",
                   "article_title", "publication_title", "title_of_paper"],
    "year": ["年份", "发表年份", "出版年", "year", "publication_year", "publish_year"],
    "venue": ["期刊", "会议", "发表期刊", "发表会议", "venue", "journal", "conference",
              "publication_venue", "source"],
    "doi": ["doi", "doi号", "文献doi"],
    "paper_id": ["论文id", "paper_id", "publication_id"],
    "authors": ["作者", "作者列表", "第一作者", "authors", "author", "author_list",
                "author_name"],
    "course_name": ["课程名称", "课程名", "课程", "course_name", "course", "class_name"],
    "course_code": ["课程代码", "课程号", "课号", "course_code", "course_id", "class_code"],
    "rating_score": ["评分", "课程评分", "综合评分", "rating", "rating_score", "score"],
    "rating_avg": ["平均评分", "均分", "rating_avg", "average_rating", "avg_rating"],
    "rating_count": ["评分数", "评价人数", "rating_count", "review_count", "num_ratings"],
    "last_semester": ["最近学期", "开课学期", "学期", "last_semester", "semester", "term"],
    "course_url": ["课程链接", "课程主页", "course_url", "class_url"],
    "entity_type": ["记录类型", "实体类型", "数据类型", "类型", "entity_type", "record_type",
                    "type"],
}

TEACHER_FIELDS = (
    "name", "name_pinyin", "college", "college_raw", "title", "email", "discipline",
    "research_directions", "bio", "homepage_url", "personal_homepage", "is_advisor",
    "is_phd_advisor", "honors", "teacher_code", "scholar_id", "scholar_name",
    "paper_count", "citation_count", "h_index", "research_topics", "institute",
)
PAPER_FIELDS = (
    "teacher_link_id", "teacher_name", "paper_title", "year", "citation_count", "venue",
    "doi", "paper_id", "authors",
)
COURSE_FIELDS = (
    "teacher_link_id", "teacher_name", "course_name", "course_code", "rating_score",
    "rating_avg", "rating_count", "last_semester", "course_url",
)
FIELD_LIMITS = {
    "name": 80, "name_pinyin": 120, "college": 120, "college_raw": 120, "title": 80,
    "email": 160, "discipline": 120, "research_directions": 1200, "bio": 6000,
    "homepage_url": 500, "personal_homepage": 500, "honors": 2000, "teacher_code": 80,
    "scholar_id": 100, "scholar_name": 120, "research_topics": 1000, "institute": 160,
    "teacher_name": 120, "paper_title": 500, "venue": 240, "doi": 240,
    "paper_id": 120, "authors": 2000, "course_name": 240, "course_code": 80,
    "last_semester": 80, "course_url": 500,
}
TABLE_FIELDS = {
    "teacher": TEACHER_FIELDS,
    "paper": PAPER_FIELDS,
    "course": COURSE_FIELDS,
}

ALIAS_INDEX = {}
for canonical, aliases in HEADER_ALIASES.items():
    for alias in aliases + [canonical]:
        ALIAS_INDEX[unicodedata.normalize("NFKC", alias).lower()
                    .replace("_", "").replace("-", "").replace(" ", "")] = canonical


def text(value):
    """统一文本：全半角、去控制字符、折叠空白。"""
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    value = value.replace("\u00a0", " ").replace("\u200b", "")
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return " ".join(value.split()).strip()


def is_null(value):
    value = text(value).lower()
    return value in NULL_TEXTS


def blank(value):
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return is_null(value)


def normalise_header(header):
    key = unicodedata.normalize("NFKC", text(header)).lower()
    key = re.sub(r"[\s_\-:：，,。.()（）\[\]【】/]+", "", key)
    return ALIAS_INDEX.get(key, "")


def parse_number(value):
    raw = text(value).replace(",", "").replace("，", "")
    if not raw:
        return None
    percent = raw.endswith("%")
    raw = raw.replace("%", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        return None
    number = float(match.group(0))
    if percent:
        number = number / 100.0
    return number


def parse_int(value):
    number = parse_number(value)
    if number is None:
        return None
    return int(round(number))


def parse_year(value):
    number = parse_int(value)
    if number is None:
        return None
    # 兼容 2023-01 / 2023年 / 2023.1 这类写法
    if 1900 <= number <= datetime.now().year + 1:
        return number
    if 19000000 <= number <= (datetime.now().year + 1) * 10000:
        return number // 10000
    return None


def parse_bool(value):
    if isinstance(value, bool):
        return value
    raw = text(value).lower()
    if raw in {"是", "yes", "y", "true", "1", "博导", "硕导", "博士生导师", "硕士生导师"}:
        return True
    if raw in {"否", "no", "n", "false", "0", "不是", "非", "无"}:
        return False
    return None


def split_list(value):
    """研究方向/作者/主题词：兼容顿号、逗号、分号、竖线、换行。"""
    if isinstance(value, (list, tuple)):
        parts = [text(item) for item in value]
    else:
        parts = [text(part) for part in re.split(r"[、,，;；|/\n]+", text(value))]
    return [part for part in dict.fromkeys(parts) if part]


HONOR_YEAR_RE = re.compile(r"(?:19|20)\d{2}\s*年?")
HONOR_PREFIX_RE = re.compile(
    r"^\s*(?:[\[\(（【]\s*(?:\d+|[一二三四五六七八九十]+)\s*[\]\)）】]"
    r"|(?:\d{1,2}|[一二三四五六七八九十]+)[\.、,，:：](?!\d))\s*"
)


def split_honors(value):
    """荣誉条目优先保留“2025年，奖项”这种年份+正文的完整关系。

    普通 `split_list` 会按逗号切开，导致“2025年”与奖项正文分离；这里只用
    分号/竖线/换行做强分隔，再只在一条里出现多个年份时按年份断句。
    """
    if isinstance(value, (list, tuple)):
        parts = [text(item) for item in value]
    else:
        parts = re.split(r"[；;|\n]+", text(value))

    entries = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        years = HONOR_YEAR_RE.findall(part)
        if len(years) >= 2:
            chunks = re.split(
                r"[、,，]\s*(?=(?:19|20)\d{2}\s*(?:年|年度)?)", part
            )
        elif not years and re.search(r"[、,，]", part):
            chunks = re.split(r"[、,，]+", part)
        else:
            chunks = [part]
        for chunk in chunks:
            item = HONOR_PREFIX_RE.sub("", chunk).strip().strip("。.,，;；")
            # NFKC 会把“2025年，”中的全角逗号转成半角；这里恢复成年份+逗号的可读格式。
            item = re.sub(
                r"^((?:19|20)\d{2})\s*年?\s*[,，:：]\s*",
                r"\1年，",
                item,
            )
            if item:
                entries.append(item)
    return [part for part in dict.fromkeys(entries) if part]


def normalise_url(value):
    raw = text(value)
    if not raw:
        return ""
    if raw.startswith("www."):
        raw = "https://" + raw
    if not URL_RE.match(raw):
        return ""
    return raw[:500]


def normalise_email(value):
    raw = text(value).lower().replace("mailto:", "").strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1].strip()
    return raw[:160] if EMAIL_RE.match(raw) else ""


def pinyin_of(name):
    if not name or lazy_pinyin is None:
        return ""
    try:
        return " ".join(lazy_pinyin(name)).lower()[:120]
    except Exception:
        return ""


def dedup_key_text(value):
    value = unicodedata.normalize("NFKC", text(value)).lower()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value)


def college_key(value):
    value = dedup_key_text(value)
    for suffix in ("学院", "school", "college", "department", "系"):
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[:-len(suffix)]
    return value


def map_row(raw):
    """把原始表头映射为规范字段；未知字段保留在 ``_extra`` 便于溯源。"""
    mapped = {}
    extra = {}
    for key, value in (raw or {}).items():
        canonical = normalise_header(key)
        if canonical:
            if canonical not in mapped or blank(mapped.get(canonical)):
                mapped[canonical] = value
        elif text(key):
            extra[text(key)] = value
    if extra:
        mapped["_extra"] = extra
    return mapped


def _entity_hint(mapped):
    raw = text(mapped.get("entity_type") or "").lower()
    if not raw:
        return ""
    for entity, words in {
        "teacher": ("teacher", "faculty", "教师", "导师", "老师"),
        "paper": ("paper", "publication", "论文", "文献", "文章"),
        "course": ("course", "class", "课程"),
    }.items():
        if any(word in raw for word in words):
            return entity
    return ""


def detect_entity_type(mapped):
    """基于字段证据打分，而不是仅凭表名/文件名。"""
    hint = _entity_hint(mapped)
    if hint:
        return hint, 95
    scores = {"teacher": 0.0, "paper": 0.0, "course": 0.0}
    teacher_evidence = {
        "name": 2.0, "college": 1.5, "title": 1.5, "email": 1.2,
        "research_directions": 1.5, "discipline": 1.0, "homepage_url": 1.0,
        "is_advisor": 1.0, "is_phd_advisor": 1.0, "honors": 0.8, "bio": 0.8,
    }
    paper_evidence = {
        "paper_title": 3.0, "doi": 2.5, "venue": 2.0, "year": 1.8,
        "authors": 1.5, "citation_count": 1.3, "paper_id": 1.2,
    }
    course_evidence = {
        "course_name": 3.0, "course_code": 2.5, "rating_score": 1.8,
        "rating_avg": 1.5, "rating_count": 1.3, "last_semester": 1.5,
        "course_url": 1.0,
    }
    for field, weight in teacher_evidence.items():
        if not blank(mapped.get(field)):
            scores["teacher"] += weight
    for field, weight in paper_evidence.items():
        if not blank(mapped.get(field)):
            scores["paper"] += weight
    for field, weight in course_evidence.items():
        if not blank(mapped.get(field)):
            scores["course"] += weight
    # 通用「标题」在不同实体里指向不同字段，结合其他证据判定
    if not blank(mapped.get("title_generic")):
        if scores["paper"] > scores["teacher"] and scores["paper"] >= scores["course"]:
            scores["paper"] += 1.2
        elif scores["course"] > scores["teacher"] and scores["course"] > scores["paper"]:
            scores["course"] += 1.0
        else:
            scores["teacher"] += 1.0
    best = max(scores, key=scores.get)
    top = scores[best]
    if top <= 0:
        return "unknown", 30
    confidence = min(96, int(45 + top * 8))
    return best, confidence


def _raw_with_type(entity, mapped):
    clean = {key: value for key, value in mapped.items() if key != "_extra"}
    if entity == "paper" and not clean.get("paper_title") and clean.get("title_generic"):
        clean["paper_title"] = clean.pop("title_generic")
    elif entity == "course" and not clean.get("course_name") and clean.get("title_generic"):
        clean["course_name"] = clean.pop("title_generic")
    elif entity == "teacher" and not clean.get("title") and clean.get("title_generic"):
        clean["title"] = clean.pop("title_generic")
    return clean


def existing_index(db_path):
    """读取现有实体键。只读，不写库；库不存在时返回空索引。"""
    index = {
        "teachers": [],
        "teacher_keys": {},
        "papers": [],
        "paper_keys": {},
        "courses": [],
        "course_keys": {},
        "teacher_names": {},
    }
    if not db_path or not os.path.exists(db_path):
        return index
    path = os.path.abspath(db_path).replace("\\", "/")
    uri = "file:" + quote(path, safe="/:") + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute(
                "SELECT id, name, college, name_pinyin FROM teachers"
            ):
                item = dict(row)
                index["teachers"].append(item)
                key = (dedup_key_text(item.get("name")), college_key(item.get("college")))
                index["teacher_keys"].setdefault(key, item)
                index["teacher_names"].setdefault(dedup_key_text(item.get("name")), []).append(item)
            for row in conn.execute(
                "SELECT id, teacher_id, title, doi FROM papers"
            ):
                item = dict(row)
                index["papers"].append(item)
                doi = dedup_key_text(item.get("doi"))
                if doi:
                    index["paper_keys"].setdefault(("doi", doi), item)
                title = dedup_key_text(item.get("title"))
                if title:
                    index["paper_keys"].setdefault((item.get("teacher_id"), title), item)
            for row in conn.execute(
                "SELECT id, teacher_id, course_name, course_code FROM courses"
            ):
                item = dict(row)
                index["courses"].append(item)
                code = dedup_key_text(item.get("course_code"))
                if code:
                    index["course_keys"].setdefault((item.get("teacher_id"), "code", code), item)
                name = dedup_key_text(item.get("course_name"))
                if name:
                    index["course_keys"].setdefault((item.get("teacher_id"), "name", name), item)
        finally:
            conn.close()
    except sqlite3.Error:
        return index
    return index


def _add_issue(issues, level, field, message):
    issues.append({"level": level, "field": field, "message": message})


def _normalise_teacher(mapped, index):
    clean = {}
    issues = []
    name = text(mapped.get("name")) or text(mapped.get("teacher_name"))
    if not name:
        _add_issue(issues, "error", "name", "缺少教师姓名")
    elif len(name) > 80:
        _add_issue(issues, "error", "name", "姓名过长（超过 80 字）")
        name = name[:80]
    clean["name"] = name
    clean["name_pinyin"] = text(mapped.get("name_pinyin")) or pinyin_of(name)
    college = text(mapped.get("college"))
    clean["college"] = college[:120]
    clean["college_raw"] = text(mapped.get("college_raw"))[:120] or college[:120]
    clean["title"] = text(mapped.get("title"))[:80]
    email_raw = text(mapped.get("email"))
    email = normalise_email(email_raw)
    if email_raw and not email:
        _add_issue(issues, "warning", "email", "邮箱格式无效，已清空")
    clean["email"] = email
    clean["discipline"] = text(mapped.get("discipline"))[:120]
    clean["research_directions"] = "、".join(split_list(mapped.get("research_directions")))[:1200]
    clean["bio"] = text(mapped.get("bio"))[:6000]
    for field in ("homepage_url", "personal_homepage"):
        url_raw = text(mapped.get(field))
        url = normalise_url(url_raw)
        if url_raw and not url:
            _add_issue(issues, "warning", field, "链接不是有效的 http(s) 地址，已清空")
        clean[field] = url
    for field in ("is_advisor", "is_phd_advisor"):
        raw = mapped.get(field)
        value = parse_bool(raw)
        if raw not in (None, "") and value is None:
            _add_issue(issues, "warning", field, "布尔值无法识别，已留空")
        clean[field] = value
    honors = split_honors(mapped.get("honors"))
    clean["honors"] = json.dumps(honors, ensure_ascii=False) if honors else ""
    clean["teacher_code"] = text(mapped.get("teacher_code"))[:80]
    clean["scholar_id"] = text(mapped.get("scholar_id"))[:100]
    clean["scholar_name"] = text(mapped.get("scholar_name"))[:120]
    for field in ("paper_count", "citation_count", "h_index"):
        raw = mapped.get(field)
        value = parse_int(raw)
        if raw not in (None, "") and (value is None or value < 0):
            _add_issue(issues, "warning", field, "应为非负整数，已留空")
            value = None
        clean[field] = value
    clean["research_topics"] = "、".join(split_list(mapped.get("research_topics")))[:1000]
    clean["institute"] = text(mapped.get("institute"))[:160]
    if not clean["college"] and clean["institute"]:
        _add_issue(issues, "warning", "college", "缺少学院，仅有研究所/系所")
    if not clean["research_directions"]:
        _add_issue(issues, "warning", "research_directions", "缺少研究方向，会影响检索与推荐")
    return clean, issues


def _resolve_teacher(mapped, index, issues, required=True):
    link_id = parse_int(mapped.get("teacher_link_id"))
    name = text(mapped.get("teacher_name"))
    teacher = None
    if link_id is not None:
        teacher = next((item for item in index["teachers"] if item.get("id") == link_id), None)
        if teacher is None:
            _add_issue(issues, "error", "teacher_link_id", "教师 ID 在库中不存在")
    if teacher is None and name:
        candidates = index["teacher_names"].get(dedup_key_text(name)) or []
        if len(candidates) == 1:
            teacher = candidates[0]
        elif len(candidates) > 1:
            # 同名教师不能默认挂到第一条；优先用学院消歧，否则要求教师 ID。
            college = college_key(mapped.get("college") or mapped.get("teacher_college"))
            if college:
                matches = [item for item in candidates
                           if college_key(item.get("college")) == college]
                if len(matches) == 1:
                    teacher = matches[0]
            if teacher is None:
                _add_issue(
                    issues, "error", "teacher_name",
                    f"库中存在 {len(candidates)} 位同名教师，请改用教师 ID 或补充学院",
                )
        else:
            _add_issue(issues, "error", "teacher_name", "库中找不到该教师，论文/课程必须先有教师档案")
    if teacher is None and required and not name and link_id is None:
        _add_issue(issues, "error", "teacher_name", "缺少教师关联（教师 ID 或姓名）")
    return teacher


def _normalise_paper(mapped, index):
    clean = {}
    issues = []
    title = text(mapped.get("paper_title")) or text(mapped.get("title_generic"))
    if not title:
        _add_issue(issues, "error", "paper_title", "缺少论文标题")
    elif len(title) > 500:
        _add_issue(issues, "warning", "paper_title", "标题过长，已截断")
        title = title[:500]
    clean["paper_title"] = title
    year_raw = mapped.get("year")
    year = parse_year(year_raw)
    if year_raw not in (None, "") and year is None:
        _add_issue(issues, "warning", "year", "年份不在合理范围，已留空")
    clean["year"] = year
    citations_raw = mapped.get("citation_count")
    citations = parse_int(citations_raw)
    if citations_raw not in (None, "") and (citations is None or citations < 0):
        _add_issue(issues, "warning", "citation_count", "引用数应为非负整数，已留空")
        citations = None
    clean["citation_count"] = citations
    clean["venue"] = text(mapped.get("venue"))[:240]
    doi_raw = text(mapped.get("doi"))
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi_raw, flags=re.I).strip()
    clean["doi"] = doi[:240]
    if doi_raw and not doi:
        _add_issue(issues, "warning", "doi", "DOI 为空")
    clean["paper_id"] = text(mapped.get("paper_id"))[:120]
    clean["authors"] = "、".join(split_list(mapped.get("authors")))[:2000]
    teacher = _resolve_teacher(mapped, index, issues)
    if teacher:
        clean["teacher_link_id"] = teacher["id"]
        clean["teacher_name"] = teacher.get("name") or text(mapped.get("teacher_name"))
        clean["_teacher_id"] = teacher["id"]
    return clean, issues


def _normalise_course(mapped, index):
    clean = {}
    issues = []
    name = text(mapped.get("course_name")) or text(mapped.get("title_generic"))
    if not name:
        _add_issue(issues, "error", "course_name", "缺少课程名称")
    else:
        name = name[:240]
    clean["course_name"] = name
    clean["course_code"] = text(mapped.get("course_code"))[:80]
    for field in ("rating_score", "rating_avg"):
        raw = mapped.get(field)
        value = parse_number(raw)
        if raw not in (None, "") and value is None:
            _add_issue(issues, "warning", field, "评分不是数字，已留空")
            value = None
        elif value is not None and not 0 <= value <= 5:
            # 兼容百分制：超过 5 分按 100 分制转为 5 分制
            if 0 <= value <= 100:
                value = round(value / 20.0, 2)
            else:
                _add_issue(issues, "warning", field, "评分超出范围，已留空")
                value = None
        clean[field] = value
    count_raw = mapped.get("rating_count")
    count = parse_int(count_raw)
    if count_raw not in (None, "") and (count is None or count < 0):
        _add_issue(issues, "warning", "rating_count", "评价人数应为非负整数，已留空")
        count = None
    clean["rating_count"] = count
    clean["last_semester"] = text(mapped.get("last_semester"))[:80]
    url_raw = text(mapped.get("course_url"))
    url = normalise_url(url_raw)
    if url_raw and not url:
        _add_issue(issues, "warning", "course_url", "课程链接不是有效的 http(s) 地址，已清空")
    clean["course_url"] = url
    teacher = _resolve_teacher(mapped, index, issues)
    if teacher:
        clean["teacher_link_id"] = teacher["id"]
        clean["teacher_name"] = teacher.get("name") or text(mapped.get("teacher_name"))
        clean["_teacher_id"] = teacher["id"]
    return clean, issues


def _duplicate_for(entity, clean, index):
    if entity == "teacher":
        key = (dedup_key_text(clean.get("name")), college_key(clean.get("college")))
        existing = index["teacher_keys"].get(key)
        if existing:
            return {"scope": "database", "entity": entity, "id": existing.get("id"),
                    "name": existing.get("name"), "college": existing.get("college")}
        if not clean.get("college"):
            matches = index["teacher_names"].get(dedup_key_text(clean.get("name"))) or []
            if len(matches) == 1:
                existing = matches[0]
                return {"scope": "database", "entity": entity, "id": existing.get("id"),
                        "name": existing.get("name"), "college": existing.get("college"),
                        "weak": True}
            if len(matches) > 1:
                return {
                    "scope": "database", "entity": entity,
                    "name": clean.get("name"),
                    "ambiguous": True,
                    "message": f"库中存在 {len(matches)} 位同名教师，请补充学院或改用教师 ID",
                }
    if entity == "paper":
        doi = dedup_key_text(clean.get("doi"))
        if doi and ("doi", doi) in index["paper_keys"]:
            existing = index["paper_keys"][("doi", doi)]
            return {"scope": "database", "entity": entity, "id": existing.get("id"),
                    "title": existing.get("title")}
        title = dedup_key_text(clean.get("paper_title"))
        teacher_id = clean.get("_teacher_id")
        if title and (teacher_id, title) in index["paper_keys"]:
            existing = index["paper_keys"][(teacher_id, title)]
            return {"scope": "database", "entity": entity, "id": existing.get("id"),
                    "title": existing.get("title")}
    if entity == "course":
        teacher_id = clean.get("_teacher_id")
        code = dedup_key_text(clean.get("course_code"))
        if code and (teacher_id, "code", code) in index["course_keys"]:
            existing = index["course_keys"][(teacher_id, "code", code)]
            return {"scope": "database", "entity": entity, "id": existing.get("id"),
                    "course_name": existing.get("course_name")}
        name = dedup_key_text(clean.get("course_name"))
        if name and (teacher_id, "name", name) in index["course_keys"]:
            existing = index["course_keys"][(teacher_id, "name", name)]
            return {"scope": "database", "entity": entity, "id": existing.get("id"),
                    "course_name": existing.get("course_name")}
    return None


def _file_key(entity, clean):
    if entity == "teacher":
        return (entity, dedup_key_text(clean.get("name")), college_key(clean.get("college")))
    if entity == "paper":
        doi = dedup_key_text(clean.get("doi"))
        return (entity, "doi", doi) if doi else (
            entity, dedup_key_text(clean.get("paper_title")), clean.get("_teacher_id"))
    if entity == "course":
        code = dedup_key_text(clean.get("course_code"))
        return (entity, clean.get("_teacher_id"), "code", code) if code else (
            entity, clean.get("_teacher_id"), "name", dedup_key_text(clean.get("course_name")))
    return (entity, id(clean))


def _diff(clean, raw_mapped):
    changes = []
    for field, value in clean.items():
        if field.startswith("_"):
            continue
        before = raw_mapped.get(field)
        if before is None:
            continue
        before_text = text(before) if not isinstance(before, (list, dict, bool)) else str(before)
        after_text = "" if value is None else (
            json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value))
        if text(before_text) != text(after_text):
            changes.append({"field": field, "before": before_text[:180], "after": after_text[:180]})
    return changes[:18]


def build_record(raw, mode, index, source="rule", overrides=None, forced_type=None):
    mapped = map_row(raw)
    if overrides:
        for key, value in overrides.items():
            if key in HEADER_ALIASES or key in FIELD_LIMITS:
                mapped[key] = value
    if forced_type in ("teacher", "paper", "course"):
        entity, confidence = forced_type, 90
    elif mode in ("teacher", "paper", "course"):
        entity, confidence = mode, 92
    else:
        entity, confidence = detect_entity_type(mapped)
    issues = []
    if entity == "teacher":
        clean, issues = _normalise_teacher(mapped, index)
    elif entity == "paper":
        clean, issues = _normalise_paper(mapped, index)
        entity = "paper"
    elif entity == "course":
        clean, issues = _normalise_course(mapped, index)
        entity = "course"
    else:
        entity, clean = "unknown", {}
        _add_issue(issues, "error", "entity_type", "无法判断这是教师、论文还是课程")
    clean = {key: value for key, value in clean.items() if not key.startswith("_")} | {
        key: value for key, value in clean.items() if key.startswith("_")
    }
    changes = _diff(clean, mapped)
    duplicate = _duplicate_for(entity, clean, index) if entity != "unknown" else None
    if duplicate:
        _add_issue(issues, "warning", "_duplicate",
                   "库中已存在相同实体，默认跳过" if duplicate.get("scope") == "database"
                   else "文件内出现重复行")
    errors = sum(1 for item in issues if item["level"] == "error")
    warnings = sum(1 for item in issues if item["level"] == "warning")
    status = "error" if errors else ("duplicate" if duplicate else ("warning" if warnings else "ready"))
    completeness = _completeness(entity, clean)
    quality = int(round(
        100 - errors * 25 - warnings * 8
        - (6 if duplicate else 0)
        - (100 - completeness) * 0.35
    ))
    quality = max(0, min(100, quality))
    if entity == "unknown":
        quality = min(quality, 30)
    return {
        "entity_type": entity,
        "entity_label": ENTITY_LABELS.get(entity, entity),
        "confidence": confidence,
        "status": status,
        "issues": issues,
        "clean": clean,
        "changes": changes,
        "duplicate": duplicate,
        "completeness": completeness,
        "quality": quality,
        "source": source,
    }


def _completeness(entity, clean):
    fields = {
        "teacher": ("name", "college", "title", "email", "research_directions", "homepage_url"),
        "paper": ("paper_title", "year", "venue", "doi", "authors", "teacher_name"),
        "course": ("course_name", "course_code", "rating_score", "last_semester", "teacher_name"),
    }.get(entity, ())
    if not fields:
        return 0
    filled = sum(1 for field in fields if not blank(clean.get(field)))
    return int(round(filled / len(fields) * 100))


def parse_upload(filename, content, max_bytes=None):
    """解析上传文件，返回 raw_rows, columns, notes；异常抛出 ValueError。"""
    name = os.path.basename(filename or "upload.csv")
    ext = os.path.splitext(name)[1].lower()
    if not content:
        raise ValueError("文件为空。")
    limit = int(max_bytes) if max_bytes is not None else MAX_FILE_BYTES
    if len(content) > limit:
        raise ValueError(
            f"文件超过 {format_file_size(limit)} 限制，请拆分后导入。"
        )
    if ext in (".xlsx", ".xlsm"):
        return _parse_excel(content, name)
    if ext in (".json", ".jsonl", ".ndjson"):
        return _parse_json(content, name)
    return _parse_csv(content, name, ext)


def _decode(content):
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，请另存为 UTF-8 CSV。")


def _parse_csv(content, name, ext):
    decoded = _decode(content)
    sample = decoded[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if ext == ".tsv" else csv.excel
    reader = csv.reader(io.StringIO(decoded), dialect)
    rows = []
    headers = None
    for cells in reader:
        if not cells or all(not text(cell) for cell in cells):
            continue
        if headers is None:
            headers = [text(cell) for cell in cells]
            continue
        if all(not text(cell) for cell in cells):
            continue
        if [text(cell) for cell in cells] == headers:
            continue
        values = [text(cell) for cell in cells]
        if len(values) < len(headers):
            values += [""] * (len(headers) - len(values))
        rows.append(dict(zip(headers, values[:len(headers)], strict=False)))
        if len(rows) > MAX_ROWS:
            raise ValueError(f"数据行超过 {MAX_ROWS} 行限制，请拆分后导入。")
    if headers is None:
        raise ValueError("没有识别到表头。")
    return rows, headers, ["CSV 解析：自动识别分隔符，空行与重复表头已跳过。"]


def _parse_json(content, name):
    decoded = _decode(content)
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        # JSON Lines
        rows = []
        for line in decoded.splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSON 第 {len(rows) + 1} 行无法解析：{exc}") from exc
            if isinstance(item, dict):
                rows.append(item)
        if not rows:
            raise ValueError("JSON 文件没有可用对象。") from None
        columns = list(dict.fromkeys(key for row in rows for key in row))
        return rows[:MAX_ROWS], columns, ["JSON Lines 解析：逐行读取对象。"]
    if isinstance(payload, dict):
        for key in ("rows", "data", "records", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            lists = {key: value for key, value in payload.items() if isinstance(value, list)}
            if lists:
                rows = []
                for key, values in lists.items():
                    hint = detect_entity_type(map_row({"entity_type": key}))
                    for item in values:
                        if isinstance(item, dict):
                            item = dict(item)
                            item.setdefault("entity_type", hint[0])
                            rows.append(item)
                payload = rows
    if not isinstance(payload, list):
        raise ValueError("JSON 顶层应为数组，或包含 rows/data/records 数组。")
    rows = [item for item in payload if isinstance(item, dict)]
    if not rows:
        raise ValueError("JSON 中没有对象行。")
    if len(rows) > MAX_ROWS:
        raise ValueError(f"数据行超过 {MAX_ROWS} 行限制，请拆分后导入。")
    columns = list(dict.fromkeys(key for row in rows for key in row))
    notes = ["JSON 解析：支持数组、rows/data/records 容器与分类数组。"]
    if len(rows) != len(payload):
        notes.append("已忽略非对象行。")
    return rows, columns, notes


def _parse_excel(content, name):
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise ValueError("未安装 pandas，无法读取 Excel。") from exc
    try:
        frame = pd.read_excel(io.BytesIO(content), sheet_name=0, dtype=str)
    except ImportError as exc:
        raise ValueError("读取 .xlsx 需要安装 openpyxl，请运行 pip install openpyxl。") from exc
    except Exception as exc:
        raise ValueError(f"Excel 解析失败：{exc}") from exc
    frame = frame.fillna("")
    if len(frame) > MAX_ROWS:
        raise ValueError(f"数据行超过 {MAX_ROWS} 行限制，请拆分后导入。")
    headers = [text(item) for item in frame.columns]
    rows = []
    for record in frame.to_dict(orient="records"):
        row = {text(key): text(value) for key, value in record.items()}
        if any(value for value in row.values()):
            rows.append(row)
    if not rows:
        raise ValueError("Excel 中没有可用数据行。")
    return rows, headers, ["Excel 解析：读取第一个工作表，空行已跳过。"]


def analyse(db_path, raw_rows, mode="auto", filename="", ai_enabled=False,
            ai_model="", column_names=None):
    """对原始行做完整规则分析，返回可直接存预览的行。"""
    index = existing_index(db_path)
    rows = []
    seen = {}
    for number, raw in enumerate(raw_rows, 1):
        record = build_record(raw, mode, index)
        record["row_number"] = number
        record["raw"] = {text(key): text(value)[:500] for key, value in raw.items()
                         if not str(key).startswith("_")}
        key = _file_key(record["entity_type"], record["clean"])
        if key in seen:
            record["duplicate"] = {
                "scope": "file", "entity": record["entity_type"],
                "row": seen[key], "message": f"与文件第 {seen[key]} 行重复",
            }
            record["status"] = "duplicate"
            record["issues"].append({"level": "warning", "field": "_duplicate",
                                     "message": f"文件内与第 {seen[key]} 行重复"})
        elif record["entity_type"] != "unknown":
            seen[key] = number
        rows.append(record)
    summary = summarise(rows, column_names or list(dict.fromkeys(
        key for raw in raw_rows for key in raw
    )), ai_enabled=ai_enabled, ai_model=ai_model)
    return rows, summary


def summarise(rows, columns, ai_enabled=False, ai_model=""):
    total = len(rows)
    status_counts = {"ready": 0, "warning": 0, "duplicate": 0, "error": 0}
    entity_counts = {"teacher": 0, "paper": 0, "course": 0, "unknown": 0}
    field_stats = {}
    issue_counts = {}
    quality_values = []
    for row in rows:
        status_counts[row.get("status", "error")] = status_counts.get(row.get("status", "error"), 0) + 1
        entity = row.get("entity_type") or "unknown"
        entity_counts[entity] = entity_counts.get(entity, 0) + 1
        quality_values.append(int(row.get("quality") or 0))
        for field, value in (row.get("clean") or {}).items():
            if str(field).startswith("_"):
                continue
            item = field_stats.setdefault(field, {"filled": 0, "total": total})
            if not blank(value):
                item["filled"] += 1
        for issue in row.get("issues") or []:
            message = issue.get("message") or ""
            issue_counts[message] = issue_counts.get(message, 0) + 1
    for item in field_stats.values():
        item["missing_rate"] = round(
            (item["total"] - item["filled"]) / item["total"] * 100, 1
        ) if item["total"] else 0
    missing_top = sorted(
        ({"field": field, "missing_rate": item["missing_rate"], "filled": item["filled"]}
         for field, item in field_stats.items()),
        key=lambda item: item["missing_rate"], reverse=True,
    )[:12]
    quality_score = int(round(sum(quality_values) / total)) if total else 0
    return {
        "total_rows": total,
        "ready_rows": status_counts.get("ready", 0),
        "warning_rows": status_counts.get("warning", 0),
        "duplicate_rows": status_counts.get("duplicate", 0),
        "error_rows": status_counts.get("error", 0),
        "invalid_rows": status_counts.get("error", 0),
        "entity_counts": entity_counts,
        "columns": list(columns),
        "field_stats": field_stats,
        "missing_top": missing_top,
        "issue_counts": dict(sorted(issue_counts.items(), key=lambda item: item[1], reverse=True)[:12]),
        "quality_score": quality_score,
        "ai_enabled": bool(ai_enabled),
        "ai_model": ai_model or "",
        "notes": [
            "规则清洗可独立运行；AI 只做辅助判定与文本规范化，不生成缺失事实。",
            "重复行默认跳过；可在应用时选择仅补空字段或覆盖更新。",
        ],
    }


def count_status(rows):
    counts = {"ready": 0, "warning": 0, "duplicate": 0, "error": 0}
    entities = {"teacher": 0, "paper": 0, "course": 0, "unknown": 0}
    for row in rows:
        counts[row.get("status", "error")] = counts.get(row.get("status", "error"), 0) + 1
        entity = row.get("entity_type") or "unknown"
        entities[entity] = entities.get(entity, 0) + 1
    return counts, entities


def backup_database(db_path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(backup_dir, f"mentor_before_import_{stamp}_{int(time.time() * 1000) % 1000:03d}.db")
    src = sqlite3.connect(db_path, timeout=10.0)
    dst = sqlite3.connect(path)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    return path


def _table_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _provider_values(entity, clean, table_columns):
    fields = TABLE_FIELDS[entity]
    db_name = {"paper_title": "title"} if entity == "paper" else {}
    values = {}
    for field in fields:
        column = db_name.get(field, field)
        if column in table_columns:
            values[column] = clean.get(field)
    # clean 中允许带 teacher_link_id 等内部键，但只写白名单字段
    if entity in ("paper", "course"):
        values["teacher_id"] = clean.get("_teacher_id") or clean.get("teacher_link_id")
    return values


def _insert(conn, table, values):
    values = {key: value for key, value in values.items()
              if value not in (None, "", [], {})}
    if not values:
        raise ValueError("没有可写入的字段")
    columns = list(values.keys())
    sql = f"INSERT INTO {table} (" + ",".join(columns) + ") VALUES (" + \
        ",".join("?" for _ in columns) + ")"
    cursor = conn.execute(sql, [values[key] for key in columns])
    return cursor.lastrowid


def _update_empty(conn, table, row_id, values):
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        return 0
    existing = dict(row)
    updates = {}
    for field, value in values.items():
        if field in ("id", "teacher_id"):
            continue
        if value in (None, "", [], {}) or field not in existing:
            continue
        if existing[field] in (None, "", "[]", "null"):
            updates[field] = value
    if updates:
        conn.execute(
            f"UPDATE {table} SET " + ",".join(f"{field} = ?" for field in updates) +
            " WHERE id = ?", list(updates.values()) + [row_id],
        )
    return len(updates)


def _update_all(conn, table, row_id, values):
    updates = {field: value for field, value in values.items()
               if field not in ("id", "teacher_id") and value not in (None, "", [], {})}
    if updates:
        conn.execute(
            f"UPDATE {table} SET " + ",".join(f"{field} = ?" for field in updates) +
            " WHERE id = ?", list(updates.values()) + [row_id],
        )
    return len(updates)


def apply_rows(db_path, rows, conflict="skip", selected_rows=None):
    """把预览行事务写入正式库。

    - error 行永不写入；
    - duplicate 行按 conflict 处理：skip / update_empty / update_all；
    - 非 duplicate 行正常插入；
    - 每行使用 SAVEPOINT，单行失败不会破坏整批。
    """
    from .db import connect
    allowed = None
    if selected_rows is not None:
        allowed = {int(item) for item in selected_rows}
    counts = {
        "teacher": {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0},
        "paper": {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0},
        "course": {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0},
        "unknown": {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0},
    }
    failures = []
    conn = connect(db_path, readonly=False, timeout=15.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        teacher_cols = _table_columns(conn, "teachers")
        paper_cols = _table_columns(conn, "papers")
        course_cols = _table_columns(conn, "courses")
        for row in rows:
            number = int(row.get("row_number") or 0)
            if allowed is not None and number not in allowed:
                continue
            entity = row.get("entity_type") or "unknown"
            status = row.get("status") or ""
            if entity == "unknown" or status == "error":
                counts[entity]["skipped"] += 1
                continue
            if status == "duplicate" and conflict == "skip":
                counts[entity]["skipped"] += 1
                continue
            conn.execute("SAVEPOINT import_row")
            try:
                target_table = {"teacher": "teachers", "paper": "papers", "course": "courses"}[entity]
                table_cols = {"teacher": teacher_cols, "paper": paper_cols,
                              "course": course_cols}[entity]
                clean = row.get("clean") or {}
                values = _provider_values(entity, clean, table_cols)
                duplicate = row.get("duplicate") or {}
                existing_id = duplicate.get("id")
                if status == "duplicate" and existing_id and conflict in ("update_empty", "update_all"):
                    updater = _update_empty if conflict == "update_empty" else _update_all
                    changed = updater(conn, target_table, existing_id, values)
                    counts[entity]["updated" if changed else "skipped"] += 1
                elif status == "duplicate":
                    counts[entity]["skipped"] += 1
                else:
                    _insert(conn, target_table, values)
                    counts[entity]["inserted"] += 1
                conn.execute("RELEASE SAVEPOINT import_row")
            except Exception as exc:
                conn.execute("ROLLBACK TO SAVEPOINT import_row")
                conn.execute("RELEASE SAVEPOINT import_row")
                counts[entity]["failed"] += 1
                failures.append({"row_number": number, "entity": entity,
                                 "message": str(exc)[:300]})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    totals = {
        "teachers_inserted": counts["teacher"]["inserted"],
        "teachers_updated": counts["teacher"]["updated"],
        "teachers_skipped": counts["teacher"]["skipped"],
        "papers_inserted": counts["paper"]["inserted"],
        "papers_updated": counts["paper"]["updated"],
        "papers_skipped": counts["paper"]["skipped"],
        "courses_inserted": counts["course"]["inserted"],
        "courses_updated": counts["course"]["updated"],
        "courses_skipped": counts["course"]["skipped"],
        "failed": sum(item["failed"] for item in counts.values()),
    }
    return {"counts": counts, "totals": totals, "failures": failures[:50]}


def rebuild_summary(rows, columns, ai_enabled=False, ai_model=""):
    return summarise(rows, columns, ai_enabled=ai_enabled, ai_model=ai_model)


def apply_ai_suggestions(db_path, rows, suggestions, mode="auto"):
    """把 AI 建议合并回规则行：强制实体类型、覆盖允许的文本字段，再重新校验。"""
    index = existing_index(db_path)
    merged = []
    by_number = {int(item.get("row_number") or 0): item for item in rows}
    suggestion_map = {int(item.get("row_number") or 0): item for item in suggestions}
    for number, row in by_number.items():
        suggestion = suggestion_map.get(number) or {}
        forced = suggestion.get("entity_type")
        if forced not in ("teacher", "paper", "course"):
            forced = None
        overrides = suggestion.get("field_updates") or {}
        overrides = {key: value for key, value in overrides.items() if key in FIELD_LIMITS}
        rebuilt = build_record(row.get("raw") or {}, mode, index, source="ai",
                               overrides=overrides, forced_type=forced)
        rebuilt["row_number"] = number
        rebuilt["raw"] = row.get("raw") or {}
        if suggestion.get("confidence") is not None:
            with contextlib.suppress(TypeError, ValueError):
                rebuilt["confidence"] = max(0, min(100, int(float(suggestion["confidence"]))))
        ai_notes = suggestion.get("notes") or []
        if isinstance(ai_notes, str):
            ai_notes = [ai_notes]
        for note in ai_notes[:4]:
            rebuilt["issues"].append({"level": "info", "field": "ai", "message": text(note)[:200]})
        if suggestion.get("drop_reason"):
            rebuilt["status"] = "error"
            rebuilt["issues"].append({"level": "error", "field": "ai",
                                       "message": text(suggestion["drop_reason"])[:200]})
        if rebuilt["status"] == "ready" and rebuilt["issues"]:
            rebuilt["status"] = "warning"
        merged.append(rebuilt)
    # AI 重建后仍需重新检查文件内重复，否则同一文件的重复行会漏掉
    seen = {}
    for row in merged:
        key = _file_key(row["entity_type"], row["clean"])
        if key in seen:
            row["duplicate"] = {
                "scope": "file", "entity": row["entity_type"],
                "row": seen[key], "message": f"与文件第 {seen[key]} 行重复",
            }
            row["status"] = "duplicate"
            row["issues"].append({"level": "warning", "field": "_duplicate",
                                  "message": f"文件内与第 {seen[key]} 行重复"})
        elif row["entity_type"] != "unknown":
            seen[key] = row["row_number"]
    return merged

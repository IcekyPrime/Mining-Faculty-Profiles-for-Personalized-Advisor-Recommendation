"""上海交通大学教师名录爬虫（faculty.sjtu.edu.cn）。

负责：学院教师列表分页抓取 -> 教师主页抓取与解析 -> 导师筛选与身份识别。
原始 HTML 缓存到 data/raw/ 下，支持断点续抓。
"""
import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config


def _make_session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[500, 502, 503, 504],
                  allowed_methods=frozenset(["GET"]))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update(config.HEADERS)
    return s


def _get(session, url, timeout=30, tries=6):
    """带手动重试的 GET，应对 faculty.sjtu.edu.cn 的间歇性读超时。"""
    last = None
    for i in range(tries):
        try:
            r = session.get(url, timeout=timeout)
            r.encoding = r.apparent_encoding or r.encoding
            return r.text
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def _slug_from_url(url):
    m = re.search(r"faculty\.sjtu\.edu\.cn/([^/]+)/", url)
    return m.group(1) if m else None


_LIST_DIR = os.path.join(config.RAW_DIR, "list_pages")
os.makedirs(_LIST_DIR, exist_ok=True)


def _fetch_list_page(session, college_id, page, totalpage=99):
    """抓取（或复用缓存）某个学院的列表页 HTML；失败返回 None（不缓存）。"""
    cache = os.path.join(_LIST_DIR, f"{college_id}_{page}.html")
    if os.path.exists(cache):
        with open(cache, "r", encoding="utf-8") as f:
            return f.read()
    try:
        if page == 1:
            html = _get(session, config.LIST_URL.format(college_id=college_id))
        else:
            html = _get(session, config.LIST_PAGE_URL.format(
                totalpage=totalpage, page=page, college_id=college_id))
    except Exception as e:
        print(f"  [warn] 列表页 {page} 抓取失败: {type(e).__name__}")
        return None
    with open(cache, "w", encoding="utf-8") as f:
        f.write(html)
    time.sleep(1.0)
    return html


def _parse_totalpage(html):
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style"]):
        s.decompose()
    fanye = soup.find(id="fanye")
    if fanye:
        m = re.search(r"共\s*(\d+)\s*条.*?(\d+)\s*/\s*(\d+)", fanye.get_text(" ", strip=True))
        if m:
            return int(m.group(3))
    return 1


def crawl_teacher_list():
    """抓取所有目标学院的教师列表（分页），返回教师条目列表。"""
    teachers = []
    session = _make_session()
    for college_id, college_name in config.COLLEGES.items():
        first_html = _fetch_list_page(session, college_id, 1)
        total_page = _parse_totalpage(first_html)
        print(f"  学院 {college_name}: 共 {total_page} 页")
        for page in range(1, total_page + 1):
            html = first_html if page == 1 else _fetch_list_page(
                session, college_id, page, totalpage=total_page)
            if html is None:
                continue
            for item in _parse_list_page(html, college_name):
                teachers.append(item)
    # 去重（按主页 slug）
    seen = set()
    dedup = []
    for t in teachers:
        if t["slug"] and t["slug"] not in seen:
            seen.add(t["slug"])
            dedup.append(t)
    out = os.path.join(config.RAW_DIR, "teacher_list.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(dedup, f, ensure_ascii=False, indent=2)
    return dedup


def _parse_list_page(html, college_name):
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style"]):
        s.decompose()
    items = []
    for li in soup.select("div.list ul li"):
        a = li.find("a")
        if not a or not a.get("href"):
            continue
        name_el = li.select_one(".name")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        title = ""
        for p in li.select(".js p"):
            txt = p.get_text(" ", strip=True)
            if txt.startswith("职称"):
                title = txt.split("：", 1)[-1].split(":", 1)[-1].strip()
        href = a.get("href")
        slug = _slug_from_url(href)
        items.append({
            "name": name,
            "title": title,
            "college": college_name,
            "homepage_url": href,
            "slug": slug,
        })
    return items


def crawl_homepages(teachers):
    """抓取并解析每位教师主页，缓存原始 HTML，返回富化后的教师列表。"""
    session = _make_session()
    enriched = []
    for i, t in enumerate(teachers):
        slug = t.get("slug")
        cache = os.path.join(config.HOMEPAGE_DIR, f"{slug}.html") if slug else None
        html = None
        if cache and os.path.exists(cache):
            with open(cache, "r", encoding="utf-8") as f:
                html = f.read()
        else:
            try:
                html = _get(session, t["homepage_url"])
            except Exception as e:
                print(f"  [skip] {t['name']} 抓取失败: {e}")
            if html and cache:
                with open(cache, "w", encoding="utf-8") as f:
                    f.write(html)
            time.sleep(2.0)
        if html:
            parsed = parse_teacher_homepage(html)
            t.update({k: v for k, v in parsed.items() if v})
        enriched.append(t)
        if (i + 1) % 20 == 0:
            print(f"  ... 已处理 {i + 1}/{len(teachers)}")
    out = os.path.join(config.RAW_DIR, "teachers_enriched.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    return enriched


def parse_teacher_homepage(html):
    """解析教师主页，兼容新旧两套模板。"""
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style"]):
        s.decompose()
    teacher = {}

    # --- 姓名 ---（旧版 div.t_name / 新版 .photo-text h3）
    tname = soup.select_one("div.t_name") or soup.select_one(".photo-text h3")
    if tname:
        teacher["name"] = tname.get_text(" ", strip=True)

    # --- 基本信息 ---（旧版 #boxscroll2 ul li；新版 .intro-text p span）
    for li in soup.select("#boxscroll2 ul li"):
        strong = li.find("strong")
        if not strong:
            continue
        label = strong.get_text(strip=True).rstrip("：:")
        value = li.get_text(" ", strip=True).replace(strong.get_text(strip=True), "", 1).strip().lstrip("：:")
        _set_basic(teacher, label, value)
    for p in soup.select(".intro-text p"):
        span = p.find("span")
        if not span:
            continue
        label = span.get_text(strip=True).rstrip("：:")
        value = p.get_text(" ", strip=True).replace(span.get_text(strip=True), "", 1).strip().lstrip("：:")
        _set_basic(teacher, label, value)
    # 新版职称：.photo-text 下无 span 的 p
    if not teacher.get("title"):
        pt = soup.select_one(".photo-text p")
        if pt:
            teacher["title"] = pt.get_text(strip=True)

    # --- Tab 内容 ---（旧版 .TabbedPanelsTab/Content；新版 .tab-menu span / .tab-wp .tab-con .tab-inner）
    tabs = [t.get_text(strip=True) for t in soup.select(".TabbedPanelsTab")]
    contents = [c.get_text(" ", strip=True) for c in soup.select(".TabbedPanelsContent")]
    if not tabs:
        tabs = [t.get_text(strip=True) for t in soup.select(".tab-menu a span")]
        contents = [c.get_text(" ", strip=True) for c in soup.select(".tab-wp .tab-con .tab-inner")]
    for label, content in zip(tabs, contents):
        if label.startswith("个人简介"):
            teacher["bio"] = content
        elif label in ("研究方向", "研究领域"):
            teacher["research_directions"] = content

    return teacher


def _set_basic(teacher, label, value):
    if label == "所在单位":
        teacher["college"] = value
    elif label == "职称":
        teacher["title"] = value
    elif label == "电子邮箱":
        teacher["email"] = value
    elif label == "教师拼音名称":
        teacher["name_pinyin"] = value
    elif label == "学科":
        teacher["discipline"] = value
    elif label == "办公地点":
        teacher["office"] = value


def extract_honors(text):
    """从简介 / 研究方向文本中识别人才称号与导师身份。"""
    if not text:
        return {}
    honors = {}
    for key, pattern in config.HONOR_PATTERNS:
        if re.search(pattern, text):
            honors[key] = True
    return honors


def classify_advisor(teacher):
    """判断是否为（硕/博）导师，返回 (是否导师, 理由)。

    以职称为主信号：教授/研究员序列直接视为导师；行政/教辅岗排除；
    职称缺失或未知时，用研究方向/学科/简介中的导师线索兜底。
    """
    title = (teacher.get("title") or "").strip()
    # 高级工程序列（可能是硕导）
    if any(k in title for k in ("高级工程师", "教授级高工", "研究员级高工")):
        return True, ""
    for kw in ("讲师", "助教", "辅导员", "科员", "秘书", "行政", "教务",
               "学工", "实验师", "馆员", "工程师", "工勤", "职员"):
        if kw in title:
            return False, f"职称[{title}]属于行政/教辅岗"
    for kw in ("教授", "研究员", "科学家"):
        if kw in title:
            return True, ""
    has_direction = bool((teacher.get("research_directions") or "").strip())
    has_discipline = bool((teacher.get("discipline") or "").strip())
    bio = teacher.get("bio") or ""
    if has_direction or has_discipline or re.search(r"导师|招生|研究生", bio):
        return True, ""
    return False, f"职称[{title or '未知'}]且无研究方向，无法确认导师身份"


def classify(teacher):
    """综合分类：补全 is_advisor / is_phd_advisor / honors 字段。"""
    bio = teacher.get("bio") or ""
    rd = teacher.get("research_directions") or ""
    awards = " ".join(teacher.get("awards") or [])
    text = f"{bio} {rd} {awards}"
    honors = extract_honors(text)
    ok, reason = classify_advisor(teacher)
    teacher["is_advisor"] = 1 if ok else 0
    teacher["filter_reason"] = reason
    teacher["is_phd_advisor"] = 1 if honors.get("博导") else 0
    teacher["honors"] = json.dumps([k for k, v in honors.items() if v], ensure_ascii=False)
    return teacher

"""四个目标学院教师名录爬虫（自动化与感知 / 集成电路 / 电气工程 / 人工智能）。

三个学院（自动化/集成电路/电气）与计算机学院同一套 CMS，走 AJAX 接口
active/ajax_teacher_list.html；人工智能学院为静态页。教师详情页模板分三类：
cs 模板（自动化/集成电路，复用 cs_crawler 解析）、see 模板（电气）、sai 模板（人工智能）。
"""
import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup

from . import config, cs_crawler

CACHE_DIR = os.path.join(config.RAW_DIR, "colleges")
os.makedirs(CACHE_DIR, exist_ok=True)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}

COLLEGES = {
    "自动化与感知学院": {
        "base": "https://sais.sjtu.edu.cn",
        "kind": "ajax",
        "list_url": "https://sais.sjtu.edu.cn/active/ajax_teacher_list.html",
        "list_data": {"cat_id": "18", "cat_code": "faculty", "type": 1, "zm": "All", "search": ""},
        "href_re": r"/faculty/([^/]+)\.html",
        "detail_parse": "js_list",
    },
    "集成电路学院": {
        "base": "https://icisee.sjtu.edu.cn",
        "kind": "ajax_paged",
        "list_url": "https://icisee.sjtu.edu.cn/active/ajax_teacher_list.html",
        "list_data": {"cat_code": "jiaoshiml", "yjszxfl": "", "name": "", "zm": "All"},
        "href_re": r"/jiaoshiml/([^/]+)\.html",
        "detail_parse": "js_list",
    },
    "电气工程学院": {
        "base": "https://see.sjtu.edu.cn",
        "kind": "ajax",
        "list_url": "https://see.sjtu.edu.cn/active/ajax_teacher_list.html",
        "list_data": {"cat_id": "40", "cat_code": "jiaoshiml", "type": 1},
        "href_re": r"/jiaoshiml/([^/]+)\.html",
        "detail_parse": "see",
    },
    "人工智能学院": {
        "base": "https://sai.sjtu.edu.cn",
        "kind": "static",
        "list_pages": [
            ("专职教师", "https://sai.sjtu.edu.cn/cn/faculty/zzjs", r"/cn/facultydetails/zzjs/([^/]+)"),
            ("双聘/客座", "https://sai.sjtu.edu.cn/cn/teacher/spkz", None),
        ],
        "detail_parse": "sai",
    },
}


def _get(url, timeout=40):
    r = requests.get(url, headers=_HEADERS, timeout=timeout)
    r.encoding = r.apparent_encoding or r.encoding
    r.raise_for_status()
    return r.text


def _post(url, data, referer, timeout=40):
    h = dict(_HEADERS)
    h["Referer"] = referer
    r = requests.post(url, data=data, headers=h, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _clean(name):
    return re.sub(r"[\u3000\s]", "", name or "")


def _extract_from_content(soup, href_re, base):
    """从内容 HTML 中提取教师链接 {name, title, detail_url, slug}。"""
    teachers = []
    seen = set()
    for a in soup.find_all("a", href=True):
        m = re.search(href_re, a.get("href", ""))
        if not m:
            continue
        slug = m.group(1)
        href = a.get("href")
        url = href if href.startswith("http") else base.rstrip("/") + href
        name_el = a.find(class_="name")
        name, title = "", ""
        if name_el:
            sp = name_el.find("span")
            title = sp.get_text(strip=True) if sp else ""
            name = name_el.get_text(" ", strip=True)
            if sp:
                name = name.replace(sp.get_text(strip=True), "", 1)
            for p in name_el.find_all("p"):
                name = name.replace(p.get_text(strip=True), "")
            name = name.strip()
        else:
            name = a.get_text(" ", strip=True)
        name = _clean(name)
        if not name:
            continue
        if url in seen:
            continue
        seen.add(url)
        teachers.append({"name": name, "title": title, "detail_url": url, "slug": slug})
    return teachers


def fetch_teacher_list(college_name):
    """获取某学院教师名录（带缓存）。"""
    cache = os.path.join(CACHE_DIR, f"{college_name}_list.json")
    if os.path.exists(cache):
        with open(cache, "r", encoding="utf-8") as f:
            return json.load(f)
    cfg = COLLEGES[college_name]
    base = cfg["base"]
    teachers = []
    if cfg["kind"] in ("ajax", "ajax_paged"):
        referer = cfg["list_url"].replace("active/ajax_teacher_list.html", "jiaoshiml.html") if "icisee" in base or "see" in base else base + "/faculty.html"
        if cfg["kind"] == "ajax":
            d = _post(cfg["list_url"], cfg["list_data"], referer)
            soup = BeautifulSoup(d.get("content", ""), "lxml")
            teachers = _extract_from_content(soup, cfg["href_re"], base)
        else:  # paginated
            page = 1
            while True:
                data = dict(cfg["list_data"])
                data["page"] = page
                d = _post(cfg["list_url"], data, referer)
                soup = BeautifulSoup(d.get("content", ""), "lxml")
                teachers += _extract_from_content(soup, cfg["href_re"], base)
                pg = d.get("page", "")
                # 判断是否还有下一页
                has_next = bool(re.search(rf"ajax_page\({page + 1}\)", pg))
                if not has_next or page > 200:
                    break
                page += 1
    else:  # static（人工智能学院）
        for category, page_url, href_re in cfg["list_pages"]:
            html = _get(page_url)
            soup = BeautifulSoup(html, "lxml")
            if href_re:
                for t in _extract_from_content(soup, href_re, base):
                    t["category"] = category
                    teachers.append(t)
            else:
                # 双聘/客座：无详情页，仅从列表抽取姓名/职称/邮箱
                teachers += _extract_spkz(soup, category)
    for t in teachers:
        t["college"] = college_name
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(teachers, f, ensure_ascii=False, indent=2)
    return teachers


def _extract_spkz(soup, category):
    """从人工智能学院双聘/客座列表页抽取姓名/职称/邮箱（无详情页）。"""
    items = []
    for li in soup.select("li"):
        text = li.get_text(" ", strip=True)
        if not text:
            continue
        # 姓名：2-4 个汉字的片段（取第一个）
        m = re.search(r"[\u4e00-\u9fff]{2,4}", text)
        name = m.group(0) if m else ""
        title = ""
        mt = re.search(r"职称[：:]\s*([^\s，,<]+)", text)
        if mt:
            title = mt.group(1)
        email = ""
        me = re.search(r"邮箱[：:]\s*([^\s，,<]+)", text)
        if me:
            email = me.group(1)
        if name and (title or email or "教授" in text or "研究员" in text):
            items.append({"name": name, "title": title or None, "email": email or None,
                          "category": category, "detail_url": None, "slug": None})
    # 去重
    seen, out = set(), []
    for it in items:
        if it["name"] not in seen:
            seen.add(it["name"])
            out.append(it)
    return out


def parse_teacher_detail(college_name, html):
    """按学院模板解析详情页。"""
    cfg = COLLEGES[college_name]
    kind = cfg["detail_parse"]
    if kind == "cs":
        return cs_crawler.parse_teacher_detail(html)
    if kind == "js_list":
        return _parse_js_list_detail(html)
    if kind == "see":
        return _parse_see_detail(html)
    if kind == "sai":
        return _parse_sai_detail(html)
    return {}


def _parse_js_list_detail(html):
    """自动化/集成电路学院详情页模板：.js-info + .js-list .js-item .tit/.detail .txt。"""
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style"]):
        s.decompose()
    t = {}
    info = soup.select_one(".js-info")
    if info:
        nm = info.select_one(".txt .tit p")
        if nm:
            t["name"] = _clean(nm.get_text(strip=True))
        zw = info.select_one(".txt .tit span")
        if zw:
            t["title"] = zw.get_text(strip=True)
        for p in info.select(".txt .detail p"):
            txt = p.get_text(" ", strip=True)
            if txt.startswith("电子邮件"):
                t["email"] = txt.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif txt.startswith("所在系所") or txt.startswith("所在研究所"):
                t["institute"] = txt.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif txt.startswith("个人主页"):
                a = p.find("a")
                t["personal_homepage"] = (a.get("href") if a else None) or txt.split("：", 1)[-1].strip()
    for item in soup.select(".js-list .js-item"):
        tit = item.select_one(".tit")
        if not tit:
            continue
        title = tit.get_text(strip=True)
        detail = item.select_one(".detail .txt")
        if not detail:
            continue
        if title == "研究方向":
            t["research_directions"] = detail.get_text(" ", strip=True)
        elif title in ("研究成果", "代表性论文及专著"):
            papers = []
            for li in detail.select("li"):
                ptext = li.get_text(" ", strip=True)
                if ptext and len(ptext) > 20 and not re.match(r"^(作为|著作|部分|专利|学术)", ptext):
                    papers.append({"citation": ptext, "venue": ""})
            if not papers:
                for line in detail.get_text("\n", strip=True).split("\n"):
                    line = line.strip()
                    if len(line) > 20 and not re.match(r"^(作为|著作|部分|专利|学术|\d+\.\s*$)", line):
                        papers.append({"citation": line, "venue": ""})
            t["papers_cs"] = papers
        elif title == "荣誉奖励":
            t["awards"] = [li.get_text(" ", strip=True) for li in detail.select("li") if li.get_text(strip=True)]
            if not t["awards"]:
                t["awards"] = [l.strip() for l in detail.get_text("\n", strip=True).split("\n") if l.strip()]
        elif title == "工作经历":
            # 集成电路学院「工作经历」实际为个人简介（含人才称号/博导）
            if not t.get("bio"):
                t["bio"] = detail.get_text(" ", strip=True)
    return t


def _parse_see_detail(html):
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style"]):
        s.decompose()
    t = {}
    info = soup.select_one(".js-info")
    if info:
        nm = info.select_one(".txt .tit p")
        if nm:
            t["name"] = _clean(nm.get_text(strip=True))
        zw = info.select_one(".txt .tit span")
        if zw:
            t["title"] = zw.get_text(strip=True)
        for p in info.select(".txt .detail p"):
            txt = p.get_text(" ", strip=True)
            if txt.startswith("电子邮件"):
                t["email"] = txt.split("：", 1)[-1].split(":", 1)[-1].strip()
    for item in soup.select(".js-box-item"):
        head = item.select_one(".name")
        if not head:
            continue
        title = head.get_text(strip=True)
        txt = item.select_one(".txt")
        if not txt:
            continue
        if title == "研究兴趣":
            t["research_directions"] = txt.get_text(" ", strip=True)
        elif title == "学术发表":
            papers = []
            raw = txt.get_text("\n", strip=True)
            for line in raw.split("\n"):
                line = line.strip()
                if line and len(line) > 5:
                    papers.append({"citation": line, "venue": ""})
            t["papers_cs"] = papers
        elif title == "获奖信息":
            t["awards"] = [li.get_text(" ", strip=True) for li in txt.select("li") if li.get_text(strip=True)]
    return t


def _parse_sai_detail(html):
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style"]):
        s.decompose()
    t = {}
    head = soup.select_one(".facultyInfoHead")
    if head:
        nm = head.select_one(".text .h3")
        if nm:
            t["name"] = _clean(nm.get_text(strip=True))
        for p in head.select(".text .p p"):
            txt = p.get_text(" ", strip=True)
            if txt.startswith("职称"):
                t["title"] = txt.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif txt.startswith("邮箱"):
                t["email"] = txt.split("：", 1)[-1].split(":", 1)[-1].strip()
    bottom = soup.select_one(".facultyInfoBottom")
    if bottom:
        for li in bottom.select(".li"):
            h3 = li.select_one(".h3")
            if h3 and h3.get_text(strip=True) == "个人简介":
                p = li.select_one(".p")
                if p:
                    t["bio"] = p.get_text(" ", strip=True)
    return t


def crawl_details(college_name, teachers):
    """抓取并解析某学院教师详情页（带缓存）。"""
    enriched = []
    for i, t in enumerate(teachers):
        slug = t.get("slug")
        if not t.get("detail_url"):
            enriched.append(t)
            continue
        cache = os.path.join(CACHE_DIR, f"{college_name}_{slug}.html")
        html = None
        if os.path.exists(cache):
            with open(cache, "r", encoding="utf-8") as f:
                html = f.read()
        else:
            try:
                html = _get(t["detail_url"])
            except Exception as e:
                print(f"  [skip] {t['name']} 抓取失败: {type(e).__name__}")
            if html:
                with open(cache, "w", encoding="utf-8") as f:
                    f.write(html)
            time.sleep(0.2)
        if html:
            parsed = parse_teacher_detail(college_name, html)
            t.update({k: v for k, v in parsed.items() if v})
        enriched.append(t)
        if (i + 1) % 50 == 0:
            print(f"    ... {college_name} 已抓取 {i + 1}/{len(teachers)}")
    out = os.path.join(CACHE_DIR, f"{college_name}_enriched.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    return enriched

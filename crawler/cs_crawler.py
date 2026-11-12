"""上海交通大学计算机学院（cs.sjtu.edu.cn）教师名录爬虫。

替代 faculty.sjtu.edu.cn：教师名录经 AJAX 接口 ajax_teacher_list.html 获取，
每位教师有独立详情页 /jiaoshiml/<拼音>.html，含职称、所在研究所、个人简介（研究方向/身份）、
论文发表（代表论文+会议/期刊）、获奖信息、教授课程等。URL 中的拼音 slug 可用于学术检索。

原始 HTML 缓存到 data/raw/cs/ 下，支持断点续抓。
"""
import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup

from . import config

BASE = "https://www.cs.sjtu.edu.cn"
AJAX_URL = BASE + "/active/ajax_teacher_list.html"
CACHE_DIR = os.path.join(config.RAW_DIR, "cs")
os.makedirs(CACHE_DIR, exist_ok=True)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE + "/jiaoshiml.html",
}


def _get(url, timeout=40):
    r = requests.get(url, headers=_HEADERS, timeout=timeout)
    r.encoding = r.apparent_encoding or r.encoding
    r.raise_for_status()
    return r.text


def fetch_teacher_list():
    """经 AJAX 接口获取全量教师名录，返回 {name, slug, detail_url, institute} 列表。"""
    cache = os.path.join(CACHE_DIR, "teacher_list.json")
    if os.path.exists(cache):
        with open(cache, "r", encoding="utf-8") as f:
            return json.load(f)
    r = requests.post(AJAX_URL, headers=_HEADERS, timeout=60, data={
        "page": 1, "cat_id": "20", "cat_code": "jiaoshiml",
        "type": 1, "zm": "All", "zc": "全部", "search": "",
    })
    r.raise_for_status()
    content = r.json().get("content", "")
    soup = BeautifulSoup(content, "lxml")
    teachers = []
    seen = set()
    for rc in soup.select(".rc-item"):
        institute = ""
        tit = rc.select_one(".tit .name")
        if tit:
            institute = tit.get_text(strip=True)
        # 所长/副所长 与 普通教师链接都抓
        for a in rc.select("a[href*='jiaoshiml/']"):
            href = a.get("href", "")
            name = a.get_text(strip=True)
            name = name.replace("\u3000", "").replace(" ", "")
            m = re.search(r"jiaoshiml/([^/]+)\.html", href)
            slug = m.group(1) if m else ""
            if not name or not slug:
                continue
            if slug in seen:
                continue
            seen.add(slug)
            teachers.append({
                "name": name,
                "slug": slug,
                "detail_url": href if href.startswith("http") else BASE + href,
                "institute": institute,
            })
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(teachers, f, ensure_ascii=False, indent=2)
    return teachers


def _extract_english_name(papers):
    """从论文作者列表里提取出现最频繁的「名 姓」英文名（如 Haibo Chen）。"""
    from collections import Counter
    counter = Counter()
    for p in papers or []:
        text = p.get("citation", "")
        for m in re.finditer(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b", text):
            counter[(m.group(1), m.group(2))] += 1
    if counter:
        (a, b), _ = counter.most_common(1)[0]
        return f"{a} {b}"
    return None


def parse_teacher_detail(html):
    """解析教师详情页，返回字段 dict。"""
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style"]):
        s.decompose()
    t = {}
    info = soup.select_one(".js-info")
    if info:
        nm = info.select_one(".txt .name")
        if nm:
            t["name"] = nm.get_text(strip=True).replace("\u3000", "").replace(" ", "")
        zw = info.select_one(".txt .zw")
        if zw:
            t["title"] = zw.get_text(strip=True)
        for p in info.select(".txt .dt p"):
            txt = p.get_text(" ", strip=True)
            if txt.startswith("所在研究所"):
                t["institute"] = txt.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif txt.startswith("个人主页"):
                a = p.find("a")
                if a:
                    t["personal_homepage"] = a.get("href")
    # 分节内容
    for item in soup.select(".js-dt .item"):
        head = item.select_one(".name p")
        if not head:
            continue
        title = head.get_text(strip=True)
        txt = item.select_one(".txt")
        if not txt:
            continue
        if title == "个人简介":
            t["bio"] = txt.get_text(" ", strip=True)
        elif title == "论文发表":
            papers = []
            for li in txt.select("li"):
                ptext = li.get_text(" ", strip=True)
                if ptext:
                    m = re.match(r"^\[([^\]]+)\]", ptext)
                    venue = m.group(1) if m else ""
                    papers.append({"citation": ptext, "venue": venue})
            t["papers_cs"] = papers
            t["name_pinyin"] = _extract_english_name(papers)
        elif title == "获奖信息":
            t["awards"] = [li.get_text(" ", strip=True) for li in txt.select("li") if li.get_text(strip=True)]
        elif title == "教授课程":
            t["courses_taught"] = txt.get_text(" ", strip=True)
    return t


def crawl_details(teachers):
    """抓取并解析每位教师详情页（带缓存），返回富化后的列表。"""
    enriched = []
    for i, t in enumerate(teachers):
        slug = t.get("slug")
        cache = os.path.join(CACHE_DIR, f"{slug}.html") if slug else None
        html = None
        if cache and os.path.exists(cache):
            with open(cache, "r", encoding="utf-8") as f:
                html = f.read()
        else:
            try:
                html = _get(t["detail_url"])
            except Exception as e:
                print(f"  [skip] {t['name']} 抓取失败: {type(e).__name__}")
            if html and cache:
                with open(cache, "w", encoding="utf-8") as f:
                    f.write(html)
            time.sleep(0.3)
        if html:
            parsed = parse_teacher_detail(html)
            t.update({k: v for k, v in parsed.items() if v})
        enriched.append(t)
        if (i + 1) % 50 == 0:
            print(f"  ... 已抓取 {i + 1}/{len(teachers)}")
    out = os.path.join(CACHE_DIR, "teachers_enriched.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    return enriched

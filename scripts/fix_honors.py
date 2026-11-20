# -*- coding: utf-8 -*-
"""修复荣誉条目缺失年份的问题。

部分教师页面的获奖年份与奖励文本被拆成多个 span / 纯文本，
早期合并时年份丢失，留下“年，国家杰出青年…”这类条目。
本脚本在原始详情页的“荣誉奖励/获奖信息”区块中定位奖励正文，
取正文前最近的年份补回；只替换异常条目，保留其余荣誉。
"""
import glob
import json
import os
import re
import sqlite3
import sys
import time

import requests
from bs4 import BeautifulSoup
from pypinyin import lazy_pinyin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawler import config  # noqa: E402

DB = os.path.join(ROOT, "data", "db", "mentor.db")
RAW = os.path.join(ROOT, "data", "raw")

# 与 processing/score.py 保持一致的称号白名单
CANON = {
    "院士", "杰青", "优青", "长江", "长江学者", "万人计划", "国家级高层次人才",
    "海外高层次", "国家级青年人才", "IEEE Fellow", "Fellow", "ACM Fellow",
    "CCF Fellow", "博导", "硕导", "国家级人才", "青年长江",
}


def bad_entry(text):
    """缺少年份的异常条目：以“年/年度/标点”开头，或出现“、年、”等断片。"""
    return bool(re.match(r"^[年，,、；;]", text)
                or re.search(r"(^|[，,、；;])年[，,、；;]", text))


def section_text(html):
    """提取详情页的荣誉奖励区块文本。"""
    soup = BeautifulSoup(html, "lxml")
    for item in soup.select(".js-item"):
        head = item.select_one(".tit")
        if head and ("荣誉" in head.get_text() or "获奖" in head.get_text()):
            body = item.select_one(".detail") or item
            return body.get_text("\n", strip=True)
    for item in soup.select(".js-box-item"):
        head = item.select_one(".name")
        if head and "获奖" in head.get_text():
            body = item.select_one(".txt") or item
            return body.get_text("\n", strip=True)
    for item in soup.select(".js-dt .item"):
        head = item.select_one(".name p")
        if head and "获奖" in head.get_text():
            body = item.select_one(".txt") or item
            return body.get_text("\n", strip=True)
    return ""


def normalized(text):
    """返回仅保留中英文数字的小写串及每个字符在原文中的位置。"""
    chars, positions = [], []
    for i, ch in enumerate(text or ""):
        if re.match(r"[\u4e00-\u9fffA-Za-z0-9]", ch):
            chars.append(ch.lower())
            positions.append(i)
    return "".join(chars), positions


def year_before(text, core):
    """在原文中找到奖励正文，取正文前最近的 4 位年份。"""
    haystack, positions = normalized(text)
    needle, _ = normalized(core)
    if not needle:
        return ""
    start = haystack.find(needle)
    if start < 0:
        return ""
    pos = positions[start]
    years = [m for m in re.finditer(r"(?:19|20)\d{2}\s*年?", text)
             if m.end() <= pos]
    if not years:
        return ""
    match = years[-1]
    if pos - match.end() > 80:
        return ""
    return match.group(0)[:4]


def core_of(text):
    """去掉“年，/年度/前导标点”，保留正文原有空格。"""
    text = re.sub(r"^\s*年度[，,、；;：:\s]*", "", text)
    text = re.sub(r"^\s*年[，,、；;：:\s]*", "", text)
    text = re.sub(r"^\s*[，,、；;：:\s]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def repair_entry(text, section):
    """为单条异常荣誉补回年份；找不到年份时返回空串。"""
    core = core_of(text)
    if not core:
        return ""
    # 正文前 20 字内出现年份（如“感动上海年度人物,2019年9月”）优先使用
    near = re.search(r"(?:19|20)\d{2}", core)
    if near and near.start() <= 20:
        year = near.group(0)
    else:
        year = year_before(section, core)
    if not year:
        return ""
    core = re.sub(rf"^{year}\s*年?[，,：:\s]*", "", core)
    if not core:
        return f"{year}年"
    if re.match(r"^\d{1,2}月", core):
        return f"{year}年{core}"
    return f"{year}年，{core}"


def slug_from_url(url):
    m = re.search(r"/([^/]+)\.html?$", url or "")
    return m.group(1) if m else None


def cache_path(row):
    """按学院+slug、拼音与页面内容依次定位教师原始页面。"""
    slug = slug_from_url(row["homepage_url"])
    college = row["college"] or ""
    exact = [
        os.path.join(RAW, "colleges", f"{college}_{slug}.html") if slug else "",
        os.path.join(RAW, "cs", f"{slug}.html") if slug else "",
        os.path.join(RAW, "homepages", f"{slug}.html") if slug else "",
    ]
    for path in exact:
        if path and os.path.exists(path):
            return path
    py = lazy_pinyin(row["name"] or "")
    forms = set()
    if py:
        forms.add("".join(py))
        if len(py) >= 2:
            forms.add(py[0] + "".join(py[1:]))
            forms.add("".join(py[1:]) + py[0])
    for form in forms:
        for path in glob.glob(os.path.join(RAW, "colleges", f"*{form}*.html")):
            with open(path, encoding="utf-8", errors="ignore") as f:
                head = f.read(30000)
            if row["name"] in head:
                return path
    return None


def fetch_page(url):
    if not url:
        return ""
    try:
        resp = requests.get(url, headers=config.HEADERS, timeout=30)
        resp.encoding = resp.apparent_encoding or resp.encoding
        resp.raise_for_status()
        time.sleep(0.5)
        return resp.text
    except Exception as exc:
        print(f"  [warn] {url}: {type(exc).__name__}")
        return ""


def clean_current(row, current, section):
    """只替换异常条目，保留其余荣誉，避免引入页面中的论文/新闻噪声。"""
    keep = []
    for entry in current:
        text = (entry or "").strip()
        if not text:
            continue
        if "@" in text or text == row["name"]:
            continue
        if re.fullmatch(r"\d+[.、]?\s*(?:19|20)\d{2}年?", text):
            continue
        # 多个奖励拼接成一条的长文本，交给其拆分后的独立条目处理
        if len(text) >= 60 and text.count("年") >= 2 and "、" in text:
            continue
        if not bad_entry(text):
            # 少部分旧条目本身没有“年”前缀，但正文可从页面补回年份
            if (len(text) > 8 and not re.search(r"(19|20)\d{2}", text)
                    and re.match(r"^(因|获|获得|入选|参加|指导|论文|成立|作为|被授予)", text)):
                year = year_before(section, text)
                if year:
                    keep.append(f"{year}年，{text}")
                    continue
            keep.append(text)
            continue
        fixed = repair_entry(text, section)
        if fixed:
            keep.append(fixed)
    seen, result = set(), []
    for item in keep:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name, college, honors, homepage_url FROM teachers"
    ).fetchall()

    affected = []
    for row in rows:
        honors = json.loads(row["honors"] or "[]")
        if any(bad_entry(h) for h in honors):
            affected.append(row)
    print(f"发现荣誉缺年份的教师 {len(affected)} 人")

    unresolved = []
    for row in affected:
        path = cache_path(row)
        html = open(path, encoding="utf-8", errors="ignore").read() if path else ""
        section = section_text(html) if html else ""
        if not section:
            html = fetch_page(row["homepage_url"])
            section = section_text(html) if html else ""
        current = json.loads(row["honors"] or "[]")
        fixed = clean_current(row, current, section)
        if any(bad_entry(h) for h in fixed):
            unresolved.append(row["name"])
        conn.execute("UPDATE teachers SET honors=? WHERE id=?",
                     (json.dumps(fixed, ensure_ascii=False), row["id"]))
        print(f"  {row['name']}: {len(current)} -> {len(fixed)} 条")

    conn.commit()
    conn.close()
    print(f"完成，仍有异常 {len(unresolved)} 人：{unresolved}")


if __name__ == "__main__":
    main()

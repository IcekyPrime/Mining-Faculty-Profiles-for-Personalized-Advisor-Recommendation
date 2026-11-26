# -*- coding: utf-8 -*-
"""公开学术来源工具。

只使用无需 API Key 的来源：学校/学院/教师官方主页、arXiv、Crossref，
以及 Acemap 的人工检索入口。
不接入 OpenAlex 等需要认证或配额的站点。
"""
import html as html_lib
import ipaddress
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin, urlparse

import requests

UA = "JiaWoDao-CourseProject/1.0 (course project; contact: local user)"
TIMEOUT = 4
MAX_BYTES = 600 * 1024
ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works"


def _host_allowed(host):
    """官方主页抓取只允许教育网域名。"""
    host = (host or "").lower().rstrip(".")
    return host.endswith(".edu.cn")


def _host_is_public(host):
    """避免把请求发到内网地址。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            return False
    return True


def _text_from_html(body):
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
    cleaned = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", body)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = html_lib.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (html_lib.unescape(title.group(1)).strip() if title else ""), cleaned


def fetch_official_page(url):
    """读取教师官方主页的可见文本，限制域名、跳转次数与响应大小。"""
    current = url
    for _ in range(3):
        parsed = urlparse(current)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("unsupported url")
        if not _host_allowed(parsed.hostname) or not _host_is_public(parsed.hostname):
            raise ValueError("host not allowed")

        resp = requests.get(
            current, timeout=TIMEOUT, headers={"User-Agent": UA},
            stream=True, allow_redirects=False,
        )
        if resp.is_redirect:
            current = urljoin(current, resp.headers.get("location", ""))
            continue
        resp.raise_for_status()

        chunks, size = [], 0
        for chunk in resp.iter_content(8192):
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_BYTES:
                break
        encoding = resp.encoding or resp.apparent_encoding or "utf-8"
        body = b"".join(chunks).decode(encoding, errors="ignore")
        title, text = _text_from_html(body)
        if not text:
            return None
        return {
            "type": "official",
            "title": title or parsed.hostname,
            "url": current,
            "excerpt": text[:600],
        }
    return None


def arxiv_search(term, max_results=4):
    params = {
        "search_query": f'all:"{term}"',
        "start": 0,
        "max_results": max(1, min(8, max_results)),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    resp = requests.get(ARXIV_API, params=params, timeout=TIMEOUT,
                        headers={"User-Agent": UA})
    resp.raise_for_status()
    import xml.etree.ElementTree as ET

    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.content)
    items = []
    for entry in root.findall("a:entry", ns):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        link = (entry.findtext("a:id", default="", namespaces=ns) or "").strip()
        published = entry.findtext("a:published", default="", namespaces=ns) or ""
        if not title or not link:
            continue
        items.append({
            "type": "arxiv",
            "title": re.sub(r"\s+", " ", title),
            "url": link,
            "year": published[:4],
        })
    return items


def crossref_search(term, rows=4):
    params = {
        "query.bibliographic": term,
        "rows": max(1, min(8, rows)),
        "select": "DOI,title,issued,container-title",
    }
    mailto = os.environ.get("CROSSREF_MAILTO")
    if mailto:
        params["mailto"] = mailto
    resp = requests.get(CROSSREF_API, params=params, timeout=TIMEOUT,
                        headers={"User-Agent": UA})
    resp.raise_for_status()
    data = resp.json().get("message", {})
    items = []
    for work in data.get("items", []):
        titles = work.get("title") or []
        title = titles[0] if titles else ""
        doi = work.get("DOI") or ""
        if not title or not doi:
            continue
        parts = (work.get("issued") or {}).get("date-parts") or [[None]]
        year = parts[0][0] if parts and parts[0] else None
        items.append({
            "type": "crossref",
            "title": re.sub(r"\s+", " ", title),
            "url": "https://doi.org/" + doi,
            "year": str(year) if year else "",
        })
    return items


def acemap_link(term):
    """Acemap 未提供公开查询 API，这里只返回可人工核验的检索入口。"""
    return {
        "type": "acemap",
        "title": term,
        "url": "https://www.acemap.info/search?q=" + quote(term),
        "year": "",
        "link_only": True,
    }


def gather(term, teacher=None, want_recent=False):
    """并行补充公开来源。返回 (items, notes)。

    notes 使用 (kind, value) 结构，由回答层转成对应语言的说明。
    """
    items, notes = [], []

    if term:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                "arxiv": pool.submit(arxiv_search, term),
                "crossref": pool.submit(crossref_search, term),
            }
            for name, future in futures.items():
                try:
                    items.extend(future.result(timeout=TIMEOUT + 2) or [])
                except Exception:
                    notes.append(("source_failed", name))
        items.append(acemap_link(term))

    if teacher and want_recent:
        url = teacher.get("personal_homepage") or teacher.get("homepage_url")
        if url:
            try:
                page = fetch_official_page(url)
                if page:
                    items.append(page)
                else:
                    notes.append(("official_empty", teacher.get("name") or ""))
            except Exception:
                notes.append(("official_failed", teacher.get("name") or ""))

    return items, notes

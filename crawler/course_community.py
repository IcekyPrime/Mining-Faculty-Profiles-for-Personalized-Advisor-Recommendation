"""上海交通大学选课社区（course.sjtu.plus）接入。

通过 jAccount 邮箱 + 选课社区密码登录，获取教师的新学院归属、职称、工号，
以及每位教师开设课程的平均评分（rating_score / rating_avg / rating_count）。

登录流程：GET /api/auth/csrf 取 X-CSRF-Token → POST /api/auth/login。
结果按教师名缓存到 data/raw/course_community/。
"""
import json
import os
import re

import requests

from . import config

BASE = "https://course.sjtu.plus"


def credentials():
    """从环境变量读取选课社区账号，避免把账号密码写进代码库。"""
    return (os.environ.get("COURSE_COMMUNITY_EMAIL", ""),
            os.environ.get("COURSE_COMMUNITY_PASSWORD", ""))

CACHE_DIR = os.path.join(config.RAW_DIR, "course_community")
os.makedirs(CACHE_DIR, exist_ok=True)

_session = None
_csrf = None


def _headers():
    return {
        "X-CSRF-Token": _csrf or "",
        "Content-Type": "application/json",
        "Referer": BASE + "/",
        "Origin": BASE,
    }


def login():
    global _session, _csrf
    if _session is not None:
        return
    email, password = credentials()
    if not email or not password:
        raise RuntimeError(
            "缺少选课社区账号，请先设置环境变量 "
            "COURSE_COMMUNITY_EMAIL 与 COURSE_COMMUNITY_PASSWORD"
        )
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    })
    r = s.get(f"{BASE}/api/auth/csrf", timeout=30)
    _csrf = r.headers.get("X-CSRF-Token", "")
    r = s.post(f"{BASE}/api/auth/login", json={"email": email, "password": password},
               headers=_headers(), timeout=30)
    r.raise_for_status()
    _session = s


def _get(path, params=None, retry=True):
    global _session
    login()
    r = _session.get(BASE + path, params=params, headers=_headers(), timeout=30)
    if r.status_code in (401, 403) and retry:
        _session = None
        return _get(path, params=params, retry=False)
    r.raise_for_status()
    return r.json()


def search_teacher(name):
    """按姓名检索教师，返回精确匹配或首个结果。"""
    data = _get("/api/teacher/", {"q": name, "page": 1, "page_size": 5})
    items = data.get("items") or []
    for t in items:
        if t.get("name") == name:
            return t
    return items[0] if items else None


def get_teacher_courses(teacher_id):
    data = _get(f"/api/teacher/{teacher_id}/course", {"page": 1, "page_size": 50})
    return data.get("items") or []


def enrich_teacher(teacher):
    """用选课社区补充：新学院、职称、工号、课程与评分。返回补充字段 dict。"""
    name = (teacher.get("name") or "").strip()
    if not name:
        return {}
    cache = os.path.join(CACHE_DIR, f"{name}.json")
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    try:
        t = search_teacher(name)
    except Exception as e:
        print(f"  [选课社区] {name}: 检索失败 {type(e).__name__}")
        return {}
    if not t:
        return {}
    result = {
        "course_community_id": t.get("id"),
        "teacher_code": t.get("code"),
        "college": t.get("department"),
    }
    if t.get("title") and t["title"] != "无":
        result["title"] = t["title"]
    tid = t.get("id")
    result["course_community_url"] = f"{BASE}/teacher/{tid}" if tid else None
    try:
        courses = get_teacher_courses(tid) if tid else []
    except Exception:
        courses = []
    result["courses"] = []
    for c in courses:
        rating = c.get("rating") or {}
        result["courses"].append({
            "course_name": c.get("name"),
            "course_code": c.get("code"),
            "rating_score": rating.get("score"),
            "rating_avg": rating.get("avg"),
            "rating_count": rating.get("count"),
            "last_semester": c.get("last_semester"),
            "course_url": f"{BASE}/course/{c['id']}" if c.get("id") else None,
        })
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return result

# -*- coding: utf-8 -*-
"""导出移动端离线数据。

复用桌面端 Flask 接口的返回结构，生成 android/assets/www/data.js：
    window.__MOBILE_DATA__ = { stats, insights, teachers, details }
不修改桌面端代码。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # mobile/
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PROJECT, "app"))

from app import app  # noqa: E402

OUT = os.path.join(HERE, "android", "assets", "www", "data.js")


def main():
    client = app.test_client()

    stats = client.get("/api/stats").get_json()
    insights = client.get("/api/insights").get_json()

    teachers = []
    page = 1
    while True:
        data = client.get(
            "/api/search", query_string={"page": page, "size": 100, "sort": "score"}
        ).get_json()
        teachers.extend(data.get("items") or [])
        if page * 100 >= data.get("total", 0):
            break
        page += 1

    details = {}
    for item in teachers:
        tid = item["id"]
        details[str(tid)] = client.get("/api/teacher/%d" % tid).get_json()

    payload = {
        "meta": {"total": len(teachers)},
        "stats": stats,
        "insights": insights,
        "teachers": teachers,
        "details": details,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("window.__MOBILE_DATA__=")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    size = os.path.getsize(OUT) / 1024 / 1024
    print("教师 %d 人，详情 %d 份" % (len(teachers), len(details)))
    print("输出 %s（%.2f MB）" % (OUT, size))


if __name__ == "__main__":
    main()

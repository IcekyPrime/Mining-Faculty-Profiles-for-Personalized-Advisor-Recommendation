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
PROJECT = os.path.join(HERE, "Project")
if not os.path.isdir(PROJECT):
    PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

from app import create_app  # noqa: E402

OUT = os.path.join(HERE, "android", "assets", "www", "data.js")


def main():
    client = create_app().test_client()

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
        details[str(tid)] = client.get(f"/api/teacher/{tid}").get_json()

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
    print(f"教师 {len(teachers)} 人，详情 {len(details)} 份")
    print(f"输出 {OUT}（{size:.2f} MB）")


if __name__ == "__main__":
    main()

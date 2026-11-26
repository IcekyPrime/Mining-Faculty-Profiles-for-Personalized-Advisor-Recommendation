# -*- coding: utf-8 -*-
"""校验移动端离线包与桌面库/接口 schema 一致。"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "mobile", "android", "assets", "www", "data.js")
with open(PATH, encoding="utf-8") as handle:
    raw = handle.read()
payload = json.loads(raw.split("=", 1)[1].rstrip(";\n"))
stats = payload["stats"]
insights = payload["insights"]
print("teachers", len(payload["teachers"]), "details", len(payload["details"]))
print("stats", stats)
print("insights keys", sorted(insights))
print("legacy top", len(insights.get("top") or []))
print("coverage pct", insights["coverage"][0].get("pct"))
print("teaching pct", insights["teaching"].get("pct"))
print("community", insights["communities"][0])
first = next(iter(payload["details"].values()))
print("detail keys", sorted(first)[:20])
assert len(payload["teachers"]) == 773
assert len(payload["details"]) == 773
assert insights.get("top")
assert insights["coverage"][0].get("pct") is not None
assert insights["teaching"].get("pct") is not None
assert insights["communities"][0].get("sample")
print("mobile data OK")

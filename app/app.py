# -*- coding: utf-8 -*-
"""启动入口（兼容两种运行方式）。

    python -m app.app          # 推荐：以模块方式运行
    python app/app.py          # 直接运行脚本（自动把项目根目录加入 sys.path）

应用本体在 `app/__init__.py` 的 `create_app()` 里，这里只保留兼容旧代码的
模块级 `app` 对象与开发服务器启动逻辑。
"""
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app import create_app  # noqa: E402
else:
    from . import create_app  # noqa: E402

app = create_app()


if __name__ == "__main__":
    app.run(
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=False,
        threaded=True,
    )

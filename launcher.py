# -*- coding: utf-8 -*-
"""交大导师 · 桌面应用启动器

启动内置 Flask 服务，并打开原生窗口。
"""
import os
import threading
import time
import urllib.request

import webview

from app.app import app

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/"
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")


def run_server():
    app.run(host=HOST, port=PORT, debug=False, threaded=True, use_reloader=False)


def wait_until_ready(timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(URL, timeout=0.5)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def main():
    server = threading.Thread(target=run_server, daemon=True)
    server.start()
    wait_until_ready()

    webview.create_window(
        "交大导师 · 导师选择系统",
        URL,
        width=1100,
        height=780,
        min_size=(900, 640),
    )
    webview.start(icon=ICON if os.path.exists(ICON) else None)


if __name__ == "__main__":
    main()

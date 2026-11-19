# -*- coding: utf-8 -*-
"""Wait until the local Advisor Finder server is healthy, then open the browser.

Used by run.bat. Kept ASCII-only and dependency-free on purpose.
"""
import sys
import time
import urllib.request
import webbrowser


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765/"
    health = url.rstrip("/") + "/api/health"
    for _ in range(90):
        try:
            with urllib.request.urlopen(health, timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return 0
        except Exception:
            time.sleep(0.5)
    # Server never became healthy: still open the page so the user sees the error.
    webbrowser.open(url)
    return 1


if __name__ == "__main__":
    sys.exit(main())

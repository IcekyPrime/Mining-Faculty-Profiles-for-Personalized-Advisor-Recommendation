"""移动端 AI 助手的静态接线检查。

不启动 WebView，只防止页面/原生兜底/构建脚本三处漏接。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WWW = ROOT / "mobile" / "android" / "assets" / "www"


def test_mobile_ai_page_and_assets_wired():
    html = (WWW / "index.html").read_text(encoding="utf-8")
    assert 'id="ai-sheet"' in html
    assert "js/mobile-ai.js?v=" in html
    assert "mobile.css?v=" in html
    assert "js/i18n.js?v=" in html


def test_mobile_ai_has_raw_fallback_mapping():
    java = (
        ROOT / "mobile" / "android" / "src" / "com" / "jiaowodao" / "app" / "MainActivity.java"
    ).read_text(encoding="utf-8")
    build = (ROOT / "mobile" / "build_apk.ps1").read_text(encoding="utf-8")
    assert "www/js/mobile-ai.js" in java
    assert "R.raw.web_ai" in java
    assert "web_ai" in build
    assert "--version-name 2.7" in build
    manifest = (ROOT / "mobile" / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'android:versionCode="18"' in manifest
    assert 'android:versionName="2.7"' in manifest


def test_mobile_ai_safety_and_defaults():
    js = (WWW / "js" / "mobile-ai.js").read_text(encoding="utf-8")
    assert 'DEFAULT_API_BASE = "https://api.deepseek.com/v1"' in js
    assert 'DEFAULT_API_MODEL = "deepseek-flash"' in js
    assert "safeHttpUrl" in js
    assert "MIXED_CONTENT" not in js


def test_mobile_ai_merges_v27_pinyin_and_touch_fixes():
    js = (WWW / "js" / "mobile-ai.js").read_text(encoding="utf-8")
    assert "NAME_KEYS" in js
    assert "asciiTokens" in js
    assert "aliasHit(text, s)" in js
    assert '"机器学习": ["机器学习", "machine learning", "ml"]' in js
    assert 't("ai.expand")' in js
    assert "lostpointercapture" in js
    assert "sheet.scrollTop = 0" in js
    assert "document.activeElement === el.input" in js

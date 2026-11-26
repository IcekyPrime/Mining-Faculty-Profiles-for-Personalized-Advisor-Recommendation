"""桌面 AI 对话抽屉的静态接线检查。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_chat_drawer_is_wired():
    html = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="ai-sheet"' in html
    assert 'id="ai-messages"' in html
    assert 'id="ai-form"' in html
    assert "css/chat.css?v=" in html
    assert "js/chat.js?v=" in html


def test_chat_i18n_keys_are_namespaced():
    i18n = (ROOT / "app" / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    chat_js = (ROOT / "app" / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    for key in ("chat.title", "chat.placeholder", "chat.welcome", "chat.error"):
        assert f'"{key}"' in i18n
    assert 't("ai.' not in chat_js
    assert 't("chat.' in chat_js

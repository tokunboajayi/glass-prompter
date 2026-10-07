"""Phone screen view + AI chat: API auth, privacy switch, request building, and the key never leaving the PC."""
import base64
import json

import pytest

from glassprompter import ai, config, paths, scripts
from glassprompter.server import api
from test_api import PIN, free_port, login, req

JPEG = b"\xff\xd8\xff\xe0fakejpeg\xff\xd9"


class ScreenBridge:
    def __init__(self, allowed=True, key="", model="claude-sonnet-5-5"):
        self.allowed, self.key, self.model, self.grabs = allowed, key, model, 0

    def control(self, a): pass
    def load_script(self, sid, src): pass
    def script_changed(self, sid): pass

    def screen_allowed(self):
        return self.allowed

    def screenshot(self, full=False):
        self.grabs += 1
        self.last_full = full
        return JPEG

    def ai_settings(self):
        return self.key, self.model

    def script_context(self):
        return "Demo", "# Intro\nHello everyone."


@pytest.fixture
def mk():
    made = []

    def make(**kw):
        store = scripts.ScriptStore(paths.database_path())
        s = api.RemoteServer(store, ScreenBridge(**kw), PIN, port=free_port(), bind="127.0.0.1")
        assert s.start()
        made.append((s, store))
        return s
    yield make
    for s, store in made:
        s.stop()
        store.close()


def test_screen_requires_login_and_returns_jpeg(mk):
    s = mk()
    r, _ = req(s, "GET", "/api/v1/screen.jpg", raw=True)
    assert r.status == 401
    tok = login(s)
    r, data = req(s, "GET", "/api/v1/screen.jpg", token=tok, raw=True)
    assert r.status == 200 and data == JPEG
    assert r.getheader("Content-Type") == "image/jpeg"
    assert r.getheader("Cache-Control") == "no-store"
    assert "frame-ancestors 'none'" in r.getheader("Content-Security-Policy")


def test_full_resolution_screenshot(mk):
    s = mk()
    tok = login(s)
    r, data = req(s, "GET", "/api/v1/screen.jpg?full=1", token=tok, raw=True)
    assert r.status == 200 and data == JPEG and s.bridge.last_full is True
    req(s, "GET", "/api/v1/screen.jpg", token=tok, raw=True)
    assert s.bridge.last_full is False


def test_requests_answer_anything_with_web_search():
    body = ai.build_request([{"role": "user", "content": "What's the capital of Ghana?"}], None)
    assert body["tools"][0]["name"] == "web_search" and body["max_tokens"] >= 2000
    assert "ANY question" in "".join(b["text"] for b in body["system"])
    assert "tools" not in ai.build_request([{"role": "user", "content": "x"}], None, web=False)


def test_screen_respects_privacy_switch(mk):
    s = mk(allowed=False)
    tok = login(s)
    r, d = req(s, "GET", "/api/v1/screen.jpg", token=tok)
    assert r.status == 403 and d["error"]["code"] == "screen_off"
    assert s.bridge.grabs == 0


def test_features_never_expose_the_key(mk):
    s = mk(key="sk-ant-secret-123")
    tok = login(s)
    r, d = req(s, "GET", "/api/v1/features", token=tok)
    assert r.status == 200 and d["screen"] is True and d["ai"] is True and d["ai_model"] == "claude-sonnet-5-5"
    assert b"secret" not in json.dumps(d).encode()


def test_ai_chat_without_key_is_friendly(mk):
    s = mk(key="")
    tok = login(s)
    r, d = req(s, "POST", "/api/v1/ai/chat", {"messages": [{"role": "user", "content": "hi"}]}, token=tok)
    assert r.status == 400 and d["error"]["code"] == "ai_no_key" and "Settings" in d["error"]["message"]
    r, _ = req(s, "POST", "/api/v1/ai/chat", {"messages": [{"role": "user", "content": "hi"}]})
    assert r.status == 401


def test_ai_chat_passes_screen_and_script(mk, monkeypatch):
    seen = {}

    def fake_chat(key, messages, model=None, screen_jpeg=None, script_title="", script_text="", timeout=60):
        seen.update(key=key, model=model, jpeg=screen_jpeg, title=script_title, text=script_text, n=len(messages))
        return "Say hello."
    monkeypatch.setattr(ai, "chat", fake_chat)
    s = mk(key="sk-ant-x")
    tok = login(s)
    msgs = [{"role": "user", "content": "what now?"}]
    r, d = req(s, "POST", "/api/v1/ai/chat", {"messages": msgs, "screen": True}, token=tok)
    assert r.status == 200 and d == {"reply": "Say hello.", "saw_screen": True}
    assert seen["jpeg"] == JPEG and seen["title"] == "Demo" and seen["key"] == "sk-ant-x"
    r, d = req(s, "POST", "/api/v1/ai/chat", {"messages": msgs, "screen": False}, token=tok)
    assert d["saw_screen"] is False and seen["jpeg"] is None


def test_ai_chat_does_not_grab_screen_when_switched_off(mk, monkeypatch):
    monkeypatch.setattr(ai, "chat", lambda *a, **k: "ok")
    s = mk(key="k", allowed=False)
    tok = login(s)
    r, d = req(s, "POST", "/api/v1/ai/chat", {"messages": [{"role": "user", "content": "x"}], "screen": True},
               token=tok)
    assert r.status == 200 and d["saw_screen"] is False and s.bridge.grabs == 0


def test_ai_errors_become_502_with_message(mk, monkeypatch):
    def boom(*a, **k):
        raise ai.AIError("The API key was rejected. Check it in Settings > AI.")
    monkeypatch.setattr(ai, "chat", boom)
    s = mk(key="bad")
    tok = login(s)
    r, d = req(s, "POST", "/api/v1/ai/chat", {"messages": [{"role": "user", "content": "x"}]}, token=tok)
    assert r.status == 502 and "rejected" in d["error"]["message"]


def test_ai_chat_validates_body(mk):
    s = mk(key="k")
    tok = login(s)
    r, d = req(s, "POST", "/api/v1/ai/chat", {"messages": "nope"}, token=tok)
    assert r.status == 400


# ------------------------------------------------------------------ ai module
def test_clean_merges_and_trims():
    msgs = [{"role": "assistant", "content": "hi"}, {"role": "user", "content": "a"},
            {"role": "user", "content": "b"}, {"role": "system", "content": "ignore me"},
            {"role": "assistant", "content": " "}]
    assert ai._clean(msgs) == [{"role": "user", "content": "a\n\nb"}]
    with pytest.raises(ai.AIError):
        ai._clean([{"role": "assistant", "content": "only me"}])
    long = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(41)]
    assert len(ai._clean(long)) <= ai.MAX_TURNS


def test_build_request_adds_image_and_script():
    body = ai.build_request([{"role": "user", "content": "help"}], "claude-haiku-4-5-20251001",
                            screen_jpeg=JPEG, script_title="Pitch", script_text="Hello world")
    assert body["model"] == "claude-haiku-4-5-20251001"
    system = "".join(b["text"] for b in body["system"])
    assert "Pitch" in system and "Hello world" in system
    assert body["system"][-1]["cache_control"] == {"type": "ephemeral"}      # prompt caching saves tokens
    content = body["messages"][-1]["content"]
    assert content[0]["type"] == "image" and base64.b64decode(content[0]["source"]["data"]) == JPEG
    assert content[0]["source"]["media_type"] == "image/jpeg" and content[1]["text"].endswith("help")
    plain = ai.build_request([{"role": "user", "content": "help"}], None)
    assert plain["messages"][-1]["content"] == "help" and plain["model"] in ai.MODELS


def test_chat_without_key_raises_before_network():
    with pytest.raises(ai.AIError, match="API key"):
        ai.chat("", [{"role": "user", "content": "x"}])


def test_settings_defaults_and_validation():
    s = config.validate(config.Settings(phone_screen="yes", ai_model=None, ai_provider="nonsense", ai_max_tokens=10**9))
    assert isinstance(s.phone_screen, bool) and s.ai_model == ""
    assert s.ai_provider == "auto" and s.ai_max_tokens == 64000
    assert config.Settings().phone_screen is True and config.Settings().ai_model == ""
    assert not hasattr(config.Settings(), "ai_key")                  # the key never goes in settings.json


def test_key_file_roundtrip_and_env_override(monkeypatch):
    import os
    assert ai.load_key() == ""
    ai.save_key("  sk-ant-test  ")
    assert ai.load_key() == "sk-ant-test" and os.path.basename(ai.key_path()) == "ai.key"
    c = config.Config(); c.load(); c.save()
    for name in os.listdir(paths.data_dir()):
        if name != "ai.key" and os.path.isfile(os.path.join(paths.data_dir(), name)):
            assert b"sk-ant-test" not in open(os.path.join(paths.data_dir(), name), "rb").read()
    monkeypatch.setenv(ai.ENV_KEY, "sk-env")
    assert ai.load_key() == "sk-env"
    monkeypatch.delenv(ai.ENV_KEY)
    ai.save_key("")
    assert ai.load_key() == "" and not os.path.exists(ai.key_path())


def test_every_platform_can_hide_all_windows():
    from glassprompter import platform as native
    assert callable(native.exclude_all_windows)
    assert native.exclude_all_windows(()) == 0          # headless test run: nothing to hide
    import glassprompter.app as gpapp
    assert hasattr(gpapp.Controller, "guard_capture") and hasattr(gpapp.Controller, "eventFilter")


def test_clean_key_repairs_copy_damage():
    assert ai.clean_key(" sk-ant-abc\n def \t") == "sk-ant-abcdef"
    assert ai.clean_key('"sk-ant-x"') == "sk-ant-x"
    ai.save_key("sk-ant-one\ntwo ")
    assert ai.load_key() == "sk-ant-onetwo"


def test_check_key_rejects_obvious_mistakes_offline():
    assert ai.check_key("")[0] is False
    ok, msg = ai.check_key("abc", provider="custom", base_url="")
    assert ok is False and "server URL" in msg


def test_dialog_stacking_api_exists_on_every_platform():
    from glassprompter import platform as native
    assert callable(native.lower_for_dialogs) and callable(native.prepare_window)
    import inspect
    assert "above_prompter" in inspect.signature(native.prepare_window).parameters


def test_c_key_needs_two_presses_to_reveal(monkeypatch):
    import glassprompter.ui.prompter as pm

    class Fake:
        _reveal_armed = 0
        toasts = []

        def __init__(self):
            self.cfg = type("C", (), {"hide_from_capture": True})()
            self.toggled = 0

        def toast(self, msg, *a):
            self.toasts.append(msg)

        def toggle_capture(self):
            self.toggled += 1
            self.cfg.hide_from_capture = not self.cfg.hide_from_capture
    f = Fake()
    pm.Prompter.key_toggle_capture(f)
    assert f.toggled == 0 and "again" in f.toasts[-1]          # first press only warns
    pm.Prompter.key_toggle_capture(f)
    assert f.toggled == 1 and f.cfg.hide_from_capture is False  # second press reveals
    pm.Prompter.key_toggle_capture(f)
    assert f.toggled == 2 and f.cfg.hide_from_capture is True   # hiding again is a single press



# ------------------------------------------------------------------ any AI provider
def test_detects_provider_from_key():
    cases = {"sk-ant-api03-x": "anthropic", "sk-or-v1-x": "openrouter", "sk-proj-abc": "openai", "sk-abc": "openai",
             "AIzaSyX": "gemini", "xai-abc": "xai", "gsk_abc": "groq", "pplx-abc": "perplexity", "weird": None}
    for key, want in cases.items():
        assert ai.detect_provider(key) == want, key
    assert ai.resolve("auto", "weird")[0] == "openai"                 # unknown keys: OpenAI-compatible
    assert ai.resolve("ollama", "", "http://pc:11434/v1/")[2] == "http://pc:11434/v1"
    with pytest.raises(ai.AIError):
        ai.resolve("custom", "k", "")


def test_ranks_full_size_stable_newest_first():
    ids = ["gpt-4o-mini", "gpt-5", "gpt-6-preview", "gpt-6", "gpt-4o"]
    created = {"gpt-4o-mini": 3, "gpt-5": 5, "gpt-6-preview": 7, "gpt-6": 6, "gpt-4o": 2}
    assert ai._rank("openai", ids, created)[0] == "gpt-6"
    g = ai._rank("gemini", ["gemini-3.7-flash", "gemini-3.8-flash-lite", "gemini-3.8-flash", "gemini-3.5-pro"], {})
    assert g[0] == "gemini-3.5-pro" and g[-1] == "gemini-3.8-flash-lite"
    a = ai._rank("anthropic", ["claude-haiku-4-5", "claude-opus-5-5", "claude-sonnet-5-5"],
                 {"claude-sonnet-5-5": "2026-08-01T00:00:00Z"})
    assert a[0] == "claude-sonnet-5-5"


def test_openai_and_gemini_bodies_carry_the_screenshot():
    msgs = [{"role": "user", "content": "what is this?"}]
    b = ai._openai_body("openai", "gpt-x", msgs, JPEG, "T", "script", 9000)
    assert b["messages"][0]["role"] == "system" and b["max_completion_tokens"] == 9000
    parts = b["messages"][-1]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "max_tokens" in ai._openai_body("xai", "grok", msgs, None, "", "", 500)
    g = ai._gemini_body(msgs, JPEG, "", "", 7000, True)
    assert g["contents"][-1]["parts"][0]["inline_data"]["mime_type"] == "image/jpeg"
    assert g["generationConfig"]["maxOutputTokens"] == 7000 and g["tools"] == [{"google_search": {}}]


class _HTTPErr(Exception):
    pass


def _http_error(code, msg):
    import io
    import urllib.error
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(json.dumps({"error": {"message": msg}}).encode()))


def test_chat_adapts_to_text_only_models_and_smaller_limits(monkeypatch):
    calls = []

    def fake_http(url, body=None, headers=None, timeout=30):
        calls.append(body)
        if len(calls) == 1:
            raise _http_error(400, "This model does not support image input")
        if len(calls) == 2:
            raise _http_error(400, "max_tokens is too large: 16000. This model supports at most 8192")
        return {"choices": [{"message": {"content": "Answer."}}]}
    monkeypatch.setattr(ai, "_http", fake_http)
    out = ai.chat("sk-abc", [{"role": "user", "content": "hi"}], "some-model", JPEG, provider="deepseek")
    assert out.endswith("Answer.") and "can't see images" in out
    assert isinstance(calls[0]["messages"][-1]["content"], list) and isinstance(calls[1]["messages"][-1]["content"], str)
    assert calls[2]["max_tokens"] == 8000                               # halved after the limit error
    assert calls[0]["messages"][0]["role"] == "system"


def test_chat_gemini_and_anthropic_parse_answers(monkeypatch):
    monkeypatch.setattr(ai, "_http", lambda url, body=None, headers=None, timeout=30: (
        {"candidates": [{"content": {"parts": [{"text": "G"}]}}]} if "generateContent" in url else
        {"content": [{"type": "text", "text": "C"}], "stop_reason": "end_turn"}))
    assert ai.chat("AIzaX", [{"role": "user", "content": "q"}], "gemini-x") == "G"
    assert ai.chat("sk-ant-x", [{"role": "user", "content": "q"}], "claude-x") == "C"


def test_rejected_key_message_names_the_provider(monkeypatch):
    def boom(*a, **k):
        raise _http_error(401, "invalid key")
    monkeypatch.setattr(ai, "_http", boom)
    with pytest.raises(ai.AIError, match="OpenAI"):
        ai.chat("sk-proj-abc", [{"role": "user", "content": "q"}], "gpt-x")


def test_model_is_chosen_automatically(monkeypatch):
    ai._cache.clear()
    monkeypatch.setattr(ai, "_http", lambda url, body=None, headers=None, timeout=30: {
        "data": [{"id": "gpt-old", "created": 1}, {"id": "gpt-new", "created": 9}, {"id": "whisper-1", "created": 99},
                 {"id": "gpt-new-mini", "created": 10}]})
    assert ai.pick_model("openai", "sk-abc") == "gpt-new"
    assert ai.pick_model("openrouter", "sk-or-x") == "openrouter/auto"
    assert ai.pick_model("openai", "sk-abc", "claude-sonnet-5-5") == "gpt-new"   # old Claude default ignored
    assert ai.pick_model("openai", "sk-abc", "my-model") == "my-model"


def test_api_passes_provider_settings_through(mk, monkeypatch):
    seen = {}

    def fake_chat(key, messages, model=None, screen_jpeg=None, script_title="", script_text="", **kw):
        seen.update(kw, key=key, model=model)
        return "ok"
    monkeypatch.setattr(ai, "chat", fake_chat)
    s = mk(key="AIzaX")
    s.bridge.ai_config = lambda: {"key": "AIzaX", "provider": "gemini", "model": "", "base_url": "",
                                  "max_tokens": 32000}
    tok = login(s)
    r, d = req(s, "GET", "/api/v1/features", token=tok)
    assert d["ai"] is True and d["ai_provider"] == "Google Gemini" and "AIza" not in json.dumps(d)
    r, d = req(s, "POST", "/api/v1/ai/chat", {"messages": [{"role": "user", "content": "x"}]}, token=tok)
    assert r.status == 200 and seen["provider"] == "gemini" and seen["max_tokens"] == 32000


def test_blank_capture_is_detected():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QImage
    from glassprompter.app import _looks_blank
    flat = QImage(200, 100, QImage.Format.Format_RGB32)
    flat.fill(QColor(128, 128, 128))
    assert _looks_blank(flat)
    busy = QImage(200, 100, QImage.Format.Format_RGB32)
    for x in range(200):
        for y in range(100):
            busy.setPixel(x, y, QColor((x * 7) % 256, (y * 13) % 256, (x * y) % 256).rgb())
    assert not _looks_blank(busy)


def test_saved_model_from_another_provider_is_ignored(monkeypatch):
    ai._cache.clear()
    monkeypatch.setattr(ai, "_http", lambda url, body=None, headers=None, timeout=30: {
        "models": [{"name": "models/gemini-9-pro", "supportedGenerationMethods": ["generateContent"]}],
        "data": [{"id": "claude-sonnet-9", "created_at": "2026-01-01T00:00:00Z"}]})
    assert ai.pick_model("gemini", "AIzaX", "claude-sonnet-5-5") != "claude-sonnet-5-5"
    assert ai.pick_model("anthropic", "sk-ant-x", "gpt-5") != "gpt-5"
    assert ai.pick_model("deepseek", "sk-x", "grok-4") == "deepseek-chat"
    assert ai.pick_model("openrouter", "sk-or-x", "anthropic/claude-sonnet-5") == "anthropic/claude-sonnet-5"
    assert ai.pick_model("gemini", "AIzaX", "gemini-custom") == "gemini-custom"
    assert ai.pick_model("openai", "sk-x", "ft:my-tuned") == "ft:my-tuned"


def test_retired_default_model_falls_back_to_live_list(monkeypatch):
    ai._cache.clear()
    calls = []

    def fake_http(url, body=None, headers=None, timeout=30):
        if url.endswith("/models"):
            return {"data": [{"id": "deepseek-v9", "created": 9}]}
        calls.append(body["model"])
        if body["model"] == "deepseek-chat":
            raise _http_error(400, "Model Not Exist: the model deepseek-chat does not exist")
        return {"choices": [{"message": {"content": "ok"}}]}
    monkeypatch.setattr(ai, "_http", fake_http)
    assert ai.chat("sk-x", [{"role": "user", "content": "q"}], provider="deepseek") == "ok"
    assert calls == ["deepseek-chat", "deepseek-v9"]


def test_users_own_model_is_not_swapped_silently(monkeypatch):
    def fake_http(url, body=None, headers=None, timeout=30):
        raise _http_error(404, "The model my-model does not exist")
    monkeypatch.setattr(ai, "_http", fake_http)
    with pytest.raises(ai.AIError):
        ai.chat("sk-x", [{"role": "user", "content": "q"}], "my-model", provider="deepseek")


def _png(color=None):
    from PySide6.QtCore import QBuffer
    from PySide6.QtGui import QColor, QImage
    img = QImage(320, 200, QImage.Format.Format_RGB32)
    if color:
        img.fill(QColor(*color))
    else:
        for x in range(320):
            for y in range(200):
                img.setPixel(x, y, QColor((x * 7) % 256, (y * 13) % 256, (x * y) % 256).rgb())
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


@pytest.fixture
def mac(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from glassprompter import app as gapp
    from glassprompter.platform import macos
    state = {"allowed": True, "png": _png(), "asked": 0, "rect": None}
    monkeypatch.setattr(gapp.native, "OS", "macos")
    monkeypatch.setattr(gapp.native, "screen_capture_allowed", lambda: state["allowed"], raising=False)
    monkeypatch.setattr(gapp.native, "request_screen_capture",
                        lambda: state.__setitem__("asked", state["asked"] + 1), raising=False)
    monkeypatch.setattr(gapp.native, "grab_screen_png",
                        lambda rect: (state.__setitem__("rect", rect), state["png"])[1], raising=False)
    monkeypatch.setattr(gapp.native, "SCREEN_PERMISSION_MSG", macos.SCREEN_PERMISSION_MSG, raising=False)
    monkeypatch.setattr(gapp.native, "SCREEN_BLANK_MSG", macos.SCREEN_BLANK_MSG, raising=False)
    return gapp, state


def test_mac_capture_uses_screencapture(mac):
    gapp, state = mac
    img = gapp.capture_image(rect=(0, 0, 320, 200))
    assert img.width() == 320 and state["rect"] == (0, 0, 320, 200) and state["asked"] == 0
    assert gapp.encode_jpeg(img, 1280, 80)[:2] == b"\xff\xd8"


def test_mac_capture_without_permission_asks(mac):
    gapp, state = mac
    state["allowed"] = False
    with pytest.raises(RuntimeError, match="Screen & System Audio Recording"):
        gapp.capture_image(rect=(0, 0, 320, 200))
    assert state["asked"] == 1


def test_mac_gray_capture_explains_the_fix(mac):
    gapp, state = mac
    state["png"] = _png((128, 128, 128))
    with pytest.raises(RuntimeError, match="off and on again"):
        gapp.capture_image(rect=(0, 0, 320, 200))
    state["png"] = b""
    with pytest.raises(RuntimeError):
        gapp.capture_image(rect=(0, 0, 320, 200))

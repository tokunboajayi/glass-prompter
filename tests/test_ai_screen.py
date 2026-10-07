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
    assert "ANY question" in body["system"]
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
    assert r.status == 200 and d == {"screen": True, "ai": True, "ai_model": "claude-sonnet-5-5"}
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
    assert "Pitch" in body["system"] and "Hello world" in body["system"]
    content = body["messages"][-1]["content"]
    assert content[0]["type"] == "image" and base64.b64decode(content[0]["source"]["data"]) == JPEG
    assert content[0]["source"]["media_type"] == "image/jpeg" and content[1]["text"].endswith("help")
    plain = ai.build_request([{"role": "user", "content": "help"}], None)
    assert plain["messages"][-1]["content"] == "help" and plain["model"] in ai.MODELS


def test_chat_without_key_raises_before_network():
    with pytest.raises(ai.AIError, match="API key"):
        ai.chat("", [{"role": "user", "content": "x"}])


def test_settings_defaults_and_validation():
    s = config.validate(config.Settings(phone_screen="yes", ai_model=None))
    assert isinstance(s.phone_screen, bool) and s.ai_model == config.Settings().ai_model
    assert config.Settings().phone_screen is True and config.Settings().ai_model in ai.MODELS
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
    ok, msg = ai.check_key("hello")
    assert ok is False and "sk-ant-" in msg


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

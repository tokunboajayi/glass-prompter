import base64
import hashlib
import json
import threading
import time
import urllib.parse
import urllib.request

import pytest

from glassprompter import ai, signin


def _jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return enc({"alg": "RS256", "typ": "JWT"}) + "." + enc(claims) + ".sig"


def _browser(fill):
    """A fake browser: reads the authorize URL, then calls the app's local callback like the real redirect."""
    seen = {}

    def open_url(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        seen.clear()
        seen.update(q)
        callback = q.get("callback_url") or q.get("redirect_uri")
        params = fill(q)

        def hit():
            time.sleep(0.2)
            urllib.request.urlopen(callback + "?" + urllib.parse.urlencode(params), timeout=5).read()
        threading.Thread(target=hit, daemon=True).start()
        return True
    return open_url, seen


def test_pkce_challenge_is_s256_of_the_verifier():
    v, c = signin.pkce_pair()
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    assert 43 <= len(v) <= 128


def test_openrouter_sign_in_exchanges_the_code_for_a_key(monkeypatch):
    sent = {}

    def fake_request(url, data=None, headers=None, form=False, timeout=30):
        sent.update(url=url, data=data)
        return 200, {"key": "sk-or-v1-test"}
    monkeypatch.setattr(signin, "_request", fake_request)
    browser, seen = _browser(lambda q: {"code": "abc123", "state": q["state"]})
    key = signin.openrouter_sign_in(open_browser=browser, timeout=10)
    assert key == "sk-or-v1-test"
    assert seen["callback_url"].startswith("http://localhost:") and seen["code_challenge_method"] == "S256"
    assert sent["url"] == signin.OPENROUTER_EXCHANGE and sent["data"]["code"] == "abc123"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(sent["data"]["code_verifier"].encode()).digest())
    assert challenge.decode().rstrip("=") == seen["code_challenge"]       # the verifier matches what we sent


def test_callback_with_the_wrong_state_is_ignored(monkeypatch):
    monkeypatch.setattr(signin, "_request", lambda *a, **k: (200, {"key": "x"}))

    def bad(url):
        cb = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["callback_url"]

        def hit():
            time.sleep(0.2)
            try:
                urllib.request.urlopen(cb + "?code=evil&state=forged", timeout=5).read()
            except Exception:
                pass
        threading.Thread(target=hit, daemon=True).start()
        return True
    with pytest.raises(signin.SignInError, match="timed out"):
        signin.openrouter_sign_in(open_browser=bad, timeout=1.5)


def _chatgpt_server(monkeypatch, scope=signin.CHATGPT_SCOPES, client_id="app_123"):
    monkeypatch.setattr(signin, "_discovery", {
        "issuer": signin.CHATGPT_ISSUER, "authorization_endpoint": signin.CHATGPT_ISSUER + "/authorize",
        "token_endpoint": signin.CHATGPT_ISSUER + "/token", "revocation_endpoint": signin.CHATGPT_ISSUER + "/revoke"})
    calls, nonce = [], {}

    def fake_request(url, data=None, headers=None, form=False, timeout=30):
        calls.append((url, dict(data or {})))
        if url.endswith("/revoke"):
            return 200, {}
        claims = {"iss": signin.CHATGPT_ISSUER, "aud": client_id, "sub": "user-1", "email": "sam@example.com",
                  "exp": time.time() + 3600, "iat": time.time()}
        if data.get("grant_type") == "authorization_code":
            claims["nonce"] = nonce["value"]
        return 200, {"access_token": "at-%d" % len(calls), "refresh_token": "rt-%d" % len(calls),
                     "token_type": "Bearer", "expires_in": 3600, "scope": scope, "id_token": _jwt(claims)}
    monkeypatch.setattr(signin, "_request", fake_request)

    def fill(q):
        nonce["value"] = q["nonce"]
        return {"code": "code-1", "state": q["state"], "client_id": client_id}
    browser, seen = _browser(fill)
    return browser, seen, calls


def test_chatgpt_sign_in_registers_the_app_and_keeps_a_renewable_plan_session(monkeypatch):
    browser, seen, calls = _chatgpt_server(monkeypatch)
    s = signin.chatgpt_sign_in(open_browser=browser, timeout=10)
    assert seen["client_id"] == "dynamic_agent_client" and seen["agent_name_hint"] == "Glass Prompter"
    assert seen["redirect_uri"].startswith("http://127.0.0.1:") and seen["redirect_uri"].endswith("/auth/callback")
    assert "chatgpt.tokens.use.direct" in seen["scope"].split() and seen["resource"] == signin.CHATGPT_RESOURCE
    exchange = calls[0][1]
    assert exchange["grant_type"] == "authorization_code" and exchange["client_id"] == "app_123"
    assert exchange["redirect_uri"] == seen["redirect_uri"]
    assert s["client_id"] == "app_123" and signin.chatgpt_connected() and signin.chatgpt_account() == "sam@example.com"
    assert ai.is_ready("chatgpt")
    assert signin.chatgpt_access_token() == s["access_token"]              # still fresh: no network call
    assert len(calls) == 1


def test_chatgpt_refreshes_an_expiring_token_and_signs_out(monkeypatch):
    browser, _, calls = _chatgpt_server(monkeypatch)
    signin.chatgpt_sign_in(open_browser=browser, timeout=10)
    s = signin.load_session()
    s["expires_at"] = time.time() + 10                                     # about to expire
    signin.save_session(s)
    token = signin.chatgpt_access_token()
    assert calls[-1][1]["grant_type"] == "refresh_token" and token == signin.load_session()["access_token"]
    signin.chatgpt_sign_out()
    assert not signin.chatgpt_connected() and not ai.is_ready("chatgpt")
    assert calls[-1][0].endswith("/revoke") and signin.load_session()["client_id"] == "app_123"   # registration kept


def test_second_sign_in_reuses_the_registration(monkeypatch):
    browser, seen, _ = _chatgpt_server(monkeypatch)
    signin.chatgpt_sign_in(open_browser=browser, timeout=10)
    signin.chatgpt_sign_in(open_browser=browser, timeout=10)
    assert seen["client_id"] == "app_123" and "agent_name_hint" not in seen


def test_chatgpt_sign_in_without_plan_permission_is_refused(monkeypatch):
    browser, _, _ = _chatgpt_server(monkeypatch, scope="openid profile email offline_access")
    with pytest.raises(signin.SignInError, match="Use your ChatGPT plan"):
        signin.chatgpt_sign_in(open_browser=browser, timeout=10)
    assert not signin.chatgpt_connected()


def test_id_token_claims_are_checked():
    good = {"iss": signin.CHATGPT_ISSUER, "aud": "app", "sub": "u", "exp": time.time() + 60, "nonce": "n"}
    assert signin.check_id_token(_jwt(good), "app", "n")["sub"] == "u"
    for bad in ({"iss": "https://evil.example"}, {"aud": "other"}, {"nonce": "x"}, {"exp": time.time() - 60},
                {"sub": ""}):
        with pytest.raises(signin.SignInError):
            signin.check_id_token(_jwt(dict(good, **bad)), "app", "n")


def test_chatgpt_requests_follow_the_plan_rules():
    body = ai.chatgpt_body("gpt-x", [{"role": "user", "content": "what should I say?"}], b"\xff\xd8jpeg",
                           context="Live transcript")
    assert body["store"] is False and body["stream"] is True and "Live transcript" in body["instructions"]
    assert not {"max_output_tokens", "temperature", "tools", "system"} & set(body)
    assert all(m["role"] in ("user", "assistant") for m in body["input"])
    parts = body["input"][-1]["content"]
    assert parts[0]["type"] == "input_text" and parts[1]["image_url"].startswith("data:image/jpeg;base64,")


class _FakeStream:
    def __init__(self, events):
        self.lines = [("data: " + json.dumps(e) + "\n").encode() for e in events]

    def __enter__(self):
        return iter(self.lines)

    def __exit__(self, *a):
        return False


def test_chatgpt_stream_collects_text_and_maps_plan_errors(monkeypatch):
    monkeypatch.setattr(ai, "_chatgpt_token", lambda: "at")
    monkeypatch.setattr(ai, "_chatgpt_open", lambda req, timeout: _FakeStream([
        {"type": "response.output_text.delta", "delta": "It's $49 "},
        {"type": "response.output_text.delta", "delta": "per user."}, {"type": "response.completed"}]))
    assert ai._chatgpt_stream("https://api.openai.com/v1", {}, 5) == "It's $49 per user."
    code, msg = ai._chatgpt_error(429, json.dumps({"error": {"code": "subscription_sharing_usage_limit_exceeded"}}))
    assert code == "subscription_sharing_usage_limit_exceeded" and "usage limit" in msg
    code, msg = ai._chatgpt_error(403, json.dumps({"detail": {"code": "subscription_sharing_v2_user_not_eligible"}}))
    assert "Plus or Pro" in msg


def test_ready_rules():
    assert ai.is_ready("ollama") and not ai.is_ready("anthropic", "") and ai.is_ready("anthropic", "sk-ant-x")
    assert not ai.is_ready("chatgpt")

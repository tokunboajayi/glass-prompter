"""End-to-end tests of the remote API against a real server on a free local port."""
import http.client
import io
import json
import socket
import threading
import time
import zipfile

import pytest

from glassprompter import paths, scripts
from glassprompter.server import api

PIN = "246810"


class FakeBridge:
    def __init__(self):
        self.calls = []

    def control(self, action):
        self.calls.append(("control", action))

    def load_script(self, sid, source):
        self.calls.append(("load", sid, source))

    def script_changed(self, sid):
        self.calls.append(("changed", sid))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def srv():
    store = scripts.ScriptStore(paths.database_path())
    bridge = FakeBridge()
    server = api.RemoteServer(store, bridge, PIN, port=free_port(), bind="127.0.0.1")
    assert server.start()
    server.publish_state({"playing": False, "wpm": 140})
    yield server
    server.stop()
    store.close()


def req(server, method, path, body=None, headers=None, token=None, raw=False):
    h = {"Host": "127.0.0.1:%d" % server.port}
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = "Bearer " + token
    h.update(headers or {})
    c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    if raw:
        return r, data
    try:
        return r, json.loads(data or b"{}")
    except ValueError:
        return r, data


def login(server, ip_note=""):
    r, d = req(server, "POST", "/api/v1/session", {"pin": PIN})
    assert r.status == 200, d
    return d["token"]


# ------------------------------------------------------------------ basics & headers
def test_health_is_public_and_has_security_headers(srv):
    r, d = req(srv, "GET", "/api/v1/health")
    assert r.status == 200 and d["ok"] is True
    assert "default-src 'none'" in r.getheader("Content-Security-Policy")
    assert r.getheader("X-Content-Type-Options") == "nosniff"
    assert r.getheader("X-Frame-Options") == "DENY"
    assert r.getheader("Cache-Control") == "no-store"


def test_static_page_served(srv):
    r, body = req(srv, "GET", "/", raw=True)
    assert r.status == 200 and b"Glass Prompter Remote" in body
    r, body = req(srv, "GET", "/app.js", raw=True)
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/javascript")


def test_path_traversal_and_unknown_paths_404(srv):
    for p in ("/../../windows/win.ini", "/static/../api.py", "/settings.json", "/app.js/../../x"):
        r, _ = req(srv, "GET", p)
        assert r.status == 404, p


def test_dns_rebinding_host_rejected(srv):
    r, _ = req(srv, "GET", "/api/v1/health", headers={"Host": "evil.example.com"})
    assert r.status == 421
    r, _ = req(srv, "GET", "/api/v1/health", headers={"Host": "localhost:%d" % srv.port})
    assert r.status == 200


def test_options_and_wrong_method(srv):
    r, _ = req(srv, "OPTIONS", "/api/v1/state")
    assert r.status == 405 and r.getheader("Access-Control-Allow-Origin") is None
    r, _ = req(srv, "PUT", "/api/v1/health")
    assert r.status == 405


# ------------------------------------------------------------------ auth
def test_data_endpoints_require_session(srv):
    for m, p in (("GET", "/api/v1/state"), ("GET", "/api/v1/scripts"), ("POST", "/api/v1/control")):
        r, d = req(srv, m, p, {"action": "play"} if m == "POST" else None)
        assert r.status == 401, p
    assert srv.bridge.calls == []


def test_pin_is_not_accepted_as_query_param(srv):
    r, _ = req(srv, "GET", "/api/v1/state?k=" + PIN)
    assert r.status == 401


def test_login_sets_strict_httponly_cookie(srv):
    r, d = req(srv, "POST", "/api/v1/session", {"pin": PIN})
    assert r.status == 200 and d["token"]
    cookie = r.getheader("Set-Cookie")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    tok = cookie.split(";")[0].split("=", 1)[1]
    r, d = req(srv, "GET", "/api/v1/state", headers={"Cookie": "gp_session=" + tok})
    assert r.status == 200 and d["wpm"] == 140


def test_wrong_pin_lockout(srv):
    for _ in range(api.FAIL_LIMIT):
        r, d = req(srv, "POST", "/api/v1/session", {"pin": "000000"})
        assert r.status == 401
    r, d = req(srv, "POST", "/api/v1/session", {"pin": PIN})     # even the right PIN is refused now
    assert r.status == 429 and int(r.getheader("Retry-After")) > 0


def test_session_requires_json_content_type(srv):
    r, _ = req(srv, "POST", "/api/v1/session", body=b"pin=" + PIN.encode(),
               headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status == 415


def test_new_pin_revokes_sessions(srv):
    tok = login(srv)
    srv.set_pin("135790")
    r, _ = req(srv, "GET", "/api/v1/state", token=tok)
    assert r.status == 401


def test_rate_limiter_unit():
    now = [1000.0]
    rl = api.RateLimiter(window=60, limit=3, lockout=30, clock=lambda: now[0])
    for _ in range(3):
        assert rl.check("ip") == 0
        rl.fail("ip")
    assert rl.check("ip") > 0
    now[0] += 31
    assert rl.check("ip") == 0


def test_host_allowed_unit():
    assert api.host_allowed("192.168.1.5:8765")
    assert api.host_allowed("[::1]:8765")
    assert api.host_allowed("localhost")
    assert not api.host_allowed("attacker.com")
    assert not api.host_allowed("")


# ------------------------------------------------------------------ control & scripts
def test_control(srv):
    tok = login(srv)
    r, _ = req(srv, "POST", "/api/v1/control", {"action": "play"}, token=tok)
    assert r.status == 200 and srv.bridge.calls[-1] == ("control", "play")
    r, d = req(srv, "POST", "/api/v1/control", {"action": "rm -rf"}, token=tok)
    assert r.status == 400 and d["error"]["code"] == "bad_action"


def test_script_crud_flow(srv):
    tok = login(srv)
    r, s = req(srv, "POST", "/api/v1/scripts", {"title": "Pitch", "body": "Hello investors", "load": True}, token=tok)
    assert r.status == 201 and s["title"] == "Pitch"
    assert ("load", s["id"], "your phone") in srv.bridge.calls
    r, d = req(srv, "GET", "/api/v1/scripts?q=invest", token=tok)
    assert [x["id"] for x in d["scripts"]] == [s["id"]]
    r, s2 = req(srv, "PUT", "/api/v1/scripts/%d" % s["id"], {"body": "Hello again"}, token=tok)
    assert r.status == 200 and s2["body"] == "Hello again" and s2["title"] == "Pitch"
    r, _ = req(srv, "POST", "/api/v1/scripts/%d/load" % s["id"], token=tok)
    assert r.status == 200
    r, _ = req(srv, "DELETE", "/api/v1/scripts/%d" % s["id"], token=tok)
    assert r.status == 200
    r, _ = req(srv, "GET", "/api/v1/scripts/%d" % s["id"], token=tok)
    assert r.status == 404


def test_script_validation_errors(srv):
    tok = login(srv)
    r, d = req(srv, "POST", "/api/v1/scripts", {"body": "   "}, token=tok)
    assert r.status == 400 and d["error"]["code"] == "invalid"
    r, d = req(srv, "POST", "/api/v1/scripts", body=b"{bad json", token=tok,
               headers={"Content-Type": "application/json"})
    assert r.status == 400 and d["error"]["code"] == "bad_json"


def test_upload(srv):
    tok = login(srv)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>From Word</w:t></w:r></w:p>"
                                        "</w:body></w:document>")
    r, s = req(srv, "POST", "/api/v1/upload?name=Big%20Talk.docx", body=buf.getvalue(), token=tok,
               headers={"Content-Type": "application/octet-stream"})
    assert r.status == 201 and s["body"] == "From Word" and s["title"] == "Big Talk"
    r, d = req(srv, "POST", "/api/v1/upload?name=virus.exe", body=b"MZ", token=tok,
               headers={"Content-Type": "application/octet-stream"})
    assert r.status == 400


def test_oversized_body_rejected(srv):
    tok = login(srv)
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    c.putrequest("POST", "/api/v1/upload?name=a.txt", skip_host=True)
    c.putheader("Host", "127.0.0.1")
    c.putheader("Authorization", "Bearer " + tok)
    c.putheader("Content-Length", str(api.MAX_BODY + 1))
    c.endheaders()
    r = c.getresponse()
    assert r.status == 413
    c.close()


# ------------------------------------------------------------------ realtime
def test_sse_pushes_state_changes(srv):
    tok = login(srv)
    received = []

    def listen():
        c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        c.request("GET", "/api/v1/events", headers={"Host": "127.0.0.1", "Authorization": "Bearer " + tok})
        r = c.getresponse()
        assert r.getheader("Content-Type").startswith("text/event-stream")
        buf = b""
        while len(received) < 2:
            chunk = r.fp.readline()
            if not chunk:
                break
            buf += chunk
            if chunk == b"\n" and b"data:" in buf:
                received.append(json.loads(buf.split(b"data:", 1)[1].strip()))
                buf = b""
        c.close()

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.4)
    srv.publish_state({"playing": True, "wpm": 150})
    t.join(timeout=8)
    assert received[0]["wpm"] == 140          # current state on connect
    assert received[1] == {"playing": True, "wpm": 150}


def test_sse_closes_on_pin_change(srv):
    tok = login(srv)
    events = []

    def listen():
        c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        c.request("GET", "/api/v1/events", headers={"Host": "127.0.0.1", "Authorization": "Bearer " + tok})
        r = c.getresponse()
        for line in r.fp:
            if line.startswith(b"event:"):
                events.append(line.strip().decode())
        c.close()

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.4)
    srv.set_pin("111222")
    t.join(timeout=8)
    assert "event: logout" in events

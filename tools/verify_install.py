"""Post-install check against the RUNNING installed app (uses the real settings PIN)."""
import http.client, json, os, sqlite3
home = os.path.join(os.environ["APPDATA"], "GlassPrompter")
s = json.load(open(os.path.join(home, "settings.json"), encoding="utf-8"))
print("settings: wpm=%s font=%s geometry=%s first_run_done=%s remote=%s" % (
    s["wpm"], s["font_px"], s["geometry"], s["first_run_done"], s["remote_enabled"]))
db = sqlite3.connect(os.path.join(home, "library.db"))
print("library:", [r[0] for r in db.execute("SELECT title FROM scripts ORDER BY id")])


def call(method, path, body=None, tok=None):
    c = http.client.HTTPConnection("127.0.0.1", s["remote_port"], timeout=5)
    h = {"Host": "127.0.0.1"}
    if body is not None:
        h["Content-Type"] = "application/json"
        body = json.dumps(body)
    if tok:
        h["Authorization"] = "Bearer " + tok
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"{}")


st, d = call("POST", "/api/v1/session", {"pin": s["pin"]})
st, state = call("GET", "/api/v1/state", tok=d["token"])
print("state:", {k: state.get(k) for k in ("capture_hidden", "window_visible", "playing", "wpm", "script")})
st, page = 0, None
c = http.client.HTTPConnection("127.0.0.1", s["remote_port"], timeout=5)
c.request("GET", "/", headers={"Host": "127.0.0.1"})
r = c.getresponse()
print("phone page:", r.status, len(r.read()), "bytes")

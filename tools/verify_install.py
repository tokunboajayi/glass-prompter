"""Post-install check against the RUNNING installed app (uses the real settings PIN).
Exercises Voice Follow inside the packaged build, then restores the user's state."""
import http.client, json, os, sqlite3, time
home = os.path.join(os.environ["APPDATA"], "GlassPrompter")
s = json.load(open(os.path.join(home, "settings.json"), encoding="utf-8"))
print("settings: wpm=%s font=%s first_run_done=%s remote=%s voice=%s" % (
    s["wpm"], s["font_px"], s["first_run_done"], s["remote_enabled"], s.get("voice_follow")))
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


st, d = call("GET", "/api/v1/health")
print("health:", d)
st, d = call("POST", "/api/v1/session", {"pin": s["pin"]})
tok = d["token"]
st, state = call("GET", "/api/v1/state", tok=tok)
print("state:", {k: state.get(k) for k in ("capture_hidden", "window_visible", "voice_follow", "sections")})
was_voice = state.get("voice_follow")
if not was_voice:
    call("POST", "/api/v1/control", {"action": "voice"}, tok)
call("POST", "/api/v1/control", {"action": "play"}, tok)        # start listening (opens the mic)
time.sleep(5)
st, state = call("GET", "/api/v1/state", tok=tok)
print("voice in packaged app -> listening:", state.get("listening"))
call("POST", "/api/v1/control", {"action": "play"}, tok)        # stop
if not was_voice:
    call("POST", "/api/v1/control", {"action": "voice"}, tok)   # restore
log = open(os.path.join(home, "logs", "glassprompter.log"), encoding="utf-8").read().splitlines()[-25:]
print("\n".join(l for l in log if "Voice" in l or "ERROR" in l or "CRIT" in l or "WARN" in l))
c = http.client.HTTPConnection("127.0.0.1", s["remote_port"], timeout=5)
c.request("GET", "/icon.svg", headers={"Host": "127.0.0.1"})
r = c.getresponse()
print("icon:", r.status, len(r.read()), "bytes")

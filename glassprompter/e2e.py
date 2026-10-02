"""End-to-end audit of a real, running Glass Prompter:  GlassPrompter --e2e [REPORT]   (exit 0 = all passed)

Starts the real app (from source or the installed/bundled build) on a throw-away profile and drives it the way a
person and the phone remote would, through the same HTTP API the phone uses. Works on Windows, macOS and Linux,
with or without a sound device (no device -> silent output that keeps real-time pacing).

Checks: single instance under a 4-way launch race - pairing - phone page + security headers - script library
(create, load, edit, upload, delete) - every control action - ghost mode and both see-through directions -
Read Aloud with the natural voice following word by word - crash guard - no crash at the end.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PIN = "246810"
SCRIPT = ("# Opening\nGood morning everyone, and thanks for joining the quarterly review today.\n"
          "We grew revenue and kept every customer we signed last spring.\n"
          "# Numbers\nRevenue grew eighteen percent and churn fell again this quarter.\n"
          "Thank you all for the hard work that made it possible.\n")


class Audit:
    def __init__(self, report=None):
        self.report, self.lines, self.failed = report, [], []
        self.home = tempfile.mkdtemp(prefix="gp_e2e_")
        self.port = _free_port()
        self.token = None
        self.procs = []

    # -------------------------------------------------------------- output
    def out(self, text):
        self.lines.append(text)
        if sys.stdout is not None:
            try:
                print(text, flush=True)
            except Exception:
                pass

    def check(self, name, ok, detail=""):
        self.out("%-34s %s  %s" % (name, "PASS" if ok else "FAIL", detail))
        if not ok:
            self.failed.append(name)
        return ok

    # -------------------------------------------------------------- http
    def call(self, method, path, body=None, raw=None, headers=None, auth=True, timeout=10):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        h = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        elif raw is not None:
            data = raw
            h.setdefault("Content-Type", "application/octet-stream")
        if auth and self.token:
            h["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                txt = r.read()
                return r.status, dict(r.headers), txt
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def api(self, method, path, body=None, **kw):
        st, _, txt = self.call(method, "/api/v1" + path, body, **kw)
        try:
            return st, json.loads(txt or b"{}")
        except ValueError:
            return st, {}

    def state(self):
        return self.api("GET", "/state")[1]

    def control(self, action):
        st, _ = self.api("POST", "/control", {"action": action})
        time.sleep(0.6)                                # let the UI apply it and publish
        return st

    def wait(self, pred, timeout, step=0.25):
        end = time.time() + timeout
        while time.time() < end:
            try:
                v = pred()
                if v:
                    return v
            except Exception:
                pass
            time.sleep(step)
        return None

    # -------------------------------------------------------------- app
    def prepare_profile(self):
        os.environ["GLASSPROMPTER_HOME"] = self.home
        from . import config
        c = config.Config()
        c.load()
        s = c.s
        s.first_run_done, s.auto_update, s.remote_enabled = True, False, True
        s.remote_port, s.pin, s.start_with_windows = self.port, PIN, False
        s.drop_dir = os.path.join(self.home, "drop")
        c.save()
        if not _has_output_device():
            os.environ["GLASSPROMPTER_NULL_AUDIO"] = "1"
            self.out("(no sound device here: Read Aloud plays to a silent output at real-time pace)")

    def _dump(self, path, title, n):
        if os.path.exists(path):
            lines = open(path, encoding="utf-8", errors="replace").read().splitlines()[-n:]
            self.out("  --- %s (%s) ---" % (title, os.path.basename(path)))
            for ln in lines:
                self.out("  | " + ln)

    def launch(self, n):
        from .selftest import _command, _no_window
        env = dict(os.environ, GLASSPROMPTER_STARTUP_TRACE=os.path.join(self.home, "startup_trace.txt"))
        self.procs = [subprocess.Popen(_command(), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       **_no_window()) for _ in range(n)]

    def alive(self):
        return [p for p in self.procs if p.poll() is None]

    def stop_all(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
        for p in self.procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()

    # -------------------------------------------------------------- the audit
    def run(self):
        self.out("Glass Prompter end-to-end audit (%s, %s)" % (sys.platform, "frozen" if getattr(sys, "frozen", False)
                                                                else "source"))
        self.prepare_profile()

        # 1. single instance: four copies started in the same instant
        self.launch(4)
        t0 = time.time()
        up = self.wait(lambda: self.call("GET", "/api/v1/health", auth=False, timeout=2)[0] == 200, 90, 0.5)
        if not self.check("app starts and phone server is up", bool(up)):
            self.out("  processes: %s" % ", ".join("running" if p.poll() is None else "exit %s" % p.returncode
                                                   for p in self.procs))
            self._dump(os.path.join(self.home, "startup_trace.txt"), "where the app is stuck", 80)
            self._dump(os.path.join(self.home, "logs", "glassprompter.log"), "app log", 40)
            return self.finish()
        took = time.time() - t0
        self.out("%-34s %s  %.0f s to start" % ("startup time", "PASS" if took < 20 else "SLOW", took))
        if took >= 20:                                 # not fatal, but show exactly where the time went
            self._dump(os.path.join(self.home, "startup_trace.txt"), "where startup spent its time", 120)
        time.sleep(8)                                  # losers hand over and exit
        self.check("single instance (4-way launch race)", len(self.alive()) == 1,
                   "%d running" % len(self.alive()))

        # 2. pairing + phone page
        st, _ = self.api("POST", "/session", {"pin": "000000"}, auth=False)
        self.check("wrong PIN rejected", st in (401, 403), "HTTP %s" % st)
        st, res = self.api("POST", "/session", {"pin": PIN}, auth=False)
        self.token = res.get("token")
        self.check("phone pairs with the PIN", st == 200 and bool(self.token), "HTTP %s" % st)
        st, _ = self.api("GET", "/state", auth=False)
        self.check("data needs a session", st == 401, "HTTP %s" % st)
        for path, kind in (("/", "text/html"), ("/app.js", "javascript"), ("/app.css", "text/css")):
            st, hd, body = self.call("GET", path, auth=False)
            ctype = hd.get("Content-Type", "")
            self.check("phone page %s" % path, st == 200 and kind in ctype and len(body) > 200,
                       "%s %s %d bytes" % (st, ctype, len(body)))
        st, hd, _ = self.call("GET", "/", auth=False)
        csp = hd.get("Content-Security-Policy", "")
        self.check("phone page security headers", "default-src 'none'" in csp and hd.get("X-Frame-Options") == "DENY")

        # 3. script library
        st, res = self.api("POST", "/scripts", {"title": "E2E review", "body": SCRIPT, "load": True})
        sid = res.get("id") or (res.get("script") or {}).get("id")
        self.check("create + load a script", st in (200, 201) and bool(sid), "HTTP %s id=%s" % (st, sid))
        loaded = self.wait(lambda: (self.state().get("script") or {}).get("title") == "E2E review", 8)
        self.check("prompter shows the script", bool(loaded))
        st, res = self.api("GET", "/scripts")
        items = res.get("scripts", res if isinstance(res, list) else [])
        self.check("list scripts", st == 200 and any(x.get("id") == sid for x in items), "%d scripts" % len(items))
        st, _ = self.api("PUT", "/scripts/%s" % sid, {"title": "E2E review", "body": SCRIPT + "One more line.\n"})
        self.check("edit a script", st == 200, "HTTP %s" % st)
        st, _, body = self.call("POST", "/api/v1/upload?name=notes.txt", raw=b"Uploaded from the phone test.\n",
                                headers={"Content-Type": "text/plain"})
        self.check("upload a file", st in (200, 201), "HTTP %s" % st)
        try:
            up_id = json.loads(body or b"{}").get("id")
        except ValueError:
            up_id = None
        if up_id:
            st, _ = self.api("DELETE", "/scripts/%s" % up_id)
            self.check("delete a script", st in (200, 204), "HTTP %s" % st)
        st, _ = self.api("POST", "/scripts/%s/load" % sid)
        self.check("load from library", st == 200, "HTTP %s" % st)
        time.sleep(1)

        # 4. controls
        s0 = self.state()
        self.control("bigger")
        self.check("bigger text", self.state().get("font_px", 0) > s0.get("font_px", 0))
        self.control("smaller")
        self.check("smaller text", self.state().get("font_px") == s0.get("font_px"))
        self.control("faster")
        self.check("faster", self.state().get("wpm", 0) > s0.get("wpm", 0))
        self.control("slower")
        self.check("slower", self.state().get("wpm") == s0.get("wpm"))
        self.control("play")
        playing = self.wait(lambda: self.state().get("playing") and not self.state().get("counting"), 6)
        time.sleep(2.5)
        moved = self.state().get("progress", 0)
        self.check("play scrolls the script", bool(playing) and moved > 0, "progress %.3f" % moved)
        self.control("play")
        self.check("pause", not self.state().get("playing"))
        self.control("next_section")
        p1 = self.state().get("pos", 0)
        self.control("prev_section")
        self.check("next / previous section", p1 > self.state().get("pos", 0), "pos %.0f -> %.0f"
                   % (p1, self.state().get("pos", 0)))
        self.control("restart")
        self.check("restart", self.state().get("progress", 1) < 0.01)
        self.control("hide")
        self.check("hide prompter", self.state().get("window_visible") is False)
        self.control("hide")
        self.check("show prompter", self.state().get("window_visible") is True)

        # 5. ghost mode and see-through levels
        lvl = self.state().get("ghost_opacity", 0)
        self.control("ghost_less")
        st1 = self.state()
        self.check("more see-through (turns ghost on)", st1.get("ghost") is True and st1.get("ghost_opacity", 1) < lvl,
                   "ghost=%s %.2f -> %.2f" % (st1.get("ghost"), lvl, st1.get("ghost_opacity", 0)))
        self.control("ghost_more")
        st2 = self.state()
        self.check("more solid", st2.get("ghost_opacity", 0) > st1.get("ghost_opacity", 1),
                   "%.2f -> %.2f" % (st1.get("ghost_opacity", 0), st2.get("ghost_opacity", 0)))
        self.control("ghost")
        self.check("ghost mode off", self.state().get("ghost") is False)
        self.control("ghost")
        self.check("ghost mode on", self.state().get("ghost") is True)
        self.control("ghost")

        # 6. Read Aloud with the natural voice
        guard = self.wait(lambda: self.state().get("guard") not in ("", "pending") and self.state().get("guard"), 90, 1)
        self.check("crash guard finished", guard == "ok", str(guard))
        self.control("restart")
        self.control("read_aloud")
        started = self.wait(lambda: self.state().get("reading_aloud") and self.state().get("tts_engine"), 10)
        eng = self.state().get("tts_engine")
        self.check("Read Aloud starts", bool(started), "engine=%s" % eng)
        words = []
        end = time.time() + 25
        while time.time() < end and len(set(words)) < 6:
            w = self.state().get("tts_word", -1)
            if w >= 0:
                words.append(w)
            time.sleep(0.5)
        distinct = sorted(set(words))
        self.check("natural voice reads word by word", eng == "natural" and len(distinct) >= 6
                   and words == sorted(words), "engine=%s words=%s" % (eng, distinct[:10]))
        self.control("read_aloud")
        stopped = self.wait(lambda: not self.state().get("reading_aloud"), 3)
        self.check("Read Aloud stops", bool(stopped))

        # 7. Voice Follow switch (no microphone needed to toggle; listening itself needs a mic)
        self.control("voice")
        self.check("Voice Follow on", self.state().get("voice_follow") is True)
        time.sleep(3)
        self.control("voice")
        self.check("Voice Follow off", self.state().get("voice_follow") is False)

        # 8. still healthy
        time.sleep(1)
        self.check("app still running (no crash)", len(self.alive()) == 1)
        return self.finish()

    def finish(self):
        self.stop_all()
        crash = os.path.join(self.home, "logs", "crash.log")
        text = open(crash, encoding="utf-8", errors="replace").read() if os.path.exists(crash) else ""
        self.check("no native crash recorded", not text.strip(), text.strip()[-300:])
        log = os.path.join(self.home, "logs", "glassprompter.log")
        if os.path.exists(log):
            bad = [ln.strip() for ln in open(log, encoding="utf-8", errors="replace")
                   if " CRITICAL " in ln or "Unhandled exception" in ln]
            self.check("no unhandled errors in the log", not bad, " | ".join(bad)[-300:])
        self.out("RESULT: %s" % ("OK" if not self.failed else "FAILED (%d): %s" % (len(self.failed),
                                                                               ", ".join(self.failed))))
        if self.report:
            with open(self.report, "w", encoding="utf-8") as f:
                f.write("\n".join(self.lines) + "\n")
            if os.path.exists(log):
                shutil.copy(log, self.report + ".app.log")
        shutil.rmtree(self.home, ignore_errors=True)
        return 1 if self.failed else 0


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _has_output_device():
    try:
        import sounddevice as sd
        sd.query_devices(kind="output")
        return True
    except Exception:
        return False


def run(report=None):
    try:
        return Audit(report).run()
    except Exception as e:                                 # the audit itself must never hang a build
        import traceback
        msg = "E2E harness error: %s\n%s" % (e, traceback.format_exc())
        if report:
            with open(report, "w", encoding="utf-8") as f:
                f.write(msg)
        if sys.stdout is not None:
            print(msg)
        return 2

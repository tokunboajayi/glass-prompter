"""Glass Prompter remote API (v1).

A small, dependency-free HTTP server on the local network that lets a phone control the
prompter and manage the script library.

Security model
  * 6-digit PIN exchanged once for a random session token (HttpOnly, SameSite=Strict cookie
    or Bearer header). The PIN is never accepted on data endpoints.
  * Failed PIN attempts are rate limited per client IP, then locked out.
  * Host header must be an IP literal, localhost or this PC's name - blocks DNS rebinding.
  * JSON endpoints require Content-Type: application/json - blocks cross-site form posts.
  * Strict CSP and security headers on every response; bodies capped at 8 MB.

Threading
  The server runs on background threads and NEVER touches the UI. It calls the `bridge`
  object, whose methods must be thread-safe (the Qt bridge emits queued signals).
"""
import http.server
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import socketserver
import threading
import time
import urllib.parse

from .. import __version__, paths, scripts

log = logging.getLogger(__name__)

API = "/api/v1"
MAX_BODY = 8 * 1024 * 1024
SESSION_TTL = 12 * 3600
MAX_SESSIONS = 32
MAX_STREAMS = 8
FAIL_WINDOW, FAIL_LIMIT, LOCKOUT = 300, 5, 300       # 5 wrong PINs in 5 min -> 5 min lockout
CONTROL_ACTIONS = {"play", "restart", "faster", "slower", "back", "ahead", "bigger", "smaller", "hide",
                   "voice", "ghost", "ghost_less", "ghost_more", "next_section", "prev_section",
                   "read_aloud"}
STATIC_FILES = {"/": ("index.html", "text/html"), "/app.css": ("app.css", "text/css"),
                "/app.js": ("app.js", "text/javascript"), "/icon.svg": ("icon.svg", "image/svg+xml")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
       "connect-src 'self'; manifest-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


def local_ip():
    """IP of the adapter used for outbound traffic. No packet is actually sent."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


class ApiError(Exception):
    def __init__(self, status, code, message, headers=None):
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


# ------------------------------------------------------------------ security primitives
class RateLimiter:
    def __init__(self, window=FAIL_WINDOW, limit=FAIL_LIMIT, lockout=LOCKOUT, clock=time.monotonic):
        self.window, self.limit, self.lockout, self.clock = window, limit, lockout, clock
        self._fails, self._locked = {}, {}
        self._lock = threading.Lock()

    def check(self, ip):
        """Seconds the client must wait, or 0 if it may try."""
        with self._lock:
            until = self._locked.get(ip, 0)
            left = until - self.clock()
            if left > 0:
                return int(left) + 1
            self._locked.pop(ip, None)
            return 0

    def fail(self, ip):
        now = self.clock()
        with self._lock:
            q = [t for t in self._fails.get(ip, []) if now - t < self.window] + [now]
            self._fails[ip] = q
            if len(q) >= self.limit:
                self._locked[ip] = now + self.lockout
                self._fails[ip] = []

    def success(self, ip):
        with self._lock:
            self._fails.pop(ip, None)


class Sessions:
    def __init__(self, ttl=SESSION_TTL, clock=time.time):
        self.ttl, self.clock = ttl, clock
        self._tokens = {}
        self._lock = threading.Lock()

    def create(self):
        token = secrets.token_urlsafe(32)
        now = self.clock()
        with self._lock:
            self._tokens = {t: e for t, e in self._tokens.items() if e > now}
            if len(self._tokens) >= MAX_SESSIONS:                       # evict oldest
                oldest = min(self._tokens, key=self._tokens.get)
                self._tokens.pop(oldest)
            self._tokens[token] = now + self.ttl
        return token

    def valid(self, token):
        if not token:
            return False
        with self._lock:
            exp = self._tokens.get(token)
            if exp is None:
                return False
            if exp <= self.clock():
                self._tokens.pop(token, None)
                return False
            return True

    def revoke_all(self):
        with self._lock:
            self._tokens.clear()

    def count(self):
        now = self.clock()
        with self._lock:
            return sum(1 for e in self._tokens.values() if e > now)


class EventHub:
    """Latest-state broadcaster for Server-Sent Events."""

    def __init__(self):
        self._cond = threading.Condition()
        self.version = 0
        self.state = {}

    def publish(self, state):
        with self._cond:
            if state == self.state:
                return
            self.state = dict(state)
            self.version += 1
            self._cond.notify_all()

    def wait(self, since, timeout):
        with self._cond:
            if self.version == since:
                self._cond.wait(timeout)
            return self.version, dict(self.state)

    def wake_all(self):
        with self._cond:
            self.version += 1
            self._cond.notify_all()


def host_allowed(host_header, extra_names=()):
    """Reject requests addressed to foreign hostnames (DNS-rebinding defence)."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host[1:host.find("]")] if "]" in host else host
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    names = {"localhost"}
    try:
        hn = socket.gethostname().lower()
        names |= {hn, hn + ".local", hn + ".lan", hn + ".home"}
    except OSError:
        pass
    names |= {n.lower() for n in extra_names}
    return host in names


# ------------------------------------------------------------------ server
class RemoteServer:
    def __init__(self, store, bridge, pin, port=8765, bind="0.0.0.0", static_dir=None):
        self.store = store
        self.bridge = bridge
        self._pin = str(pin)
        self.port = int(port)
        self.bind = bind
        self.static_dir = static_dir or paths.static_dir()
        self.sessions = Sessions()
        self.limiter = RateLimiter()
        self.hub = EventHub()
        self.streams = threading.BoundedSemaphore(MAX_STREAMS)
        self.screen_lock = threading.Semaphore(2)          # phone refreshes ~1/s; cap concurrent grabs
        self.ai_lock = threading.Semaphore(1)              # one AI request at a time (it costs money)
        self.last_seen = 0.0
        self.error = None
        self._httpd = None
        self._thread = None
        self._stopping = threading.Event()

    # public -----------------------------------------------------------------
    @property
    def pin(self):
        return self._pin

    def set_pin(self, pin):
        self._pin = str(pin)
        self.sessions.revoke_all()          # every phone must re-pair
        self.hub.wake_all()

    def url(self, with_pin=True):
        base = "http://%s:%d/" % (local_ip(), self.port)
        return base + ("?k=%s" % self._pin if with_pin else "")

    def connected(self, within=8.0):
        return time.time() - self.last_seen < within

    def publish_state(self, state):
        self.hub.publish(state)

    def start(self):
        server = self

        class Handler(_Handler):
            srv = server

        class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = False      # on Windows SO_REUSEADDR lets a 2nd process steal the port
            request_queue_size = 32

        try:
            self._httpd = Server((self.bind, self.port), Handler)
        except OSError as ex:
            self.error = str(ex)
            log.error("Remote server could not start on port %d: %s", self.port, ex)
            return False
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="remote-http", daemon=True)
        self._thread.start()
        log.info("Remote server listening on %s:%d", self.bind, self.port)
        return True

    def stop(self):
        self._stopping.set()
        self.hub.wake_all()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        log.info("Remote server stopped")

    @property
    def running(self):
        return self._httpd is not None


class _Handler(http.server.BaseHTTPRequestHandler):
    srv = None                  # set by subclass
    server_version = "GlassPrompter/" + __version__
    sys_version = ""
    timeout = 30                # slow-client protection

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.client_address[0], fmt % args)

    # ---------------------------------------------------------------- plumbing
    def _security_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def _send(self, status, body=b"", ctype="application/json", headers=None, cache="no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self._security_headers()
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, obj, headers=None):
        self._send(status, json.dumps(obj, separators=(",", ":")), headers=headers)

    def _error(self, e):
        self._drain()
        self._json(e.status, {"error": {"code": e.code, "message": e.message}}, e.headers)

    def _drain(self):
        """Read whatever is left of the request body before answering with an error. Replying while the client is
        still sending makes Windows reset the connection (WinError 10053/10054), so the client sees a crash instead
        of our clear 401/415. Oversized bodies are not read: we close the connection instead."""
        if getattr(self, "_consumed", True):
            return
        self._consumed = True
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if 0 < n <= MAX_BODY:
            try:
                self.rfile.read(n)
            except OSError:
                pass
        elif n > MAX_BODY:
            self.close_connection = True

    def _body(self, max_len=MAX_BODY):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "bad_request", "Invalid Content-Length")
        if n < 0:
            raise ApiError(400, "bad_request", "Invalid Content-Length")
        if n > max_len:
            raise ApiError(413, "too_large", "Request is too large (8 MB max)")
        self._consumed = True
        return self.rfile.read(n) if n else b""

    def _json_body(self):
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        raw = self._body()          # read the body first: answering with unread data makes Windows reset the socket
        if ctype != "application/json":
            raise ApiError(415, "unsupported_media_type", "Send JSON with Content-Type: application/json")
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "bad_json", "Body is not valid JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "bad_json", "Body must be a JSON object")
        return data

    def _token(self):
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        cookie = self.headers.get("Cookie") or ""
        m = re.search(r"(?:^|;\s*)gp_session=([A-Za-z0-9_\-]+)", cookie)
        return m.group(1) if m else None

    def _require_auth(self):
        if not self.srv.sessions.valid(self._token()):
            raise ApiError(401, "unauthorized", "Pair with the PIN first")
        self.srv.last_seen = time.time()

    def _route(self):
        u = urllib.parse.urlsplit(self.path)
        return u.path.rstrip("/") or "/", urllib.parse.parse_qs(u.query)

    # ---------------------------------------------------------------- dispatch
    def _dispatch(self, method):
        self._consumed = False
        try:
            if not host_allowed(self.headers.get("Host")):
                raise ApiError(421, "bad_host", "Unknown host")
            path, qs = self._route()
            if method in ("GET", "HEAD") and (path in STATIC_FILES or path == "/manifest.webmanifest"):
                return self._static(path)
            if not path.startswith(API):
                raise ApiError(404, "not_found", "Not found")
            route = path[len(API):] or "/"
            handler, params = self._match(method, route)
            handler(qs=qs, **params)
        except ApiError as e:
            self._error(e)
        except scripts.ValidationError as e:
            self._error(ApiError(400, "invalid", str(e)))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:
            log.exception("Unhandled API error on %s %s", method, self.path.split("?")[0])
            try:
                self._error(ApiError(500, "internal", "Something went wrong"))
            except Exception:
                pass

    def _match(self, method, route):
        table = [
            ("GET", r"/health", self.h_health),
            ("POST", r"/session", self.h_session),
            ("DELETE", r"/session", self.h_logout),
            ("GET", r"/state", self.h_state),
            ("GET", r"/events", self.h_events),
            ("POST", r"/control", self.h_control),
            ("GET", r"/scripts", self.h_list),
            ("POST", r"/scripts", self.h_create),
            ("GET", r"/scripts/(?P<sid>\d+)", self.h_get),
            ("PUT", r"/scripts/(?P<sid>\d+)", self.h_update),
            ("DELETE", r"/scripts/(?P<sid>\d+)", self.h_delete),
            ("POST", r"/scripts/(?P<sid>\d+)/load", self.h_load),
            ("POST", r"/upload", self.h_upload),
            ("GET", r"/features", self.h_features),
            ("GET", r"/screen\.jpg", self.h_screen),
            ("POST", r"/ai/chat", self.h_ai_chat),
        ]
        allowed = False
        for m, pattern, fn in table:
            match = re.fullmatch(pattern, route)
            if match:
                allowed = True
                if m == method or (method == "HEAD" and m == "GET"):
                    return fn, match.groupdict()
        if allowed:
            raise ApiError(405, "method_not_allowed", "Method not allowed")
        raise ApiError(404, "not_found", "Not found")

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):                      # no CORS: cross-origin callers are refused
        self._error(ApiError(405, "method_not_allowed", "Method not allowed"))

    # ---------------------------------------------------------------- static
    def _static(self, path):
        if path == "/manifest.webmanifest":
            body = json.dumps({"name": "Glass Prompter Remote", "short_name": "Prompter", "start_url": "/",
                               "display": "standalone", "background_color": "#0e0e12",
                               "theme_color": "#0e0e12",
                               "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]})
            return self._send(200, body, "application/manifest+json", cache="no-cache")
        name, ctype = STATIC_FILES[path]
        try:
            with open(os.path.join(self.srv.static_dir, name), "rb") as f:
                data = f.read()
        except OSError:
            raise ApiError(404, "not_found", "Not found")
        self._send(200, data, ctype, cache="no-cache")

    # ---------------------------------------------------------------- endpoints
    def h_health(self, qs):
        self._json(200, {"ok": True, "app": "glass-prompter", "version": __version__})

    def h_session(self, qs):
        ip = self.client_address[0]
        wait = self.srv.limiter.check(ip)
        if wait:
            raise ApiError(429, "locked", "Too many wrong PINs. Try again in %d seconds." % wait,
                           {"Retry-After": str(wait)})
        data = self._json_body()
        pin = str(data.get("pin", ""))
        if not (len(pin) == 6 and pin.isdigit() and secrets.compare_digest(pin, self.srv.pin)):
            self.srv.limiter.fail(ip)
            log.warning("Wrong PIN from %s", ip)
            raise ApiError(401, "wrong_pin", "Wrong PIN")
        self.srv.limiter.success(ip)
        token = self.srv.sessions.create()
        self.srv.last_seen = time.time()
        log.info("Phone paired from %s", ip)
        cookie = "gp_session=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d" % (token, SESSION_TTL)
        self._json(200, {"token": token, "expires_in": SESSION_TTL}, {"Set-Cookie": cookie})

    def h_logout(self, qs):
        self._json(200, {"ok": True}, {"Set-Cookie": "gp_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"})

    def h_state(self, qs):
        self._require_auth()
        self._json(200, self.srv.hub.state)

    def h_events(self, qs):
        self._require_auth()
        if not self.srv.streams.acquire(blocking=False):
            raise ApiError(503, "busy", "Too many open connections")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self._security_headers()
            self.end_headers()
            version = -1
            token = self._token()
            while not self.srv._stopping.is_set():
                if not self.srv.sessions.valid(token):      # PIN changed -> drop the stream
                    self.wfile.write(b"event: logout\ndata: {}\n\n")
                    self.wfile.flush()
                    break
                new_version, state = self.srv.hub.wait(version, timeout=15)
                if new_version != version:
                    version = new_version
                    payload = json.dumps(state, separators=(",", ":"))
                    self.wfile.write(("event: state\ndata: %s\n\n" % payload).encode("utf-8"))
                else:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                self.srv.last_seen = time.time()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.srv.streams.release()

    def h_control(self, qs):
        self._require_auth()
        action = str(self._json_body().get("action", ""))
        if action not in CONTROL_ACTIONS:
            raise ApiError(400, "bad_action", "Unknown action")
        self.srv.bridge.control(action)
        self._json(200, {"ok": True})

    def h_list(self, qs):
        self._require_auth()
        q = (qs.get("q", [""])[0] or "").strip()[:100]
        self._json(200, {"scripts": self.srv.store.list(q or None)})

    def h_get(self, qs, sid):
        self._require_auth()
        s = self.srv.store.get(int(sid))
        if not s:
            raise ApiError(404, "not_found", "Script not found")
        self._json(200, s)

    def h_create(self, qs):
        self._require_auth()
        data = self._json_body()
        s = self.srv.store.create(data.get("title", ""), data.get("body", ""))
        if data.get("load"):
            self.srv.bridge.load_script(s["id"], "your phone")
        self._json(201, s)

    def h_update(self, qs, sid):
        self._require_auth()
        data = self._json_body()
        s = self.srv.store.update(int(sid), data.get("title"), data.get("body"))
        if not s:
            raise ApiError(404, "not_found", "Script not found")
        self.srv.bridge.script_changed(s["id"])
        if data.get("load"):
            self.srv.bridge.load_script(s["id"], "your phone")
        self._json(200, s)

    def h_delete(self, qs, sid):
        self._require_auth()
        if not self.srv.store.delete(int(sid)):
            raise ApiError(404, "not_found", "Script not found")
        self.srv.bridge.script_changed(int(sid))
        self._json(200, {"ok": True})

    def h_load(self, qs, sid):
        self._require_auth()
        if not self.srv.store.get(int(sid)):
            raise ApiError(404, "not_found", "Script not found")
        self.srv.bridge.load_script(int(sid), "your phone")
        self._json(200, {"ok": True})

    def h_upload(self, qs):
        self._require_auth()
        name = os.path.basename((qs.get("name", [""])[0] or "").strip()) or "upload.txt"
        text = scripts.read_bytes(name, self._body())
        s = self.srv.store.create(scripts.title_from_filename(name), text)
        self.srv.bridge.load_script(s["id"], name)
        self._json(201, s)

    # ---------------------------------------------------------------- screen view + AI
    def _bridge_call(self, name, *args, default=None):
        fn = getattr(self.srv.bridge, name, None)
        return fn(*args) if fn else default

    def h_features(self, qs):
        self._require_auth()
        key, model = self._bridge_call("ai_settings", default=("", "")) or ("", "")
        self._json(200, {"screen": bool(self._bridge_call("screen_allowed", default=False)),
                         "ai": bool((key or "").strip()), "ai_model": model or ""})

    def h_screen(self, qs):
        self._require_auth()
        if not self._bridge_call("screen_allowed", default=False):
            raise ApiError(403, "screen_off", "Screen view is turned off in Settings > Privacy on your computer")
        if not self.srv.screen_lock.acquire(timeout=6):
            raise ApiError(503, "busy", "Screen capture is busy")
        try:
            full = (qs.get("full", ["0"])[0] or "0") == "1"
            data = self.srv.bridge.screenshot(full=True) if full else self.srv.bridge.screenshot()
        except Exception as e:                        # noqa: BLE001
            raise ApiError(503, "capture_failed", "Couldn't capture the screen (%s)" % e)
        finally:
            self.srv.screen_lock.release()
        if not data:
            raise ApiError(503, "capture_failed", "Couldn't capture the screen")
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def h_ai_chat(self, qs):
        self._require_auth()
        from .. import ai
        data = self._json_body()
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ApiError(400, "bad_request", "Send messages: [{role, content}]")
        key, model = self._bridge_call("ai_settings", default=("", "")) or ("", "")
        if not (key or "").strip():
            raise ApiError(400, "ai_no_key", "Add your Anthropic API key in Settings > AI assistant on your computer.")
        jpeg = None
        if data.get("screen") and self._bridge_call("screen_allowed", default=False):
            try:
                jpeg = self.srv.bridge.screenshot()
            except Exception as e:                    # noqa: BLE001 - answer without the screen
                log.warning("AI chat: screen capture failed: %s", e)
        title, text = ("", "")
        if data.get("script", True):
            title, text = self._bridge_call("script_context", default=("", "")) or ("", "")
        if not self.srv.ai_lock.acquire(timeout=1):
            raise ApiError(429, "ai_busy", "Still answering your last message")
        try:
            reply = ai.chat(key, messages, model, jpeg, title, text)
        except ai.AIError as e:
            raise ApiError(502, "ai_error", str(e))
        finally:
            self.srv.ai_lock.release()
        self._json(200, {"reply": reply, "saw_screen": bool(jpeg)})

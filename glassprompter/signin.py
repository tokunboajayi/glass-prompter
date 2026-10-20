"""One-click sign-in for the AI assistant, instead of copying an API key.

  * Sign in with OpenRouter: the browser opens OpenRouter, you approve, and Glass Prompter receives a normal
    OpenRouter API key (PKCE; no client secret or registration). Pay-as-you-go credit; one key reaches Claude,
    GPT, Gemini and hundreds of other models. The key is stored like any pasted key (ai.key).
  * Sign in with ChatGPT: for ChatGPT Plus/Pro subscribers. The browser opens ChatGPT, you approve "Use your
    ChatGPT plan", and requests are paid from your plan allowance instead of an API bill. OpenAI makes this
    available to open-source apps that run locally (like Glass Prompter): the app registers itself on first
    sign-in (client_id "dynamic_agent_client" -> a real client id on the callback). Tokens: ~1 h access token,
    30-day refresh token that renews on each refresh. Stored in chatgpt.json (owner-only) in the data folder.

Both flows use a one-shot HTTP listener on this computer for the browser callback, a random `state` and PKCE
(S256). Nothing passes through any other server. No Qt here: the UI runs these on a worker thread.

Protocol reference: OpenAI's Sign in with ChatGPT docs and DevKit (implemented independently here), and
OpenRouter's OAuth PKCE guide.
"""
import base64
import hashlib
import http.server
import json
import logging
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

log = logging.getLogger(__name__)

TIMEOUT = 300                       # seconds to finish signing in in the browser


class SignInError(Exception):
    pass


# ------------------------------------------------------------------ PKCE + HTTP helpers
def _b64url(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def pkce_pair():
    """-> (verifier, S256 challenge)."""
    verifier = _b64url(secrets.token_bytes(32))
    return verifier, _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def _tls():
    from .updater import tls_context
    return tls_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):   # credentials never follow a redirect
        return None


def _opener():
    return urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_tls()))


def _request(url, data=None, headers=None, form=False, timeout=30):
    """POST/GET returning (status, parsed JSON or {}). `form` sends application/x-www-form-urlencoded."""
    h = {"user-agent": "GlassPrompter", "accept": "application/json"}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode("ascii")
            h["content-type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode("utf-8")
            h["content-type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method="POST" if body is not None else "GET")
    try:
        with _opener().open(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SignInError("Couldn't reach the sign-in server. Is this computer online? (%s)" % e)
    try:
        parsed = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        parsed = {}
    return status, parsed if isinstance(parsed, dict) else {}


# ------------------------------------------------------------------ browser callback listener
_PAGE = ("<!doctype html><html lang='en'><meta charset='utf-8'><title>Glass Prompter</title>"
         "<style>body{font:17px system-ui,sans-serif;max-width:30rem;margin:18vh auto;padding:24px;"
         "background:#0c0e18;color:#f2f4fa}h1{font-size:24px}p{color:#a0a8bc}</style>"
         "<h1>%s</h1><p>%s</p></html>")


class _Listener:
    """A one-shot loopback HTTP server that waits for GET <path>?...&state=<state>."""

    def __init__(self, path, state, host="127.0.0.1"):
        self.path, self.state, self.host = path, state, host
        self.result = None
        self.done = threading.Event()
        listener = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):                   # quiet: query strings carry one-time codes
                pass

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(url.query, keep_blank_values=True)
                if url.path != listener.path or listener.done.is_set():
                    self.send_error(404)
                    return
                if q.get("state", [None]) != [listener.state] and listener.state is not None:
                    self.send_error(400, "Invalid sign-in state. Return to the tab that started sign-in.")
                    return
                ok = "error" not in q
                page = (_PAGE % ("You're signed in", "Return to Glass Prompter. You can close this tab.") if ok else
                        _PAGE % ("Sign-in was not completed", "Return to Glass Prompter to try again."))
                data = page.encode("utf-8")
                self.send_response(200)
                for k, v in (("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"),
                             ("Referrer-Policy", "no-referrer"),
                             ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'"),
                             ("Content-Length", str(len(data)))):
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)
                listener.result = {k: v[0] for k, v in q.items() if len(v) == 1}
                listener.done.set()

        self.server = http.server.HTTPServer((host, 0), Handler)
        self.server.timeout = 0.5
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self._serve, name="signin-callback", daemon=True)
        self.thread.start()

    def _serve(self):
        while not self.done.is_set():
            try:
                self.server.handle_request()
            except (OSError, ValueError):                # closed under us after sign-in finished: just stop
                break

    def wait(self, timeout=TIMEOUT, cancel=None):
        end = time.time() + timeout
        while not self.done.wait(0.25):
            if cancel is not None and cancel.is_set():
                self.close()
                raise SignInError("Sign-in was cancelled.")
            if time.time() > end:
                self.close()
                raise SignInError("Sign-in timed out. Try again and finish in the browser within a few minutes.")
        self.close()
        return self.result or {}

    def close(self):
        self.done.set()
        try:
            self.server.server_close()
        except OSError:
            pass


def _open(url, opener=None):
    if not (opener or webbrowser.open)(url):
        raise SignInError("The browser could not be opened. Open your default browser and try again.")


# ------------------------------------------------------------------ OpenRouter
OPENROUTER_AUTH = "https://openrouter.ai/auth"
OPENROUTER_EXCHANGE = "https://openrouter.ai/api/v1/auth/keys"


def openrouter_auth_url(callback, challenge, state):
    return OPENROUTER_AUTH + "?" + urllib.parse.urlencode({
        "callback_url": callback, "code_challenge": challenge, "code_challenge_method": "S256",
        "key_label": "Glass Prompter", "state": state})


def openrouter_sign_in(open_browser=None, cancel=None, timeout=TIMEOUT):
    """Browser sign-in with OpenRouter. Returns a new OpenRouter API key (the caller saves it)."""
    verifier, challenge = pkce_pair()
    state = _b64url(secrets.token_bytes(16))
    lst = _Listener("/callback", state, host="127.0.0.1")
    callback = "http://localhost:%d/callback" % lst.port         # OpenRouter accepts localhost on any port
    try:
        _open(openrouter_auth_url(callback, challenge, state), open_browser)
        q = lst.wait(timeout, cancel)
    finally:
        lst.close()
    if "error" in q or not q.get("code"):
        raise SignInError("OpenRouter sign-in was not completed.")
    status, data = _request(OPENROUTER_EXCHANGE, {"code": q["code"], "code_verifier": verifier,
                                                  "code_challenge_method": "S256"})
    key = data.get("key") if status == 200 else None
    if not key:
        raise SignInError("OpenRouter didn't issue a key (%s). Try signing in again." % (
            (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else status))
    return key


# ------------------------------------------------------------------ ChatGPT
CHATGPT_ISSUER = "https://auth.openai.com"
CHATGPT_RESOURCE = "https://api.openai.com/v1"
CHATGPT_SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
APP_NAME = "Glass Prompter"
SESSION_FILE = "chatgpt.json"
_lock = threading.Lock()
_discovery = {}


def session_path():
    from . import paths
    return os.path.join(paths.data_dir(), SESSION_FILE)


def load_session():
    try:
        with open(session_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_session(data):
    path = session_path()
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)          # owner-only on macOS/Linux
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def chatgpt_connected():
    """Signed in with plan usage allowed (a refresh token we can use)."""
    s = load_session()
    return bool(s.get("refresh_token") and PLAN_SCOPE in s.get("scopes", []))


def chatgpt_account():
    s = load_session()
    return s.get("email") or s.get("name") or ""


def discovery():
    """OpenID configuration from auth.openai.com; every endpoint must stay on that origin."""
    if _discovery:
        return _discovery
    status, data = _request(CHATGPT_ISSUER + "/.well-known/openid-configuration")
    if status != 200 or data.get("issuer") != CHATGPT_ISSUER:
        raise SignInError("ChatGPT sign-in configuration could not be verified. Try again shortly.")
    for k in ("authorization_endpoint", "token_endpoint"):
        v = data.get(k)
        if not isinstance(v, str) or not v.startswith(CHATGPT_ISSUER + "/"):
            raise SignInError("ChatGPT sign-in configuration could not be verified. Try again shortly.")
    rv = data.get("revocation_endpoint")
    _discovery.update(data if (rv is None or str(rv).startswith(CHATGPT_ISSUER + "/")) else
                      {k: v for k, v in data.items() if k != "revocation_endpoint"})
    return _discovery


def _jwt_claims(token):
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except Exception:                                   # noqa: BLE001
        return {}


def check_id_token(id_token, client_id, nonce=None, now=None):
    """Validate the ID token's claims. It comes straight from the token endpoint over verified TLS, so per
    OpenID Connect Core 3.1.3.7 the TLS server check stands in for the signature check. -> claims."""
    c = _jwt_claims(id_token or "")
    now = now or time.time()
    aud = c.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if (c.get("iss") != CHATGPT_ISSUER or client_id not in auds or not c.get("sub")
            or not isinstance(c.get("exp"), (int, float)) or c["exp"] < now - 5
            or (nonce is not None and c.get("nonce") != nonce)
            or (c.get("azp") is not None and c.get("azp") != client_id)):
        raise SignInError("The ChatGPT identity could not be verified. Please sign in again.")
    return c


def chatgpt_auth_url(endpoint, client_id, redirect, challenge, state, nonce, email=""):
    params = {"client_id": client_id, "response_type": "code", "redirect_uri": redirect,
              "scope": CHATGPT_SCOPES, "resource": CHATGPT_RESOURCE, "state": state, "nonce": nonce,
              "code_challenge_method": "S256", "code_challenge": challenge}
    if client_id == "dynamic_agent_client":
        params["agent_name_hint"] = APP_NAME              # first sign-in registers the app for this account
    if email:
        params["login_hint"] = email
    return endpoint + ("&" if "?" in endpoint else "?") + urllib.parse.urlencode(params)


def _token_fields(data):
    scopes = str(data.get("scope", "")).split()
    if not data.get("access_token") or str(data.get("token_type", "")).lower() != "bearer" \
            or not isinstance(data.get("expires_in"), (int, float)):
        raise SignInError("ChatGPT returned incomplete credentials. Please sign in again.")
    out = {"access_token": data["access_token"], "expires_at": time.time() + float(data["expires_in"]),
           "scopes": scopes}
    if data.get("refresh_token"):
        out["refresh_token"] = data["refresh_token"]
    return out


def _token_error(status, data):
    err = data.get("error")
    code = err if isinstance(err, str) else (err or {}).get("code") if isinstance(err, dict) else None
    if code == "access_denied":
        return SignInError("Sign-in was not completed. You can try again when you're ready.")
    if code in ("invalid_grant", "invalid_refresh_token", "refresh_token_expired", "refresh_token_reused",
                "refresh_token_invalidated", "token_expired"):
        return SignInError("Your ChatGPT connection has expired. Sign in with ChatGPT again in Settings.")
    return SignInError("ChatGPT sign-in failed (%s). Try again." % (code or status))


def chatgpt_sign_in(open_browser=None, cancel=None, timeout=TIMEOUT):
    """Browser sign-in with ChatGPT (Plus/Pro plan usage). Saves the session; returns it."""
    with _lock:
        prev = load_session()
    cfg = discovery()
    verifier, challenge = pkce_pair()
    state, nonce = _b64url(secrets.token_bytes(32)), _b64url(secrets.token_bytes(32))
    lst = _Listener("/auth/callback", state, host="127.0.0.1")    # ChatGPT requires 127.0.0.1 (any port)
    redirect = "http://127.0.0.1:%d/auth/callback" % lst.port
    client_id = prev.get("client_id") or "dynamic_agent_client"
    try:
        _open(chatgpt_auth_url(cfg["authorization_endpoint"], client_id, redirect, challenge, state, nonce,
                               prev.get("email", "")), open_browser)
        q = lst.wait(timeout, cancel)
    finally:
        lst.close()
    if "error" in q:
        raise _token_error(400, {"error": q.get("error")})
    code, issued = q.get("code"), q.get("client_id") or prev.get("client_id")
    if not code or not issued or issued == "dynamic_agent_client" or len(issued) > 200:
        raise SignInError("ChatGPT did not complete app registration. Please try signing in again.")
    with _lock:                                           # keep the registration even if the exchange fails
        save_session(dict(prev, client_id=issued))
    status, data = _request(cfg["token_endpoint"], {
        "grant_type": "authorization_code", "client_id": issued, "code": code, "code_verifier": verifier,
        "redirect_uri": redirect, "resource": CHATGPT_RESOURCE}, form=True)
    if status != 200:
        raise _token_error(status, data)
    claims = check_id_token(data.get("id_token"), issued, nonce)
    if prev.get("sub") and claims["sub"] != prev["sub"] and prev.get("refresh_token"):
        log.info("ChatGPT sign-in switched to a different account")
    fields = _token_fields(data)
    if PLAN_SCOPE not in fields["scopes"]:
        raise SignInError("You signed in, but didn't allow \"Use your ChatGPT plan\". Sign in again and allow it.")
    if not fields.get("refresh_token"):
        raise SignInError("ChatGPT didn't return a renewable connection. Please sign in again.")
    session = {"client_id": issued, "sub": claims["sub"], "email": claims.get("email", ""),
               "name": claims.get("name", ""), "saved_at": time.time(), **fields}
    with _lock:
        save_session(session)
    return session


def chatgpt_access_token(min_valid=60):
    """A valid access token, refreshing it when it's about to expire. Raises SignInError when signed out."""
    with _lock:
        s = load_session()
        if not s.get("refresh_token"):
            raise SignInError("Sign in with ChatGPT in Settings > AI assistant first.")
        if s.get("access_token") and s.get("expires_at", 0) - time.time() > min_valid:
            return s["access_token"]
        cfg = discovery()
        status, data = _request(cfg["token_endpoint"], {
            "grant_type": "refresh_token", "client_id": s["client_id"], "refresh_token": s["refresh_token"],
            "resource": CHATGPT_RESOURCE}, form=True)
        if status != 200:
            err = _token_error(status, data)
            if "expired" in str(err):
                s.pop("refresh_token", None)
                s.pop("access_token", None)
                save_session(s)
            raise err
        data.setdefault("scope", " ".join(s.get("scopes", [])))   # refresh may omit unchanged scopes
        fields = _token_fields(data)
        if data.get("id_token"):
            claims = check_id_token(data["id_token"], s["client_id"])
            if claims["sub"] != s.get("sub"):
                raise SignInError("The refreshed ChatGPT identity doesn't match. Sign in again.")
        s.update(fields)
        save_session(s)
        return s["access_token"]


def chatgpt_sign_out():
    """Forget the tokens (keeps the app registration) and revoke the renewable session at OpenAI."""
    with _lock:
        s = load_session()
        token = s.get("refresh_token")
        keep = {k: s[k] for k in ("client_id", "email") if k in s}
        save_session(keep)
    if not token:
        return True
    try:
        rv = discovery().get("revocation_endpoint")
        if rv:
            status, _ = _request(rv, {"token": token, "token_type_hint": "refresh_token",
                                      "client_id": s.get("client_id", "")}, form=True, timeout=10)
            return status == 200
    except SignInError:
        pass
    return False


def free_port():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]

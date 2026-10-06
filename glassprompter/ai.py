"""AI assistant: chat about your script and (optionally) what's on your screen, using Claude.

Bring your own Anthropic API key (Settings > AI assistant). It is stored in ai.key in the data folder. Requests go straight from this computer to api.anthropic.com;
nothing passes through any other server. The phone never sees the key.
"""
import base64
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

API = "https://api.anthropic.com/v1/messages"
MODELS = {
    "claude-sonnet-5-5": "Sonnet 5.5 \u00b7 best value",
    "claude-opus-5-5": "Opus 5.5 \u00b7 smartest",
    "claude-haiku-4-5-20251001": "Haiku 4.5 \u00b7 fastest",
}
MAX_TURNS = 12

SYSTEM = (
    "You are a capable general-purpose assistant built into Glass Prompter, a see-through teleprompter. "
    "Answer ANY question the user asks, on any subject (homework, work, coding, finance, writing, general "
    "knowledge, current events), accurately and completely, like a top expert would. Use web search when the "
    "answer depends on recent or changing facts, and say briefly where the information came from. "
    "The user may attach a screenshot of their computer screen: when they do, read it carefully and use it to answer "
    "(e.g. 'what does this error mean', 'solve this question', 'summarise this page'). If the screen isn't relevant, "
    "ignore it. Never read out passwords, keys or other secrets you see on screen. "
    "Get to the point: lead with the answer, then the essential detail. Use short paragraphs or simple lists; avoid "
    "heavy markdown. When the user asks for lines to say out loud or for the prompter, write plain sentences. "
    "Prompter markers, if useful: '# Heading' starts a section, '[PAUSE]' stops scrolling, '[CUE]' is a stage "
    "direction.")
WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}


class AIError(Exception):
    pass


# ---- the API key lives in its own file in the data folder (never in settings.json, never in the repo or phone)
KEY_FILE = "ai.key"
ENV_KEY = "GLASSPROMPTER_AI_KEY"


def key_path():
    import os
    from . import paths
    return os.path.join(paths.data_dir(), KEY_FILE)


def load_key():
    import os
    env = os.environ.get(ENV_KEY, "").strip()
    if env:
        return env
    try:
        with open(key_path(), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_key(key):
    import os
    key = (key or "").strip()
    path = key_path()
    if not key:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)     # owner-only on macOS/Linux
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key)
    os.replace(tmp, path)


def _clean(messages):
    out = []
    for m in (messages or [])[-MAX_TURNS:]:
        role = m.get("role")
        text = str(m.get("content", ""))[:8000]
        if role in ("user", "assistant") and text.strip():
            if out and out[-1]["role"] == role:            # the API needs alternating turns
                out[-1]["content"] += "\n\n" + text
            else:
                out.append({"role": role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if not out or out[-1]["role"] != "user":
        raise AIError("Send a message first.")
    return out


def build_request(messages, model, screen_jpeg=None, script_title="", script_text="", web=True):
    msgs = _clean(messages)
    system = SYSTEM
    if script_text.strip():
        system += ("\n\nFor context only (use it when the question is about their script), the script currently on "
                   "the prompter (%s):\n<script>\n%s\n</script>") % (
            script_title or "untitled", script_text[:12000])
    if screen_jpeg:
        last = msgs[-1]
        last["content"] = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(screen_jpeg).decode("ascii")}},
            {"type": "text", "text": "(Screenshot of my computer screen right now.)\n\n" + last["content"]},
        ]
    body = {"model": model or "claude-sonnet-5-5", "max_tokens": 2500, "system": system, "messages": msgs}
    if web:
        body["tools"] = [dict(WEB_SEARCH)]
    return body


def _post(key, body, timeout):
    from .updater import tls_context
    req = urllib.request.Request(API, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "x-api-key": key.strip(), "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=tls_context()) as r:
        return json.loads(r.read().decode("utf-8"))


def _error_detail(e):
    try:
        return json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
    except Exception:
        return ""


def chat(key, messages, model=None, screen_jpeg=None, script_title="", script_text="", timeout=90, web=True):
    """Ask Claude. Returns the answer text. Raises AIError with a message a person can act on."""
    if not (key or "").strip():
        raise AIError("Add your Anthropic API key in Settings > AI assistant on your computer.")
    body = build_request(messages, model, screen_jpeg, script_title, script_text, web)
    try:
        try:
            data = _post(key, body, timeout)
        except urllib.error.HTTPError as e:
            detail = _error_detail(e)
            if e.code == 400 and web and ("tool" in detail.lower() or "web_search" in detail.lower()):
                log.info("Web search not available (%s); answering without it", detail[:120])
                body.pop("tools", None)                           # account without web search: answer anyway
                data = _post(key, body, timeout)
            else:
                e.detail = detail
                raise
    except urllib.error.HTTPError as e:
        detail = getattr(e, "detail", None) or _error_detail(e)
        if e.code == 401:
            raise AIError("The API key was rejected. Check it in Settings > AI assistant.")
        if e.code == 429:
            raise AIError("Too many requests or no credit left on your Anthropic account. Try again shortly.")
        if e.code == 529:
            raise AIError("Claude is busy right now. Try again in a few seconds.")
        raise AIError(("AI request failed (%s). %s" % (e.code, detail))[:300])
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AIError("Couldn't reach the AI service. Is this computer online? (%s)" % e)
    content = list(data.get("content", []))
    for _ in range(2):                          # long web searches can pause; let Claude continue its turn
        if data.get("stop_reason") != "pause_turn":
            break
        body["messages"] = body["messages"] + [{"role": "assistant", "content": data.get("content", [])}]
        try:
            data = _post(key, body, timeout)
        except (urllib.error.URLError, TimeoutError, OSError):
            break
        content += data.get("content", [])
    text = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
    if not text:
        raise AIError("The AI returned an empty answer. Try asking again.")
    return text

"""AI assistant: chat about anything, optionally showing the AI your screen and the script on the prompter.

Bring your own key from almost any AI provider: Anthropic (Claude), OpenAI (ChatGPT), Google (Gemini), xAI (Grok),
DeepSeek, Mistral, Groq, Perplexity, Together, OpenRouter (hundreds of models with one key), a local Ollama model, or
any other OpenAI-compatible server. The key is stored in ai.key in the data folder, never in settings.json, the repo or
the phone. Requests go straight from this computer to the provider you chose; nothing passes through any other server.

Models are never hard-coded: the app asks the provider for its current model list and picks the best one, so new
models work the day they ship. You can also pick or type a model yourself.
"""
import base64
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ providers
# kind: which wire format to speak. "openai" covers every OpenAI-compatible API.
PROVIDERS = {
    "anthropic": dict(name="Anthropic Claude", kind="anthropic", base="https://api.anthropic.com/v1",
                      keys="https://console.anthropic.com/settings/keys", prefix=("sk-ant-",)),
    "openai": dict(name="OpenAI (ChatGPT)", kind="openai", base="https://api.openai.com/v1",
                   keys="https://platform.openai.com/api-keys", prefix=("sk-proj-", "sk-svcacct-", "sk-")),
    "gemini": dict(name="Google Gemini", kind="gemini", base="https://generativelanguage.googleapis.com/v1beta",
                   keys="https://aistudio.google.com/apikey", prefix=("AIza",)),
    "openrouter": dict(name="OpenRouter (hundreds of models)", kind="openai", base="https://openrouter.ai/api/v1",
                       keys="https://openrouter.ai/keys", prefix=("sk-or-",), default="openrouter/auto"),
    "xai": dict(name="xAI Grok", kind="openai", base="https://api.x.ai/v1", keys="https://console.x.ai",
                prefix=("xai-",)),
    "deepseek": dict(name="DeepSeek", kind="openai", base="https://api.deepseek.com/v1",
                     keys="https://platform.deepseek.com/api_keys", prefix=(), default="deepseek-chat"),
    "mistral": dict(name="Mistral", kind="openai", base="https://api.mistral.ai/v1",
                    keys="https://console.mistral.ai/api-keys", prefix=(), default="mistral-large-latest"),
    "groq": dict(name="Groq", kind="openai", base="https://api.groq.com/openai/v1",
                 keys="https://console.groq.com/keys", prefix=("gsk_",)),
    "perplexity": dict(name="Perplexity", kind="openai", base="https://api.perplexity.ai",
                       keys="https://www.perplexity.ai/settings/api", prefix=("pplx-",), default="sonar-pro"),
    "together": dict(name="Together AI", kind="openai", base="https://api.together.xyz/v1",
                     keys="https://api.together.ai/settings/api-keys", prefix=()),
    "ollama": dict(name="Ollama (free, runs on this computer)", kind="openai", base="http://localhost:11434/v1",
                   keys="https://ollama.com/download", prefix=(), nokey=True),
    "custom": dict(name="Other (OpenAI-compatible URL)", kind="openai", base="", keys="", prefix=()),
}
AUTO = "auto"

# Generous limits: long answers and long conversations. You only pay for tokens actually used.
MAX_TURNS = 40                 # messages of history sent with each question
MAX_MESSAGE_CHARS = 30000
MAX_SCRIPT_CHARS = 60000
DEFAULT_MAX_TOKENS = 16000     # longest answer; providers that allow less are retried with a smaller limit
ANSWER_LENGTHS = {2000: "Short", 8000: "Long", 16000: "Very long (default)", 32000: "Maximum"}
TIMEOUT = 240

# kept for compatibility with 2.5.x settings and the phone/desktop labels
MODELS = {
    "claude-sonnet-5-5": "Sonnet 5.5 · best value",
    "claude-opus-5-5": "Opus 5.5 · smartest",
    "claude-haiku-4-5-20251001": "Haiku 4.5 · fastest",
}

SYSTEM = (
    "You are a capable general-purpose assistant built into Glass Prompter, a see-through teleprompter. "
    "Answer ANY question the user asks, on any subject (homework, work, coding, finance, writing, general "
    "knowledge, current events), accurately and completely, like a top expert would. Use web search when it is "
    "available and the answer depends on recent or changing facts, and say briefly where the information came from. "
    "The user may attach a screenshot of their computer screen: when they do, read it carefully and use it to answer "
    "(e.g. 'what does this error mean', 'solve this question', 'summarise this page'). If the screen isn't relevant, "
    "ignore it. Never read out passwords, keys or other secrets you see on screen. "
    "Lead with the answer, then give as much useful detail as the question deserves. Use short paragraphs or simple "
    "lists; avoid heavy markdown. When the user asks for lines to say out loud or for the prompter, write plain "
    "sentences. Prompter markers, if useful: '# Heading' starts a section, '[PAUSE]' stops scrolling, '[CUE]' is a "
    "stage direction.")
WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}


class AIError(Exception):
    pass


# ------------------------------------------------------------------ key storage
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


def clean_key(text):
    """Keys get mangled by copying: line breaks where the page wrapped them, spaces, quotes. Remove all of that."""
    return re.sub(r"\s+", "", str(text or "")).strip("\"'")


def save_key(key):
    import os
    key = clean_key(key)
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


# ------------------------------------------------------------------ provider resolution
def detect_provider(key):
    """Guess the provider from the key's prefix. Falls back to OpenAI for generic 'sk-' keys."""
    key = clean_key(key)
    best, best_len = None, 0
    for pid, p in PROVIDERS.items():
        for pre in p["prefix"]:
            if key.startswith(pre) and len(pre) > best_len:
                best, best_len = pid, len(pre)
    return best


def resolve(provider, key, base_url=""):
    """-> (provider id, provider dict, base url)."""
    pid = provider if provider in PROVIDERS else None
    if pid is None:                                   # "auto": the key's prefix decides; unknown keys -> OpenAI
        pid = detect_provider(key) or ("anthropic" if not clean_key(key) else "openai")
    p = PROVIDERS[pid]
    base = (base_url or "").strip().rstrip("/") if pid in ("custom", "ollama") and base_url else p["base"]
    if pid == "custom" and not base:
        raise AIError("Enter the server URL for your AI provider in Settings > AI assistant.")
    return pid, p, base


def provider_name(provider, key=""):
    try:
        return resolve(provider, key, "x")[1]["name"]
    except AIError:
        return PROVIDERS["custom"]["name"]


# ------------------------------------------------------------------ HTTP
def _http(url, body=None, headers=None, timeout=30):
    from .updater import tls_context
    data = None if body is None else json.dumps(body).encode("utf-8")
    h = {"content-type": "application/json", "user-agent": "GlassPrompter"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET", headers=h)
    ctx = tls_context() if url.startswith("https") else None
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _error_detail(e):
    try:
        raw = e.read().decode("utf-8", "replace")
    except Exception:
        return ""
    try:
        d = json.loads(raw)
        err = d.get("error", d)
        if isinstance(err, list) and err:
            err = err[0].get("error", err[0])
        if isinstance(err, dict):
            return str(err.get("message") or err.get("msg") or err)[:300]
        return str(err)[:300]
    except Exception:
        return raw[:300]


def _auth_headers(pid, p, key):
    if p["kind"] == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    if p["kind"] == "gemini":
        return {"x-goog-api-key": key}
    h = {"authorization": "Bearer " + key} if key else {}
    if pid == "openrouter":
        h.update({"HTTP-Referer": "https://tokunboajayi.github.io/glass-prompter/", "X-Title": "Glass Prompter"})
    return h


# ------------------------------------------------------------------ models
_SKIP = re.compile(r"(embed|audio|realtime|transcri|tts|speech|whisper|image|dall|vision-preview|moderation|"
                   r"search-preview|live|instruct|babbage|davinci|guard|rerank|aqa|computer-use|codex|"
                   r"-native-audio|robotics|veo|imagen|lyria)", re.I)
_cache = {}


def list_models(provider, key, base_url="", timeout=20):
    """Ask the provider for its current chat models (newest/best first). Raises urllib/HTTP errors."""
    key = clean_key(key)
    pid, p, base = resolve(provider, key, base_url)
    ck = (pid, base, key[-8:])
    if ck in _cache and time.time() - _cache[ck][0] < 3600:
        return _cache[ck][1]
    hdr = _auth_headers(pid, p, key)
    if p["kind"] == "gemini":
        data = _http(base + "/models?pageSize=200", headers=hdr, timeout=timeout)
        rows = [m for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
        ids = [m["name"].split("/", 1)[-1] for m in rows]
    else:
        data = _http(base + "/models" + ("?limit=100" if p["kind"] == "anthropic" else ""), headers=hdr,
                     timeout=timeout)
        rows = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
        ids = [str(m.get("id") or m.get("name") or "") for m in rows if isinstance(m, dict)]
        created = {str(m.get("id")): m.get("created") or m.get("created_at") or 0 for m in rows if isinstance(m, dict)}
    ids = [i for i in ids if i and not _SKIP.search(i)]
    ids = _rank(pid, ids, created if p["kind"] != "gemini" else {})
    _cache[ck] = (time.time(), ids)
    return ids


def _version(s):
    nums = re.findall(r"(\d+(?:\.\d+)?)", s)
    return tuple(float(n) for n in nums[:2]) if nums else (0.0,)


# whole words only ("gemini" contains "mini"!)
_SMALL = re.compile(r"(?:^|[-_.:/])(?:mini|nano|lite|small|tiny|haiku|flash-8b|\d{1,2}b)(?=$|[-_.:/])")
_UNSTABLE = re.compile(r"(?:^|[-_.:/])(?:preview|exp|experimental|beta|test)(?=$|[-_.:/\d])")


def _when(v):
    """created / created_at as a number: unix seconds, or an ISO date like 2026-09-29 (Anthropic)."""
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    return float(m.group(1) + m.group(2) + m.group(3)) if m else 0.0


def _rank(pid, ids, created):
    """Best first: full-size before mini/lite/nano, stable before preview, the provider's main line first
    (Sonnet for Claude, Pro for Gemini), then the newest generation / newest release."""
    def score(i):
        low = i.lower()
        small = bool(_SMALL.search(low))
        unstable = bool(_UNSTABLE.search(low))
        if pid == "anthropic":
            tier = 0 if "sonnet" in low else 1 if "opus" in low else 2
        elif pid == "gemini":
            tier = 0 if "pro" in low else 1 if "flash" in low else 2
        else:
            tier = 0
        return (small, unstable, tier, -_version(low)[0], -_when(created.get(i)))
    try:
        return sorted(ids, key=score)
    except Exception:                                  # noqa: BLE001 - never fail on an odd list
        return ids


def pick_model(provider, key, model="", base_url=""):
    """The model to use: the user's choice, else the provider's best current model."""
    pid, p, base = resolve(provider, key, base_url)
    model = (model or "").strip()
    if model and (pid != "anthropic" and not model.startswith("claude") or pid == "anthropic"):
        return model
    if p.get("default"):
        return p["default"]
    try:
        ids = list_models(pid, key, base)
    except Exception as e:                                  # noqa: BLE001
        raise AIError("Couldn't get the model list from %s (%s). Type a model name in Settings > AI assistant."
                      % (p["name"], e))
    if not ids:
        raise AIError("%s returned no chat models. Type a model name in Settings > AI assistant." % p["name"])
    return ids[0]


def _bad_key(code, detail):
    low = (detail or "").lower()
    return code in (401, 403) or (code == 400 and any(t in low for t in ("api key", "api_key", "apikey",
                                                                          "incorrect key", "invalid key",
                                                                          "authentication", "unauthorized")))


def check_key(key, provider=AUTO, base_url="", timeout=20):
    """Does this key work? Uses free calls (model list / key info) where the provider has them, else a 1-token
    request. -> (ok, message for a person)."""
    key = clean_key(key)
    try:
        pid, p, base = resolve(provider, key, base_url)
    except AIError as e:
        return False, str(e)
    if not key and not p.get("nokey"):
        return False, "No key yet."
    _cache.pop((pid, base, key[-8:]), None)
    hdr = _auth_headers(pid, p, key)
    try:
        if pid == "openrouter":                       # OpenRouter's model list is public; ask about the key itself
            _http(base + "/key", headers=hdr, timeout=timeout)
        try:
            n = len(list_models(pid, key, base, timeout))
            return True, "Key works \u00b7 %s \u00b7 %d models" % (p["name"], n)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            # no model list on this provider (e.g. Perplexity): a 1-token request instead
            body = _openai_body(pid, pick_model(pid, key, "", base), [{"role": "user", "content": "hi"}],
                                None, "", "", 1)
            _http(base + "/chat/completions", body, hdr, timeout)
            return True, "Key works \u00b7 %s" % p["name"]
    except urllib.error.HTTPError as e:
        detail = _error_detail(e)
        if _bad_key(e.code, detail):
            return False, ("%s rejected this key (%d characters). Copy the whole key again, or pick the right "
                           "provider." % (p["name"], len(key)))
        if e.code in (402, 429):
            return False, "The key is valid, but the account has no credit left or is rate-limited."
        return False, "%s answered %s: %s" % (p["name"], e.code, detail[:160])
    except AIError as e:
        return False, str(e)
    except (urllib.error.URLError, TimeoutError, OSError):
        if pid == "ollama":
            return False, "Ollama isn't running on this computer. Install it from ollama.com and start it."
        return False, "Couldn't reach %s. Is this computer online?" % p["name"]


# ------------------------------------------------------------------ requests
def _clean(messages):
    out = []
    for m in (messages or [])[-MAX_TURNS:]:
        role = m.get("role")
        text = str(m.get("content", ""))[:MAX_MESSAGE_CHARS]
        if role in ("user", "assistant") and text.strip():
            if out and out[-1]["role"] == role:            # most APIs need alternating turns
                out[-1]["content"] += "\n\n" + text
            else:
                out.append({"role": role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if not out or out[-1]["role"] != "user":
        raise AIError("Send a message first.")
    return out


def _system(script_title, script_text):
    s = SYSTEM
    if (script_text or "").strip():
        s += ("\n\nFor context only (use it when the question is about their script), the script currently on "
              "the prompter (%s):\n<script>\n%s\n</script>") % (script_title or "untitled",
                                                                  script_text[:MAX_SCRIPT_CHARS])
    return s


SCREEN_NOTE = "(Screenshot of my computer screen right now.)\n\n"


def build_request(messages, model, screen_jpeg=None, script_title="", script_text="", web=True,
                  max_tokens=DEFAULT_MAX_TOKENS):
    """Anthropic Messages API body (kept as a public helper; tests use it)."""
    msgs = _clean(messages)
    if screen_jpeg:
        last = msgs[-1]
        last["content"] = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(screen_jpeg).decode("ascii")}},
            {"type": "text", "text": SCREEN_NOTE + last["content"]},
        ]
    body = {"model": model or "claude-sonnet-5-5", "max_tokens": int(max_tokens),
            # prompt caching: the system prompt + script is reused across a conversation, so later questions are
            # cheaper and faster
            "system": [{"type": "text", "text": _system(script_title, script_text),
                        "cache_control": {"type": "ephemeral"}}],
            "messages": msgs}
    if web:
        body["tools"] = [dict(WEB_SEARCH)]
    return body


def _openai_body(pid, model, messages, screen_jpeg, script_title, script_text, max_tokens):
    msgs = [{"role": "system", "content": _system(script_title, script_text)}] + _clean(messages)
    if screen_jpeg:
        last = msgs[-1]
        last["content"] = [
            {"type": "text", "text": SCREEN_NOTE + last["content"]},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,"
                                                + base64.b64encode(screen_jpeg).decode("ascii")}},
        ]
    body = {"model": model, "messages": msgs}
    if max_tokens:
        body["max_completion_tokens" if pid == "openai" else "max_tokens"] = int(max_tokens)
    return body


def _gemini_body(messages, screen_jpeg, script_title, script_text, max_tokens, web):
    contents = []
    for m in _clean(messages):
        contents.append({"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]})
    if screen_jpeg:
        contents[-1]["parts"] = [{"inline_data": {"mime_type": "image/jpeg",
                                                  "data": base64.b64encode(screen_jpeg).decode("ascii")}},
                                 {"text": SCREEN_NOTE + contents[-1]["parts"][0]["text"]}]
    body = {"systemInstruction": {"parts": [{"text": _system(script_title, script_text)}]}, "contents": contents}
    if max_tokens:
        body["generationConfig"] = {"maxOutputTokens": int(max_tokens)}
    if web:
        body["tools"] = [{"google_search": {}}]
    return body


def _friendly(pid, p, key, e, detail):
    name = p["name"]
    if _bad_key(e.code, detail):
        return ("%s rejected the API key (%d characters). Paste the whole key again in Settings > AI assistant and "
                "wait for 'Key works'." % (name, len(key)))
    if e.code == 404:
        return "%s doesn't have that model. Pick another in Settings > AI assistant. (%s)" % (name, detail)
    if e.code in (402, 429):
        return "Too many requests, or no credit left on your %s account. Try again shortly." % name
    if e.code in (500, 502, 503, 529):
        return "%s is busy right now. Try again in a few seconds." % name
    return ("%s request failed (%s). %s" % (name, e.code, detail))[:400]


def chat(key, messages, model=None, screen_jpeg=None, script_title="", script_text="", timeout=TIMEOUT, web=True,
         provider=AUTO, base_url="", max_tokens=DEFAULT_MAX_TOKENS):
    """Ask the AI. Returns the answer text. Raises AIError with a message a person can act on."""
    key = clean_key(key)
    pid, p, base = resolve(provider, key, base_url)
    if not key and not p.get("nokey"):
        raise AIError("Add your AI API key in Settings > AI assistant on your computer.")
    model = pick_model(pid, key, model, base)
    hdr = _auth_headers(pid, p, key)
    note = ""
    tokens = int(max_tokens or DEFAULT_MAX_TOKENS)
    image, use_web = screen_jpeg, web
    for _attempt in range(5):                     # adapt to what this provider/model accepts, then give up
        try:
            if p["kind"] == "anthropic":
                body = build_request(messages, model, image, script_title, script_text, use_web, tokens)
                data = _http(base + "/messages", body, hdr, timeout)
                content = list(data.get("content", []))
                for _ in range(2):                # long web searches can pause; let Claude continue its turn
                    if data.get("stop_reason") != "pause_turn":
                        break
                    body["messages"] = body["messages"] + [{"role": "assistant", "content": data.get("content", [])}]
                    data = _http(base + "/messages", body, hdr, timeout)
                    content += data.get("content", [])
                text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            elif p["kind"] == "gemini":
                body = _gemini_body(messages, image, script_title, script_text, tokens, use_web)
                url = "%s/models/%s:generateContent" % (base, urllib.parse.quote(model, safe="-._"))
                data = _http(url, body, hdr, timeout)
                cand = (data.get("candidates") or [{}])[0]
                text = "".join(part.get("text", "") for part in cand.get("content", {}).get("parts", []))
                if not text and cand.get("finishReason") == "SAFETY":
                    raise AIError("Gemini declined to answer that (safety filter).")
            else:
                body = _openai_body(pid, model, messages, image, script_title, script_text, tokens)
                data = _http(base + "/chat/completions", body, hdr, timeout)
                msg = (data.get("choices") or [{}])[0].get("message", {})
                text = msg.get("content") or ""
                if isinstance(text, list):
                    text = "".join(c.get("text", "") for c in text if isinstance(c, dict))
            text = (text or "").strip()
            if not text:
                raise AIError("The AI returned an empty answer. Try asking again.")
            return (note + text) if note else text
        except urllib.error.HTTPError as e:
            detail = _error_detail(e)
            low = detail.lower()
            if e.code == 400 and use_web and any(t in low for t in ("tool", "web_search", "google_search", "search")):
                use_web = False                                   # account/model without web search
                continue
            if e.code in (400, 413, 422) and image is not None and any(
                    t in low for t in ("image", "vision", "multimodal", "content type", "image_url", "inline_data")):
                image = None                                      # text-only model: answer without the screenshot
                note = "(This model can't see images, so I answered from your text only.)\n\n"
                continue
            if e.code in (400, 422) and tokens > 1024 and any(
                    t in low for t in ("max_tokens", "max_completion_tokens", "maxoutputtokens", "max output",
                                       "token", "too large", "exceed", "context length")):
                tokens = max(1024, tokens // 2)                   # the model allows a shorter answer
                continue
            raise AIError(_friendly(pid, p, key, e, detail))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if pid == "ollama":
                raise AIError("Ollama isn't running on this computer. Start it, then try again.")
            raise AIError("Couldn't reach %s. Is this computer online? (%s)" % (p["name"], e))
    raise AIError("%s couldn't answer with these settings. Try another model in Settings > AI assistant." % p["name"])

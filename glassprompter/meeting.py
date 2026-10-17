"""Meeting copilot logic: live transcript, question detection, AI prompts, modes, knowledge and meeting history.

No Qt here, so it's fully testable headless. The audio side lives in listen.py and the window in ui/copilot.py.

Everything stays on this computer: speech is recognized offline (Vosk), the transcript and notes are kept in
meetings.db in the data folder, and the AI only sees the conversation when you press an action (or when Smart mode
spots a question someone asked you).
"""
import json
import os
import re
import sqlite3
import time

from . import paths

ME, THEM = "you", "them"
LABELS = {ME: "You", THEM: "Them"}

MAX_TRANSCRIPT_CHARS = 24000          # recent conversation sent with each request (the tail matters most)
MAX_KNOWLEDGE_CHARS = 40000           # all knowledge files together
KNOWLEDGE_EXT = (".txt", ".md", ".docx")

# ------------------------------------------------------------------ modes
# Each mode tells the AI who you are in this conversation and what good help looks like.
MODES = {
    "meeting": ("General meeting",
                "The user is in a live meeting. Help them follow along, answer questions put to them, contribute "
                "useful points and keep track of decisions and action items."),
    "sales": ("Sales call",
              "The user is on a sales call. Help them understand the prospect's needs, handle objections honestly, "
              "explain value clearly, ask good discovery questions and agree on next steps. Never invent product "
              "facts, prices or commitments that aren't in their notes."),
    "presentation": ("Presentation & Q&A",
                     "The user is presenting. Help them answer audience questions clearly and briefly, recover if "
                     "they lose their place, and connect answers back to their main message."),
    "support": ("Customer support",
                "The user is helping a customer. Help them diagnose the problem, give accurate step-by-step "
                "fixes from their notes, stay calm and empathetic, and confirm the issue is resolved."),
    "negotiation": ("Negotiation",
                    "The user is negotiating. Help them spot the other side's interests, keep to their goals and "
                    "limits from their notes, suggest fair trade-offs and avoid conceding too early."),
    "learning": ("Lecture & learning",
                 "The user is attending a class, webinar or talk. Explain unfamiliar terms simply, summarise what "
                 "was said and suggest good questions to ask the speaker."),
}
DEFAULT_MODE = "meeting"


def custom_modes(raw):
    """Settings hold custom modes as [{"name": ..., "prompt": ...}]; drop anything malformed."""
    out = []
    for m in raw or []:
        if isinstance(m, dict) and str(m.get("name", "")).strip() and str(m.get("prompt", "")).strip():
            out.append({"name": str(m["name"]).strip()[:60], "prompt": str(m["prompt"]).strip()[:4000]})
    return out


def all_modes(raw_custom=()):
    """-> [(id, name, prompt)]: built-ins, then custom modes with ids "custom:<name>"."""
    rows = [(k, v[0], v[1]) for k, v in MODES.items()]
    rows += [("custom:" + m["name"], m["name"], m["prompt"]) for m in custom_modes(raw_custom)]
    return rows


def mode_prompt(mode_id, raw_custom=()):
    for mid, _name, prompt in all_modes(raw_custom):
        if mid == mode_id:
            return prompt
    return MODES[DEFAULT_MODE][1]


def mode_name(mode_id, raw_custom=()):
    for mid, name, _prompt in all_modes(raw_custom):
        if mid == mode_id:
            return name
    return MODES[DEFAULT_MODE][0]


# ------------------------------------------------------------------ knowledge
def read_knowledge(files, limit=MAX_KNOWLEDGE_CHARS):
    """Text of the user's knowledge files (notes, product sheets, agendas) -> [(name, text)], within `limit`."""
    from .scripts import read_file
    out, left = [], limit
    for path in files or []:
        if left <= 0:
            break
        try:
            if not os.path.isfile(path) or not path.lower().endswith(KNOWLEDGE_EXT):
                continue
            text = read_file(path)
        except Exception:                                # noqa: BLE001 - a bad file never blocks the copilot
            continue
        text = (text or "").strip()[:left]
        if text:
            out.append((os.path.basename(path), text))
            left -= len(text)
    return out


# ------------------------------------------------------------------ transcript
class Transcript:
    """The conversation so far: [{"t": seconds since start, "who": "you" | "them", "text": str}]."""

    def __init__(self, segments=None, started=None):
        self.started = started or time.time()
        self.segments = list(segments or [])

    def add(self, who, text, at=None):
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            return None
        who = who if who in LABELS else THEM
        t = round((at or time.time()) - self.started, 1)
        last = self.segments[-1] if self.segments else None
        if last and last["who"] == who and t - last["t"] < 4 and len(last["text"]) < 400:
            last["text"] += " " + text                    # one speaker, one breath: keep it a single line
            return last
        seg = {"t": t, "who": who, "text": text}
        self.segments.append(seg)
        return seg

    def words(self):
        return sum(len(s["text"].split()) for s in self.segments)

    def duration(self):
        return self.segments[-1]["t"] if self.segments else 0.0

    def last(self, who=None):
        for s in reversed(self.segments):
            if who is None or s["who"] == who:
                return s
        return None

    def render(self, limit=MAX_TRANSCRIPT_CHARS, stamps=False):
        lines = []
        for s in self.segments:
            stamp = "[%s] " % fmt_clock(s["t"]) if stamps else ""
            lines.append("%s%s: %s" % (stamp, LABELS[s["who"]], s["text"]))
        text = "\n".join(lines)
        if len(text) > limit:
            text = "…" + text[-limit:].split("\n", 1)[-1]
        return text

    def to_json(self):
        return json.dumps(self.segments)


def fmt_clock(secs):
    secs = int(secs or 0)
    return "%d:%02d:%02d" % (secs // 3600, secs // 60 % 60, secs % 60) if secs >= 3600 else \
        "%d:%02d" % (secs // 60, secs % 60)


# Offline speech has no punctuation, so questions are spotted by how they start (and by "?" when there is one).
_Q_START = re.compile(
    r"^(?:so |and |but |okay |ok |well |um |uh |right |also )*"
    r"(?:what|why|how|when|where|who|whom|whose|which|"
    r"can|could|would|will|should|shall|do|does|did|is|are|was|were|have|has|had|may|might|"
    r"tell me|walk me through|explain|describe|talk me through|any thoughts|thoughts on|"
    r"what's|whats|how's|hows|where's|who's|isn't|aren't|don't|doesn't|didn't|won't|wouldn't|couldn't)\b", re.I)
_Q_TAIL = re.compile(r"\b(?:right|correct|yeah|no|isn't it|don't you think|you know what i mean|"
                     r"any questions|make sense|sound good|thoughts)\s*\??$", re.I)


def is_question(text):
    """True when this line (usually from the other side) asks the user something."""
    t = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if len(t.split()) < 3:
        return False
    if t.endswith("?"):
        return True
    return bool(_Q_START.search(t) or _Q_TAIL.search(t))


# ------------------------------------------------------------------ AI prompts
ACTIONS = {
    "assist": ("Assist",
               "Work out what I most need right now. Usually that's an answer to the last question someone asked "
               "me, or the next useful thing for me to say. If my screen shows something relevant (a question, an "
               "error, a document), use it. Give me a few short lines I can say out loud, then at most two bullet "
               "points of supporting facts."),
    "say": ("What should I say?",
            "Suggest exactly what I should say next, in my own voice, as 1-3 short spoken sentences. No preamble."),
    "followups": ("Follow-up questions",
                  "Suggest 3-5 sharp follow-up questions I could ask now, based on what was just said. One line each."),
    "recap": ("Recap",
              "Recap the conversation so far in a few bullets: what was discussed, what was decided, and what's "
              "still open. Keep it short enough to read at a glance."),
    "factcheck": ("Fact-check",
                  "Check the factual claims made in the last few minutes of the conversation. For each one that "
                  "matters, say whether it's right, wrong or unclear, with a one-line correction or source."),
    "explain": ("Explain",
                "Explain any jargon, acronyms, names or concepts from the last few minutes that I might not know. "
                "One short line each."),
}
LIVE_TOKENS = 1500                     # live suggestions stay short and fast
NOTES_TOKENS = 6000

COPILOT_SYSTEM = (
    "You are the live meeting copilot in Glass Prompter. The user sees your answer on a small private overlay while "
    "they talk, so be brief and scannable: lead with what to say or do, use plain sentences or short bullets, no "
    "headings, no filler, no 'As an AI'. Lines labelled 'Them' are the other people (from the computer's audio); "
    "lines labelled 'You' are the user (their microphone). The transcript comes from offline speech recognition, so "
    "it has no punctuation and some words may be misheard: read it for meaning. Use the user's notes as the source "
    "of truth for facts about them, their company and their offer; never invent prices, commitments or personal "
    "facts. If you don't know, say so in a few words.")


def build_context(mode_id, raw_custom, transcript, knowledge=(), extra=""):
    """The system-prompt text added for every copilot request: mode, notes, knowledge files, transcript."""
    parts = [COPILOT_SYSTEM, "Mode: %s. %s" % (mode_name(mode_id, raw_custom), mode_prompt(mode_id, raw_custom))]
    if (extra or "").strip():
        parts.append("The user's notes for this conversation:\n<notes>\n%s\n</notes>" % extra.strip()[:8000])
    for name, text in knowledge or ():
        parts.append("Reference file '%s':\n<file>\n%s\n</file>" % (name, text))
    conv = transcript.render() if transcript is not None else ""
    parts.append("Live transcript so far (oldest first):\n<transcript>\n%s\n</transcript>"
                 % (conv or "(nothing has been said yet)"))
    return "\n\n".join(parts)


def action_message(action, question=""):
    """The user turn for a quick action. A detected question focuses Assist on it."""
    text = ACTIONS.get(action, ACTIONS["assist"])[1]
    if question:
        text = ("Someone just asked me: \"%s\". Give me a strong, honest answer I can say out loud in 2-4 short "
                "sentences, then up to two bullets of supporting facts." % question.strip()[:600])
    return text


def listen_context(transcript, limit=MAX_TRANSCRIPT_CHARS):
    """Extra system text for the AI assistant's normal chat while it listens to a meeting."""
    conv = transcript.render(limit=limit) if transcript is not None else ""
    if not conv:
        return ""
    return ("The user is in a live conversation and this assistant is listening. Lines labelled 'Them' are the "
            "other people (computer audio), 'You' is the user (microphone). The transcript comes from offline speech "
            "recognition, so it has no punctuation and may mishear words. Use it when the question is about the "
            "conversation.\n<transcript>\n%s\n</transcript>" % conv)


class SuggestionTrigger:
    """Decides when the assistant should offer help on its own while it listens.

    * Someone else asks a question -> suggest an answer (at most every `answer_gap` seconds).
    * The others have said `followup_words` words since the last suggestion, and `followup_gap` seconds have
      passed -> suggest follow-up questions the user could ask.
    Only lines from the other side count; the user's own speech never triggers anything.
    """

    def __init__(self, answer_gap=8.0, followup_gap=45.0, followup_words=60):
        self.answer_gap, self.followup_gap, self.followup_words = answer_gap, followup_gap, followup_words
        self.last = -1e9
        self.heard = 0

    def on_segment(self, who, text, now):
        """-> ("answer", question) | ("followups", "") | None."""
        if who != THEM:
            return None
        self.heard += len(str(text or "").split())
        if is_question(text) and now - self.last >= self.answer_gap:
            self.last, self.heard = now, 0
            return ("answer", text)
        if self.heard >= self.followup_words and now - self.last >= self.followup_gap:
            self.last, self.heard = now, 0
            return ("followups", "")
        return None


NOTES_PROMPT = (
    "The meeting has ended. Write the meeting notes from the transcript, using exactly these headings on their own "
    "lines:\n"
    "TITLE\n(a 3-8 word title)\n"
    "SUMMARY\n(3-5 sentences)\n"
    "KEY POINTS\n(bullets)\n"
    "DECISIONS\n(bullets, or 'None recorded')\n"
    "ACTION ITEMS\n(bullets: owner - task - due date if mentioned)\n"
    "OPEN QUESTIONS\n(bullets, or 'None')\n"
    "FOLLOW-UP EMAIL\n(a short, friendly follow-up email from the user to the other participants: subject line "
    "first as 'Subject: ...', then the body)\n"
    "Only use what's in the transcript and the user's notes; don't invent names, numbers or promises.")

NOTE_HEADINGS = ("TITLE", "SUMMARY", "KEY POINTS", "DECISIONS", "ACTION ITEMS", "OPEN QUESTIONS", "FOLLOW-UP EMAIL")


def parse_notes(text):
    """Split the AI's notes into {heading: body}. Tolerates markdown (#, **) around the headings."""
    out, cur = {}, None
    pat = re.compile(r"^[#*\s]*(%s)[*:\s]*$" % "|".join(re.escape(h) for h in NOTE_HEADINGS), re.I)
    for line in (text or "").splitlines():
        m = pat.match(line.strip())
        if m:
            cur = m.group(1).upper()
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def notes_markdown(notes):
    """The AI's notes with their plain headings (SUMMARY, ACTION ITEMS...) turned into Markdown headings."""
    parsed = parse_notes(notes)
    if not parsed:
        return (notes or "").strip()
    out = []
    for h in NOTE_HEADINGS:
        body = parsed.get(h, "").strip()
        if h != "TITLE" and body:
            body = "\n".join(line.rstrip() + "  " for line in body.splitlines())    # keep the email's line breaks
            out += ["### " + h.capitalize(), "", body, ""]
    return "\n".join(out).strip()


def save_notes(store, mid, reply):
    """Store the AI's notes (and the title and follow-up email it found) on meeting `mid`. Safe from any thread,
    so notes are kept even if the window that asked for them has closed."""
    parsed = parse_notes(reply)
    fields = {"notes": reply, "email": parsed.get("FOLLOW-UP EMAIL", "")}
    title = (parsed.get("TITLE") or "").strip().strip("\"'*# ")
    if title:
        fields["title"] = title.splitlines()[0][:80]
    store.update(mid, **fields)
    return fields


# ------------------------------------------------------------------ history
def meetings_path():
    return os.path.join(paths.data_dir(), "meetings.db")


class MeetingStore:
    """Past meetings: transcript, notes and follow-up email. SQLite in the data folder."""

    def __init__(self, path=None):
        self.db = sqlite3.connect(path or meetings_path(), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started REAL NOT NULL, ended REAL, title TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT '',
            transcript TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '')""")
        self.db.commit()

    @staticmethod
    def _row(r, full=True):
        d = dict(r)
        segs = json.loads(d.pop("transcript") or "[]") if "transcript" in d else []
        d["words"] = sum(len(s.get("text", "").split()) for s in segs)
        if full:
            d["segments"] = segs
        return d

    def create(self, started, mode, title=""):
        cur = self.db.execute("INSERT INTO meetings (started, mode, title) VALUES (?, ?, ?)",
                              (float(started), mode, title or default_title(started)))
        self.db.commit()
        return cur.lastrowid

    def update(self, mid, **fields):
        allowed = {"ended", "title", "mode", "transcript", "notes", "email"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        self.db.execute("UPDATE meetings SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in sets),
                        list(sets.values()) + [mid])
        self.db.commit()

    def get(self, mid):
        r = self.db.execute("SELECT * FROM meetings WHERE id = ?", (mid,)).fetchone()
        return self._row(r) if r else None

    def list(self, query=None, limit=300):
        if query:
            like = "%" + query.strip() + "%"
            rows = self.db.execute("SELECT * FROM meetings WHERE title LIKE ? OR notes LIKE ? OR transcript LIKE ? "
                                   "ORDER BY started DESC LIMIT ?", (like, like, like, limit)).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM meetings ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r, full=False) for r in rows]

    def delete(self, mid):
        self.db.execute("DELETE FROM meetings WHERE id = ?", (mid,))
        self.db.commit()

    def close(self):
        try:
            self.db.close()
        except Exception:                                # noqa: BLE001
            pass


def default_title(started):
    return time.strftime("Meeting %d %b %Y, %H:%M", time.localtime(started))


def to_markdown(m):
    """A meeting as a Markdown document (for export and 'Send to prompter')."""
    when = time.strftime("%A %d %B %Y, %H:%M", time.localtime(m["started"]))
    out = ["# %s" % (m.get("title") or default_title(m["started"])), "", "*%s*" % when, ""]
    if m.get("notes"):
        out += [notes_markdown(m["notes"]), ""]
    segs = m.get("segments") or []
    if segs:
        out += ["## Transcript", ""]
        out += ["**%s** \u00b7 %s  \n%s\n" % (LABELS.get(s.get("who"), "Them"), fmt_clock(s.get("t", 0)),
                                             s.get("text", "")) for s in segs]
    return "\n".join(out).strip() + "\n"

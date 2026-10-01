"""Pure prompter logic - no Qt, fully unit-tested.

Script markers (each on its own line):
  [PAUSE]     scrolling stops on this line until play is pressed
  [ANY CUE]   shown in the accent colour, upper-cased (e.g. [SMILE])
"""
import re
from dataclasses import dataclass

PAUSE_RE = re.compile(r"\[\s*pause\s*\]", re.I)
HEADING_RE = re.compile(r"#{1,6}\s*(.+)")
CUE_RE = re.compile(r"\[(.+)\]")
_INVISIBLE = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF), None)


@dataclass(frozen=True)
class Line:
    text: str
    kind: str        # text | cue | pause | section | blank | end


END_TEXT = chr(0x2014) + "  END  " + chr(0x2014)


def normalize(text):
    text = (text or "").translate(_INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    lines = [ln.rstrip() for ln in text.split("\n")]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def is_marker(line):
    s = line.strip()
    return bool(PAUSE_RE.fullmatch(s) or CUE_RE.fullmatch(s) or HEADING_RE.fullmatch(s))


def count_words(text):
    return sum(len(ln.split()) for ln in normalize(text).split("\n") if not is_marker(ln))


def title_from(text, limit=60):
    for ln in normalize(text).split("\n"):
        s = ln.strip()
        h = HEADING_RE.fullmatch(s)
        if h:
            s = h.group(1).strip()
        if s and (h or not is_marker(s)):
            return s if len(s) <= limit else s[: limit - 1].rstrip() + chr(0x2026)
    return "Untitled script"


def wrap(text, max_width, measure):
    """Word-wrap the script into display lines.

    measure(str) -> width in the same units as max_width. Words wider than the line
    are hard-broken so nothing ever overflows the panel.
    """
    out = []
    for para in normalize(text).split("\n"):
        s = para.strip()
        if not s:
            out.append(Line("", "blank"))
            continue
        if PAUSE_RE.fullmatch(s):
            out.append(Line("PAUSE", "pause"))
            continue
        h = HEADING_RE.fullmatch(s)
        if h:
            out.append(Line(h.group(1).strip().upper(), "section"))
            continue
        m = CUE_RE.fullmatch(s)
        kind = "text"
        if m:
            kind, s = "cue", m.group(1).strip().upper()
        line = ""
        for word in s.split():
            while measure(word) > max_width and len(word) > 1:      # hard-break very long tokens
                cut = len(word)
                while cut > 1 and measure(word[:cut]) > max_width:
                    cut -= 1
                if line:
                    out.append(Line(line, kind))
                    line = ""
                out.append(Line(word[:cut], kind))
                word = word[cut:]
            candidate = word if not line else line + " " + word
            if not line or measure(candidate) <= max_width:
                line = candidate
            else:
                out.append(Line(line, kind))
                line = word
        if line:
            out.append(Line(line, kind))
    out += [Line("", "blank"), Line(END_TEXT, "end")]
    return out


def sections(lines):
    """[(line_index, title)] for every '# Heading' in the script."""
    return [(i, ln.text) for i, ln in enumerate(lines) if ln.kind == "section"]


def word_map(lines):
    """Spoken-word index for Voice Follow.

    Returns (words, word_line, line_tokens): every normalized word in reading order, the display
    line each word sits on, and per line the cumulative word count after each space-separated token
    (used to highlight words that have already been said).
    """
    from .tracking import norm_words
    words, word_line, line_tokens = [], [], {}
    for i, ln in enumerate(lines):
        if ln.kind != "text":
            continue
        cum, ends = len(words), []
        for tok in ln.text.split(" "):
            nw = norm_words(tok)
            words.extend(nw)
            word_line.extend([i] * len(nw))
            cum += len(nw)
            ends.append(cum)
        line_tokens[i] = ends
    return words, word_line, line_tokens


def voice_target(word_line, cursor):
    """Scroll position (in lines) for Voice Follow when `cursor` is the last word spoken.

    Instead of snapping a whole line at a time, the text glides continuously: the current line passes
    through the reading band as you read it (slightly low as you start it, centred mid-line, slightly
    high as you finish), so the next words are always where your eyes already are.
    """
    if not word_line:
        return 0.0
    c = min(max(cursor, -1), len(word_line) - 1)
    if c < 0:
        return float(word_line[0])
    line = word_line[c]
    start = c
    while start > 0 and word_line[start - 1] == line:
        start -= 1
    end = c
    while end + 1 < len(word_line) and word_line[end + 1] == line:
        end += 1
    n = end - start + 1
    frac = (c - start + 1) / n                      # 0..1 through this line
    return max(0.0, line + (frac - 0.5) * 0.6)      # drift within +-0.3 line: smooth, never straddling


def words_per_line(lines):
    text_lines = [ln.text for ln in lines if ln.kind == "text"]
    if not text_lines:
        return 6.0
    return max(1.0, sum(len(t.split()) for t in text_lines) / len(text_lines))


def px_per_sec(wpm, wpl, line_height):
    """Scroll speed from a words-per-minute target, so pace is identical at any size or width."""
    return max(1e-6, wpm / 60.0 / max(1.0, wpl) * line_height)


def max_pos(lines, line_height):
    return max(0.0, (len(lines) - 1) * line_height)


def line_index(pos, line_height):
    return int(pos / line_height + 0.5)


def find_pause(lines, old_pos, new_pos, line_height):
    """Index of the first [PAUSE] line crossed moving from old_pos to new_pos, else None."""
    a = line_index(old_pos, line_height) + 1
    b = min(len(lines) - 1, line_index(new_pos, line_height))
    for i in range(a, b + 1):
        if lines[i].kind == "pause":
            return i
    return None


def fmt_secs(s):
    s = max(0, int(round(s)))
    return "%d:%02d" % (s // 60, s % 60)


_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"')\]”’]*\s+")


def speech_plan(lines):
    """Turn wrapped prompter lines into what Read Aloud says, in order.

    Returns a list of ("say", text, first_word, word_weights) and ("rest", seconds) items. first_word is the
    index into word_map()'s word list, so playback can light up the exact word being spoken; weights are
    per-word relative durations (longer words take longer to say).
    """
    from .tracking import norm_words
    plan, para, wi = [], [], 0

    def flush():
        nonlocal wi
        if not para:
            return
        for sentence in _SENTENCE_END.split(" ".join(para)):
            sentence = sentence.strip()
            words = norm_words(sentence)
            if not words:
                continue
            plan.append(("say", sentence, wi, [len(w) + 2 for w in words]))
            wi += len(words)
        para.clear()
        plan.append(("rest", 0.35))

    for ln in lines:
        if ln.kind == "text":
            para.append(ln.text)
            continue
        flush()
        if ln.kind == "pause":
            plan.append(("rest", 1.2))
        elif ln.kind == "section":
            plan.append(("rest", 0.6))
    flush()
    while plan and plan[-1][0] == "rest":
        plan.pop()
    return plan

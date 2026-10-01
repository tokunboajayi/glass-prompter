"""Pure prompter logic - no Qt, fully unit-tested.

Script markers (each on its own line):
  [PAUSE]     scrolling stops on this line until play is pressed
  [ANY CUE]   shown in the accent colour, upper-cased (e.g. [SMILE])
"""
import re
from dataclasses import dataclass

PAUSE_RE = re.compile(r"\[\s*pause\s*\]", re.I)
CUE_RE = re.compile(r"\[(.+)\]")
_INVISIBLE = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF), None)


@dataclass(frozen=True)
class Line:
    text: str
    kind: str        # text | cue | pause | blank | end


END_TEXT = chr(0x2014) + "  END  " + chr(0x2014)


def normalize(text):
    text = (text or "").translate(_INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    lines = [ln.rstrip() for ln in text.split("\n")]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def is_marker(line):
    s = line.strip()
    return bool(PAUSE_RE.fullmatch(s) or CUE_RE.fullmatch(s))


def count_words(text):
    return sum(len(ln.split()) for ln in normalize(text).split("\n") if not is_marker(ln))


def title_from(text, limit=60):
    for ln in normalize(text).split("\n"):
        s = ln.strip()
        if s and not is_marker(s):
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

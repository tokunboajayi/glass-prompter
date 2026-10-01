"""Voice Follow alignment - pure logic, no audio, fully unit-tested.

The recognizer gives us the last few words it heard. We find where those words best match
the script near the current position and move the cursor there. Small forward steps need
little evidence; big jumps or going backwards need more, so off-script chatter or a cough
can't yank the prompter around.
"""
import difflib
import re

_WORD = re.compile(r"[a-z0-9']+")


def norm_words(text):
    return _WORD.findall((text or "").lower().replace(chr(0x2019), "'"))


def similar(a, b):
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4:
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8
    return False


class Aligner:
    def __init__(self, words, back=16, ahead=40):
        self.words = list(words)
        self.back, self.ahead = back, ahead
        self.cursor = -1                     # index of the last word confirmed as spoken

    def reset(self, cursor=-1):
        self.cursor = cursor

    def _score_ending_at(self, tail, j):
        """How many of the heard words line up with the script ending at word j (allows small slips)."""
        score, i, k, slips = 0, len(tail) - 1, j, 0
        while i >= 0 and k >= 0 and slips <= 2:
            if similar(tail[i], self.words[k]):
                score += 1
                i -= 1
                k -= 1
            elif i - 1 >= 0 and similar(tail[i - 1], self.words[k]):      # an extra heard word
                i -= 1
                slips += 1
            elif k - 1 >= 0 and similar(tail[i], self.words[k - 1]):      # a skipped script word
                k -= 1
                slips += 1
            else:
                break
        return score

    def update(self, heard):
        """Feed the most recent recognized words; returns the (possibly moved) cursor."""
        tail = [w for w in heard if w][-8:]
        if not tail or not self.words:
            return self.cursor
        lo = max(0, self.cursor - self.back)
        hi = min(len(self.words) - 1, self.cursor + self.ahead)
        best_key, best_j = None, None
        for j in range(lo, hi + 1):
            if not similar(tail[-1], self.words[j]):     # the newest word must be the one at the cursor
                continue
            s = self._score_ending_at(tail, j)
            if s == 0:
                continue
            key = (s, -abs(j - (self.cursor + 1)))
            if best_key is None or key > best_key:
                best_key, best_j = key, j
        if best_j is None or best_j == self.cursor:
            return self.cursor
        score, jump = best_key[0], best_j - self.cursor
        if jump < 0:
            need = 3                 # re-reading earlier lines needs strong evidence
        elif jump <= 3:
            need = 1
        elif jump <= 12:
            need = 2
        else:
            need = 3
        if score >= need:
            self.cursor = best_j
        return self.cursor

    @property
    def done(self):
        return bool(self.words) and self.cursor >= len(self.words) - 1

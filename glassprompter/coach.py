"""Rehearsal Coach - pure scoring logic (no audio, no Qt), fully unit-tested.

Fed by Voice Follow: finished utterances from the recognizer, and cursor moves from the aligner.
Produces a report card: pace, filler words, pauses, skipped words and a 0-100 score with one tip.
"""
from dataclasses import dataclass, field

FILLERS = {"um", "uh", "er", "erm", "ah", "hmm", "like", "basically", "actually", "literally"}
FILLER_PHRASES = {("you", "know"), ("i", "mean"), ("sort", "of"), ("kind", "of")}
GOOD_PACE = (130, 165)            # comfortable presenting range, words per minute
LONG_PAUSE = 3.0                  # seconds of no recognized speech


@dataclass
class Coach:
    script_words: list
    started: float = 0.0
    last_speech: float = 0.0
    spoken: int = 0
    fillers: dict = field(default_factory=dict)
    longest_pause: float = 0.0
    long_pauses: int = 0
    reached: int = -1
    skipped: int = 0

    def start(self, t, cursor=-1):
        self.started = self.last_speech = t
        self.reached = cursor

    def on_utterance(self, words, t):
        """A finished phrase from the recognizer."""
        if not words:
            return
        gap = t - self.last_speech
        if self.spoken and gap > LONG_PAUSE:
            self.long_pauses += 1
            self.longest_pause = max(self.longest_pause, gap)
        self.last_speech = t
        script_vocab = set(self.script_words)
        prev = None
        for w in words:
            if w in FILLERS and not self._in_script_context(w, script_vocab):
                self.fillers[w] = self.fillers.get(w, 0) + 1
            if prev and (prev, w) in FILLER_PHRASES and not self._phrase_in_script(prev, w):
                key = prev + " " + w
                self.fillers[key] = self.fillers.get(key, 0) + 1
            prev = w
        self.spoken += len(words)

    def _in_script_context(self, w, vocab):
        # "like"/"actually"/"literally" can be real script words; only count them if the script never uses them
        return w in vocab and w not in {"um", "uh", "er", "erm", "ah", "hmm"}

    def _phrase_in_script(self, a, b):
        sw = self.script_words
        return any(sw[i] == a and sw[i + 1] == b for i in range(len(sw) - 1))

    def on_cursor(self, old, new):
        """Aligner moved: a forward jump of more than 3 words means lines were skipped."""
        if new - old > 3:
            self.skipped += new - old - 1
        self.reached = max(self.reached, new)

    def report(self, t, prev_scores=()):
        minutes = max(1e-6, (t - self.started) / 60.0)
        covered = max(0, self.reached + 1)
        wpm = int(round(covered / minutes)) if covered else 0
        n_fill = sum(self.fillers.values())
        fill_per_min = n_fill / minutes
        coverage = covered / len(self.script_words) if self.script_words else 0

        score = 100.0
        lo, hi = GOOD_PACE
        if wpm and wpm < lo:
            score -= min(20, (lo - wpm) * 0.5)
        elif wpm > hi:
            score -= min(20, (wpm - hi) * 0.5)
        score -= min(30, fill_per_min * 6)
        score -= min(15, self.long_pauses * 3)
        if self.script_words:
            score -= min(20, self.skipped / len(self.script_words) * 100)
        score = int(max(0, min(100, round(score))))

        tips = []
        if wpm > hi:
            tips.append((wpm - hi, "You're rushing. Aim for %d-%d wpm and let key points land." % GOOD_PACE))
        if wpm and wpm < lo:
            tips.append((lo - wpm, "Pick up the pace a little; %d-%d wpm keeps people engaged." % GOOD_PACE))
        if n_fill:
            top = max(self.fillers, key=self.fillers.get)
            tips.append((fill_per_min * 8, 'Watch "%s" (%dx). Pause silently instead of filling the gap.'
                         % (top, self.fillers[top])))
        if self.skipped:
            tips.append((self.skipped, "You skipped %d words. Slow down on the lines you jumped." % self.skipped))
        if self.long_pauses:
            tips.append((self.long_pauses * 3, "%d long pause%s. Mark tricky spots with [PAUSE] so they're "
                                               "intentional." % (self.long_pauses, "" if self.long_pauses == 1 else "s")))
        tip = max(tips)[1] if tips else "Clean run. Smooth pace, no fillers. You're ready."
        trend = (score - prev_scores[0]) if prev_scores else None
        return {
            "score": score, "wpm": wpm, "seconds": int(round(t - self.started)), "fillers": dict(self.fillers),
            "filler_count": n_fill, "long_pauses": self.long_pauses, "longest_pause": round(self.longest_pause, 1),
            "skipped": self.skipped, "coverage": round(coverage, 3), "tip": tip, "trend": trend,
        }


def pace_label(wpm):
    lo, hi = GOOD_PACE
    if not wpm:
        return ""
    if wpm < lo - 10:
        return "slow"
    if wpm > hi + 10:
        return "fast"
    return "good"

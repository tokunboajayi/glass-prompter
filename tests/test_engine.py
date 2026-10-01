from glassprompter import engine


def measure(s):
    return len(s)            # 1 unit per character keeps the maths obvious


def test_normalize_strips_invisible_and_collapses_blank_lines():
    raw = "﻿Hello​ world\r\n\r\n\r\n\r\nNext\tline   "
    assert engine.normalize(raw) == "Hello world\n\nNext line"


def test_count_words_ignores_markers():
    text = "One two three\n[PAUSE]\n[SMILE AT THEM]\nfour five"
    assert engine.count_words(text) == 5


def test_wrap_never_exceeds_width():
    text = "the quick brown fox jumps over the lazy dog " * 20
    lines = engine.wrap(text, 24, measure)
    assert all(len(ln.text) <= 24 for ln in lines if ln.kind == "text")
    assert lines[-1].kind == "end"


def test_wrap_hard_breaks_long_tokens():
    url = "https://example.com/" + "x" * 80
    lines = engine.wrap(url, 20, measure)
    assert all(len(ln.text) <= 20 for ln in lines if ln.kind == "text")
    assert "".join(ln.text for ln in lines if ln.kind == "text") == url


def test_markers():
    lines = engine.wrap("Hi\n[pause]\n[look up]\nBye", 40, measure)
    kinds = [(ln.kind, ln.text) for ln in lines]
    assert ("pause", "PAUSE") in kinds
    assert ("cue", "LOOK UP") in kinds
    assert ("text", "Hi") in kinds


def test_find_pause_detects_crossing_only_once():
    lines = engine.wrap("a\nb\n[PAUSE]\nc\nd", 40, measure)
    idx = [i for i, ln in enumerate(lines) if ln.kind == "pause"][0]
    lh = 10.0
    assert engine.find_pause(lines, 0, idx * lh + 3, lh) == idx
    # resuming exactly on the pause line must not stop again
    assert engine.find_pause(lines, idx * lh, idx * lh + 15, lh) is None


def test_pacing_is_independent_of_text_size():
    """Same words per minute must take the same time at any font size / line height."""
    text = " ".join("word%d" % i for i in range(300))
    secs = []
    for width, lh in ((40, 20.0), (80, 48.0)):
        lines = engine.wrap(text, width, measure)
        wpl = engine.words_per_line(lines)
        secs.append(engine.max_pos(lines, lh) / engine.px_per_sec(140, wpl, lh))
    assert abs(secs[0] - secs[1]) / secs[0] < 0.08


def test_title_from_skips_markers_and_truncates():
    assert engine.title_from("[PAUSE]\n\nHello there") == "Hello there"
    assert len(engine.title_from("x" * 200)) == 60


def test_fmt_secs():
    assert engine.fmt_secs(0) == "0:00"
    assert engine.fmt_secs(125.4) == "2:05"
    assert engine.fmt_secs(-3) == "0:00"

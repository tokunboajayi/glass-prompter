"""Natural Read Aloud: what gets said, in what order, and how playback maps to words on screen."""
from glassprompter import engine, tts
from glassprompter.tracking import norm_words


def lines(text):
    return engine.wrap(text, 400, lambda s: len(s) * 8)


def test_plan_words_line_up_with_voice_follow_word_map():
    ls = lines("# Intro\nHello there, friends. This is a test!\n\n[SMILE]\nSecond paragraph here.\n[PAUSE]\nEnd now.")
    plan = engine.speech_plan(ls)
    says = [it for it in plan if it[0] == "say"]
    assert [it[1] for it in says] == ["Hello there, friends.", "This is a test!", "Second paragraph here.", "End now."]
    words, _, _ = engine.word_map(ls)
    for _, text, first, weights in says:                      # every sentence points at its own words
        assert len(weights) == len(norm_words(text))
        assert words[first] == text.split()[0].lower().strip(",.!")
    assert says[-1][2] + len(says[-1][3]) == len(words)       # nothing skipped, nothing invented
    assert ("rest", 1.2) in plan                               # [PAUSE] becomes a real pause
    assert "SMILE" not in " ".join(it[1] for it in says)       # cues are never read out


def test_word_at_is_monotonic_and_bounded():
    w = [5, 3, 9, 4]
    seq = [tts.word_at(w, f / 100) for f in range(101)]
    assert seq == sorted(seq) and seq[0] == 0 and seq[-1] == 3


def test_length_scale_tracks_pace_but_stays_natural():
    assert tts.length_scale("lessac", 200) == 1.0
    assert tts.length_scale("lessac", 120) == 1.35            # never drawn out
    assert tts.length_scale("lessac", 400) == 0.8             # never chipmunk
    assert tts.length_scale("unknown", 200) == 1.0


def test_voice_catalog_has_one_bundled_default():
    assert tts.DEFAULT_VOICE in tts.VOICES and tts.VOICES[tts.DEFAULT_VOICE][3]
    assert tts.voice_file("nope") is None

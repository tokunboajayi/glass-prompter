from glassprompter.coach import Coach, pace_label
from glassprompter.tracking import norm_words

SCRIPT = norm_words("Good morning everyone. Today I want to walk you through our results and what we "
                    "actually learned this quarter.")


def run(words_with_times, cursor_path, end):
    c = Coach(SCRIPT)
    c.start(0.0)
    for t, phrase in words_with_times:
        c.on_utterance(norm_words(phrase), t)
    prev = -1
    for cur in cursor_path:
        c.on_cursor(prev, cur)
        prev = cur
    return c.report(end)


def test_clean_run_scores_high():
    r = run([(4, "good morning everyone today i want"), (8, "to walk you through our results"),
             (9, "and what we actually learned this quarter")], range(len(SCRIPT)), 7.0)
    assert r["filler_count"] == 0 and r["skipped"] == 0
    assert r["score"] >= 90


def test_fillers_counted_but_script_words_are_not():
    r = run([(3, "um good morning uh everyone"), (6, "like you know today i want"),
             (9, "we actually learned")], range(len(SCRIPT)), 10.0)
    # "actually" is in the script, so it is not a filler; "like" isn't, so it is
    assert r["fillers"] == {"um": 1, "uh": 1, "like": 1, "you know": 1}
    assert "um" in r["tip"] or "like" in r["tip"] or "uh" in r["tip"] or "you know" in r["tip"]


def test_skips_pauses_and_pace():
    r = run([(2, "good morning everyone"), (9, "our results"), (16, "this quarter")],
            [0, 1, 2, 10, 11, len(SCRIPT) - 1], 30.0)
    assert r["skipped"] > 0
    assert r["long_pauses"] == 2 and r["longest_pause"] == 7.0
    assert r["score"] < 90


def test_trend_and_pace_labels():
    c = Coach(SCRIPT)
    c.start(0)
    c.on_cursor(-1, len(SCRIPT) - 1)
    r = c.report(10.0, prev_scores=(50,))
    assert r["trend"] == r["score"] - 50
    assert pace_label(100) == "slow" and pace_label(150) == "good" and pace_label(200) == "fast"

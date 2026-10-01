from glassprompter.tracking import Aligner, norm_words

SCRIPT = norm_words(
    "Good morning everyone. Thank you for joining. Today I want to walk you through our quarterly "
    "results, the risks we see ahead, and the plan for next year. Let's start with revenue, which grew "
    "eighteen percent year over year.")


def feed(al, phrase):
    heard = []
    for w in norm_words(phrase):           # simulate growing partial results
        heard.append(w)
        al.update(heard)
    return al.cursor


def test_follows_reading_in_order():
    al = Aligner(SCRIPT)
    feed(al, "good morning everyone")
    assert SCRIPT[al.cursor] == "everyone"
    feed(al, "thank you for joining today I want to walk you through")
    assert SCRIPT[al.cursor] == "through"


def test_tolerates_misrecognized_and_skipped_words():
    al = Aligner(SCRIPT)
    feed(al, "good morning everyone thank you for joining")
    feed(al, "today want to walk ewe through our quarterly results")      # dropped "I", "you" -> "ewe"
    assert SCRIPT[al.cursor] == "results"


def test_off_script_chatter_does_not_jump():
    al = Aligner(SCRIPT)
    feed(al, "good morning everyone")
    before = al.cursor
    feed(al, "sorry one second my dog is barking")
    assert al.cursor - before <= 3          # at most a tiny drift from a common word


def test_needs_evidence_to_jump_far():
    al = Aligner(SCRIPT)
    feed(al, "good morning")
    al.update(["revenue"])                  # one word far ahead is not enough
    assert al.cursor < 5
    feed(al, "lets start with revenue which grew")
    assert SCRIPT[al.cursor] == "grew"


def test_can_go_back_when_rereading():
    al = Aligner(SCRIPT)
    feed(al, "good morning everyone thank you for joining today i want to walk you through our quarterly results")
    feed(al, "thank you for joining")
    assert SCRIPT[al.cursor] == "joining"


def test_done_and_empty():
    al = Aligner(norm_words("short script"))
    feed(al, "short script")
    assert al.done
    assert Aligner([]).update(["x"]) == -1

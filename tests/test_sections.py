from glassprompter import engine


def test_headings_become_sections_and_are_not_spoken():
    text = "# Intro\nHello there friends\n## Main point\nOur revenue grew"
    lines = engine.wrap(text, 100, len)
    assert engine.sections(lines) == [(0, "INTRO"), (2, "MAIN POINT")]
    assert engine.count_words(text) == 6
    assert engine.title_from(text) == "Intro"


def test_word_map_tracks_lines_and_tokens():
    lines = engine.wrap("Don't stop now.\n[PAUSE]\nKeep going, friends", 100, len)
    words, word_line, tokens = engine.word_map(lines)
    assert words == ["don't", "stop", "now", "keep", "going", "friends"]
    assert word_line == [0, 0, 0, 2, 2, 2]
    assert tokens[0] == [1, 2, 3] and tokens[2] == [4, 5, 6]

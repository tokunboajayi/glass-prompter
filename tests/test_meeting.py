import os

from glassprompter import ai, meeting


def test_transcript_merges_one_speakers_breath_and_labels_sides():
    tr = meeting.Transcript(started=1000.0)
    tr.add(meeting.THEM, "so what does pricing look like", at=1001.0)
    tr.add(meeting.THEM, "for a team of ten", at=1002.0)
    tr.add(meeting.ME, "great question", at=1004.0)
    assert len(tr.segments) == 2
    assert tr.render() == "Them: so what does pricing look like for a team of ten\nYou: great question"
    assert tr.words() == 13 and tr.last(meeting.THEM)["t"] == 1.0


def test_transcript_keeps_the_newest_part_when_long():
    tr = meeting.Transcript(started=0.0)
    for i in range(400):
        tr.add(meeting.ME if i % 2 else meeting.THEM, "line number %d with some words" % i, at=i * 10.0)
    text = tr.render(limit=2000)
    assert len(text) <= 2001 and "line number 399" in text and "line number 0 " not in text


def test_questions_are_spotted_without_punctuation():
    for q in ("what does pricing look like", "can you walk me through the setup", "so how long does it take",
              "tell me about your background", "it works with zoom right", "is that available today?"):
        assert meeting.is_question(q), q
    for s in ("thanks everyone", "we shipped it last week", "okay", "the price is fine"):
        assert not meeting.is_question(s), s


def test_modes_include_custom_ones_and_fall_back():
    custom = [{"name": "Pitch", "prompt": "Answer like a founder."}, {"name": "", "prompt": "x"}, "junk"]
    ids = [m[0] for m in meeting.all_modes(custom)]
    assert "sales" in ids and "custom:Pitch" in ids and len(ids) == len(meeting.MODES) + 1
    assert meeting.mode_prompt("custom:Pitch", custom) == "Answer like a founder."
    assert meeting.mode_name("nope", custom) == meeting.MODES[meeting.DEFAULT_MODE][0]


def test_context_carries_mode_notes_files_and_transcript():
    tr = meeting.Transcript(started=0.0)
    tr.add(meeting.THEM, "how much is the pro plan", at=1.0)
    ctx = meeting.build_context("sales", [], tr, [("pricing.md", "Pro is $49")], "I'm Sam at Acme")
    assert "Sales call" in ctx and "I'm Sam at Acme" in ctx and "Pro is $49" in ctx
    assert "Them: how much is the pro plan" in ctx
    assert "how much is the pro plan" in meeting.action_message("assist", "how much is the pro plan")


def test_context_reaches_every_provider_format():
    msgs = [{"role": "user", "content": "help"}]
    body = ai.build_request(msgs, "claude-x", context="COPILOT CONTEXT")
    assert "COPILOT CONTEXT" in body["system"][0]["text"]
    assert "COPILOT CONTEXT" in ai._openai_body("openai", "gpt-x", msgs, None, "", "", 100, "COPILOT CONTEXT")[
        "messages"][0]["content"]
    assert "COPILOT CONTEXT" in ai._gemini_body(msgs, None, "", "", 100, False, "COPILOT CONTEXT")[
        "systemInstruction"]["parts"][0]["text"]


def test_copilot_actions_send_context_through_chat(monkeypatch):
    seen = {}

    def fake_http(url, body=None, headers=None, timeout=30):
        seen["body"] = body
        return {"content": [{"type": "text", "text": "Say: it's $49 per user."}]}
    monkeypatch.setattr(ai, "_http", fake_http)
    reply = ai.chat("sk-ant-test", [{"role": "user", "content": "assist"}], model="claude-x", web=False,
                    context="Live transcript so far")
    assert reply.startswith("Say:") and "Live transcript so far" in seen["body"]["system"][0]["text"]


def test_notes_are_parsed_by_heading():
    text = ("TITLE\nAcme pilot kickoff\n**SUMMARY**\nWe agreed a pilot.\n## ACTION ITEMS\n- Sam - send contract\n"
            "FOLLOW-UP EMAIL:\nSubject: Next steps\nHi team,")
    n = meeting.parse_notes(text)
    assert n["TITLE"] == "Acme pilot kickoff" and n["SUMMARY"] == "We agreed a pilot."
    assert n["ACTION ITEMS"] == "- Sam - send contract" and n["FOLLOW-UP EMAIL"].startswith("Subject: Next steps")


def test_knowledge_files_are_read_within_the_limit(tmp_path):
    a, b, bad = tmp_path / "a.md", tmp_path / "b.txt", tmp_path / "c.exe"
    a.write_text("# Pricing\nPro is $49", encoding="utf-8")
    b.write_text("x" * 500, encoding="utf-8")
    bad.write_text("nope", encoding="utf-8")
    got = meeting.read_knowledge([str(a), str(b), str(bad), str(tmp_path / "missing.txt")], limit=100)
    names = [n for n, _ in got]
    assert names == ["a.md", "b.txt"] and sum(len(t) for _, t in got) <= 100


def test_meeting_store_round_trip_search_and_markdown(tmp_path):
    st = meeting.MeetingStore(str(tmp_path / "m.db"))
    mid = st.create(1_700_000_000.0, "sales")
    tr = meeting.Transcript(started=1_700_000_000.0)
    tr.add(meeting.THEM, "what about security", at=1_700_000_005.0)
    st.update(mid, transcript=tr.to_json(), notes="SUMMARY\nTalked security.", title="Security review",
              ended=1_700_000_100.0, bogus="ignored")
    m = st.get(mid)
    assert m["title"] == "Security review" and m["words"] == 3 and m["segments"][0]["who"] == "them"
    assert [x["id"] for x in st.list("security")] == [mid] and st.list("nothing-like-this") == []
    md = meeting.to_markdown(m)
    assert md.startswith("# Security review") and "**Them** · 0:05  \nwhat about security" in md
    assert "### Summary\n\nTalked security." in md
    st.delete(mid)
    assert st.get(mid) is None
    st.close()


def test_notes_are_saved_with_title_and_email_from_any_thread(tmp_path):
    import threading
    st = meeting.MeetingStore(str(tmp_path / "m.db"))
    mid = st.create(1_700_000_000.0, "sales")
    reply = "TITLE\n**Acme pilot kickoff**\nSUMMARY\nAgreed a pilot.\nFOLLOW-UP EMAIL\nSubject: Next steps\nHi Jo,"
    t = threading.Thread(target=meeting.save_notes, args=(st, mid, reply))
    t.start()
    t.join()
    m = st.get(mid)
    assert m["title"] == "Acme pilot kickoff" and m["email"].startswith("Subject: Next steps")
    assert meeting.notes_markdown(m["notes"]).startswith("### Summary")
    st.close()


def test_speech_models_are_discovered(tmp_path, monkeypatch):
    from glassprompter import paths
    d = tmp_path / "home" / "models" / "vosk-model-small-fr-0.22" / "am"
    d.mkdir(parents=True)
    (d / "final.mdl").write_bytes(b"")
    assert "vosk-model-small-fr-0.22" in paths.speech_models()
    from glassprompter import listen
    assert listen.model_path("vosk-model-small-fr-0.22").endswith("vosk-model-small-fr-0.22")
    assert os.path.isdir(listen.model_path("vosk-model-small-fr-0.22"))


def test_copilot_hotkeys_are_registered_everywhere():
    from glassprompter import app
    from glassprompter import platform as native
    actions = {a for _, a in app.HOTKEYS.values()}
    assert {"assist", "meeting"} <= actions
    assert "ENTER" in native.HOTKEY_KEYS and "M" in native.HOTKEY_KEYS


def test_suggestions_fire_on_their_questions_and_after_a_long_stretch():
    t = meeting.SuggestionTrigger(answer_gap=8, followup_gap=45, followup_words=20)
    assert t.on_segment(meeting.ME, "what do you think about pricing", 0) is None      # my own words never trigger
    assert t.on_segment(meeting.THEM, "what does pricing look like for us", 1) == (
        "answer", "what does pricing look like for us")
    assert t.on_segment(meeting.THEM, "and how long is onboarding", 3) is None          # too soon after the last one
    talk = "we have been growing quickly and the team now spans three offices"         # 12 words, no question
    assert t.on_segment(meeting.THEM, talk, 20) is None
    assert t.on_segment(meeting.THEM, talk, 30) is None                                 # 24 words but only 29 s
    assert t.on_segment(meeting.THEM, talk, 60) == ("followups", "")
    assert t.on_segment(meeting.THEM, "so can you send the contract", 70) == ("answer", "so can you send the contract")


def test_listen_context_carries_the_transcript_only_when_there_is_one():
    assert meeting.listen_context(None) == "" and meeting.listen_context(meeting.Transcript()) == ""
    tr = meeting.Transcript(started=0.0)
    tr.add(meeting.THEM, "how much is the pro plan", at=2.0)
    ctx = meeting.listen_context(tr)
    assert "Them: how much is the pro plan" in ctx and "<transcript>" in ctx

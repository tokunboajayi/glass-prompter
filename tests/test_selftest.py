import json

from glassprompter import config, selftest


def test_child_writes_a_result_even_when_a_check_fails(tmp_path):
    out = tmp_path / "r.json"
    assert selftest.child("no_such_check", str(out)) == 1
    res = json.loads(out.read_text())
    assert res["ok"] is False and "ValueError" in res["detail"]


def test_required_checks_cover_both_voice_features():
    assert {"voice_follow", "read_aloud_synth", "speech_model"} <= set(selftest.REQUIRED)
    assert set(selftest.REQUIRED) <= set(selftest.CHECKS)


def test_crash_guard_settings_validate():
    s = config.Settings()
    s.native_crashes = "garbage"
    s.probe_version = 3
    config.validate(s)
    assert s.native_crashes == [] and s.probe_version == "3"

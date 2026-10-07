import getpass
import os
import re
import urllib.parse

import pytest

from glassprompter import __version__, paths, support

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMS = os.path.join(ROOT, ".github", "ISSUE_TEMPLATE")


def _query(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)


def test_bug_link_is_prefilled_with_version_and_system():
    url = support.report_url("bug", True)
    assert url.startswith("https://github.com/tokunboajayi/glass-prompter/issues/new?")
    q = _query(url)
    assert q["template"] == ["bug_report.yml"] and q["version"] == [__version__]
    assert "Glass Prompter " + __version__ in q["system"][0] and "Hidden from screen share: yes" in q["system"][0]
    assert len(url) < 4000                                   # browsers and GitHub handle this comfortably


def test_report_never_contains_personal_data():
    url = urllib.parse.unquote(support.report_url("bug", False))
    user = getpass.getuser()
    assert paths.data_dir() not in url and os.path.expanduser("~") not in url
    if len(user) > 3:
        assert user not in url
    assert "key" not in support.diagnostics().lower()


def test_feature_link_uses_feature_form():
    q = _query(support.report_url("feature"))
    assert q["template"] == ["feature_request.yml"] and "version" not in q


def test_issue_forms_match_prefilled_fields():
    with open(os.path.join(FORMS, "bug_report.yml"), encoding="utf-8") as f:
        text = f.read()
    ids = set(re.findall(r"^\s+id:\s*(\w+)\s*$", text, re.M))
    assert {"version", "system", "what"} <= ids              # the app fills version + system by these ids


def test_issue_forms_are_valid_yaml():
    yaml = pytest.importorskip("yaml")
    for name in ("bug_report.yml", "feature_request.yml", "config.yml"):
        with open(os.path.join(FORMS, name), encoding="utf-8") as f:
            assert yaml.safe_load(f)

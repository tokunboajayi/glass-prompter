"""Feedback links: open a pre-filled GitHub issue so people can report problems in one click.

Privacy: the link carries only the app version, OS name/version, Python/Qt versions and whether screen-share
hiding is available. No file paths, user names, scripts, keys or anything typed into the app. Nothing is sent
until the person reviews the issue in their browser and presses Submit themselves.
"""
import platform
import sys
import urllib.parse

from . import __version__
from .updater import REPO

ISSUES = "https://github.com/%s/issues/new" % REPO
WEBSITE = "https://tokunboajayi.github.io/glass-prompter/"


def _os_label():
    s = platform.system()
    if s == "Darwin":
        ver = platform.mac_ver()[0] or platform.release()
        return "macOS %s (%s)" % (ver, platform.machine())
    if s == "Windows":
        rel, ver = platform.release(), platform.version()
        return "Windows %s (build %s, %s)" % (rel, ver.split(".")[-1] if ver else "?", platform.machine())
    return "%s %s (%s)" % (s or "Unknown", platform.release(), platform.machine())


def diagnostics(capture_state=None):
    """Plain-text system summary that is safe to share publicly."""
    try:
        from PySide6 import __version__ as qt
    except Exception:                                   # noqa: BLE001
        qt = "?"
    lines = [
        "Glass Prompter %s" % __version__,
        "OS: %s" % _os_label(),
        "Python %s, Qt %s" % (platform.python_version(), qt),
        "Installed app" if getattr(sys, "frozen", False) else "Running from source",
    ]
    if capture_state is not None:
        lines.append("Hidden from screen share: %s" % ("yes" if capture_state else "no / not supported"))
    return "\n".join(lines)


def report_url(kind="bug", capture_state=None):
    """URL of a new GitHub issue, pre-filled from the matching issue form."""
    if kind == "feature":
        q = {"template": "feature_request.yml", "labels": "enhancement"}
    else:
        q = {"template": "bug_report.yml", "labels": "bug",
             "version": __version__, "system": diagnostics(capture_state)}
    return ISSUES + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)

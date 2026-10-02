"""Updater: version logic and picking the right installer, without touching the network."""
from glassprompter import updater

ASSETS = [{"name": n, "browser_download_url": "https://x/" + n, "size": 1} for n in (
    "GlassPrompter-Setup-2.3.0.exe", "GlassPrompter-Setup-2.3.0.sha256.txt",
    "GlassPrompter-2.3.0-macOS-arm64.dmg", "GlassPrompter-2.3.0-macOS-arm64.sha256.txt",
    "GlassPrompter-2.3.0-macOS-x86_64.dmg", "GlassPrompter-2.3.0-macOS-x86_64.sha256.txt")]


def test_versions_compare_numerically():
    assert updater.parse_version("v2.10.1") == (2, 10, 1)
    assert updater.parse_version("v3") == (3, 0, 0)
    assert updater.is_newer("v2.10.0", "2.9.9")
    assert not updater.is_newer("v2.2.0", "2.2.0")
    assert not updater.is_newer("garbage", "2.2.0")


def test_picks_installer_and_checksum_for_each_platform():
    exe, sha = updater.asset_for(ASSETS, "windows", "AMD64")
    assert exe["name"].endswith(".exe") and sha["name"] == "GlassPrompter-Setup-2.3.0.sha256.txt"
    dmg, sha = updater.asset_for(ASSETS, "macos", "arm64")
    assert "arm64" in dmg["name"] and sha["name"].startswith("GlassPrompter-2.3.0-macOS-arm64")
    dmg, _ = updater.asset_for(ASSETS, "macos", "x86_64")
    assert "x86_64" in dmg["name"]
    assert updater.asset_for(ASSETS, "linux", "x86_64") == (None, None)


def test_daily_throttle(monkeypatch):
    called = []
    monkeypatch.setattr(updater, "fetch_latest", lambda: called.append(1) or {"tag": "v0.0.1", "assets": []})
    import time
    assert updater.check(force=False, last_checked=time.time()) is None and not called
    assert updater.check(force=True) is None and called


def test_github_digest_is_preferred_over_checksum_file():
    hexd = "ab" * 32
    assert updater.expected_sha256(None, installer={"digest": "sha256:" + hexd.upper()}) == hexd
    assert updater.expected_sha256(None, installer={}) is None

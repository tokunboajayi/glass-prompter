"""Updates from GitHub Releases: check, download, verify (SHA-256), install.

Privacy: the only request is to api.github.com for the latest release (no identifiers, no telemetry).
Users can turn checks off in Settings.

Flow:
  Windows - download GlassPrompter-Setup-X.exe, verify its .sha256.txt, quit, run the installer silently with
            /UPDATE=1 so it relaunches the app when it finishes (scripts and settings are untouched).
  macOS   - download the .dmg for this chip, verify, open it in Finder (drag to Applications to replace).
"""
import hashlib
import json
import logging
import os
import platform as _platform
import re
import sys
import tempfile
import time
import urllib.request

from . import __version__

log = logging.getLogger(__name__)

REPO = "tokunboajayi/glass-prompter"
API = "https://api.github.com/repos/%s/releases/latest" % REPO
PAGE = "https://github.com/%s/releases/latest" % REPO
CHECK_EVERY = 24 * 3600


def parse_version(text):
    """'v2.10.1' -> (2, 10, 1). Unknown parts become 0, so odd tags never crash a comparison."""
    nums = [int(n) for n in re.findall(r"\d+", text or "")[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def is_newer(latest, current=__version__):
    return parse_version(latest) > parse_version(current)


def asset_for(assets, os_name=None, machine=None):
    """Pick the installer for this computer from a release's asset list: (installer, checksum) dicts."""
    os_name = os_name or ("windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux")
    machine = (machine or _platform.machine()).lower()
    by_name = {a["name"]: a for a in assets}
    pick = None
    for name in by_name:
        if os_name == "windows" and name.startswith("GlassPrompter-Setup-") and name.endswith(".exe"):
            pick = name
        elif os_name == "macos" and name.endswith(".dmg"):
            arm = machine in ("arm64", "aarch64")
            if ("arm64" in name) == arm:
                pick = name
    if not pick:
        return None, None
    stem = pick.rsplit(".", 1)[0]
    return by_name[pick], by_name.get(stem + ".sha256.txt")


def fetch_latest(timeout=8):
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "GlassPrompter/" + __version__})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return {"tag": data.get("tag_name", ""), "name": data.get("name", ""), "notes": data.get("body", "") or "",
            "url": data.get("html_url", PAGE), "assets": data.get("assets", [])}


def check(force=False, last_checked=0.0):
    """Return an update dict if a newer release has an installer for this computer, else None."""
    if not force and time.time() - last_checked < CHECK_EVERY:
        return None
    rel = fetch_latest()
    if not is_newer(rel["tag"]):
        return None
    installer, checksum = asset_for(rel["assets"])
    if not installer:
        return None
    rel.update(version=".".join(map(str, parse_version(rel["tag"]))), installer=installer, checksum=checksum)
    return rel


def expected_sha256(checksum_asset, timeout=15, installer=None):
    digest = (installer or {}).get("digest") or ""          # GitHub publishes "sha256:<hex>" for every asset
    if digest.startswith("sha256:") and len(digest) == 71:
        return digest[7:].lower()
    if not checksum_asset:
        return None
    with urllib.request.urlopen(checksum_asset["browser_download_url"], timeout=timeout) as r:
        text = r.read().decode("utf-8", "replace")
    m = re.search(r"\b([0-9a-fA-F]{64})\b", text)
    return m.group(1).lower() if m else None


def download(update, progress=None, cancelled=lambda: False):
    """Download and verify the installer. Returns its path; raises if the checksum doesn't match."""
    asset = update["installer"]
    want = expected_sha256(update.get("checksum"), installer=asset)
    dest = os.path.join(tempfile.gettempdir(), asset["name"])
    tmp = dest + ".part"
    h = hashlib.sha256()
    with urllib.request.urlopen(asset["browser_download_url"], timeout=30) as r, open(tmp, "wb") as f:
        size, got = int(r.headers.get("Content-Length") or asset.get("size") or 0), 0
        while True:
            if cancelled():
                raise RuntimeError("cancelled")
            block = r.read(1 << 17)
            if not block:
                break
            f.write(block)
            h.update(block)
            got += len(block)
            if progress and size:
                progress(got / size)
    if want and h.hexdigest() != want:
        os.remove(tmp)
        raise RuntimeError("The download didn't match its checksum, so it wasn't installed.")
    os.replace(tmp, dest)
    return dest


def install(path):
    """Hand over to the installer. Windows: caller must quit right after this returns True."""
    import subprocess
    if sys.platform == "win32":
        subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/UPDATE=1"], close_fds=True)
        return True
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
        return False                 # user drags the new app over the old one; we stay open until they quit
    return False

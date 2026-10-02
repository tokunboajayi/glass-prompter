"""Generate package-manager manifests for a published release (winget + Homebrew cask).

    python packaging/distribution.py            # latest release
    python packaging/distribution.py v2.2.0     # a specific tag

Reads the release from the GitHub API (asset URLs + SHA-256 digests), writes:
    packaging/winget/manifests/t/TokunboAjayi/GlassPrompter/<version>/*.yaml
    packaging/homebrew/Casks/glass-prompter.rb
"""
import json
import os
import sys
import urllib.request

REPO = "tokunboajayi/glass-prompter"
ID = "TokunboAjayi.GlassPrompter"
PRODUCT_CODE = "{6F1C2D4E-8B7A-4C3D-9E21-5A7C3B9D0E14}_is1"        # Inno AppId + _is1
HOME = "https://tokunboajayi.github.io/glass-prompter/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def release(tag=None):
    url = "https://api.github.com/repos/%s/releases/%s" % (REPO, "tags/" + tag if tag else "latest")
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "gp-dist"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def sha(asset):
    d = asset.get("digest") or ""
    if not d.startswith("sha256:"):
        raise SystemExit("No digest for %s" % asset["name"])
    return d[7:]


def build(rel):
    version = rel["tag_name"].lstrip("v")
    assets = {a["name"]: a for a in rel["assets"]}
    exe = assets["GlassPrompter-Setup-%s.exe" % version]
    arm = assets["GlassPrompter-%s-macOS-arm64.dmg" % version]
    intel = assets["GlassPrompter-%s-macOS-x86_64.dmg" % version]
    date = (rel.get("published_at") or "")[:10]

    wdir = os.path.join(ROOT, "packaging", "winget", "manifests", "t", "TokunboAjayi", "GlassPrompter", version)
    os.makedirs(wdir, exist_ok=True)
    head = "# yaml-language-server: $schema=https://aka.ms/winget-manifest.%s.1.6.0.schema.json\n\n"
    files = {
        ID + ".yaml": head % "version" + f"""PackageIdentifier: {ID}
PackageVersion: {version}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.6.0
""",
        ID + ".installer.yaml": head % "installer" + f"""PackageIdentifier: {ID}
PackageVersion: {version}
InstallerType: inno
Scope: user
InstallModes:
- interactive
- silent
- silentWithProgress
UpgradeBehavior: install
ReleaseDate: {date}
Installers:
- Architecture: x64
  InstallerUrl: {exe["browser_download_url"]}
  InstallerSha256: {sha(exe).upper()}
  ProductCode: '{PRODUCT_CODE}'
ManifestType: installer
ManifestVersion: 1.6.0
""",
        ID + ".locale.en-US.yaml": head % "defaultLocale" + f"""PackageIdentifier: {ID}
PackageVersion: {version}
PackageLocale: en-US
Publisher: Olatokunbo Ajayi
PublisherUrl: https://github.com/tokunboajayi
PublisherSupportUrl: https://github.com/{REPO}/issues
PackageName: Glass Prompter
PackageUrl: {HOME}
License: MIT
LicenseUrl: https://github.com/{REPO}/blob/main/LICENSE
Copyright: Copyright (c) 2026 Olatokunbo Ajayi
ShortDescription: See-through teleprompter under your webcam that follows your voice.
Description: |-
  Glass Prompter sits right under your webcam so you keep eye contact on calls and recordings.
  It scrolls with your voice word by word (offline), reads your script aloud in a natural voice,
  has a click-through ghost mode, a phone remote and a rehearsal coach, and is hidden from screen sharing.
Moniker: glass-prompter
Tags:
- teleprompter
- prompter
- webcam
- presentation
- voice
- video-call
ReleaseNotesUrl: {rel["html_url"]}
ManifestType: defaultLocale
ManifestVersion: 1.6.0
""",
    }
    for name, text in files.items():
        with open(os.path.join(wdir, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    cdir = os.path.join(ROOT, "packaging", "homebrew", "Casks")
    os.makedirs(cdir, exist_ok=True)
    cask = f'''cask "glass-prompter" do
  arch arm: "arm64", intel: "x86_64"

  version "{version}"
  sha256 arm:   "{sha(arm)}",
         intel: "{sha(intel)}"

  url "https://github.com/{REPO}/releases/download/v#{{version}}/GlassPrompter-#{{version}}-macOS-#{{arch}}.dmg"
  name "Glass Prompter"
  desc "See-through teleprompter under your webcam that follows your voice"
  homepage "{HOME}"

  livecheck do
    url :url
    strategy :github_latest
  end

  auto_updates true
  depends_on macos: ">= :ventura"

  app "Glass Prompter.app"

  zap trash: [
    "~/Library/Application Support/GlassPrompter",
    "~/Library/LaunchAgents/app.glassprompter.plist",
  ]

  caveats <<~EOS
    Glass Prompter is not notarized yet. The first time, right-click it in Applications and choose Open
    (on macOS 15+: System Settings > Privacy & Security > Open Anyway).
  EOS
end
'''
    with open(os.path.join(cdir, "glass-prompter.rb"), "w", encoding="utf-8", newline="\n") as f:
        f.write(cask)
    print("winget  ->", os.path.relpath(wdir, ROOT))
    print("brew    ->", os.path.relpath(os.path.join(cdir, "glass-prompter.rb"), ROOT))
    return version


if __name__ == "__main__":
    build(release(sys.argv[1] if len(sys.argv) > 1 else None))

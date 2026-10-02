# Releasing Glass Prompter

Everything is driven by a version tag. You don't build anything by hand.

## 1. Ship a version

1. Bump `__version__` in `glassprompter/__init__.py` and add a section to `CHANGELOG.md`.
2. Commit and push to `main`.
3. Tag the release and push the tag:

   ```bash
   git tag v2.5.0
   git push origin v2.5.0
   ```

4. **GitHub Actions** (`.github/workflows/release.yml`) then:
   - builds the Windows installer and both Mac disk images;
   - attaches all three to the release with a `.sha256.txt` file for each.

   The release notes come from `packaging/RELEASE_NOTES.md`. Watch it with `gh run watch`. It takes about 15 minutes.
5. **In-app updates:** installed copies find the new release within a day, or straight away with *Check for updates*.

## 2. Update the package managers

```bash
python packaging/distribution.py v2.5.0     # writes winget manifests + the Homebrew cask from the release
git add packaging && git commit -m "winget + Homebrew manifests for 2.5.0" && git push
```

| Channel | How it updates |
|---|---|
| **Homebrew** | Copy `packaging/homebrew/Casks/glass-prompter.rb` into the [`tokunboajayi/homebrew-tap`](https://github.com/tokunboajayi/homebrew-tap) repo under `Casks/`, then commit and push. Users then get it with `brew upgrade`. |
| **winget** | `wingetcreate update TokunboAjayi.GlassPrompter -v 2.5.0 -u <Setup .exe URL> --submit`. Microsoft reviews the PR, usually within 1 to 3 days. Submit only one PR at a time. |

## 3. The website

- **Address:** <https://tokunboajayi.github.io/glass-prompter/>
- **Source:** `docs/index.html` plus `docs/img/`. GitHub Pages serves it from `docs/` on `main` (*Settings › Pages*).
- **Updating:** edit `docs/index.html` and push to `main`. It's live within a minute or two.
- **Download buttons** always point at the latest release. The page asks the GitHub API when it loads, so you don't need to edit the site for a new version.
- **Screenshots:** rebuild them with `python tools/shots.py shots`, then `python tools/marketing_images.py`.
- **After winget approves the listing:** delete the line marked `data-winget-pending` in `docs/index.html`.

## 4. Code signing (not set up yet)

| | What it removes | Cost |
|---|---|---|
| Windows | The "Windows protected your PC" SmartScreen warning | Azure Artifact Signing, about $10/month |
| macOS | The "can't be opened" Gatekeeper warning, plus the caveat in the Homebrew cask | Apple Developer ID, $99/year, plus notarization |

When you have them, add the certificates as repository secrets and add a signing step to `release.yml`.

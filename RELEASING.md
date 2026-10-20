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

Signing is what takes Glass Prompter from public beta to "anyone can install it". Unsigned builds work, but
first-time users see a scary warning, and on macOS every unsigned update looks like a new app, so the Screen
Recording permission resets after each update.

| | What it removes | Cost | Do it |
|---|---|---|---|
| macOS (do first) | The "can't be opened" warning, the Homebrew caveat, and Screen Recording resets after updates | Apple Developer Program, $99/year | Step A |
| Windows | The "Windows protected your PC" SmartScreen warning | Azure Artifact (Trusted) Signing, about $10/month | Step B |

### Step A: macOS (Developer ID + notarization)

**Already built in.** `release.yml` and `packaging/build_mac.sh` sign with the hardened runtime
(`packaging/entitlements.plist`: microphone + what PyInstaller needs), self-test the signed app, then sign,
notarize and staple the .dmg. Each part switches on only when its secrets exist; with none, builds stay ad-hoc
signed exactly as before. All you add is secrets (GitHub > Settings > Secrets and variables > Actions).

The account can be your own, or someone else's **with their permission**. Never use their Apple ID password.
Instead they add your Apple ID to their team, or give you the two items below.

1. **Certificate.** The account holder creates a **Developer ID Application** certificate (Xcode > Settings >
   Accounts > Manage Certificates, or developer.apple.com > Certificates) and exports it from Keychain Access as a
   `.p12` with a password. macOS will show their name or company as the developer.
   - `MACOS_CERT_P12`: the .p12, base64-encoded (`base64 -i cert.p12 | pbcopy`)
   - `MACOS_CERT_PASSWORD`: the .p12 export password
2. **Notarization**, one of these:
   - *Recommended, no password shared:* an **App Store Connect API key** (appstoreconnect.apple.com > Users and
     Access > Integrations > Team Keys, role Developer). They can revoke it at any time.
     `APPLE_API_KEY_P8` (the whole `AuthKey_XXXX.p8` file contents), `APPLE_API_KEY_ID`, `APPLE_API_ISSUER`
   - *Or* the account holder's Apple ID with an app-specific password: `APPLE_ID`, `APPLE_TEAM_ID`,
     `APPLE_APP_PASSWORD`
3. Tag a release. The Mac build logs "Signing as: Developer ID Application: ..." and "notarizing", and fails loudly
   if Apple rejects it (the notary log is printed).
4. Once a signed release is out, remove the "not notarized" notes from the Homebrew cask, the README and the
   website's Mac FAQ.

Keep the same signing identity from then on. A different certificate makes macOS treat updates as a new app,
which resets the Screen Recording permission.

### Step B: Windows (Azure Artifact Signing)

1. Create an Azure account and an **Artifact Signing** (formerly Trusted Signing) account; complete identity
   validation as an individual.
2. Create a certificate profile and an app registration (service principal) with the *Artifact Signing
   Certificate Profile Signer* role.
3. Add repository secrets: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, plus the account endpoint,
   account name and profile name.
4. In `release.yml`, sign `dist/GlassPrompter/GlassPrompter.exe` before Inno Setup runs and the finished
   `GlassPrompter-Setup-<version>.exe` after, using the `azure/trusted-signing-action`.
5. Remove the SmartScreen FAQ entry once signed builds have been out for a few weeks (SmartScreen reputation
   builds up over time even for signed apps).

Never commit certificates, passwords or keys. Secrets live only in GitHub Actions secrets.

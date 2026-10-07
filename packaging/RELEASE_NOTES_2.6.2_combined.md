## 2.6.2 - 2026-10-08
Public beta: easier to give feedback, clearer setup.

- **Report a problem in one click.** The menu has *Report a problem* and *Suggest a feature*, and About has a
  *Report a problem* button. They open a GitHub form with your app version and system already filled in. Nothing
  personal is included (no file paths, scripts or keys), and nothing is sent until you press Submit yourself.
- **Step-by-step AI key guide** on the website: what an API key is, where to get one, and how to paste it in.
- **Security policy** (SECURITY.md) with a private way to report security problems and a plain summary of what
  stays on your computer.
- The website now says AI messages go to the provider you picked (one line still said Anthropic).
A see-through teleprompter that sits right under your webcam, follows your voice word by word and stays off the screen share. Free for Windows and Mac.

**Easiest:** download from the website, which picks the right file for you: https://tokunboajayi.github.io/glass-prompter/

| Your computer | File | Or run |
|---|---|---|
| Windows 10 (2004+) / 11, 64-bit | `GlassPrompter-Setup-<version>.exe` | `winget install TokunboAjayi.GlassPrompter` |
| Mac with Apple silicon (M1 to M4), macOS 13+ | `GlassPrompter-<version>-macOS-arm64.dmg` | `brew install --cask tokunboajayi/tap/glass-prompter` |
| Intel Mac, macOS 13+ | `GlassPrompter-<version>-macOS-x86_64.dmg` | same Homebrew command |

- **Windows:** run the installer. No admin rights are needed. If *"Windows protected your PC"* appears, click **More info**, then **Run anyway**.
- **Mac:** open the .dmg and drag the app to Applications. The first time, right-click it and choose **Open**. On macOS 15+, go to System Settings › Privacy & Security and click **Open Anyway**.
- **Already installed?** The app updates itself. Look for **Update to …** in the tray or menu bar.

**What's new:** see the [changelog](https://github.com/tokunboajayi/glass-prompter/blob/main/CHANGELOG.md). **Full guide:** [README](https://github.com/tokunboajayi/glass-prompter#readme).

You can check each download against the `.sha256.txt` file next to it. The in-app updater does this check automatically.

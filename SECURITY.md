# Security

## Reporting a problem

Please **don't** open a public issue for security problems. Report them privately instead:
[GitHub › Security › Report a vulnerability](https://github.com/tokunboajayi/glass-prompter/security/advisories/new).

Include what you found, how to reproduce it, and which version you used. You'll get a reply within a few days,
and a fix is released as soon as it's ready. Thank you for helping keep users safe.

## Supported versions

Only the latest release gets security fixes. The app checks for updates on its own and can install them for you.

## How Glass Prompter handles your data

- **Scripts and settings** stay on your computer. Nothing is uploaded.
- **Your AI API key** is stored only on your computer (`ai.key` in the data folder). It is never sent to the phone
  and never included in bug reports. Messages go from your computer straight to the AI provider you chose, and
  only when you press Send.
- **The phone remote** runs on your local network only. A 6-digit PIN is exchanged for a session token, 5 wrong
  PINs lock that device out for 5 minutes, and choosing a new PIN signs every phone out.
- **Updates** come from GitHub Releases and are checked against a SHA-256 checksum before they install.
- **Report a problem** opens a pre-filled GitHub issue containing only the app version and your OS. Nothing is
  sent until you review it and press Submit yourself.
- There is no tracking, analytics or telemetry.

# GitHub Actions workflows

Copy these two files to `.github/workflows/` to turn on CI and the cross-platform release builds:

```powershell
New-Item -ItemType Directory -Force .github\workflows | Out-Null
Copy-Item packaging\github-workflows\*.yml .github\workflows\
git add .github; git commit -m "Enable CI and release builds"; git push
```

- `ci.yml` runs the tests and renders every screen on Windows, macOS and Linux for each push.
- `release.yml` builds the Windows installer and the Apple silicon + Intel `.dmg` files when you push a tag
  like `v2.0.0`, then attaches them to the GitHub release.

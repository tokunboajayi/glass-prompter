# Build Glass Prompter: tests -> assets -> PyInstaller bundle -> Inno Setup installer.
# Usage (from the project root):  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$version = (python -c "import glassprompter; print(glassprompter.__version__)").Trim()
Write-Host "== Glass Prompter $version =="

Write-Host "-- tests"
python -m pytest -q -p no:cacheprovider --basetemp=.pytest_tmp tests
if ($LASTEXITCODE -ne 0) { throw "Tests failed - not building." }

Write-Host "-- speech model"
$model = Join-Path $env:LOCALAPPDATA "GlassPrompter-build\models\vosk-model-small-en-us-0.15"
if (-not (Test-Path $model)) {
  New-Item -ItemType Directory -Force (Split-Path $model) | Out-Null
  $zip = Join-Path (Split-Path $model) "model.zip"
  Invoke-WebRequest -UseBasicParsing "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" -OutFile $zip
  Expand-Archive $zip -DestinationPath (Split-Path $model) -Force
  Remove-Item $zip
}

Write-Host "-- assets"
python packaging\make_assets.py
if ($LASTEXITCODE -ne 0) { throw "Asset generation failed." }

Write-Host "-- bundle"
# build outside OneDrive so hundreds of MB of temp files never sync
$build = Join-Path $env:LOCALAPPDATA "GlassPrompter-build"
python -m PyInstaller --noconfirm --clean --log-level WARN `
  --distpath "$build\dist" --workpath "$build\work" packaging\GlassPrompter.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

Write-Host "-- installer"
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup" }
& $iscc /Q "/DAppVersion=$version" "/DBundleDir=$build\dist\GlassPrompter" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

$out = "dist\GlassPrompter-Setup-$version.exe"
$size = [math]::Round((Get-Item $out).Length / 1MB, 1)
$hash = (Get-FileHash $out -Algorithm SHA256).Hash
"$hash  GlassPrompter-Setup-$version.exe" | Set-Content "dist\GlassPrompter-Setup-$version.sha256.txt"
Write-Host "== Done: $out ($size MB)  SHA-256 $hash"

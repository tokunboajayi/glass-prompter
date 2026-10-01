#!/usr/bin/env bash
# Build Glass Prompter for macOS: tests -> assets -> PyInstaller .app -> .dmg
# Usage (from the project root):  bash packaging/build_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python3 -c "import glassprompter; print(glassprompter.__version__)")
ARCH=$(uname -m)
BUILD="${HOME}/Library/Caches/GlassPrompter-build"
MODEL="${BUILD}/models/vosk-model-small-en-us-0.15"
echo "== Glass Prompter ${VERSION} (${ARCH}) =="

echo "-- tests"
QT_QPA_PLATFORM=offscreen python3 -m pytest -q -p no:cacheprovider tests

echo "-- speech model"
if [ ! -f "${MODEL}/am/final.mdl" ]; then
  mkdir -p "${BUILD}/models"
  curl -fsSL -o "${BUILD}/models/model.zip" https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
  (cd "${BUILD}/models" && unzip -q -o model.zip && rm model.zip)
fi

echo "-- assets"
QT_QPA_PLATFORM=offscreen python3 packaging/make_assets.py
iconutil -c icns assets/GlassPrompter.iconset -o assets/GlassPrompter.icns

echo "-- bundle"
python3 -m PyInstaller --noconfirm --clean --log-level WARN \
  --distpath "${BUILD}/dist" --workpath "${BUILD}/work" packaging/GlassPrompter.spec
APP="${BUILD}/dist/Glass Prompter.app"
codesign --force --deep --sign - "${APP}"          # ad-hoc signature (required on Apple silicon)

echo "-- disk image"
mkdir -p dist
STAGE="${BUILD}/dmg"
rm -rf "${STAGE}" && mkdir -p "${STAGE}"
cp -R "${APP}" "${STAGE}/"
ln -s /Applications "${STAGE}/Applications"
OUT="dist/GlassPrompter-${VERSION}-macOS-${ARCH}.dmg"
rm -f "${OUT}"
hdiutil create -volname "Glass Prompter ${VERSION}" -srcfolder "${STAGE}" -ov -format UDZO "${OUT}" >/dev/null
shasum -a 256 "${OUT}" | tee "${OUT%.dmg}.sha256.txt"
echo "== Done: ${OUT}"

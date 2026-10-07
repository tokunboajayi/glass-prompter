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

echo "-- natural voice"
mkdir -p "${BUILD}/voices"
for ext in .onnx .onnx.json; do
  [ -f "${BUILD}/voices/en_US-lessac-medium${ext}" ] || curl -fsSL -o "${BUILD}/voices/en_US-lessac-medium${ext}" \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium${ext}"
done

echo "-- assets"
QT_QPA_PLATFORM=offscreen python3 packaging/make_assets.py
iconutil -c icns assets/GlassPrompter.iconset -o assets/GlassPrompter.icns

echo "-- bundle"
python3 -m PyInstaller --noconfirm --clean --log-level WARN \
  --distpath "${BUILD}/dist" --workpath "${BUILD}/work" packaging/GlassPrompter.spec
APP="${BUILD}/dist/Glass Prompter.app"
codesign --force --deep --sign - "${APP}"          # ad-hoc signature (required on Apple silicon)

echo "-- self-test of the built app (Voice Follow engine + model, Read Aloud voice + synthesis)"
for f in "Contents/Frameworks/vosk/libvosk.dyld" "Contents/Frameworks/piper/espeakbridge.so"; do
  [ -e "${APP}/${f}" ] || { echo "MISSING in bundle: ${f}"; exit 1; }
done
"${APP}/Contents/MacOS/GlassPrompter" --selftest "${BUILD}/selftest.txt" || { cat "${BUILD}/selftest.txt"; exit 1; }
cat "${BUILD}/selftest.txt"

echo "-- self-test from an App Translocation-length path (app opened from the disk image or Downloads)"
LONG="${BUILD}/translocated/AppTranslocation/00000000-0000-0000-0000-000000000000/d/padding-to-the-length-a-real-translocated-path-has"
rm -rf "${BUILD}/translocated" && mkdir -p "${LONG}"
cp -R "${APP}" "${LONG}/"
"${LONG}/Glass Prompter.app/Contents/MacOS/GlassPrompter" --selftest "${BUILD}/selftest-long.txt" \
  || { cat "${BUILD}/selftest-long.txt"; exit 1; }
cat "${BUILD}/selftest-long.txt"
rm -rf "${BUILD}/translocated"

echo "-- end-to-end audit of the built app (launch race, phone API, every control, ghost, Read Aloud)"
"${APP}/Contents/MacOS/GlassPrompter" --e2e "${BUILD}/e2e.txt" & E2E=$!
( sleep 600; kill -9 ${E2E} 2>/dev/null ) & WATCH=$!
if wait ${E2E}; then RC=0; else RC=$?; fi
kill ${WATCH} 2>/dev/null || true
cat "${BUILD}/e2e.txt" || true
[ -f "${BUILD}/e2e.txt.app.log" ] && tail -40 "${BUILD}/e2e.txt.app.log"
[ "${RC}" = "0" ] || { echo "End-to-end audit failed"; exit 1; }

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

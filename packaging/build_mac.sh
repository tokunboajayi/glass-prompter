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
# Developer ID signing when MACOS_SIGN_IDENTITY is set (release.yml imports the certificate and sets it), e.g.
#   MACOS_SIGN_IDENTITY="Developer ID Application: Jane Doe (ABCDE12345)"
# Without it: an ad-hoc signature, which Apple silicon requires, and the app stays "unidentified developer".
SIGN_ID="${MACOS_SIGN_IDENTITY:-}"
ENT="packaging/entitlements.plist"
if [ -n "${SIGN_ID}" ]; then
  echo "-- signing with ${SIGN_ID} (hardened runtime)"
  # inside-out: every nested binary first, then the app bundle itself
  find "${APP}/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -name "*.dyld" -o -perm -111 \) -print0 |
    while IFS= read -r -d '' f; do
      if file "$f" | grep -q "Mach-O"; then
        codesign --force --timestamp --options runtime --entitlements "${ENT}" --sign "${SIGN_ID}" "$f"
      fi
    done
  find "${APP}/Contents" -type d -name "*.framework" -prune -print0 |
    while IFS= read -r -d '' fw; do
      codesign --force --timestamp --options runtime --sign "${SIGN_ID}" "$fw"
    done
  codesign --force --timestamp --options runtime --entitlements "${ENT}" --sign "${SIGN_ID}" "${APP}"
  codesign --verify --deep --strict --verbose=2 "${APP}"
else
  echo "-- ad-hoc signature (no MACOS_SIGN_IDENTITY)"
  codesign --force --deep --sign - "${APP}"        # ad-hoc signature (required on Apple silicon)
fi

echo "-- self-test of the built app (Voice Follow engine + model, Read Aloud voice + synthesis)"
for f in "Contents/Frameworks/vosk/libvosk.dyld" "Contents/Frameworks/piper/espeakbridge.so"; do
  [ -e "${APP}/${f}" ] || { echo "MISSING in bundle: ${f}"; exit 1; }
done
"${APP}/Contents/MacOS/GlassPrompter" --selftest "${BUILD}/selftest.txt" || { cat "${BUILD}/selftest.txt"; exit 1; }
cat "${BUILD}/selftest.txt"

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

# Notarize when signed and notary credentials exist. Either an App Store Connect API key (preferred: no account
# password involved; revocable):  NOTARY_KEY_PATH (.p8 file), NOTARY_KEY_ID, NOTARY_ISSUER
# or an Apple ID with an app-specific password:  APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD
if [ -n "${SIGN_ID}" ]; then
  codesign --force --timestamp --sign "${SIGN_ID}" "${OUT}"
  NOTARY_MODE=""
  if [ -n "${NOTARY_KEY_PATH:-}" ] && [ -n "${NOTARY_KEY_ID:-}" ] && [ -n "${NOTARY_ISSUER:-}" ]; then
    NOTARY_MODE="key"
  elif [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
    NOTARY_MODE="appleid"
  fi
  notary() {                                       # xcrun notarytool <command> ... with the chosen credentials
    if [ "${NOTARY_MODE}" = "key" ]; then
      xcrun notarytool "$@" --key "${NOTARY_KEY_PATH}" --key-id "${NOTARY_KEY_ID}" --issuer "${NOTARY_ISSUER}"
    else
      xcrun notarytool "$@" --apple-id "${APPLE_ID}" --team-id "${APPLE_TEAM_ID}" --password "${APPLE_APP_PASSWORD}"
    fi
  }
  if [ -n "${NOTARY_MODE}" ]; then
    echo "-- notarizing with ${NOTARY_MODE} credentials (usually a few minutes)"
    SUBMIT="${BUILD}/notary.json"
    notary submit "${OUT}" --wait --timeout 30m --output-format json | tee "${SUBMIT}"
    STATUS=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('status',''))" "${SUBMIT}")
    if [ "${STATUS}" != "Accepted" ]; then
      SUB_ID=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('id',''))" "${SUBMIT}")
      [ -n "${SUB_ID}" ] && notary log "${SUB_ID}" || true
      echo "Notarization was not accepted (${STATUS})"; exit 1
    fi
    xcrun stapler staple "${OUT}"
    xcrun stapler validate "${OUT}"
    spctl --assess --type open --context context:primary-signature --verbose=2 "${OUT}" || true
  else
    echo "-- signed but NOT notarized (no notary credentials set)"
  fi
fi
shasum -a 256 "${OUT}" | tee "${OUT%.dmg}.sha256.txt"
echo "== Done: ${OUT}"

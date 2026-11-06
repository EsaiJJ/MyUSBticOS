#!/usr/bin/env bash
# Build the Portable Privacy Vault Android APK using only the Android
# build-tools (aapt2 / d8 / zipalign / apksigner). No Gradle, no dependencies.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}"

# Pick the newest available build-tools and a matching platform.
BT_DIR="$(ls -d "$SDK"/build-tools/* 2>/dev/null | sort -V | tail -1)"
if [ -z "$BT_DIR" ]; then
  echo "ERROR: Android build-tools not found under $SDK" >&2
  exit 1
fi
# Prefer a stable platform (android-36) else newest.
PLATFORM=""
for v in 36 35 34 33; do
  if [ -f "$SDK/platforms/android-$v/android.jar" ]; then
    PLATFORM="$SDK/platforms/android-$v/android.jar"; break
  fi
done
if [ -z "$PLATFORM" ]; then
  PLATFORM="$(ls "$SDK"/platforms/*/android.jar 2>/dev/null | sort -V | tail -1)"
fi

AAPT2="$BT_DIR/aapt2"
D8="$BT_DIR/d8"
ZIPALIGN="$BT_DIR/zipalign"
APKSIGNER="$BT_DIR/apksigner"
KEYSTORE="${VAULT_KEYSTORE:-$HOME/.android/debug.keystore}"
KS_PASS="${VAULT_KS_PASS:-android}"
KEY_ALIAS="${VAULT_KEY_ALIAS:-androiddebugkey}"

for tool in "$AAPT2" "$D8" "$ZIPALIGN" "$APKSIGNER"; do
  [ -x "$tool" ] || { echo "ERROR: missing $tool" >&2; exit 1; }
done
if [ ! -f "$KEYSTORE" ]; then
  echo ">> keystore not found, generating a throwaway debug keystore"
  mkdir -p "$(dirname "$KEYSTORE")"
  keytool -genkeypair -v \
    -keystore "$KEYSTORE" -storetype PKCS12 \
    -storepass "$KS_PASS" -keypass "$KS_PASS" \
    -alias "$KEY_ALIAS" -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US" >/dev/null 2>&1
fi

BUILD="$ROOT/build-android"
rm -rf "$BUILD"
mkdir -p "$BUILD/compiled" "$BUILD/gen" "$BUILD/classes" "$BUILD/dex" "$ROOT/dist"

MIN_SDK=26
TARGET_SDK=34

echo ">> build-tools: ${BT_DIR##*/}"
echo ">> platform   : $PLATFORM"
echo ">> compiling resources"
"$AAPT2" compile --dir "$HERE/res" -o "$BUILD/compiled/res.zip"

echo ">> linking resources"
"$AAPT2" link \
  -o "$BUILD/base.apk" \
  -I "$PLATFORM" \
  --manifest "$HERE/AndroidManifest.xml" \
  --java "$BUILD/gen" \
  --min-sdk-version "$MIN_SDK" \
  --target-sdk-version "$TARGET_SDK" \
  --auto-add-overlay \
  "$BUILD/compiled/res.zip"

echo ">> compiling java"
mkdir -p "$BUILD/gen/com/portablevault/vault"
javac --release 8 -Xlint:-options \
  -classpath "$PLATFORM" \
  -d "$BUILD/classes" \
  $(find "$HERE/src" "$BUILD/gen" -name '*.java')

echo ">> dexing"
"$D8" --lib "$PLATFORM" --min-api "$MIN_SDK" --output "$BUILD/dex" \
  $(find "$BUILD/classes" -name '*.class')

echo ">> packaging apk"
cp "$BUILD/base.apk" "$BUILD/unsigned.apk"
( cd "$BUILD/dex" && zip -q "$BUILD/unsigned.apk" classes.dex )
"$ZIPALIGN" -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"

echo ">> signing"
"$APKSIGNER" sign \
  --ks "$KEYSTORE" \
  --ks-pass "pass:$KS_PASS" \
  --key-pass "pass:$KS_PASS" \
  --ks-key-alias "$KEY_ALIAS" \
  --out "$ROOT/dist/vault-runner.apk" \
  "$BUILD/aligned.apk"

echo ">> verifying"
"$APKSIGNER" verify --print-certs "$ROOT/dist/vault-runner.apk" | head -5

echo ">> done: $ROOT/dist/vault-runner.apk"
ls -lh "$ROOT/dist/vault-runner.apk"

#!/usr/bin/env bash
# Build every artifact that this machine can build.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

echo "##### sanity: python sources #####"
python3 -m py_compile core/vaultlib.py installer/usb_installer.py \
  linux/vault_runner.py windows/vault_runner.py
echo "OK"

echo "##### sanity: core layout #####"
TMP="$(mktemp -d)"
python3 installer/usb_installer.py init "$TMP" >/dev/null
python3 installer/usb_installer.py verify "$TMP" >/dev/null
echo "layout OK ($TMP)"
rm -rf "$TMP"

echo "##### Linux .deb #####"
bash linux/build_deb.sh

echo "##### Android .apk #####"
if [ -d "${ANDROID_HOME:-$HOME/Android/Sdk}/build-tools" ]; then
  bash android/build_apk.sh
else
  echo "skipped: Android SDK not found"
fi

echo
echo "##### artifacts #####"
ls -lh dist/ 2>/dev/null || echo "(no dist/)"

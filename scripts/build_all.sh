#!/usr/bin/env bash
# Build every artifact that this machine can build.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

echo "##### sanity: python sources #####"
python3 -m py_compile core/vaultlib.py installer/usb_installer.py \
  linux/vault_runner.py windows/vault_runner.py scripts/build_system_image.py
echo "OK"

echo "##### sanity: core layout + checksum verify #####"
TMP="$(mktemp -d)"
python3 installer/usb_installer.py init "$TMP" >/dev/null
head -c 1048576 /dev/urandom > "$TMP/Vault/system.img"
python3 - "$TMP" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "core")
import vaultlib
vault = vaultlib.find_vault(sys.argv[1])
vaultlib.update_image_config(vault, sha512=vaultlib.sha512_file(vault.system_image))
PY
python3 installer/usb_installer.py verify "$TMP" >/dev/null
python3 linux/vault_runner.py --vault "$TMP" --no-verify --dry-run \
  --qemu /bin/true --accel tcg --display none >/dev/null
echo "layout OK ($TMP)"
rm -rf "$TMP"

if [ "${BUILD_SYSTEM_IMAGE:-0}" = "1" ]; then
  echo "##### Vault/system.img #####"
  python3 scripts/build_system_image.py
else
  echo "##### Vault/system.img #####"
  echo "skipped (set BUILD_SYSTEM_IMAGE=1 to build the 430 MB Debian image)"
fi

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

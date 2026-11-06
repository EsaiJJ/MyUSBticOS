#!/usr/bin/env bash
# Build the Linux .deb package for the Portable Privacy Vault launcher.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
VERSION="${VERSION:-1.0.0}"
ARCH="all"
PKG="vault-runner"
OUT="$ROOT/dist"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo ">> staging files"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/lib/$PKG" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/doc/$PKG" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps"

install -m 0644 "$ROOT/linux/vault_runner.py" "$STAGE/usr/lib/$PKG/vault_runner.py"
install -m 0644 "$ROOT/core/vaultlib.py"      "$STAGE/usr/lib/$PKG/vaultlib.py"
install -m 0644 "$ROOT/README.md"             "$STAGE/usr/share/doc/$PKG/README.md"

cat > "$STAGE/usr/bin/$PKG" <<'WRAP'
#!/bin/sh
exec python3 /usr/lib/vault-runner/vault_runner.py "$@"
WRAP
chmod 0755 "$STAGE/usr/bin/$PKG"

cat > "$STAGE/usr/share/applications/$PKG.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=Portable Privacy Vault
Comment=Start the portable sandboxed workspace from the USB vault
Exec=vault-runner
Terminal=true
Categories=Utility;System;
Keywords=vault;usb;portable;privacy;sandbox;
DESK

cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.8), bubblewrap
Recommends: exfatprogs | exfat-utils
Maintainer: Portable Privacy Vault Contributors <noreply@portablevault.local>
Description: Portable Privacy Vault launcher
 Starts a sandboxed workspace whose home directory is stored on a USB
 vault drive. Uses bubblewrap to mount the host read-only and the vault
 read-write, so nothing is written to the host disk. The same workspace
 is shared with the Windows and Android companion apps.
CONTROL

# Detect installed size in KiB.
SIZE="$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)"
echo "Installed-Size: $SIZE" >> "$STAGE/DEBIAN/control"
# Preserve control file permissions.
chmod 0644 "$STAGE/DEBIAN/control"

mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_${ARCH}.deb"
echo ">> building $DEB"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >/dev/null
echo ">> done: $DEB"
ls -lh "$DEB"

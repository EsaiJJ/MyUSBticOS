#!/usr/bin/env python3
"""
Portable Privacy Vault - Windows launcher.

Finds the vault USB drive and boots its preconfigured Debian system image in
an isolated QEMU virtual machine.  Vault/SharedData is shared into the guest
as /home/vault over virtio-9p, so the guest persists data to the USB drive and
the Windows filesystem is not exposed to the VM.

QEMU for Windows is auto-detected on PATH, under C:\\Program Files\\qemu, or in
Launchers/qemu. If it is missing, install it from https://www.qemu.org/download/
"""

from __future__ import annotations

import argparse
import string
import subprocess
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for candidate in (_here, _here.parent / "core"):
    if (candidate / "vaultlib.py").is_file():
        sys.path.insert(0, str(candidate))
        break
import vaultlib  # noqa: E402


def windows_vault_roots() -> list[Path]:
    roots: list[Path] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        try:
            if root.exists() and (root / "Vault").is_dir():
                roots.append(root)
        except OSError:
            continue
    return roots


def find_vault_windows(explicit: str | None) -> vaultlib.Vault | None:
    if explicit:
        return vaultlib.find_vault(explicit)
    for root in windows_vault_roots():
        vault = vaultlib.find_vault(str(root))
        if vault:
            return vault
    return vaultlib.find_vault()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Boot the Portable Privacy Vault VM (HOME = USB SharedData)."
    )
    parser.add_argument("--vault", help="explicit vault drive root, e.g. E:\\")
    parser.add_argument("--qemu", help="path to qemu-system-x86_64.exe")
    parser.add_argument("--memory", type=int, help="guest RAM in MiB")
    parser.add_argument("--cpus", type=int, help="guest vCPUs")
    parser.add_argument("--accel", choices=["auto", "whpx", "tcg"], default="auto",
                        help="virtualisation backend (default: auto)")
    parser.add_argument("--display", default="default",
                        choices=["default", "gtk", "sdl", "none", "nographic"],
                        help="QEMU display backend (default: auto)")
    parser.add_argument("--headless", action="store_true", help="same as --display none")
    parser.add_argument("--offline", action="store_true", help="disable guest networking")
    parser.add_argument("--no-verify", action="store_true", help="skip system.img checksum")
    parser.add_argument("--dry-run", action="store_true", help="print the QEMU command and exit")
    parser.add_argument("extra", nargs=argparse.REMAINDER,
                        help="extra QEMU arguments after --")
    args = parser.parse_args(argv)

    vault = find_vault_windows(args.vault)
    if not vault:
        print("ERROR: no Portable Privacy Vault found.", file=sys.stderr)
        print("Plug in the vault USB drive, or pass --vault E:\\", file=sys.stderr)
        return 1

    vault = vaultlib.create_layout(vault.root)
    if not vault.system_image.is_file():
        print(f"ERROR: missing {vault.system_image}", file=sys.stderr)
        print("Run: python installer\\usb_installer.py fetch <drive>", file=sys.stderr)
        return 1

    if not args.no_verify:
        print("Verifying system image checksum...")
        ok, message = vaultlib.verify_image(vault)
        if not ok:
            print(f"ERROR: {message}", file=sys.stderr)
            print("Re-run the installer 'fetch' command to repair the image.", file=sys.stderr)
            return 1
        print(f"  {message}")

    qemu = vaultlib.find_qemu(args.qemu)
    if not qemu:
        print("ERROR: qemu-system-x86_64.exe was not found.", file=sys.stderr)
        print("Install QEMU for Windows (https://www.qemu.org/download/#windows),", file=sys.stderr)
        print("or place it in Launchers\\qemu\\ and try again.", file=sys.stderr)
        return 1

    display = "none" if args.headless else args.display
    extra = list(args.extra)
    if extra and extra[0] == "--":
        extra = extra[1:]

    accel = None if args.accel == "auto" else args.accel
    cmd = vaultlib.build_qemu_command(
        vault, qemu, accel=accel, memory=args.memory, cpus=args.cpus,
        display=display, offline=args.offline, extra=extra,
    )

    print("=" * 62)
    print("Portable Privacy Vault - Windows VM")
    print("=" * 62)
    print(f"  vault     : {vault.root}")
    print(f"  system    : {vault.system_image}")
    print(f"  workspace : {vault.shareddata}  ->  9p:/home/vault")
    print(f"  qemu      : {qemu}")
    print(f"  user      : {vault.config.get('vm', {}).get('user', 'vault')} "
          f"(password: {vault.config.get('vm', {}).get('password', 'vault')})")
    print()

    if args.dry_run:
        print("QEMU command:\n  " + " \\\n  ".join(cmd))
        return 0

    print("Starting the VM (close the QEMU window or press Ctrl+C to stop)...")
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"ERROR: could not start QEMU: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

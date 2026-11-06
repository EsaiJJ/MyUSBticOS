#!/usr/bin/env python3
"""
Portable Privacy Vault - USB installer / preparer.

Creates the cross-platform vault layout on a USB drive.

Two ways to use it:

  1. Prepare an already-mounted USB (works on Windows, macOS, Linux):
         python3 usb_installer.py init /path/to/mount/point

  2. (Linux) Format a whole USB disk and then create the layout:
         sudo python3 usb_installer.py prepare /dev/sdb --fs exfat

Other commands:
     python3 usb_installer.py list      # list candidate disks (Linux)
     python3 usb_installer.py verify /path/to/mount/point

The filesystem is exFAT or NTFS *without* volume encryption so that Windows,
Linux and Android can all read and write it natively.  Privacy comes from the
sandboxed host apps, not from disk encryption.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Make the shared core importable no matter where this file lives.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import vaultlib  # noqa: E402


BANNER = "Portable Privacy Vault - USB Installer"


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _mount_of(device: str) -> Path | None:
    """Return the current mount point of a device, if any (Linux)."""
    try:
        out = subprocess.run(
            ["lsblk", "-no", "MOUNTPOINT", device],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    for line in out.splitlines():
        line = line.strip()
        if line:
            return Path(line)
    return None


def _mount(device: str) -> Path | None:
    """Mount a device under /run/media/vault-installer (Linux, needs root)."""
    mp = Path(f"/run/media/vault-installer/{Path(device).name}")
    mp.mkdir(parents=True, exist_ok=True)
    mount_cmd = ["mount", device, str(mp)]
    if subprocess.run(mount_cmd, capture_output=True).returncode != 0:
        # exFAT/NTFS sometimes need explicit type detection helpers.
        for extra in (["-t", "exfat"], ["-t", "ntfs"], ["-t", "ntfs3"]):
            if subprocess.run(["mount", *extra, device, str(mp)], capture_output=True).returncode == 0:
                return mp
        return None
    return mp


def cmd_list(_: argparse.Namespace) -> int:
    disks = vaultlib.list_removable_disks()
    if not disks:
        print("No candidate disks found (this command is Linux-only).")
        print("On Windows/macOS: plug the USB in and run:")
        print("  python3 usb_installer.py init <MOUNT_POINT>")
        return 0
    print(f"{'DEVICE':<16}{'SIZE':<10}{'TRANSPORT':<12}{'USB':<6}MOUNT")
    for d in disks:
        print(f"{d['path']:<16}{d['size']:<10}"
              f"{(d['transport'] or '-'):<12}"
              f"{'yes' if d['is_usb'] else 'no':<6}{d['mountpoint'] or ''}")
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    device = args.device
    if not _is_root():
        print("ERROR: preparing (formatting) a disk requires root. Use sudo.")
        return 2

    disks = {d["path"]: d for d in vaultlib.list_removable_disks()}
    info = disks.get(device)
    if info is None:
        print(f"ERROR: {device} is not a recognised removable/whole disk.")
        print("Run 'list' to see candidates.")
        return 2

    if not args.yes:
        print(f"About to ERASE {device} ({info['size']}) and create a Vault.")
        if input("Type 'ERASE' to continue: ").strip() != "ERASE":
            print("Cancelled.")
            return 1

    # Unmount anything currently mounted from the disk.
    try:
        subprocess.run(["umount", device], capture_output=True)
        for part in subprocess.run(
            ["lsblk", "-nlo", "NAME", device], capture_output=True, text=True
        ).stdout.split():
            subprocess.run(["umount", f"/dev/{part}"], capture_output=True)
    except FileNotFoundError:
        pass

    ok, msg = vaultlib.format_disk(device, args.fs, args.label)
    print(("OK: " if ok else "FAIL: ") + msg)
    if not ok:
        return 1

    mount_point = _mount(device)
    if not mount_point:
        print("ERROR: formatted, but could not mount the new filesystem.")
        print("Mount it manually and run:")
        print(f"  python3 usb_installer.py init <MOUNT_POINT>")
        return 1

    vault = vaultlib.create_layout(mount_point)
    _print_result(vault)
    subprocess.run(["umount", str(mount_point)], capture_output=True)
    try:
        mount_point.rmdir()
    except OSError:
        pass
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory / mount point.")
        return 2
    if not os.access(root, os.W_OK):
        print(f"ERROR: {root} is not writable (permissions).")
        return 2
    vault = vaultlib.find_vault(explicit_root=str(root))
    if vault and vault.is_valid and not args.force:
        print(f"Existing vault detected at {root}; verifying only.")
    else:
        vault = vaultlib.create_layout(root)
    _print_result(vault)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    vault = vaultlib.find_vault(explicit_root=str(root))
    if not vault:
        print(f"No vault found under {root}.")
        return 1
    checks = vaultlib.verify_layout(vault)
    width = max(len(n) for n, _ in checks)
    for name, ok in checks:
        print(f"[{'OK' if ok else 'MISSING':<7}] {name:<{width}}")
    return 0 if all(ok for _, ok in checks) else 1


def _print_result(vault: vaultlib.Vault) -> None:
    print()
    print(f"Vault ready at: {vault.root}")
    print(f"  workspace : {vault.shareddata}   (mounted as HOME)")
    print(f"  config    : {vault.vault_dir / 'config.json'}")
    print(f"  uuid      : {vault.config.get('vault_uuid', '?')}")
    for name, ok in vaultlib.verify_layout(vault):
        if not ok:
            print(f"  WARNING: missing {name}")
    print()
    print("Next: install the companion app on each device")
    print("  Windows : vault-runner.exe")
    print("  Linux   : vault-runner.deb  (or AppImage)")
    print("  Android : vault-runner.apk")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=BANNER)
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("list", help="list candidate disks (Linux)")
    pl.set_defaults(func=cmd_list)

    pp = sub.add_parser("prepare", help="format a disk and create the vault (Linux, root)")
    pp.add_argument("device", help="whole disk path, e.g. /dev/sdb")
    pp.add_argument("--fs", choices=["exfat", "ntfs", "fat32"], default="exfat")
    pp.add_argument("--label", default="VaultUSB")
    pp.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    pp.set_defaults(func=cmd_prepare)

    pi = sub.add_parser("init", help="create the vault on an existing mount point")
    pi.add_argument("path", help="mounted USB path, e.g. /media/user/VaultUSB or E:\\")
    pi.add_argument("--force", action="store_true")
    pi.set_defaults(func=cmd_init)

    pv = sub.add_parser("verify", help="verify an existing vault")
    pv.add_argument("path")
    pv.set_defaults(func=cmd_verify)
    return p


def main(argv: list[str] | None = None) -> int:
    print("=" * 60)
    print(BANNER)
    print("=" * 60)
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

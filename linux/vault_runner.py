#!/usr/bin/env python3
"""
Portable Privacy Vault - Linux launcher.

Boots the vault's preconfigured Debian system image in an isolated QEMU/KVM
virtual machine.  The USB folder Vault/SharedData is shared into the guest as
/home/vault using virtio-9p, so the guest can only persist data to the drive;
the host filesystem is not exposed to the VM at all.

The guest is preconfigured to auto-login as user ``vault`` (password ``vault``)
and mount the shared folder as its home directory.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for candidate in (_here, _here.parent / "core", Path("/usr/lib/vault-runner")):
    if (candidate / "vaultlib.py").is_file():
        sys.path.insert(0, str(candidate))
        break
import vaultlib  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Boot the Portable Privacy Vault VM (HOME = USB SharedData)."
    )
    parser.add_argument("--vault", help="explicit vault mount root (skip auto-detect)")
    parser.add_argument("--qemu", help="path to qemu-system-x86_64")
    parser.add_argument("--memory", type=int, help="guest RAM in MiB (default from config)")
    parser.add_argument("--cpus", type=int, help="guest vCPUs (default from config)")
    parser.add_argument("--accel", choices=["auto", "kvm", "tcg"], default="auto",
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

    vault = vaultlib.find_vault(args.vault)
    if not vault:
        print("ERROR: no Portable Privacy Vault found.", file=sys.stderr)
        print("Plug in the USB (or pass --vault <mount point>).", file=sys.stderr)
        return 1

    vault = vaultlib.create_layout(vault.root)
    if not vault.system_image.is_file():
        print(f"ERROR: missing {vault.system_image}", file=sys.stderr)
        print("Run: python3 installer/usb_installer.py fetch <mount point>", file=sys.stderr)
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
        print("ERROR: qemu-system-x86_64 was not found.", file=sys.stderr)
        print("Install it with:  sudo apt install qemu-system-x86 qemu-system-gui qemu-utils",
              file=sys.stderr)
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
    print("Portable Privacy Vault - Linux VM")
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

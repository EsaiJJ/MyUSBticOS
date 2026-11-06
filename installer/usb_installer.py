#!/usr/bin/env python3
"""
Project MyUSBticOS - USB installer / preparer.

Creates the cross-platform vault layout on a USB drive, downloads the
preconfigured Debian system image and verifies it.

Typical use on an already-mounted drive (any OS):

    python3 usb_installer.py init E:\\            # create folders + config
    python3 usb_installer.py fetch E:\\           # download Vault/system.img
    python3 usb_installer.py install-launchers E:\\

Linux, format a whole disk then do all of the above:

    sudo python3 usb_installer.py list
    sudo python3 usb_installer.py prepare /dev/sdb --fs exfat

The filesystem is exFAT or NTFS *without* volume encryption so Windows, Linux
and Android can read it natively. Privacy comes from the isolated VM, not from
disk encryption.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_core_candidates = [
    Path(__file__).resolve().parent.parent / "core",
    Path(__file__).resolve().parent,
]
for _candidate in _core_candidates:
    if (_candidate / "vaultlib.py").is_file():
        sys.path.insert(0, str(_candidate))
        break
import vaultlib  # noqa: E402


BANNER = "Project MyUSBticOS - USB Installer"
CHUNK = 1024 * 1024


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _mount_of(device: str) -> Path | None:
    try:
        out = subprocess.run(
            ["lsblk", "-no", "MOUNTPOINT", device],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    for line in out.splitlines():
        if line.strip():
            return Path(line.strip())
    return None


def _mount(device: str) -> Path | None:
    mp = Path(f"/run/media/vault-installer/{Path(device).name}")
    mp.mkdir(parents=True, exist_ok=True)
    if subprocess.run(["mount", device, str(mp)], capture_output=True).returncode == 0:
        return mp
    for extra in (["-t", "exfat"], ["-t", "ntfs"], ["-t", "ntfs3"]):
        if subprocess.run(["mount", *extra, device, str(mp)], capture_output=True).returncode == 0:
            return mp
    return None


def _progress(done: int, total: int, label: str) -> None:
    if total <= 0:
        return
    if done != total and done % (16 * CHUNK) not in (0,):
        return
    pct = 100.0 * done / total
    sys.stderr.write(
        f"\r  {label}: {vaultlib.human_size(done)} / {vaultlib.human_size(total)} "
        f"({pct:5.1f}%)"
    )
    if done >= total:
        sys.stderr.write("\n")
    sys.stderr.flush()


def _copy_with_progress(src: Path, dst: Path, label: str) -> None:
    total = vaultlib.file_size(src)
    done = 0
    with src.open("rb") as inf, dst.open("wb") as outf:
        while True:
            block = inf.read(CHUNK)
            if not block:
                break
            outf.write(block)
            done += len(block)
            _progress(done, total, label)
    if total == 0:
        sys.stderr.write(f"  {label}: copied 0 bytes\n")


def _download(url: str, dst: Path, label: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "vault-installer"})
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with dst.open("wb") as outf:
            while True:
                block = response.read(CHUNK)
                if not block:
                    break
                outf.write(block)
                done += len(block)
                _progress(done, total, label)
    if total and done != total:
        raise IOError(f"short download: got {done} of {total} bytes")


def _fetch_remote_checksum(url: str) -> str:
    sha_url = url + ".sha512"
    try:
        request = urllib.request.Request(sha_url, headers={"User-Agent": "vault-installer"})
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError):
        return ""
    for token in text.split():
        if len(token) == 128:
            try:
                int(token, 16)
                return token.lower()
            except ValueError:
                continue
    return ""


def _local_checksum(path: Path) -> str:
    for candidate in (Path(str(path) + ".sha512"), path.with_suffix(path.suffix + ".sha512")):
        if candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for token in text.split():
                if len(token) == 128:
                    return token.lower()
    return ""


def _install_image(vault: vaultlib.Vault, *, url: str = "", from_path: str = "", sha512: str = "") -> int:
    target = vault.system_image
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")

    expected = (sha512 or "").lower()
    try:
        if from_path:
            src = Path(from_path).expanduser()
            if src.is_dir():
                src = src / vaultlib.SYSTEM_IMAGE_NAME
            if not src.is_file():
                print(f"ERROR: image not found: {src}", file=sys.stderr)
                return 2
            expected = expected or _local_checksum(src)
            print(f"Copying system image from {src}")
            _copy_with_progress(src, temporary, "copy")
        else:
            url = url or vaultlib.SYSTEM_IMAGE_URL
            expected = expected or _fetch_remote_checksum(url)
            print(f"Downloading system image:\n  {url}")
            _download(url, temporary, "download")

        actual = vaultlib.sha512_file(temporary)
        if expected and actual != expected:
            temporary.unlink(missing_ok=True)
            print("ERROR: checksum verification failed.", file=sys.stderr)
            print(f"  expected: {expected}", file=sys.stderr)
            print(f"  actual  : {actual}", file=sys.stderr)
            return 1
        if not expected:
            print("WARNING: no published checksum was found; recording the observed hash.",
                  file=sys.stderr)

        temporary.replace(target)
        vaultlib.update_image_config(vault, sha512=actual)
        print(f"OK: Vault/system.img ({vaultlib.human_size(vaultlib.file_size(target))})")
        print(f"    sha512: {actual}")
        return 0
    except (urllib.error.URLError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _copy_launchers(root: Path, source: Path) -> int:
    launchers = root / vaultlib.LAUNCHERS_DIRNAME
    launchers.mkdir(parents=True, exist_ok=True)
    if not source.is_dir():
        print(f"ERROR: launcher directory not found: {source}", file=sys.stderr)
        return 2

    mapping = {".exe": "vault-runner.exe", ".deb": "vault-runner.deb", ".apk": "vault-runner.apk"}
    copied = 0
    for entry in sorted(source.iterdir()):
        suffix = entry.suffix.lower()
        if entry.is_file() and suffix in mapping:
            dst = launchers / mapping[suffix]
            shutil.copy2(entry, dst)
            print(f"  {entry.name} -> {dst.relative_to(root)}")
            copied += 1
    qemu_dir = source / "qemu"
    if qemu_dir.is_dir():
        dst = launchers / "qemu"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(qemu_dir, dst)
        print(f"  qemu/ -> {dst.relative_to(root)}")
        copied += 1
    if not copied:
        print("No .exe/.deb/.apk files found to copy.")
        return 1
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    disks = vaultlib.list_removable_disks()
    if not disks:
        print("No candidate disks found (this command is Linux-only).")
        print("On Windows/macOS: plug the USB in and run 'init <MOUNT_POINT>'.")
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
        print("Mount it manually and run 'init <MOUNT_POINT>'.")
        return 1

    vault = vaultlib.create_layout(mount_point)
    print(f"Layout created at {mount_point}")
    if not args.no_fetch:
        rc = _install_image(vault, url=args.url, sha512=args.sha512)
        if rc != 0:
            return rc
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

    vault = vaultlib.create_layout(root)
    if args.image:
        rc = _install_image(vault, from_path=args.image, sha512=args.sha512)
        if rc != 0:
            return rc
    _print_result(vault)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory / mount point.")
        return 2
    vault = vaultlib.find_vault(str(root))
    if vault is None:
        vault = vaultlib.create_layout(root)
    return _install_image(vault, url=args.url, from_path=args.source, sha512=args.sha512)


def cmd_install_launchers(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    source = Path(args.dir).expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory / mount point.")
        return 2
    vaultlib.create_layout(root)
    return _copy_launchers(root, source)


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    vault = vaultlib.find_vault(str(root))
    if not vault:
        print(f"No vault found under {root}.")
        return 1

    checks = vaultlib.verify_layout(vault)
    width = max(len(n) for n, _ in checks)
    for name, ok in checks:
        print(f"[{'OK' if ok else 'MISSING':<7}] {name:<{width}}")

    image_ok, message = vaultlib.verify_image(vault)
    print(f"[{'OK' if image_ok else 'FAIL':<7}] image: {message}")
    return 0 if all(ok for _, ok in checks) and image_ok else 1


def _print_result(vault: vaultlib.Vault) -> None:
    print()
    print(f"Vault ready at: {vault.root}")
    print(f"  system image : {vault.system_image}  (HOME is the 9p SharedData share)")
    print(f"  workspace    : {vault.shareddata}")
    print(f"  config       : {vault.vault_dir / 'config.json'}")
    print(f"  launchers    : {vault.launchers}")
    print(f"  uuid         : {vault.config.get('vault_uuid', '?')}")
    for name, ok in vaultlib.verify_layout(vault):
        if not ok:
            print(f"  WARNING: missing {name}")
    print()
    print("Next steps")
    print("  - if system.img is missing:  python3 installer/usb_installer.py fetch <drive>")
    print("  - copy launchers onto drive: python3 installer/usb_installer.py install-launchers <drive>")
    print("  - launch the VM with the app for your OS from Launchers/")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=BANNER)
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("list", help="list candidate disks (Linux)")
    pl.set_defaults(func=cmd_list)

    pp = sub.add_parser("prepare", help="format a disk, create the vault and fetch the image (Linux, root)")
    pp.add_argument("device", help="whole disk path, e.g. /dev/sdb")
    pp.add_argument("--fs", choices=["exfat", "ntfs", "fat32"], default="exfat")
    pp.add_argument("--label", default="VaultUSB")
    pp.add_argument("--url", default="", help="override system.img download URL")
    pp.add_argument("--sha512", default="", help="expected system.img SHA-512")
    pp.add_argument("--no-fetch", action="store_true", help="only create the layout")
    pp.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    pp.set_defaults(func=cmd_prepare)

    pi = sub.add_parser("init", help="create the vault on an existing mount point")
    pi.add_argument("path", help="mounted USB path, e.g. /media/user/VaultUSB or E:\\")
    pi.add_argument("--image", default="", help="copy system.img from this local path")
    pi.add_argument("--sha512", default="", help="expected system.img SHA-512")
    pi.set_defaults(func=cmd_init)

    pf = sub.add_parser("fetch", help="download / copy and verify Vault/system.img")
    pf.add_argument("path", help="mounted USB path")
    pf.add_argument("--url", default="", help="override download URL")
    pf.add_argument("--from", dest="source", default="", help="copy from a local image instead")
    pf.add_argument("--sha512", default="", help="expected SHA-512")
    pf.set_defaults(func=cmd_fetch)

    pc = sub.add_parser("install-launchers", help="copy .exe/.deb/.apk into <drive>/Launchers")
    pc.add_argument("path")
    pc.add_argument("--dir", default=str(Path(__file__).resolve().parent.parent / "dist"))
    pc.set_defaults(func=cmd_install_launchers)

    pv = sub.add_parser("verify", help="verify an existing vault and its image")
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

#!/usr/bin/env python3
"""
Portable Privacy Vault - shared core library.

Handles vault discovery, configuration, image verification and QEMU command
construction so the Windows/Linux launchers and the USB installer agree on one
format.

On-disk layout written to the USB (exFAT/NTFS, no volume encryption):

    <USB>/
      Vault/
        system.img          # preconfigured Debian 12 qcow2 (HOME = 9p share)
        SharedData/         # the workspace, mounted as HOME in the VM
          Documents/
          Downloads/
          Apps/
        config.json
      Launchers/            # vault-runner.exe / .deb / .apk
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

VAULT_DIRNAME = "Vault"
SHARED_DIRNAME = "SharedData"
SYSTEM_IMAGE_NAME = "system.img"
CONFIG_FILENAME = "config.json"
LAUNCHERS_DIRNAME = "Launchers"
CONFIG_VERSION = 2

# Standard folders inside SharedData.  These are the only entries the installer
# creates; everything else the user makes stays on the USB as well.
SHARED_SUBDIRS = ["Documents", "Downloads", "Apps"]

MOUNT_TAG = "vault"
GUEST_HOME = "/home/vault"
GUEST_USER = "vault"
GUEST_PASSWORD = "vault"

PROJECT_VERSION = "1.1.0"
GITHUB_REPO = "EsaiJJ/portable-privacy-vault"
RELEASE_BASE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download"
SYSTEM_IMAGE_URL = f"{RELEASE_BASE_URL}/system.img"
SYSTEM_IMAGE_SHA_URL = f"{RELEASE_BASE_URL}/system.img.sha512"

# Pinned official Debian image used to build Vault/system.img.
BASE_IMAGE_NAME = "Debian 12 (bookworm) generic amd64 cloud image"
BASE_IMAGE_VERSION = "20261026-2643"
BASE_IMAGE_URL = (
    "https://cloud.debian.org/images/cloud/bookworm/"
    f"{BASE_IMAGE_VERSION}/debian-12-generic-amd64-{BASE_IMAGE_VERSION}.qcow2"
)
BASE_IMAGE_SHA512 = (
    "ba6073af9f789c0f7d6b73ec1b23bb207f07f06f2d31bfd3ce5e550fe43eb941"
    "5ef983dc0e039014cd59797e0cbea5c32592e6900fa8f974f2e4466b88ff0d80"
)


@dataclass
class Vault:
    """A discovered vault on a mounted filesystem."""

    root: Path
    vault_dir: Path
    shareddata: Path
    config: dict = field(default_factory=dict)

    @property
    def system_image(self) -> Path:
        return self.vault_dir / SYSTEM_IMAGE_NAME

    @property
    def launchers(self) -> Path:
        return self.root / LAUNCHERS_DIRNAME

    @property
    def is_valid(self) -> bool:
        return self.shareddata.is_dir() and self.system_image.is_file()

    @property
    def label(self) -> str:
        return self.config.get("drive_label", "VaultUSB")

    @property
    def image_sha512(self) -> str:
        return ((self.config.get("image") or {}).get("sha512") or "").lower()


def _candidate_mount_roots() -> list[Path]:
    system = platform.system()
    candidates: list[Path] = []

    if system == "Windows":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            candidates.append(Path(f"{letter}:\\"))
    elif system == "Darwin":
        candidates.append(Path("/Volumes"))
    else:
        candidates += [
            Path("/media"),
            Path(f"/run/media/{os.environ.get('USER', '')}"),
            Path("/run/media"),
            Path("/mnt"),
        ]
    return candidates


def _iter_mount_points() -> list[Path]:
    points: list[Path] = []
    for base in _candidate_mount_roots():
        if os.name == "nt":
            if base.exists():
                points.append(base)
            continue
        if not base.is_dir():
            continue
        points.append(base)
        try:
            for entry in sorted(base.iterdir()):
                if entry.is_dir():
                    points.append(entry)
        except (PermissionError, OSError):
            continue
    return points


def find_vault(explicit_root: Optional[str] = None) -> Optional[Vault]:
    """Locate the vault, optionally constrained to a given mount root."""
    if explicit_root:
        roots = [Path(explicit_root)]
    else:
        roots = _iter_mount_points()

    for root in roots:
        vault_dir = root / VAULT_DIRNAME
        if not vault_dir.is_dir():
            continue
        shareddata = vault_dir / SHARED_DIRNAME
        vault = Vault(root=root, vault_dir=vault_dir, shareddata=shareddata)
        vault.config = load_config(vault)
        return vault
    return None


def load_config(vault: Vault) -> dict:
    path = vault.vault_dir / CONFIG_FILENAME
    if path.is_file():
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return default_config()


def default_config() -> dict:
    return {
        "config_version": CONFIG_VERSION,
        "project_version": PROJECT_VERSION,
        "vault_uuid": "",
        "drive_label": "VaultUSB",
        "created": "",
        "layout": {
            "vault_dir": VAULT_DIRNAME,
            "system_image": f"{VAULT_DIRNAME}/{SYSTEM_IMAGE_NAME}",
            "shareddata": f"{VAULT_DIRNAME}/{SHARED_DIRNAME}",
            "launchers": LAUNCHERS_DIRNAME,
        },
        "shared_subdirs": list(SHARED_SUBDIRS),
        "image": {
            "file": f"{VAULT_DIRNAME}/{SYSTEM_IMAGE_NAME}",
            "format": "qcow2",
            "sha512": "",
            "size": 0,
            "base": {
                "name": BASE_IMAGE_NAME,
                "version": BASE_IMAGE_VERSION,
                "url": BASE_IMAGE_URL,
                "sha512": BASE_IMAGE_SHA512,
            },
        },
        "vm": {
            "mount_tag": MOUNT_TAG,
            "guest_home": GUEST_HOME,
            "user": GUEST_USER,
            "password": GUEST_PASSWORD,
            "memory_mb": 2048,
            "cpus": 2,
        },
        "launchers": {
            "windows": {"file": "Launchers/vault-runner.exe", "backend": "qemu-whpx"},
            "linux": {"file": "Launchers/vault-runner.deb", "backend": "qemu-kvm"},
            "android": {"file": "Launchers/vault-runner.apk", "backend": "termux-qemu"},
        },
    }


def save_config(vault: Vault, config: dict) -> None:
    path = vault.vault_dir / CONFIG_FILENAME
    with path.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")


def init_config(config: Optional[dict] = None) -> dict:
    cfg = config or default_config()
    cfg.setdefault("config_version", CONFIG_VERSION)
    cfg["project_version"] = PROJECT_VERSION
    if not cfg.get("vault_uuid"):
        cfg["vault_uuid"] = uuid.uuid4().hex
    if not cfg.get("created"):
        cfg["created"] = datetime.now(timezone.utc).isoformat()
    cfg.setdefault("drive_label", "VaultUSB")
    return cfg


def create_layout(root: Path) -> Vault:
    """Create the complete vault layout under ``root`` and return the Vault."""
    root = Path(root)
    vault_dir = root / VAULT_DIRNAME
    shareddata = vault_dir / SHARED_DIRNAME

    for name in SHARED_SUBDIRS:
        (shareddata / name).mkdir(parents=True, exist_ok=True)
    (root / LAUNCHERS_DIRNAME).mkdir(parents=True, exist_ok=True)

    vault = Vault(root=root, vault_dir=vault_dir, shareddata=shareddata)
    config_path = vault_dir / CONFIG_FILENAME
    if config_path.exists():
        vault.config = load_config(vault)
        vault.config["project_version"] = PROJECT_VERSION
        vault.config["layout"] = default_config()["layout"]
        vault.config.setdefault("shared_subdirs", list(SHARED_SUBDIRS))
        save_config(vault, vault.config)
    else:
        vault.config = init_config()
        save_config(vault, vault.config)
    return vault


def verify_layout(vault: Vault) -> list[tuple[str, bool]]:
    checks = [
        ("Vault/", vault.vault_dir.is_dir()),
        ("Vault/config.json", (vault.vault_dir / CONFIG_FILENAME).is_file()),
        ("Vault/system.img", vault.system_image.is_file()),
        ("Vault/SharedData", vault.shareddata.is_dir()),
    ]
    for name in SHARED_SUBDIRS:
        checks.append((f"Vault/SharedData/{name}", (vault.shareddata / name).is_dir()))
    checks.append((f"{LAUNCHERS_DIRNAME}/", vault.launchers.is_dir()))
    return checks


# --------------------------------------------------------------------------
# Image helpers
# --------------------------------------------------------------------------

def sha512_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha512()
    with Path(path).open("rb") as fh:
        while True:
            block = fh.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def file_size(path: Path) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def update_image_config(vault: Vault, *, sha512: str = "", size: Optional[int] = None) -> None:
    image = vault.config.setdefault("image", {})
    image["file"] = f"{VAULT_DIRNAME}/{SYSTEM_IMAGE_NAME}"
    image["format"] = "qcow2"
    if sha512:
        image["sha512"] = sha512.lower()
    image["size"] = file_size(vault.system_image) if size is None else size
    save_config(vault, vault.config)


def verify_image(vault: Vault) -> tuple[bool, str]:
    image = vault.system_image
    if not image.is_file():
        return False, f"missing {image}"
    expected = vault.image_sha512
    if not expected:
        return True, "system.img present (no checksum recorded in config.json)"
    actual = sha512_file(image)
    if actual != expected:
        return False, f"checksum mismatch: expected {expected[:16]}... got {actual[:16]}..."
    return True, "system.img checksum OK"


def human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024.0 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num} B"


# --------------------------------------------------------------------------
# QEMU helpers
# --------------------------------------------------------------------------

def _is_executable(path: Path) -> bool:
    return path.is_file() and (os.name == "nt" or os.access(path, os.X_OK))


def find_qemu(explicit: Optional[str] = None) -> Optional[str]:
    names = ["qemu-system-x86_64.exe", "qemu-system-x86_64"]
    candidates: list[Path] = []

    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("QEMU"):
        candidates.append(Path(os.environ["QEMU"]))

    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    if getattr(sys, "frozen", False):
        here = Path(sys.executable).resolve().parent
    else:
        here = Path(__file__).resolve().parent
    for base in (here, here.parent, Path.cwd()):
        for name in names:
            candidates.append(base / LAUNCHERS_DIRNAME / "qemu" / name)
            candidates.append(base / "qemu" / name)

    if os.name == "nt":
        for base in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "qemu",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "qemu",
            Path(r"C:\qemu"),
        ):
            for name in names:
                candidates.append(base / name)
    else:
        for base in (Path("/usr/bin"), Path("/usr/local/bin"), Path("/opt/homebrew/bin")):
            for name in names:
                candidates.append(base / name)

    for candidate in candidates:
        try:
            if _is_executable(candidate):
                return str(candidate)
        except OSError:
            continue
    return None


def qemu_accels(qemu: str) -> list[str]:
    try:
        proc = subprocess.run(
            [qemu, "-accel", "help"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    known = {"kvm", "whpx", "hvf", "tcg", "hax", "xen"}
    found: list[str] = []
    for line in proc.stdout.splitlines():
        token = line.strip().split()[0] if line.strip() else ""
        if token in known and token not in found:
            found.append(token)
    return found


def choose_accel(qemu: str, requested: Optional[str] = None) -> str:
    available = qemu_accels(qemu)
    if requested and requested != "auto":
        if not available or requested in available:
            return requested
    for name in ("kvm", "whpx", "hvf", "tcg"):
        if name in available:
            return name
    return "tcg"


def build_qemu_command(
    vault: Vault,
    qemu: str,
    *,
    accel: Optional[str] = None,
    memory: Optional[int] = None,
    cpus: Optional[int] = None,
    display: str = "default",
    offline: bool = False,
    extra: Optional[list[str]] = None,
) -> list[str]:
    vm_cfg = vault.config.get("vm") or {}
    memory = int(memory or vm_cfg.get("memory_mb") or 2048)
    cpus = int(cpus or vm_cfg.get("cpus") or 2)
    chosen = choose_accel(qemu, accel)

    cpu = "host" if chosen == "kvm" else "max"
    cmd: list[str] = [
        qemu,
        "-name", "Portable Privacy Vault",
        "-machine", f"q35,accel={chosen}",
        "-cpu", cpu,
        "-m", str(memory),
        "-smp", str(cpus),
        "-drive", f"file={vault.system_image},if=none,id=vaultdisk,format=qcow2",
        "-device", "virtio-blk-pci,drive=vaultdisk,bootindex=1",
        "-snapshot",
        "-virtfs",
        "local,path={},mount_tag={},security_model=none,multidevs=remap".format(
            str(vault.shareddata).replace("\\", "/"),
            vault.config.get("vm", {}).get("mount_tag", MOUNT_TAG),
        ),
        "-boot", "order=c",
        "-device", "virtio-rng-pci",
    ]

    if not offline:
        cmd += ["-netdev", "user,id=net0", "-device", "virtio-net-pci,netdev=net0"]

    if display == "nographic":
        cmd += ["-nographic"]
    elif display == "none":
        cmd += ["-display", "none"]
    elif display and display != "default":
        cmd += ["-display", display]

    if extra:
        cmd += list(extra)
    return cmd


# --------------------------------------------------------------------------
# Drive detection / formatting helpers (used by the installer)
# --------------------------------------------------------------------------

def list_removable_disks() -> list[dict]:
    """Best-effort list of removable/whole disks using lsblk (Linux)."""
    if platform.system() != "Linux" or not shutil.which("lsblk"):
        return []
    try:
        out = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,TRAN,MOUNTPOINT"],
            capture_output=True, text=True, check=True,
        ).stdout
        data = json.loads(out)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []

    disks = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        name = dev.get("name", "")
        if name.startswith(("nvme", "loop", "sr")):
            continue
        size_bytes = int(dev.get("size") or 0)
        size_gb = size_bytes / (1024 ** 3)
        if not (0.1 <= size_gb <= 512):
            continue
        transport = (dev.get("tran") or "").lower()
        disks.append({
            "name": name,
            "path": f"/dev/{name}",
            "size_bytes": size_bytes,
            "size": f"{size_gb:.1f}G",
            "transport": transport,
            "is_usb": transport == "usb",
            "mountpoint": dev.get("mountpoint"),
        })
    disks.sort(key=lambda d: (not d["is_usb"], d["path"]))
    return disks


def format_disk(device: str, filesystem: str = "exfat", label: str = "VaultUSB") -> tuple[bool, str]:
    """Format a whole disk. Returns (ok, message). Destructive!"""
    fs = filesystem.lower()
    if fs == "exfat":
        if not shutil.which("mkfs.exfat"):
            return False, "mkfs.exfat not found"
        cmd = ["mkfs.exfat", "-n", label, device]
    elif fs == "ntfs":
        tool = "mkfs.ntfs" if shutil.which("mkfs.ntfs") else (
            "mkntfs" if shutil.which("mkntfs") else None
        )
        if not tool:
            return False, "mkfs.ntfs / mkntfs not found"
        cmd = [tool, "-F", "-Q", "-L", label, device]
    elif fs == "fat32":
        if not shutil.which("mkfs.vfat"):
            return False, "mkfs.vfat not found"
        cmd = ["mkfs.vfat", "-F", "32", "-n", label, device]
    else:
        return False, f"unsupported filesystem: {filesystem}"

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()
    return True, f"formatted {device} as {fs}"

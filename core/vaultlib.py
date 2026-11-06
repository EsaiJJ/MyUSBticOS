#!/usr/bin/env python3
"""
Portable Privacy Vault - shared core library.

Handles vault discovery, configuration, and the on-disk layout so that the
Windows and Linux launchers, and the USB installer, all agree on one format.

Layout written to the USB (filesystem exFAT or NTFS, no volume encryption):

    <USB>/
      Vault/
        config.json                 # vault configuration
        SharedData/                 # THE unified workspace, mounted as HOME
          Home/                     # user home directory
          Documents/
          Downloads/
          Apps/
          Settings/
        Images/                     # optional rootfs / disk images
        Launchers/                  # per-platform metadata
        README.md
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

VAULT_DIRNAME = "Vault"
SHARED_DIRNAME = "SharedData"
CONFIG_FILENAME = "config.json"
CONFIG_VERSION = 1

# Directory names created inside SharedData.  These double as the user's
# standard folders so that every host OS sees the same workspace.
SHARED_SUBDIRS = ["Home", "Documents", "Downloads", "Apps", "Settings"]


@dataclass
class Vault:
    """A discovered vault on a mounted filesystem."""

    root: Path                      # e.g. /media/user/VaultUSB
    vault_dir: Path                 # <root>/Vault
    shareddata: Path                # <root>/Vault/SharedData
    config: dict = field(default_factory=dict)

    @property
    def home(self) -> Path:
        return self.shareddata / "Home"

    @property
    def images(self) -> Path:
        return self.vault_dir / "Images"

    @property
    def is_valid(self) -> bool:
        return self.shareddata.is_dir()

    @property
    def label(self) -> str:
        return self.config.get("drive_label", "VaultUSB")


def _candidate_mount_roots() -> list[Path]:
    """Return plausible mount-point parent directories for this OS."""
    system = platform.system()
    candidates: list[Path] = []

    if system == "Windows":
        # Probe every logical drive letter.
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            candidates.append(Path(f"{letter}:\\"))
    elif system == "Darwin":
        candidates.append(Path("/Volumes"))
    else:  # Linux / *BSD
        candidates += [
            Path("/media"),
            Path(f"/run/media/{os.environ.get('USER', '')}"),
            Path("/run/media"),
            Path("/mnt"),
        ]
    return candidates


def _iter_mount_points() -> list[Path]:
    """Yield directories that might be the root of a mounted volume."""
    for base in _candidate_mount_roots():
        if base.name and base.drive:  # windows "X:\\"
            if base.exists():
                yield base
            continue
        if not base.is_dir():
            continue
        # Some roots (e.g. /run/media/<user>) are one level deeper.
        try:
            for entry in sorted(base.iterdir()):
                if entry.is_dir():
                    yield entry
        except (PermissionError, OSError):
            continue


def find_vault(explicit_root: Optional[str] = None) -> Optional[Vault]:
    """Locate the vault, optionally constrained to a given mount root."""
    roots = [Path(explicit_root)] if explicit_root else list(_iter_mount_points())
    for root in roots:
        vault_dir = root / VAULT_DIRNAME
        if vault_dir.is_dir():
            shareddata = vault_dir / SHARED_DIRNAME
            vault = Vault(root=root, vault_dir=vault_dir, shareddata=shareddata)
            vault.config = load_config(vault)
            return vault
    return None


def load_config(vault: Vault) -> dict:
    """Load config.json; return defaults (without writing) if missing."""
    path = vault.vault_dir / CONFIG_FILENAME
    if path.is_file():
        try:
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            pass
    return default_config()


def default_config() -> dict:
    return {
        "config_version": CONFIG_VERSION,
        "vault_uuid": "",
        "drive_label": "VaultUSB",
        "shareddata_path": "/Vault/SharedData",
        "created": "",
        "filesystem": "exfat",
        "environment": {
            "default_image": "host",
            "persistence": "real-time writes to Vault/SharedData",
        },
        "host_apps": {
            "windows": {"exe": "vault-runner.exe", "backend": "isolated-profile"},
            "linux": {"deb": "vault-runner.deb", "backend": "bubblewrap"},
            "android": {"apk": "vault-runner.apk", "access": "storage-access-framework"},
        },
    }


def save_config(vault: Vault, config: dict) -> None:
    path = vault.vault_dir / CONFIG_FILENAME
    with path.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)


def init_config(config: Optional[dict] = None) -> dict:
    """Return a fully populated config (UUID + timestamp)."""
    cfg = config or default_config()
    cfg.setdefault("config_version", CONFIG_VERSION)
    if not cfg.get("vault_uuid"):
        cfg["vault_uuid"] = uuid.uuid4().hex
    if not cfg.get("created"):
        cfg["created"] = datetime.now(timezone.utc).isoformat()
    cfg.setdefault("drive_label", "VaultUSB")
    cfg.setdefault("shareddata_path", "/Vault/SharedData")
    return cfg


# --------------------------------------------------------------------------
# Filesystem helpers
# --------------------------------------------------------------------------

def create_layout(root: Path) -> Vault:
    """Create the complete vault layout under ``root`` and return the Vault."""
    vault_dir = root / VAULT_DIRNAME
    shareddata = vault_dir / SHARED_DIRNAME
    for name in SHARED_SUBDIRS:
        (shareddata / name).mkdir(parents=True, exist_ok=True)
    (vault_dir / "Images").mkdir(exist_ok=True)
    (vault_dir / "Launchers").mkdir(exist_ok=True)

    vault = Vault(root=root, vault_dir=vault_dir, shareddata=shareddata)
    if not (vault_dir / CONFIG_FILENAME).exists():
        vault.config = init_config()
        save_config(vault, vault.config)
    else:
        vault.config = load_config(vault)

    _write_readme(vault)
    _write_launcher_metadata(vault)
    return vault


def _write_readme(vault: Vault) -> None:
    readme = vault.vault_dir / "README.md"
    if readme.exists():
        return
    readme.write_text(
        "# Portable Privacy Vault\n\n"
        "This USB drive holds a cross-platform portable workspace.\n\n"
        "- `Vault/SharedData/` - the unified workspace. Every host app mounts\n"
        "  this folder as the user's home directory, so files, downloads and\n"
        "  settings follow you between Windows, Linux and Android.\n"
        "- `Vault/Images/` - optional root filesystem / disk images.\n"
        "- `Vault/config.json` - machine readable vault configuration.\n"
        "- `Vault/Launchers/` - per-platform launcher metadata.\n\n"
        "Launch the companion app for your OS (vault-runner.exe on Windows,\n"
        "vault-runner on Linux, vault-runner.apk on Android) to start the\n"
        "sandboxed workspace.\n",
        encoding="utf-8",
    )


def _write_launcher_metadata(vault: Vault) -> None:
    launchers = {
        "windows.json": {
            "name": "Vault Runner (Windows)",
            "entry": "vault-runner.exe",
            "backend": "isolated user profile",
            "mounts": [str(vault.shareddata)],
        },
        "linux.json": {
            "name": "Vault Runner (Linux)",
            "entry": "vault-runner",
            "backend": "bubblewrap (bwrap)",
            "mounts": [str(vault.shareddata)],
        },
        "android.json": {
            "name": "Vault Runner (Android)",
            "entry": "vault-runner.apk",
            "backend": "Storage Access Framework",
            "mounts": [str(vault.shareddata)],
        },
    }
    out_dir = vault.vault_dir / "Launchers"
    out_dir.mkdir(exist_ok=True)
    for filename, data in launchers.items():
        (out_dir / filename).write_text(json.dumps(data, indent=2), encoding="utf-8")


def verify_layout(vault: Vault) -> list[tuple[str, bool]]:
    checks = [
        ("Vault/config.json", (vault.vault_dir / CONFIG_FILENAME).is_file()),
        ("Vault/SharedData", vault.shareddata.is_dir()),
    ]
    for name in SHARED_SUBDIRS:
        checks.append((f"Vault/SharedData/{name}", (vault.shareddata / name).is_dir()))
    checks += [
        ("Vault/Images", (vault.vault_dir / "Images").is_dir()),
        ("Vault/Launchers", (vault.vault_dir / "Launchers").is_dir()),
        ("Vault/README.md", (vault.vault_dir / "README.md").is_file()),
    ]
    return checks


# --------------------------------------------------------------------------
# Drive detection / formatting helpers (used by the installer)
# --------------------------------------------------------------------------

def _parse_size_gb(size: str) -> float:
    size = size.strip().replace(",", ".")
    mult = 1.0
    if size and size[-1].upper() == "T":
        mult, size = 1024.0, size[:-1]
    elif size and size[-1].upper() == "G":
        mult, size = 1.0, size[:-1]
    elif size and size[-1].upper() == "M":
        mult, size = 1.0 / 1024.0, size[:-1]
    elif size and size[-1].upper() == "K":
        mult, size = 1.0 / (1024.0 * 1024.0), size[:-1]
    try:
        return float(size) * mult
    except ValueError:
        return 0.0


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
        # Prefer real USB devices but keep others selectable.
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

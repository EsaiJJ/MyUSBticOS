#!/usr/bin/env python3
"""
Portable Privacy Vault - Windows launcher.

Finds the vault USB drive, then starts a shell whose entire user profile
(HOME, USERPROFILE, APPDATA, LOCALAPPDATA, TEMP) points at the vault's
SharedData folder.  Programs launched from that shell therefore read and
write their data on the USB stick instead of the host machine.

This is the "portable profile" isolation strategy for Windows; it needs no
administrator rights and no driver.  If Windows Subsystem for Linux (WSL) is
available it can additionally start a Linux workspace inside the vault.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
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


def windows_ready_volumes() -> list[Path]:
    """Return drive roots that look like removable vault drives."""
    roots: list[Path] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        if root.exists() and (root / "Vault" / "SharedData").is_dir():
            roots.append(root)
    return roots


def find_vault_windows(explicit: str | None) -> vaultlib.Vault | None:
    if explicit:
        return vaultlib.find_vault(explicit)
    for root in windows_ready_volumes():
        vault = vaultlib.find_vault(str(root))
        if vault:
            return vault
    # Fall back to the generic (cross-platform) detector.
    return vaultlib.find_vault()


def build_isolated_env(vault: vaultlib.Vault) -> dict:
    """Return an environment whose profile lives entirely on the vault."""
    base = vault.shareddata
    sub = {
        "HOME": base,
        "USERPROFILE": base,
        "APPDATA": base / "Settings" / "AppData" / "Roaming",
        "LOCALAPPDATA": base / "Settings" / "AppData" / "Local",
        "TEMP": base / ".tmp",
        "TMP": base / ".tmp",
        "HOMEDRIVE": str(base.anchor or "C:"),
        "HOMEPATH": str(base),
        "OneDrive": base / "Documents",
        "VAULT_SESSION": "1",
    }
    env = os.environ.copy()
    for key, path in sub.items():
        if key in ("VAULT_SESSION", "HOMEDRIVE"):
            env[key] = str(path)
            continue
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    return env


def wsl_available() -> bool:
    if shutil.which("wsl") is None:
        return False
    try:
        return subprocess.run(
            ["wsl", "-l", "-q"], capture_output=True, timeout=8
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def launch_wsl(vault: vaultlib.Vault) -> int:
    """Start a WSL bash whose working dir is the mounted vault (if visible)."""
    win_shared = str(vault.shareddata)
    # Convert C:\a\b -> /mnt/c/a/b for WSL.
    drive = win_shared[0].lower()
    wsl_path = "/mnt/" + drive + win_shared[2:].replace("\\", "/")
    script = (
        f"export HOME='{wsl_path}'; cd '{wsl_path}' || true; "
        f"echo 'Vault (WSL) home:' $HOME; exec bash"
    )
    print(f"Starting WSL workspace at {wsl_path}")
    return subprocess.call(["wsl", "bash", "-lc", script])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the Portable Privacy Vault workspace.")
    parser.add_argument("--vault", help="explicit vault mount root")
    parser.add_argument("--wsl", action="store_true", help="start a WSL Linux workspace instead of cmd")
    parser.add_argument("--shell", default=os.environ.get("COMSPEC", "cmd.exe"))
    parser.add_argument("--dry-run", action="store_true", help="print the isolated profile and exit")
    args = parser.parse_args(argv)

    vault = find_vault_windows(args.vault)
    if not vault:
        print("ERROR: no Portable Privacy Vault found.", file=sys.stderr)
        print("Plug in the vault USB drive and try again.", file=sys.stderr)
        return 1

    vaultlib.create_layout(vault.root)
    vault = find_vault_windows(str(vault.root)) or vault

    print("=" * 62)
    print("Portable Privacy Vault - Windows workspace")
    print("=" * 62)
    print(f"  vault     : {vault.root}")
    print(f"  workspace : {vault.shareddata}")
    print(f"  uuid      : {vault.config.get('vault_uuid', '?')}")
    print()

    if args.dry_run:
        env = build_isolated_env(vault)
        for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP"):
            print(f"  {key} = {env[key]}")
        return 0

    if args.wsl and wsl_available():
        return launch_wsl(vault)

    env = build_isolated_env(vault)
    print("Starting isolated shell (profile on USB, host profile untouched)...")
    try:
        return subprocess.call([args.shell], env=env, cwd=str(vault.shareddata))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

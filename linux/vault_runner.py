#!/usr/bin/env python3
"""
Portable Privacy Vault - Linux launcher.

Starts a sandboxed workspace whose HOME is the USB vault's SharedData folder.
Isolation is provided by bubblewrap (bwrap):

  * the host filesystem is mounted READ-ONLY inside the sandbox,
  * /tmp is a throw-away tmpfs (nothing is written to the host disk),
  * the vault's SharedData is the only writable, persistent location,
  * the host's HOME, caches and history are never touched.

If bwrap is unavailable it degrades to a plain shell with HOME pointed at the
vault (still persistent, but without filesystem isolation).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Allow running straight from the repo as well as from an installed .deb.
_here = Path(__file__).resolve().parent
for candidate in (_here, _here.parent / "core"):
    if (candidate / "vaultlib.py").is_file():
        sys.path.insert(0, str(candidate))
        break
import vaultlib  # noqa: E402


RO_SYSTEM_DIRS = ["/usr", "/bin", "/sbin", "/lib", "/lib64", "/lib32", "/etc", "/opt"]
GUEST_HOME = "/home/vault"


def _existing(paths: list[str]) -> list[str]:
    return [p for p in paths if os.path.exists(p)]


def build_bwrap_command(vault: vaultlib.Vault, argv: list[str], *, offline: bool, gui: bool) -> list[str]:
    shared = str(vault.shareddata)
    cmd: list[str] = ["bwrap"]

    # Read-only host system.
    for d in _existing(RO_SYSTEM_DIRS):
        cmd += ["--ro-bind", d, d]
    for d in _existing(["/run", "/var", "/sys"]):
        cmd += ["--ro-bind", d, d]
    cmd += ["--ro-bind-try", "/usr/share", "/usr/share"]

    # The one writable, persistent location: the vault.
    cmd += ["--bind", shared, GUEST_HOME]

    # Ephemeral runtime.
    cmd += [
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--tmpfs", "/run/user",
    ]

    # Isolation / lifecycle.
    cmd += ["--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent"]
    if offline:
        cmd += ["--unshare-net"]

    # Environment.
    env = {
        "HOME": GUEST_HOME,
        "USER": os.environ.get("USER", "vault"),
        "XDG_CONFIG_HOME": f"{GUEST_HOME}/Settings/config",
        "XDG_DATA_HOME": f"{GUEST_HOME}/Settings/share",
        "XDG_CACHE_HOME": f"{GUEST_HOME}/.cache",
        "XDG_DOCUMENTS_DIR": f"{GUEST_HOME}/Documents",
        "XDG_DOWNLOAD_DIR": f"{GUEST_HOME}/Downloads",
        "VAULT_SESSION": "1",
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    if gui:
        if os.environ.get("DISPLAY"):
            env["DISPLAY"] = os.environ["DISPLAY"]
        if os.environ.get("WAYLAND_DISPLAY"):
            env["WAYLAND_DISPLAY"] = os.environ["WAYLAND_DISPLAY"]
        if os.environ.get("XDG_RUNTIME_DIR"):
            env["XDG_RUNTIME_DIR"] = os.environ["XDG_RUNTIME_DIR"]
        for sock in ("/tmp/.X11-unix", "/run/user"):
            if os.path.exists(sock):
                cmd += ["--ro-bind-try", sock, sock]
    for key, val in env.items():
        cmd += ["--setenv", key, val]

    cmd += ["--chdir", GUEST_HOME]
    cmd += ["--", *argv]
    return cmd


def run_plain(vault: vaultlib.Vault, argv: list[str]) -> int:
    """Fallback: run with HOME on the vault, no isolation."""
    env = os.environ.copy()
    env["HOME"] = str(vault.shareddata)
    env["VAULT_SESSION"] = "1"
    return subprocess.call(argv, env=env, cwd=str(vault.shareddata))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Start the Portable Privacy Vault sandboxed workspace."
    )
    parser.add_argument("--vault", help="explicit vault mount root (skip auto-detect)")
    parser.add_argument("--shell", default="/bin/bash", help="shell to run (default /bin/bash)")
    parser.add_argument("--offline", action="store_true", help="disable network in the sandbox")
    parser.add_argument("--gui", action="store_true", help="share X11/Wayland sockets for GUI apps")
    parser.add_argument("--dry-run", action="store_true", help="print the sandbox command and exit")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="optional command to run instead of an interactive shell")
    args = parser.parse_args(argv)

    vault = vaultlib.find_vault(args.vault)
    if not vault:
        print("ERROR: no Portable Privacy Vault found.", file=sys.stderr)
        print("Plug in the USB (or pass --vault <mount point>) and try again.", file=sys.stderr)
        return 1

    # Ensure the layout is sane even on a drive prepared elsewhere.
    vaultlib.create_layout(vault.root)
    vault = vaultlib.find_vault(str(vault.root)) or vault

    print("=" * 62)
    print("Portable Privacy Vault - Linux workspace")
    print("=" * 62)
    print(f"  vault     : {vault.root}")
    print(f"  workspace : {vault.shareddata}  ->  {GUEST_HOME}")
    print(f"  uuid      : {vault.config.get('vault_uuid', '?')}")
    print()

    # Command to run inside the sandbox.
    run = args.command or []
    if run and run[0] == "--":
        run = run[1:]
    if not run:
        run = [args.shell]

    bwrap = shutil.which("bwrap")
    if not bwrap:
        print("bwrap not found - running without filesystem isolation.", file=sys.stderr)
        print("  (install 'bubblewrap' for full sandboxing)", file=sys.stderr)
        return run_plain(vault, run)

    cmd = build_bwrap_command(vault, run, offline=args.offline, gui=args.gui)
    if args.dry_run:
        print("sandbox command:\n  " + " \\\n  ".join(cmd))
        return 0

    print("Starting sandbox (host is read-only; workspace persists to USB)...")
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

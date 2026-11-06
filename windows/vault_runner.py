#!/usr/bin/env python3
"""
Portable Privacy Vault - Windows Host Application (.exe skeleton)
Detects the USB drive, mounts the Vault/SharedData folder, and launches
a lightweight containerized/virtualized workspace environment.

This Python script can be compiled to a Windows .exe using PyInstaller.
"""

import os
import sys
import json
import subprocess
import platform
import ctypes
from pathlib import Path


def find_usb_drive():
    """Detect the Vault USB drive by looking for the Vault directory structure."""
    system = platform.system()
    
    # Windows drive letters
    if system == "Windows":
        import win32con
        import win32api
        
        # Get all drive types
        drives = win32api.GetLogicalDriveStrings()
        drive_list = drives.split("\x00")[:-1]
        
        for drive in drive_list:
            # Check if it's a removable drive
            try:
                drive_type = win32api.GetDriveType(drive)
                if drive_type == win32con.REMOVABLE:
                    # Check if Vault directory exists
                    vault_path = os.path.join(drive, "Vault")
                    if os.path.isdir(vault_path):
                        shareddata_path = os.path.join(vault_path, "SharedData")
                        if os.path.isdir(shareddata_path):
                            return {
                                "drive_letter": drive,
                                "vault_path": vault_path,
                                "shareddata_path": shareddata_path,
                                "label": "VaultUSB"
                            }
            except Exception:
                continue
    
    # Linux - check /media, /run/media, /mnt
    elif system == "Linux":
        mount_points = ["/media", "/run/media", "/mnt"]
        for mp in mount_points:
            if not os.path.isdir(mp):
                continue
            try:
                for entry in os.listdir(mp):
                    drive_path = os.path.join(mp, entry)
                    if os.path.isdir(drive_path):
                        vault_path = os.path.join(drive_path, "Vault")
                        shareddata_path = os.path.join(vault_path, "SharedData")
                        if os.path.isdir(vault_path) and os.path.isdir(shareddata_path):
                            return {
                                "drive_letter": entry,
                                "vault_path": vault_path,
                                "shareddata_path": shareddata_path,
                                "label": "VaultUSB"
                            }
            except PermissionError:
                continue
    
    # macOS - check /Volumes
    elif system == "Darwin":
        volumes_path = "/Volumes"
        if os.path.isdir(volumes_path):
            for entry in os.listdir(volumes_path):
                drive_path = os.path.join(volumes_path, entry)
                if os.path.isdir(drive_path):
                    vault_path = os.path.join(drive_path, "Vault")
                    shareddata_path = os.path.join(vault_path, "SharedData")
                    if os.path.isdir(vault_path) and os.path.isdir(shareddata_path):
                        return {
                            "drive_letter": entry,
                            "vault_path": vault_path,
                            "shareddata_path": shareddata_path,
                            "label": "VaultUSB"
                        }
    
    return None


def load_config():
    """Load vault configuration from the USB drive."""
    usb_drive = find_usb_drive()
    if not usb_drive:
        return None
    
    config_path = os.path.join(usb_drive["vault_path"], "Config", "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    
    # Return default config if not found
    return {
        "vault_uuid": os.urandom(16).hex(),
        "shareddata_path": "/Vault/SharedData",
        "container_runtime": "auto",
        "host": "windows"
    }


def find_qemu_or_container():
    """Find available container/virtualization runtime."""
    # Check for QEMU
    qemu_paths = [
        "/usr/bin/qemu-system-x86_64",
        "/usr/local/bin/qemu-system-x86_64",
        "qemu-system-x86_64",
    ]
    
    for path in qemu_paths:
        if shutil.which(path) or os.path.exists(path):
            return {"type": "qemu", "path": path}
    
    # Check for systemd-nspawn
    if shutil.which("systemd-nspawn"):
        return {"type": "systemd-nspawn"}
    
    # Check for LXD/LXC
    if shutil.which("lxc-start"):
        return {"type": "lxc"}
    
    return None


def launch_virtualized_environment(shareddata_path, config):
    """Launch the containerized/virtualized workspace."""
    runtime = find_qemu_or_container()
    
    if not runtime:
        print("No virtualization/runtime found. Falling back to direct execution.")
        return launch_directly(shareddata_path)
    
    print(f"Using runtime: {runtime['type']}")
    
    # Determine the workspace type based on config or auto-detect
    env_type = config.get("environment", {}).get("default_image", "linux-base")
    
    if runtime["type"] == "qemu":
        return launch_qemu_environment(shareddata_path, env_type, runtime)
    elif runtime["type"] == "systemd-nspawn":
        return launch_systemd_nspawn(shareddata_path, env_type)
    elif runtime["type"] == "lxc":
        return launch_lxc_environment(shareddata_path, env_type)
    
    return launch_directly(shareddata_path)


def launch_qemu_environment(shareddata_path, env_type, runtime):
    """Launch a QEMU virtualized environment."""
    # Build QEMU command
    mem_mb = config.get("host_apps", {}).get("windows", {}).get("ram_limit_mb", 2048)
    cpu_limit = config.get("host_apps", {}).get("windows", {}).get("cpu_limit", "auto")
    
    # Determine the image to use
    image_name = f"{env_type}.img"
    image_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vault", "Images", image_name)
    
    # If image doesn't exist, create a minimal one or use shareddata as root
    if not os.path.exists(image_path):
        print(f"Image not found at {image_path}, using shareddata as root")
        image_path = None
    
    # QEMU command for a lightweight workspace
    qemu_cmd = [
        runtime["path"],
        "-m", str(mem_mb),
        "-cpu", "host",
        "-drive", f"file={image_path or shareddata_path},format=raw",
        "-net", "none",
        "-nographic",
        "-no-reboot"
    ]
    
    # Add CPU pinning if specified
    if cpu_limit != "auto":
        qemu_cmd.extend(["-smp", str(cpu_limit)])
    
    print(f"Launching QEMU environment with shareddata: {shareddata_path}")
    
    try:
        subprocess.Popen(qemu_cmd, 
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL)
        print("QEMU session started in background.")
    except FileNotFoundError:
        print(f"Could not find QEMU at {runtime['path']}")
        return launch_directly(shareddata_path)
    except Exception as e:
        print(f"QEMU launch error: {e}")
        return launch_directly(shareddata_path)


def launch_systemd_nspawn(shareddata_path, env_type):
    """Launch a systemd-nspawn container."""
    container_name = "vault-container"
    
    # Create the container if it doesn't exist
    subprocess.run([
        "systemd-nspawn", "-D", shareddata_path,
        "-b", "--register=no",
        "--machine", container_name
    ], capture_output=True)
    
    print(f"systemd-nspawn container started with root: {shareddata_path}")
    return True


def launch_lxc_environment(shareddata_path, env_type):
    """Launch an LXC container."""
    print(f"LXC container launch with {shareddata_path}")
    subprocess.run(["lxc-start", "-n", "vault", "-s", "/tmp/vault.socket"], capture_output=True)
    return True


def launch_directly(shareddata_path):
    """Launch a direct Python-based workspace (no virtualization)."""
    print(f"Direct execution with shareddata: {shareddata_path}")
    
    # Launch a Python process that uses the shareddata as home
    home_dir = os.path.join(shareddata_path, "Home")
    os.makedirs(home_dir, exist_ok=True)
    
    # Set HOME environment variable
    env = os.environ.copy()
    env["HOME"] = home_dir
    env["XDG_DATA_HOME"] = os.path.join(home_dir, ".local", "share")
    
    # Launch a simple Python shell or script
    try:
        subprocess.Popen(
            [sys.executable, "-i", "-c", "import os; print(f'Vault workspace active. Home: {os.environ.get(\"HOME\')}')"],
            env=env
        )
        return True
    except Exception as e:
        print(f"Direct launch error: {e}")
        return False


def main():
    """Main entry point for the Windows host application."""
    print("=" * 60)
    print("Portable Privacy Vault - Windows Host Launcher")
    print("=" * 60)
    print()
    
    # Load configuration
    config = load_config()
    if not config:
        print("ERROR: Could not find Vault USB drive.")
        print("Please ensure the Vault USB is connected and contains the proper structure.")
        print("Expected structure: /Vault/SharedData/ on the drive root")
        sys.exit(1)
    
    print(f"Vault USB detected: {usb_drive['label']}" if 'usb_drive' in dir() else "Vault USB detected")
    print(f"Configuration loaded: {config.get('vault_uuid', '')[:8]}...")
    print()
    
    # Find the USB drive
    usb_drive = find_usb_drive()
    if not usb_drive:
        print("ERROR: Could not find Vault USB drive.")
        sys.exit(1)
    
    print(f"USB Drive: {usb_drive['drive_letter']}")
    print(f"Vault Path: {usb_drive['vault_path']}")
    print(f"Shared Data: {usb_drive['shareddata_path']}")
    print()
    
    # Load shared data configuration
    shareddata_path = usb_drive["shareddata_path"]
    
    # Launch the virtualized environment
    print("Launching virtualized workspace...")
    print("-" * 60)
    success = launch_virtualized_environment(shareddata_path, config)
    
    if success:
        print()
        print("Vault workspace is now running.")
        print("All files created/modified will be persisted to:", shareddata_path)
        print("When you close this application, the workspace will pause.")
        print("Plug the USB into another device to continue where you left off.")
    else:
        print()
        print("Failed to launch virtualized environment.")
        print("Falling back to direct shared data access...")
        launch_directly(shareddata_path)
    
    print()
    print("=" * 60)
    print("Portable Privacy Vault - Windows Host Launcher")
    print("=" * 60)


if __name__ == "__main__":
    # Import shutil here to avoid circular imports at module level
    import shutil
    main()
#!/usr/bin/env python3
"""
Portable Privacy Vault - USB Installer
Creates the vault directory structure on a USB drive for the cross-platform portable workspace.

Features:
- Formats USB as exFAT (or NTFS if exFAT tools not available)
- Creates /Vault/SharedData/ unified shared data partition
- Creates /Vault/Images/ for container/VM images
- Creates /Vault/Config.json configuration
- Installs minimal launcher metadata
- Safe: operates on user-specified path, no automatic drive wiping
"""

import os
import sys
import json
import argparse
import shutil
import subprocess
from pathlib import Path


def check_dependencies():
    """Check required tools are available."""
    missing = []
    
    # Check for exFAT/NTFS tools
    if shutil.which("mkfs.exfat") is None:
        if shutil.which("mkfs.ntfs") is None:
            missing.append("mkfs.exfat or mkfs.ntfs (for formatting)")
    
    if shutil.which("parted") is None:
        missing.append("parted (for partition table)")
    
    if shutil.which("mkdir") is None:
        missing.append("mkdir (basic filesystem)")
    
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print("Installing via apt...")
        try:
            subprocess.run(["apt", "update"], capture_output=True)
            for pkg in missing:
                subprocess.run(["apt", "install", "-y", pkg], capture_output=True)
        except Exception as e:
            print(f"Could not auto-install dependencies: {e}")
            sys.exit(1)
    
    print("Dependencies checked OK.")


def detect_usb_drives():
    """Detect available USB drives."""
    drives = []
    result = subprocess.run(["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINT", "-J"], 
                          capture_output=True, text=True)
    if result.returncode != 0:
        return drives
    
    import json as _json
    data = _json.loads(result.stdout)
    for device in data.get("blockdevices", []):
        name = device.get("name", "")
        size = device.get("size", "0")
        devtype = device.get("type", "")
        mounts = device.get("mountpoints", [])
        
        if devtype == "disk" and size:
            # Check if it looks like a USB drive (typically smaller than internal drives)
            size_gb = float(size.replace("G", "").replace("M", "/1024"))
            # If size is reasonable for a USB (128MB - 256GB)
            if 0.1 < size_gb < 256 and "nvme" not in name.lower():
                drives.append({
                    "name": name,
                    "path": f"/dev/{name}",
                    "size": size,
                    "mountpoints": mounts
                })
    
    return drives


def format_usb(drive_path, fs="exfat"):
    """Format the USB drive with the specified filesystem."""
    print(f"Formatting {drive_path} as {fs}...")
    
    if fs == "exfat":
        mkfs_cmd = ["mkfs.exfat", "-n", "VaultUSB", drive_path]
    else:
        mkfs_cmd = ["mkfs.ntfs", "-F", "-Q", drive_path]
    
    result = subprocess.run(mkfs_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Format failed: {result.stderr}")
        return False
    
    print(f"Successfully formatted {drive_path} as {fs}")
    return True


def create_vault_structure(mount_point):
    """Create the vault directory structure on the mounted USB."""
    print(f"Creating vault structure at {mount_point}...")
    
    vault_dir = os.path.join(mount_point, "Vault")
    shareddata_dir = os.path.join(vault_dir, "SharedData")
    images_dir = os.path.join(vault_dir, "Images")
    templates_dir = os.path.join(vault_dir, "Templates")
    config_dir = os.path.join(vault_dir, "Config")
    
    # Create directories
    dirs = [vault_dir, shareddata_dir, images_dir, templates_dir, config_dir]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        print(f"  Created: {d}")
    
    # Create SharedData subdirectories
    subdirs = [
        os.path.join(shareddata_dir, "Home"),
        os.path.join(shareddata_dir, "Documents"),
        os.path.join(shareddata_dir, "Downloads"),
        os.path.join(shareddata_dir, "Apps"),
        os.path.join(shareddata_dir, "Settings"),
    ]
    for d in subdirs:
        os.makedirs(d, exist_ok=True)
    
    # Create config.json
    config = {
        "vault_uuid": os.urandom(16).hex(),
        "drive_label": "VaultUSB",
        "shareddata_path": "/Vault/SharedData",
        "created": subprocess.run(["date"], capture_output=True, text=True).stdout,
        "format": "exFAT" if shutil.which("mkfs.exfat") else "NTFS",
        "host_apps": {
            "windows": "vault-runner.exe",
            "linux": "vault-runner AppImage/deb",
            "android": "vault-runner.apk"
        }
    }
    
    config_path = os.path.join(config_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"  Created: {config_path}")
    
    # Create README
    readme_path = os.path.join(vault_dir, "README.md")
    if not os.path.exists(readme_path):
        with open(readme_path, "w") as f:
            f.write("# Portable Privacy Vault\n\n")
            f.write("## USB Drive Structure\n\n")
            f.write("- `Vault/SharedData/` - Your persistent workspace (mounted as primary home by all host apps)\n")
            f.write("- `Vault/Images/` - Container/VM environment images\n")
            f.write("- `Vault/Config/config.json` - Vault configuration\n")
            f.write("- `Vault/Templates/` - Pre-configured environment templates\n\n")
            f.write("## How It Works\n\n")
            f.write("1. Plug the USB into any host device (Windows, Linux, or Android)\n")
            f.write("2. Launch the native host app (.exe, .deb, or .apk)\n")
            f.write("3. The app mounts `Vault/SharedData/` as your home/storage directory\n")
            f.write("4. Any files you create, download, or settings you change are written back to this folder\n")
            f.write("5. Your workspace follows you to the next device instantly\n")
    
    print(f"  Created: {readme_path}")
    
    # Create .nomedia files to prevent indexing on some systems
    for d in [shareddata_dir, os.path.join(vault_dir)]:
        nomedia = os.path.join(d, ".nomedia")
        if not os.path.exists(nomedia):
            with open(nomedia, "w") as f:
                f.write("")
    
    print("Vault structure created successfully!")
    print()
    print("Directory structure:")
    print(f"  {mount_point}/")
    print(f"    Vault/")
    print(f"      Config/config.json")
    print(f"      README.md")
    print(f"      SharedData/")
    print(f"        Home/")
    print(f"        Documents/")
    print(f"        Downloads/")
    print(f"        Apps/")
    print(f"        Settings/")
    print(f"      Images/")
    print(f"      Templates/")


def install_launcher_metadata(mount_point):
    """Install launcher metadata that host apps can read."""
    print("Installing launcher metadata...")
    
    vault_dir = os.path.join(mount_point, "Vault")
    config_dir = os.path.join(vault_dir, "Config")
    
    # Read existing config
    config_path = os.path.join(config_dir, "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = json.load(f)
    else:
        config = {
            "vault_uuid": os.urandom(16).hex(),
            "drive_label": "VaultUSB",
            "shareddata_path": "/Vault/SharedData",
            "host_apps": {
                "windows": "vault-runner.exe",
                "linux": "vault-runner AppImage/deb",
                "android": "vault-runner.apk"
            }
        }
    
    # Create launcher info for each platform
    launchers_dir = os.path.join(vault_dir, "Launchers")
    os.makedirs(launchers_dir, exist_ok=True)
    
    # Windows launcher info
    win_info = {
        "name": "Vault Runner Windows",
        "exe": "vault-runner.exe",
        "description": "Launches the portable workspace on Windows",
        "detects_usb": True,
        "mounts": ["/Vault/SharedData"],
        "virtualization": "QEMU/KVM or Windows Subsystem for Linux"
    }
    with open(os.path.join(launchers_dir, "windows.json"), "w") as f:
        json.dump(win_info, f, indent=2)
    
    # Linux launcher info
    linux_info = {
        "name": "Vault Runner Linux",
        "appimage": "vault-runner.AppImage",
        "deb_package": "vault-runner.deb",
        "description": "Launches the portable workspace on Linux",
        "detects_usb": True,
        "mounts": ["/Vault/SharedData"],
        "virtualization": "QEMU/KVM, systemd-nspawn, or LXC"
    }
    with open(os.path.join(launchers_dir, "linux.json"), "w") as f:
        json.dump(linux_info, f, indent=2)
    
    # Android launcher info
    android_info = {
        "name": "Vault Runner Android",
        "apk": "vault-runner.apk",
        "description": "Launches the portable workspace on Android",
        "uses_usb_otg": True,
        "mounts": ["/Vault/SharedData"],
        "virtualization": "Local execution on mobile hardware, QEMU guest"
    }
    with open(os.path.join(launchers_dir, "android.json"), "w") as f:
        json.dump(android_info, f, indent=2)
    
    print(f"  Created launcher metadata in {launchers_dir}/")


def verify_usb_structure(mount_point):
    """Verify the vault structure is correct."""
    print("Verifying vault structure...")
    
    checks = [
        ("Vault directory", os.path.isdir(os.path.join(mount_point, "Vault"))),
        ("Config.json", os.path.isfile(os.path.join(mount_point, "Vault", "Config", "config.json"))),
        ("SharedData directory", os.path.isdir(os.path.join(mount_point, "Vault", "SharedData"))),
        ("Home subdirectory", os.path.isdir(os.path.join(mount_point, "Vault", "SharedData", "Home"))),
        ("Documents subdirectory", os.path.isdir(os.path.join(mount_point, "Vault", "SharedData", "Documents"))),
        ("Downloads subdirectory", os.path.isdir(os.path.join(mount_point, "Vault", "SharedData", "Downloads"))),
        ("Apps subdirectory", os.path.isdir(os.path.join(mount_point, "Vault", "SharedData", "Apps"))),
        ("Settings subdirectory", os.path.isdir(os.path.join(mount_point, "Vault", "SharedData", "Settings"))),
        ("Images directory", os.path.isdir(os.path.join(mount_point, "Vault", "Images"))),
        ("Templates directory", os.path.isdir(os.path.join(mount_point, "Vault", "Templates"))),
        ("README.md", os.path.isfile(os.path.join(mount_point, "Vault", "README.md"))),
    ]
    
    all_ok = True
    for name, result in checks:
        status = "OK" if result else "MISSING"
        if not result:
            all_ok = False
        print(f"  [{status}] {name}")
    
    if all_ok:
        print("Verification complete: all required structures present.")
    else:
        print("Verification complete: some structures are missing.")
    
    return all_ok


def main():
    parser = argparse.ArgumentParser(
        description="Portable Privacy Vault - USB Installer"
    )
    parser.add_argument(
        "target_drive",
        nargs="?",
        help="Target USB drive device path (e.g., /dev/sdb). If not provided, will detect available drives."
    )
    parser.add_argument(
        "--filesystem", 
        choices=["exfat", "ntfs"], 
        default="exfat",
        help="Filesystem to use (default: exfat). Use ntfs if exFAT tools are unavailable."
    )
    parser.add_argument(
        "--no-format", 
        action="store_true",
        help="Skip formatting, assume drive is already formatted with correct filesystem."
    )
    parser.add_argument(
        "--verify-only", 
        action="store_true",
        help="Only verify existing vault structure on a drive."
    )
    parser.add_argument(
        "--list-drives", 
        action="store_true",
        help="List available USB drives."
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Portable Privacy Vault - USB Installer")
    print("=" * 60)
    print()
    
    # Check dependencies
    check_dependencies()
    print()
    
    # List drives if requested
    if args.list_drives:
        drives = detect_usb_drives()
        print("Available USB drives:")
        for i, drive in enumerate(drives):
            print(f"  {i+1}. {drive['name']} - {drive['size']} - Mounts: {drive['mountpoints']}")
        print()
        return
    
    # Detect drives if none specified
    if not args.target_drive:
        drives = detect_usb_drives()
        if not drives:
            print("No USB drives detected. Please specify the target drive path.")
            print("Usage: python usb_installer.py /dev/sdb")
            sys.exit(1)
        
        print("Detected USB drives:")
        for i, drive in enumerate(drives):
            print(f"  {i+1}. {drive['name']} - {drive['size']}")
        print()
        
        # Let user select
        while True:
            try:
                choice = input(f"Select drive (1-{len(drives)}) or 'q' to quit: ")
                if choice.lower() == 'q':
                    sys.exit(0)
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(drives):
                    args.target_drive = drives[choice_idx]["path"]
                    break
                else:
                    print(f"Please enter a number between 1 and {len(drives)}")
            except ValueError:
                print("Please enter a valid number or 'q' to quit")
    
    target_drive = args.target_drive
    print(f"Target drive: {target_drive}")
    print()
    
    # Verify-only mode
    if args.verify_only:
        # Try to find the vault structure - guess common mount points
        # or ask user for mount point
        mount_point = input("Enter the mount point of the USB drive (e.g., /media/user/USBNAME): ").strip()
        if os.path.isdir(os.path.join(mount_point, "Vault")):
            verify_usb_structure(mount_point)
        else:
            print("Vault directory not found at that mount point.")
            # List what's there
            print(f"Contents: {os.listdir(mount_point)[:10]}")
        return
    
    # Format the drive (unless --no-format)
    if not args.no_format:
        print("=" * 60)
        print("WARNING: Formatting will ERASE all data on the target drive!")
        print("=" * 60)
        confirm = input("Type 'YES' to confirm formatting: ")
        if confirm != "YES":
            print("Operation cancelled.")
            sys.exit(0)
        
        print()
        print("Step 1: Formatting drive...")
        if not format_usb(target_drive, args.filesystem):
            print("Format failed. Exiting.")
            sys.exit(1)
        print()
    
    # Detect the mount point (try to mount or ask user)
    print("Step 2: Setting up vault structure...")
    print()
    
    # Try to determine mount point
    # If the drive has a label, we can try to find it
    import re
    label_match = re.search(r'[/-](\S+)[ -]', subprocess.run(
        ["lsblk", "-o", "NAME,FSTYPE,LABEL", target_drive], 
        capture_output=True, text=True
    ).stdout)
    
    # Try mounting if not already mounted
    mount_point = None
    
    # Check if already mounted
    result = subprocess.run(["findmnt", "-nro", " mountpoint ", target_drive], 
                          capture_output=True, text=True)
    if result.stdout.strip():
        mount_point = result.stdout.strip()
    else:
        # Try to mount (simple approach - needs appropriate permissions)
        # For now, ask user
        print(f"Drive {target_drive} is not mounted.")
        print("Please mount the drive and then run the script again,")
        print("or provide the mount point manually.")
        print()
        
        # Try common mount points
        for candidate in ["/media", "/run/media", "/mnt"]:
            if os.path.isdir(candidate):
                candidates = os.listdir(candidate)
                for c in candidates:
                    test_path = os.path.join(candidate, c)
                    if os.path.ismount(test_path) or os.path.exists(os.path.join(test_path, "Vault")):
                        mount_point = test_path
                        break
        
        if not mount_point:
            mount_point = input("Enter the mount point of the USB drive: ").strip()
    
    if not os.path.isdir(os.path.join(mount_point, "Vault")):
        # Create vault structure
        create_vault_structure(mount_point)
        install_launcher_metadata(mount_point)
    else:
        print("Vault directory already exists. Verifying...")
        verify_usb_structure(mount_point)
        if not verify_usb_structure(mount_point):
            print("Creating missing structures...")
            create_vault_structure(mount_point)
            install_launcher_metadata(mount_point)
    
    # Final verification
    print()
    print("Final verification...")
    verify_usb_structure(mount_point)
    
    print()
    print("=" * 60)
    print("Portable Privacy Vault USB installation complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. The vault structure is ready on your USB drive")
    print("2. Install the native host apps on your target devices:")
    print("   - Windows: Install vault-runner.exe")
    print("   - Linux: Install vault-runner.deb or use vault-runner.AppImage")
    print("   - Android: Install vault-runner.apk")
    print("3. Plug the USB into any host device and launch the companion app")
    print("4. Your workspace will mount Vault/SharedData/ as your primary home")
    print("5. All files, apps, and settings are persisted to the USB drive")
    print()
    print("Important: The USB uses exFAT/NTFS - no encryption at the volume level.")
    print("Data privacy is achieved through the sandboxed host applications.")
    print("=" * 60)


if __name__ == "__main__":
    main()
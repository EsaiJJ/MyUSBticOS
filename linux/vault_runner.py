#!/usr/bin/env python3
"""
Portable Privacy Vault - Linux Host Application (.deb/.AppImage skeleton)
Detects the USB drive, mounts the Vault/SharedData folder, and launches
a lightweight containerized/virtualized workspace environment using
native Linux backend tools (QEMU/KVM, systemd-nspawn, or LXC).

This script can be packaged as a .deb or AppImage for distribution.
"""

import os
import sys
import json
import subprocess
import platform
from pathlib import Path
import shutil


def find_usb_drive():
    """Detect the Vault USB drive by looking for the Vault directory structure."""
    system = platform.system()
    
    # Linux - check common mount points
    mount_points = ["/media", "/run/media", "/mnt", "/tmp/mnt"]
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
                            "mount_point": mp,
                            "drive_name": entry,
                            "vault_path": vault_path,
                            "shareddata_path": shareddata_path,
                            "label": "VaultUSB"
                        }
        except PermissionError:
            continue
        except Exception as e:
            print(f"Error scanning {mp}: {e}")
            continue
    
    # Check block devices directly using lsblk
    try:
        result = subprocess.run(
            ["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINT", "-J"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            import json as _json
            data = _json.loads(result.stdout)
            for device in data.get("blockdevices", []):
                name = device.get("name", "")
                mounts = device.get("mountpoints", [])
                if not mounts:
                    continue
                for mount in mounts:
                    vault_path = os.path.join(mount, "Vault")
                    shareddata_path = os.path.join(vault_path, "SharedData")
                    if os.path.isdir(vault_path) and os.path.isdir(shareddata_path):
                        return {
                            "mount_point": mount,
                            "drive_name": name,
                            "vault_path": vault_path,
                            "shareddata_path": shareddata_path,
                            "label": "VaultUSB"
                        }
    except Exception as e:
        print(f"Error running lsblk: {e}")
    
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
        "host": "linux"
    }


def find_container_runtime():
    """Find available container/virtualization runtime on Linux."""
    # Check QEMU/KVM
    qemu_path = shutil.which("qemu-system-x86_64")
    if qemu_path:
        # Check if KVM is available
        if os.path.exists("/dev/kvm"):
            return {"type": "qemu-kvm", "path": qemu_path}
    
    # Check systemd-nspawn
    if shutil.which("systemd-nspawn"):
        return {"type": "systemd-nspawn"}
    
    # Check LXC
    if shutil.which("lxc-start"):
        return {"type": "lxc"}
    
    # Check Docker (if available, though we want lightweight)
    if shutil.which("docker"):
        return {"type": "docker"}
    
    return None


def launch_qemu_environment(shareddata_path, env_type, runtime):
    """Launch a QEMU/KVM virtualized environment."""
    mem_mb = 2048  # Default 2GB
    cpu_limit = "auto"
    
    # Determine the disk image to use
    # Prefer a pre-built image, fall back to using SharedData as root
    vault_dir = os.path.dirname(shareddata_path)
    image_path = os.path.join(vault_dir, "Images", f"{env_type}.qcow2")
    
    # Build QEMU command
    qemu_cmd = [
        runtime["path"],
        "-m", str(mem_mb),
        "-enable-kvm",
        "-drive", f"file={image_path or shareddata_path},format=raw",
        "-net", "none",
        "-nographic",
        "-no-reboot",
        "-overcommit", "mem-lock=on"
    ]
    
    # Add CPU allocation
    if cpu_limit != "auto":
        qemu_cmd.extend(["-smp", str(cpu_limit)])
    
    print(f"Launching QEMU/KVM environment with {shareddata_path}")
    
    try:
        # Use subprocess.Popen to start QEMU in the background
        # We redirect output but allow it to run
        proc = subprocess.Popen(
            qemu_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        
        # Print some info
        print(f"QEMU process started with PID: {proc.pid}")
        print("The virtualized environment is running in the background.")
        print("To access the workspace, you may need to set up a VNC connection")
        print("or use SPICE for graphical access.")
        
        return True
        
    except FileNotFoundError:
        print(f"Could not find QEMU at {runtime['path']}")
        return False
    except Exception as e:
        print(f"QEMU launch error: {e}")
        return False


def launch_systemd_nspawn(shareddata_path, env_type):
    """Launch a systemd-nspawn container."""
    container_name = "vault-container"
    home_dir = os.path.join(shareddata_path, "Home")
    
    # Ensure Home directory exists
    os.makedirs(home_dir, exist_ok=True)
    
    # Try to create/start the container
    cmd = [
        "systemd-nspawn",
        "-D", shareddata_path,
        "-b",  # Boot the container
        "--register=no",
        "--machine", container_name,
        "--pipe"
    ]
    
    # If the container directory doesn't exist, we need to create it first
    container_dir = f"/var/lib/machines/{container_name}"
    if not os.path.exists(container_dir):
        print(f"Creating systemd-nspawn container at {container_dir}")
        os.makedirs(container_dir, exist_ok=True)
        # Copy necessary base system - for now, just use the shareddata as root
        # In a full implementation, you'd copy a minimal root filesystem
    
    print(f"Starting systemd-nspawn container with root: {shareddata_path}")
    
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        print(f"systemd-nspawn PID: {proc.pid}")
        return True
    except FileNotFoundError:
        print("systemd-nspawn not found, trying alternative...")
        return False
    except Exception as e:
        print(f"systemd-nspawn error: {e}")
        return False


def launch_lxc_environment(shareddata_path, env_type):
    """Launch an LXC container."""
    print(f"LXC environment launch")
    # Basic LXC launch - in full implementation would need proper config
    container_name = "vault"
    
    # Create basic LXC config if needed
    lxc_config = os.path.join("/var/lib/lxc", container_name, "config")
    os.makedirs(os.path.dirname(lxc_config), exist_ok=True)
    
    # Write minimal config
    with open(lxc_config, "w") as f:
        f.write("lxc.network.type = veth\n")
        f.write("lxc.network.link = lxcbr0\n")
        f.write("lxc.rootfs = " + shareddata_path + "\n")
        f.write("lxc.tty = 0\n")
    
    try:
        proc = subprocess.Popen(
            ["lxc-start", "-n", container_name, "-o", "/dev/null"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        print(f"LXC container started: PID {proc.pid}")
        return True
    except FileNotFoundError:
        print("lxc-start not found")
        return False
    except Exception as e:
        print(f"LXC error: {e}")
        return False


def launch_directly(shareddata_path):
    """Launch a direct Python-based workspace (no virtualization/containers)."""
    print(f"Direct execution with shareddata: {shareddata_path}")
    
    # Set up the home directory from SharedData
    home_dir = os.path.join(shareddata_path, "Home")
    os.makedirs(home_dir, exist_ok=True)
    
    # Set environment variables
    env = os.environ.copy()
    env["HOME"] = home_dir
    env["XDG_DATA_HOME"] = os.path.join(home_dir, ".local", "share")
    env["XDG_CONFIG_HOME"] = os.path.join(home_dir, ".config")
    
    # Launch a Python-based workspace
    print("Starting vault Python workspace...")
    try:
        # Launch a simple interactive Python session that demonstrates the vault
        subprocess.Popen(
            [sys.executable, "-c", f"""
import os
import sys

# Set up vault home from SharedData
vault_home = os.path.expanduser("~")
print(f"Portable Privacy Vault - Linux Workspace")
print(f"Home directory: {vault_home}")
print(f"Shared data root: {os.path.dirname({repr(shareddata_path)}})")
print()
print("Your workspace is mounted from the USB drive's Vault/SharedData/ folder.")
print("Any files you create here will be persisted to the USB drive.")
print("To exit, press Ctrl+C or type 'exit()'")
print()

# Simple demo - list the home directory
try:
    files = os.listdir(vault_home)
    print(f"Files in home: {files}")
except Exception as e:
    print(f"Error listing files: {e}")

# Start a basic interactive loop
while True:
    cmd = input("> ").strip()
    if cmd.lower() in ['exit', 'quit', '']:
        break
    elif cmd == 'list':
        try:
            print(os.listdir(vault_home))
        except:
            pass
    else:
        print(f"Command not recognized: {cmd}")
"""],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print("Python workspace session started.")
        return True
    except Exception as e:
        print(f"Direct launch error: {e}")
        return False


def main():
    """Main entry point for the Linux host application."""
    print("=" * 60)
    print("Portable Privacy Vault - Linux Host Launcher")
    print("=" * 60)
    print()
    
    # Load configuration
    config = load_config()
    if not config:
        print("ERROR: Could not find Vault USB drive.")
        print("Please ensure the Vault USB is connected and contains the proper structure.")
        print("Expected structure: /Vault/SharedData/ on the drive root")
        sys.exit(1)
    
    print(f"Vault configuration loaded (UUID: {config.get('vault_uuid', '')[:8]}...)")
    print()
    
    # Find the USB drive
    usb_drive = find_usb_drive()
    if not usb_drive:
        print("ERROR: Could not find Vault USB drive.")
        sys.exit(1)
    
    print(f"USB Drive detected: {usb_drive['drive_name']}")
    print(f"Mount point: {usb_drive['mount_point']}")
    print(f"Vault Path: {usb_drive['vault_path']}")
    print(f"Shared Data: {usb_drive['shareddata_path']}")
    print()
    
    # Load shared data path
    shareddata_path = usb_drive["shareddata_path"]
    
    # Find available container/runtime
    runtime = find_container_runtime()
    if runtime:
        print(f"Available runtime: {runtime['type']}")
    else:
        print("No native virtualization/runtime found.")
        print("Falling back to direct shared data access.")
        runtime = {"type": "none"}
    
    print("Launching virtualized workspace...")
    print("-" * 60)
    
    # Determine environment type
    env_type = config.get("environment", {}).get("default_image", "linux-base")
    
    # Launch based on available runtime
    if runtime["type"] == "qemu-kvm":
        success = launch_qemu_environment(shareddata_path, env_type, runtime)
    elif runtime["type"] == "systemd-nspawn":
        success = launch_systemd_nspawn(shareddata_path, env_type)
    elif runtime["type"] == "lxc":
        success = launch_lxc_environment(shareddata_path, env_type)
    else:
        success = launch_directly(shareddata_path)
    
    if success:
        print()
        print("Vault workspace is now running on this Linux device.")
        print("All files created/modified will be persisted to:", shareddata_path)
        print("Your workspace follows you to the next device via the USB drive.")
    else:
        print()
        print("Failed to launch virtualized environment.")
        print("Falling back to direct shared data access...")
        launch_directly(shareddata_path)
    
    print()
    print("=" * 60)
    print("Portable Privacy Vault - Linux Host Launcher")
    print("=" * 60)


if __name__ == "__main__":
    main()
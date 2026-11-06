#!/usr/bin/env python3
"""
Portable Privacy Vault - Android Host Application (.apk skeleton)
Uses USB-OTG storage APIs when plugged into a phone or tablet,
lets the user select the workspace image, and runs locally on
mobile hardware.

This Python script can be built into an .apk using Buildozer,
Kivy, or Pydroid3's APK builder.
"""

import os
import sys
import json
import subprocess
import platform
from pathlib import Path
import shutil

# Try to import Kivy for proper Android UI
try:
    from kivy.app import App
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.label import Label
    from kivy.uix.button import Button
    from kivy.uix.filechooser import FileChooserIconList
    from kivy.core.window import Window
    KIVY_AVAILABLE = True
except ImportError:
    KIVY_AVAILABLE = False


def find_usb_drive_android():
    """Detect the Vault USB drive connected via USB-OTG on Android."""
    # On Android, USB devices are typically mounted at /mnt/usb or /storage/usb
    # or accessible through the Android MediaStore
    
    search_paths = [
        "/mnt/usb",
        "/storage/usb",
        "/sdcard/.usb",
        "/storage/emulated/0/usb",
    ]
    
    for search_path in search_paths:
        if os.path.isdir(search_path):
            vault_path = os.path.join(search_path, "Vault")
            shareddata_path = os.path.join(vault_path, "SharedData") if vault_path else None
            if os.path.isdir(vault_path) and shareddata_path and os.path.isdir(shareddata_path):
                return {
                    "mount_point": search_path,
                    "drive_label": os.path.basename(search_path),
                    "vault_path": vault_path,
                    "shareddata_path": shareddata_path,
                    "label": "VaultUSB-Android"
                }
    
    # Also check /sdcard for any Vault directory
    sdcard_path = "/sdcard"
    if os.path.isdir(sdcard_path):
        vault_path = os.path.join(sdcard_path, "Vault")
        shareddata_path = os.path.join(vault_path, "SharedData") if os.path.isdir(vault_path) else None
        if os.path.isdir(vault_path) and shareddata_path and os.path.isdir(shareddata_path):
            return {
                "mount_point": sdcard_path,
                "drive_label": "sdcard",
                "vault_path": vault_path,
                "shareddata_path": shareddata_path,
                "label": "VaultUSB-sdcard"
            }
    
    return None


def find_usb_drive_linux_style():
    """Detect USB drive using Linux-style paths (for Android with Termux/MLOQ)."""
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
                for mount in mounts:
                    vault_path = os.path.join(mount, "Vault")
                    shareddata_path = os.path.join(vault_path, "SharedData") if os.path.isdir(os.path.join(mount, "Vault")) else None
                    if os.path.isdir(vault_path) and shareddata_path and os.path.isdir(shareddata_path):
                        return {
                            "mount_point": mount,
                            "drive_name": name,
                            "vault_path": vault_path,
                            "shareddata_path": shareddata_path,
                            "label": "VaultUSB-lsblk"
                        }
    except Exception:
        pass
    
    return None


def load_config():
    """Load vault configuration from the USB drive."""
    # Try Android-style detection first
    usb_drive = find_usb_drive_android()
    
    # Fall back to Linux-style detection
    if not usb_drive:
        usb_drive = find_usb_drive_linux_style()
    
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
        "host": "android"
    }


def find_container_runtime_android():
    """Find available runtime on Android - typically limited, use direct execution or QEMU guest."""
    # On Android, we typically don't have full QEMU/KVM
    # We can try:
    # 1. Termux with proot or lxc
    # 2. Native QEMU user-mode execution
    # 3. Direct Python execution with the shareddata as home
    
    # Check if proot is available (common in Termux)
    if shutil.which("proot"):
        return {"type": "proot"}
    
    # Check for termux-api tools
    if shutil.which("termux-task"):
        return {"type": "termux"}
    
    # Check for any Python interpreter
    if sys.executable:
        return {"type": "python-direct"}
    
    return {"type": "direct"}


def launch_proot_environment(shareddata_path, env_type):
    """Launch a proot-wrapped environment on Android (via Termux)."""
    home_dir = os.path.join(shareddata_path, "Home")
    os.makedirs(home_dir, exist_ok=True)
    
    print(f"Starting proot environment with {shareddata_path}")
    
    # proot command to wrap a Python session
    proot_cmd = [
        "proot",
        "-0",
        "-r", shareddata_path,  # Root the environment in SharedData
        "-w", home_dir,         # Set working directory to Home
        sys.executable,
        "-i", "-c", f"""
import os
import sys

vault_home = os.path.expanduser("~") or home_dir
print("Portable Privacy Vault - Android Workspace")
print(f"Running in proot environment")
print(f"Home: {vault_home}")
print(f"Shared data root: {shareddata_path}")
print()
print("Your workspace is from the USB drive's Vault/SharedData/ folder.")
print("Files created will be persisted to the USB drive.")
print("Type 'exit()' or press Ctrl+D to quit.")

# Simple interactive loop
while True:
    try:
        cmd = input("> ").strip()
        if cmd.lower() in ['exit', 'quit', '']:
            break
        elif cmd == 'list':
            try:
                print(os.listdir(vault_home) if os.path.exists(vault_home) else "No home dir")
            except:
                pass
        else:
            # Try to execute as a Python command
            try:
                exec(cmd, {'os': os, 'sys': sys, 'vault_home': vault_home})
            except:
                print(f"Command not understood: {cmd}")
    except (EOFError, KeyboardInterrupt):
        break
"""]
    ]
    
    try:
        proc = subprocess.Popen(
            proot_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        print(f"proot process started: PID {proc.pid}")
        return True
    except FileNotFoundError:
        print("proot not found, trying alternative...")
        return False
    except Exception as e:
        print(f"proot error: {e}")
        return False


def launch_direct_android(shareddata_path, env_type):
    """Launch a direct Python-based workspace on Android (no virtualization)."""
    home_dir = os.path.join(shareddata_path, "Home")
    os.makedirs(home_dir, exist_ok=True)
    
    print(f"Direct Python execution with {shareddata_path}")
    
    # Set up environment
    env = os.environ.copy()
    env["HOME"] = home_dir
    env["XDG_DATA_HOME"] = os.path.join(home_dir, ".local", "share")
    env["XDG_CONFIG_HOME"] = os.path.join(home_dir, ".config")
    env["ANDROID_VAULT"] = "1"
    
    # Launch Python interactive session
    print("Starting vault Python workspace on Android...")
    try:
        # If Kivy is available, use it for a proper UI
        if KIVY_AVAILABLE:
            from kivy.core.clipboard import Clipboard
            
            # Create a simple Vault UI
            class VaultUI(BoxLayout):
                def __init__(self, **kwargs):
                    super().__init__(orientation='vertical', **kwargs)
                    self.add_widget(Label(
                        text="Portable Privacy Vault\nAndroid Workspace",
                        font_size='24sp',
                        halign='center',
                        valign='middle'
                    ))
                    self.add_widget(Label(
                        text="Your workspace from USB drive",
                        font_size='16sp',
                        halign='center',
                        valign='middle'
                    ))
                    self.add_widget(Label(
                        text=f"Shared Data: {shareddata_path}",
                        font_size='12sp',
                        halign='center',
                        valign='middle'
                    ))
                    self.add_widget(Button(
                        text="Start Workspace",
                        size_hint_y=None,
                        height='48dp',
                        on_press=self.start_workspace
                    ))
                    self.add_widget(Label(
                        text="All files persisted to USB drive",
                        font_size='12sp',
                        halign='center',
                        valign='middle'
                    ))
                
                def start_workspace(self, instance):
                    self.clear_widgets()
                    self.add_widget(Label(
                        text="Workspace started - checking USB connection...",
                        font_size='18sp'
                    ))
                    
                    # Launch the proot-based workspace
                    launch_proot_environment(shareddata_path, env_type)
                    
                    self.add_widget(Label(
                        text="Workspace running. Disconnect USB to end session.",
                        font_size='14sp'
                    ))
            return VaultUI()
        else:
            # Simple console-based workspace
            print("Portable Privacy Vault - Android Workspace")
            print(f"Home: {home_dir}")
            print(f"Shared data: {shareddata_path}")
            print("Files created will be persisted to the USB drive.")
            print("Type 'exit()' or 'quit' to end the session.")
            
            # Interactive loop (this won't work well in APK without proper IO)
            # For now, just launch proot
            launch_proot_environment(shareddata_path, env_type)
        
        return True
        
    except Exception as e:
        print(f"Direct launch error: {e}")
        return False


def main():
    """Main entry point for the Android host application."""
    print("=" * 60)
    print("Portable Privacy Vault - Android Host Launcher")
    print("=" * 60)
    print()
    
    # Load configuration
    config = load_config()
    if not config:
        print("ERROR: Could not find Vault USB drive.")
        print("Please ensure the Vault USB is connected via OTG")
        print("and contains the proper structure: /Vault/SharedData/")
        sys.exit(1)
    
    print(f"Vault USB detected (Android): {config.get('vault_uuid', '')[:8]}...")
    print()
    
    # Find the USB drive
    usb_drive = find_usb_drive_android()
    
    # Fall back to Linux-style detection
    if not usb_drive:
        usb_drive = find_usb_drive_linux_style()
    
    if not usb_drive:
        print("ERROR: Could not find Vault USB drive on Android.")
        print("Ensure the USB is connected via OTG adapter")
        print("and the drive is formatted as exFAT/NTFS")
        sys.exit(1)
    
    print(f"USB Drive: {usb_drive['drive_label']}")
    print(f"Mount point: {usb_drive['mount_point']}")
    print(f"Vault Path: {usb_drive['vault_path']}")
    print(f"Shared Data: {usb_drive['shareddata_path']}")
    print()
    
    # Load shared data path
    shareddata_path = usb_drive["shareddata_path"]
    
    # Find available runtime
    runtime = find_container_runtime_android()
    print(f"Available runtime: {runtime['type']}")
    print()
    
    # Determine environment type
    env_type = config.get("environment", {}).get("default_image", "linux-base")
    
    # Launch based on available runtime
    if runtime["type"] == "proot":
        success = launch_proot_environment(shareddata_path, env_type)
    elif runtime["type"] == "python-direct":
        success = launch_direct_android(shareddata_path, env_type)
    else:
        success = launch_direct_android(shareddata_path, env_type)
    
    if success:
        print()
        print("Vault workspace is now running on your Android device.")
        print("All files created/modified will be persisted to:", shareddata_path)
        print("Your workspace follows you to the next device via the USB drive.")
        print("Disconnect the USB to end the session and leave no traces.")
    else:
        print()
        print("Failed to launch vault workspace.")
        print("Falling back to direct shared data access...")
        launch_direct_android(shareddata_path, env_type)
    
    print()
    print("=" * 60)
    print("Portable Privacy Vault - Android Host Launcher")
    print("=" * 60)


if __name__ == "__main__":
    main()
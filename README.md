# Portable Privacy Vault

A cross-platform portable workspace on a dual-connector flash drive (USB-A + USB-C).

## Overview

Plug the USB into any public or borrowed device, launch the companion app, and instantly spin up a fully persistent, sandboxed environment that leaves zero trace on the host machine.

## USB Drive Structure

The drive uses **exFAT** or **NTFS** (no volume-level encryption) so Windows, Linux, and Android can all natively read and write.

```
/Vault/SharedData/     ← Unified shared data partition - mounted as primary home by all host apps
/Vault/Images/         ← Container/VM environment images
/Vault/Templates/      ← Pre-configured environment templates
/Vault/Config/config.json ← Vault configuration
/Vault/Launchers/      ← Launcher metadata per platform
/README.md             ← This file
```

## How It Works

1. **Plug in**: Connect the USB-A or USB-C end to any host device
2. **Launch**: Open the native host app (.exe for Windows, .deb/.AppImage for Linux, .apk for Android)
3. **Mount**: The app detects and mounts `Vault/SharedData/` as the primary storage/home directory
4. **Work**: Any files downloaded, apps installed, or settings tweaked are written directly back to `Vault/SharedData/` in real-time
5. **Move on**: Pull out the USB and plug into any other device - your exact same workspace is available

## Key Features

- **Zero Host Footprint**: Browsing history, cached files, and personal documents never touch the host machine's internal hard drive
- **Universal Handshake**: Work on any device - library Windows desktop, friend's phone, library Linux workstation - your workspace follows you
- **Stateful Persistence**: Your workspace follows you instantly to the next device - all writes go straight to the USB's shared data folder
- **No Installation Required on USB**: The host apps are installed once on your personal devices; the USB just contains the shared data folder

## Requirements

- USB flash drive with USB-A and USB-C connectors
- exFAT or NTFS support on the host device (native on Windows, read-write on Linux with `ntfs-3g`/`exfatutils`, read-write on Android with OTG support)
- Native host app installed on each device you plan to use

## Supported Platforms

- **Windows** (.exe) - detects USB via Windows volume management, mounts container, launches workspace in virtualized window
- **Linux** (.deb / .AppImage) - mounts via filesystem hooks, spawns container/virtualized environment using QEMU/KVM or systemd-nspawn
- **Android** (.apk) - uses USB-OTG storage APIs, lets you select the image and run locally on mobile hardware

## Publishing

This project is designed to be published on GitHub. The repository includes:
- `usb_installer.py` - Script to create the USB drive with proper vault structure
- Host application skeletons for Windows, Linux, and Android
- Configuration and template files
- Documentation

## License

MIT (or specify your preferred license)
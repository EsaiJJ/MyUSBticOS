# Portable Privacy Vault

A cross-platform portable workspace that lives on a dual-connector
(USB-A + USB-C) flash drive. Plug the drive into almost any Windows, Linux
or Android device, start the small companion app, and work inside a
persistent workspace whose files are stored on the USB stick — not on the
host machine.

This repository contains **working** components, not mock-ups:

| Component | Path | Build output |
|-----------|------|--------------|
| USB installer / preparer | `installer/usb_installer.py` | run directly (Python 3.8+) |
| Shared core library | `core/vaultlib.py` | imported by launchers |
| Linux launcher (bubblewrap sandbox) | `linux/vault_runner.py` | `dist/vault-runner_*.deb` |
| Windows launcher (isolated profile) | `windows/vault_runner.py` | `dist/vault-runner.exe` |
| Android app (Storage Access Framework) | `android/` | `dist/vault-runner.apk` |
| Cross-platform CI | `.github/workflows/build.yml` | downloadable artifacts |

The USB filesystem is **exFAT or NTFS without volume encryption** so every
OS can read and write it natively. Privacy/isolation comes from the host
apps, which keep all user data on the drive and leave the host untouched.

---

## How it works

```
USB drive (exFAT / NTFS)
└── Vault/
    ├── config.json          # vault id + configuration
    ├── SharedData/          # THE workspace (mounted as HOME everywhere)
    │   ├── Home/
    │   ├── Documents/
    │   ├── Downloads/
    │   ├── Apps/
    │   └── Settings/
    ├── Images/              # optional rootfs / disk images
    ├── Launchers/           # per-OS metadata
    └── README.md
```

Every launcher mounts/redirects the user's home to `Vault/SharedData`, so the
same files, downloads and settings appear on the next device.

### Linux (real filesystem isolation)
`vault-runner` uses [`bubblewrap`](https://github.com/containers/bubblewrap):

* the host filesystem is mounted **read-only** inside the sandbox,
* `/tmp` is a **tmpfs** (nothing written to the host disk),
* `Vault/SharedData` is bind-mounted to `/home/vault` as the **only writable,
  persistent** location,
* the host's real `$HOME`, caches and history are never touched.

```console
$ python3 linux/vault_runner.py --vault /media/$USER/VaultUSB
$ python3 linux/vault_runner.py -- /bin/sh -c 'echo hi > ~/Documents/hi.txt'
```

### Windows (isolated portable profile)
`vault-runner.exe` finds the drive and starts a shell whose `HOME`,
`USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP` all point inside
`Vault/SharedData`. Programs started from that shell keep their data on the
USB. If WSL is installed, `--wsl` starts a Linux workspace instead. No admin
rights or drivers required.

```powershell
vault-runner.exe            # auto-detect the vault drive
vault-runner.exe --wsl      # optional WSL Linux workspace
vault-runner.exe --dry-run  # show the isolated profile paths
```

### Android (Storage Access Framework)
`vault-runner.apk` asks you to pick the USB drive with Android's document
picker, persists access, then browses/reads `Vault/SharedData` and
`Vault/config.json` directly from the drive. It can also hand off to Termux
for a full Linux workspace.

---

## Build

### Prerequisites

* Python 3.8+
* Linux `.deb`: `dpkg-deb` (and `bubblewrap` at runtime for isolation)
* Windows `.exe`: Python + `pyinstaller`
* Android `.apk`: Android SDK `build-tools` (aapt2/d8/zipalign/apksigner) + JDK 17

### Linux .deb

```console
$ bash linux/build_deb.sh
$ sudo dpkg -i dist/vault-runner_1.0.0_all.deb
$ vault-runner
```

### Windows .exe

```bat
python -m pip install pyinstaller
python -m PyInstaller --clean --noconfirm windows\vault-runner.spec
:: -> dist\vault-runner.exe
```
(or run `windows\build_exe.bat`)

### Android .apk

```console
$ export ANDROID_HOME=$HOME/Android/Sdk
$ bash android/build_apk.sh
$ adb install -r dist/vault-runner.apk
```

All three are also built automatically by GitHub Actions; download them from
the workflow run, or create a tag (`v1.0.0`) to publish a release with all
artifacts attached.

---

## Prepare the USB drive

### Option A — on an already-mounted drive (any OS)

```console
$ python3 installer/usb_installer.py init /path/to/usb        # Linux/macOS
> python installer\usb_installer.py init E:\                 # Windows (drive root)
```

### Option B — format a whole disk (Linux, root)

```console
$ sudo python3 installer/usb_installer.py list
$ sudo python3 installer/usb_installer.py prepare /dev/sdb --fs exfat
```

> WARNING: `prepare` erases the target disk. Double-check the device path.

Then copy the companion app for each device onto the drive root (or just keep
it installed on your devices) and launch it.

---

## Design notes / limitations

* **No volume encryption**, by design of this project: the drive is readable
  where mounted. Keep sensitive data elsewhere if you need encryption at rest.
* The Linux sandbox shares the host's kernel and read-only system files (this
  is what makes it fast and dependency-free); it isolates *writes* and the
  user profile, not the OS itself.
* The Windows launcher isolates the user profile via environment variables;
  it does not virtualise the whole OS. Use `--wsl` for a Linux userspace.
* The Android app uses SAF; direct block-device access is not available to
  normal Android apps without root.

## License

MIT — see [LICENSE](LICENSE).

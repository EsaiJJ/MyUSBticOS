# Project MyUSBticOS

Project MyUSBticOS is a cross-platform portable workspace on a dual-connector
(USB-A + USB-C) flash drive. Plug the drive into a Windows, Linux or Android
device, start the small companion app, and work inside an isolated Debian
virtual machine whose home directory lives on the USB stick — not on the host
machine.

This repository contains **working** components, not mock-ups. The VM design
has been boot-tested end to end with KVM: the guest mounts the USB folder over
virtio-9p, writes persist back to the drive, and the host filesystem is not
shared with the guest.

---

## What is on the drive

```
USB_ROOT/
├── Vault/
│   ├── system.img       # preconfigured Debian 12 qcow2 (~430 MB)
│   ├── SharedData/      # mounted as /home/vault inside the VM
│   │   ├── Documents/
│   │   ├── Downloads/
│   │   └── Apps/
│   └── config.json      # vault id, image checksum, VM settings
└── Launchers/
    ├── vault-runner.exe # Windows launcher
    ├── vault-runner.deb # Linux launcher
    └── vault-runner.apk # Android companion
```

The filesystem is **exFAT or NTFS without volume encryption**, so every OS can
read and write it natively. Isolation comes from the virtual machine, not from
disk encryption.

---

## How it works

1. The launcher locates the USB vault and verifies `Vault/system.img` against
   the SHA-512 recorded in `Vault/config.json`.
2. It starts `qemu-system-x86_64` with:
   * `Vault/system.img` as a virtio disk in `-snapshot` mode (the base image is
     never modified, so its checksum always stays valid),
   * `Vault/SharedData` exported with `-virtfs ... mount_tag=vault`,
   * user-mode networking and a virtio RNG.
3. The guest image is preconfigured to:
   * load the 9p modules and mount tag `vault` at `/home/vault`,
   * auto-login as `vault` on the graphical console (tty1) and serial console,
   * record the boot time in `SharedData/LAST_BOOT.txt`.
4. The guest cannot see the host filesystem. Its only persistent writable
   location is the USB `SharedData` folder. The Debian system itself runs from
   a disposable snapshot: OS changes are discarded when the VM exits, which
   keeps the image checksum stable and makes every boot reproducible.

Default credentials inside the VM: user `vault`, password `vault`, with
passwordless `sudo`. Change the password inside the VM if you need to.

The preconfigured image is a **Debian 12 (bookworm) generic amd64** cloud
image from the official Debian mirror. The exact base URL, version and SHA-512
are pinned in `core/vaultlib.py` and recorded in every vault's `config.json`.
`scripts/build_system_image.py` downloads that official image, boots it once
with a cloud-init NoCloud seed to bake in the 9p mount and auto-login, then
compresses it to `dist/system.img`. No kernel or source compilation is
involved.

---

## Components

| Component | Path | Output |
|-----------|------|--------|
| Shared core library | `core/vaultlib.py` | imported by launchers/installer |
| USB installer | `installer/usb_installer.py` | run directly (Python 3.8+) |
| System image builder | `scripts/build_system_image.py` | `dist/system.img` |
| Linux launcher (QEMU/KVM) | `linux/vault_runner.py` | `dist/vault-runner_*_all.deb` |
| Windows launcher (QEMU/WHPX) | `windows/vault_runner.py` | `dist/vault-runner.exe` |
| Android companion (Termux handoff) | `android/` | `dist/vault-runner.apk` |
| CI | `.github/workflows/build.yml` | release assets |

---

## Quick start

### 1. Prepare the USB drive

On a machine with Python 3.8+ (works on Windows, macOS and Linux):

```console
# create Vault/, SharedData/{Documents,Downloads,Apps}, Launchers/ and config.json
python3 usb_installer.py init E:\

# download and verify the preconfigured Debian image
python3 usb_installer.py fetch E:\

# copy the launchers from this release into E:\Launchers
python3 usb_installer.py install-launchers E:\ --dir .
```

`usb_installer.py` and `vaultlib.py` are published together in the release, so
they can live in the same folder. Use `--from <file>` with `fetch` for offline
installation, or `init --image <file>`.

Linux users can format a whole disk and do everything in one step:

```console
$ sudo python3 usb_installer.py list
$ sudo python3 usb_installer.py prepare /dev/sdb --fs exfat
```

> WARNING: `prepare` erases the target disk. Double-check the device path.
> It writes the filesystem directly to the whole device (no partition table),
> which removable media generally supports; if your OS insists on a partition
> table, create a single partition with a disk tool and use `init` on the
> mounted partition instead.

### 2. Install a launcher

* **Linux:** `sudo dpkg -i vault-runner_1.2.0_all.deb` then run `vault-runner`.
  Requires `qemu-system-x86` and `qemu-utils` (declared as dependencies).
* **Windows:** run `vault-runner.exe` and install QEMU for Windows from
  <https://www.qemu.org/download/#windows> if it is not already present. The
  launcher searches `PATH`, `C:\Program Files\qemu` and `Launchers\qemu`.
* **Android:** install the APK, then install Termux from F-Droid and run
  `pkg install qemu-system-x86_64`. See the Android section below.

### 3. Launch

The launcher opens a QEMU window showing the Debian console. You are logged in
as `vault` with the USB `Documents`, `Downloads` and `Apps` folders as your
home. Changes made there are immediately visible from the host OS. `$HOME/Apps`
and `$HOME/Apps/bin` are on `PATH`, so portable Linux apps and AppImages kept
in those folders can be started from the guest.

Useful launcher options:

```console
$ vault-runner --vault /media/$USER/VaultUSB   # explicit drive
$ vault-runner --memory 4096 --cpus 4
$ vault-runner --offline                       # no guest network
$ vault-runner --display nographic             # terminal console instead of a window
$ vault-runner --dry-run                       # print the QEMU command
```

Windows uses the same options: `vault-runner.exe --vault E:\ --dry-run`.

---

## Android (Termux + QEMU)

Android does not let normal apps boot a VM directly, so the APK is a companion
that:

1. uses the Storage Access Framework to locate the USB vault,
2. derives candidate filesystem paths for the selected volume,
3. hands off to Termux with a `RUN_COMMAND` intent that launches QEMU with
   `-nographic` and the same virtio-9p share.

Termux setup:

```console
$ pkg update
$ pkg install qemu-system-x86_64
$ echo 'allow-external-apps = true' >> ~/.termux/termux.properties
$ termux-reload-settings
```

Then grant the MyUSBticOS app the `com.termux.permission.RUN_COMMAND`
permission in Android settings and press **Launch VM in Termux**. The Debian
serial console opens inside Termux.

Android limitations:

* Some devices block USB-OTG paths from apps entirely. If Termux cannot see
  `/storage/XXXX-XXXX`, copy the `Vault` folder to `/sdcard/Vault` and select
  it there (the launcher retries `/sdcard` paths).
* Termux QEMU runs with TCG (software emulation), so the VM is slower than on
  a desktop with KVM.
* The Termux QEMU build must include virtio-9p support (`-virtfs`). If it does
  not, the VM starts but cannot mount `SharedData`; the launcher prints a hint.

---

## Build from source

### Prerequisites

* Python 3.8+
* Linux `.deb`: `dpkg-deb`; runtime `qemu-system-x86`, `qemu-utils`
* Windows `.exe`: Python + `pyinstaller`
* Android `.apk`: Android SDK build-tools (aapt2/d8/zipalign/apksigner) + JDK 17
* Image builder: `qemu-system-x86_64`, `qemu-img`, `genisoimage` (or
  `xorriso`/`mkisofs`)

### All local artifacts

```console
$ BUILD_SYSTEM_IMAGE=1 bash scripts/build_all.sh
```

Without `BUILD_SYSTEM_IMAGE=1` the image step is skipped and the script builds
the sanity-checked layout + Linux `.deb` + Android `.apk` (when the SDK is
present).

### Only the image

```console
$ python3 scripts/build_system_image.py
# -> dist/system.img + dist/system.img.sha512
```

The builder reuses a verified cached base image in `build-system/` and falls
back to TCG when `/dev/kvm` is unavailable (for example on CI). The result is a
single qcow2 file with cloud-init disabled and a fresh machine-id on first boot.

### Only a launcher

```console
$ bash linux/build_deb.sh
$ python -m PyInstaller --clean --noconfirm windows/vault-runner.spec
$ bash android/build_apk.sh
```

On a tag `v1.2.0` the GitHub Actions workflow builds the system image, the
three launchers and publishes everything (including `system.img` and its
checksum) as a release.

---

## Security notes and limitations

* **No volume encryption**, by design: anyone with the drive can read it where
  it is mounted. Use full-disk/container encryption separately if you need
  encryption at rest.
* The VM is isolated from the host filesystem: only `Vault/SharedData` is
  shared. The guest has user-mode networking by default; use `--offline` to
  remove it.
* The default guest password is well known (`vault`/`vault`). Change it inside
  the VM if the VM will hold sensitive data.
* The guest is a minimal Debian console system. Because it runs from a
  temporary snapshot, packages installed with `apt` do not persist across
  boots. Keep applications and data in `SharedData` (use `SharedData/Apps/bin`
  for portable binaries) or change the image build in
  `scripts/build_system_image.py` and rebuild it.
* Windows acceleration uses WHPX when available, otherwise TCG. Linux uses KVM
  when `/dev/kvm` is accessible.
* The Android path is best-effort because of Android scoped-storage rules.

## License

MIT — see [LICENSE](LICENSE). The preconfigured system image is derived from
the official Debian 12 generic cloud image and remains subject to the licenses
of the software it contains (predominantly GPL/LGPL and other free-software
licenses).

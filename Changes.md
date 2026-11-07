# Changes

All notable changes to Project MyUSBticOS (formerly Portable Privacy Vault).
Versions follow [Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-11-06

### Changed

- Rebranded the project to **Project MyUSBticOS** across the README, CLI output,
  installer banner, Linux desktop entry, Debian package metadata, Android app
  label, Windows version resources and CI workflow.
- Moved the repository to `EsaiJJ/MyUSBticOS`; release download URLs now point
  at the new repository.
- Bumped all version references to 1.2.0 (Android `versionCode` 3).
- Updated the LICENSE copyright holder and the GitHub repository description.

### Added

- Windows launcher sets the console title to `Project MyUSBticOS`.
- Windows executable now embeds `windows/version_info.txt` (product name,
  description, version 1.2.0, copyright) via the PyInstaller spec.

### Compatibility

- Internal identifiers were intentionally kept unchanged: Android package
  `com.portablevault.vault`, Debian package/command `vault-runner`, and the
  vault image/9p layout.

### Verified

- All release assets passed SHA-512 verification; the `.deb` metadata, desktop
  entry, APK label/version and Windows version resource were checked.
- The released launcher booted the image successfully, wrote `LAST_BOOT.txt` to
  `SharedData`, and left `system.img` unchanged (`-snapshot`).

## [1.1.0] - 2026-11-06

### Added

- Preconfigured Debian 12 system image builder (`scripts/build_system_image.py`)
  using a pinned base image, guest user `vault`, passwordless sudo, 9p modules,
  serial autologin and a boot-info service.
- `Vault/SharedData` is shared into the guest as `/home/vault` over virtio-9p,
  so workspace data persists on the USB drive rather than the host.
- Cross-platform launchers: Linux `.deb`, Windows `.exe`, and Android/Termux
  `.apk`, with a CI release workflow publishing `system.img`,
  `system.img.sha512` and all launchers.

### Changed

- Replaced the earlier Linux `bwrap` sandbox and Windows profile-isolation
  approach with a QEMU virtual machine booting the preconfigured image.
- QEMU runs with `-snapshot`, keeping `system.img` immutable and checksum-stable.
- USB installer downloads and verifies the image by SHA-512 and supports flat
  release files alongside the vault layout.

## [1.0.0] - 2026-11-06

### Added

- First working release: Linux `bwrap` sandbox, Windows profile isolation,
  Android Storage Access Framework companion app, real `.deb`/`.apk` builds and
  GitHub Actions CI.

### Fixed

- CI uses the preinstalled Android SDK instead of the `setup-android` action.

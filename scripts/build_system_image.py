#!/usr/bin/env python3
"""
Build Vault/system.img from the pinned official Debian 12 generic image.

The official qcow2 is booted once with a cloud-init NoCloud seed that:
  * creates user ``vault`` (password ``vault``, passwordless sudo),
  * loads the 9p modules and mounts virtio-9p tag ``vault`` at /home/vault,
  * auto-logs in on tty1 and ttyS0,
  * records the boot time in /home/vault/LAST_BOOT.txt,
  * disables cloud-init, clears machine-id and removes SSH host keys,
  * powers off.

The result is compressed back to qcow2 and published as system.img, so the
launchers only need QEMU and no seed ISO.

Requires: qemu-system-x86_64, qemu-img, genisoimage (or xorriso/mkisofs).
Run from anywhere:  python3 scripts/build_system_image.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import vaultlib  # noqa: E402

CHUNK = 1024 * 1024

USER_DATA = """\
#cloud-config
datasource_list: [ NoCloud ]
hostname: vault
manage_etc_hosts: true
package_update: false
package_upgrade: false
users:
  - name: vault
    uid: 1000
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: vault
    sudo: ALL=(ALL) NOPASSWD:ALL
chpasswd:
  expire: false
  list: |
    vault:vault
ssh_pwauth: true
disable_root: true
write_files:
  - path: /etc/modules-load.d/vault-9p.conf
    permissions: '0644'
    content: |
      9p
      9pnet_virtio
  - path: /etc/systemd/system/home-vault.mount
    permissions: '0644'
    content: |
      [Unit]
      Description=Vault shared home (9p)
      After=systemd-modules-load.service
      Before=systemd-user-sessions.service getty@tty1.service serial-getty@ttyS0.service
      [Mount]
      What=vault
      Where=/home/vault
      Type=9p
      Options=trans=virtio,version=9p2000.L,access=any
      [Install]
      WantedBy=multi-user.target
  - path: /etc/systemd/system/getty@tty1.service.d/autologin.conf
    permissions: '0644'
    content: |
      [Service]
      ExecStart=
      ExecStart=-/sbin/agetty --autologin vault --noclear %I $TERM
  - path: /etc/systemd/system/serial-getty@ttyS0.service.d/autologin.conf
    permissions: '0644'
    content: |
      [Service]
      ExecStart=
      ExecStart=-/sbin/agetty --autologin vault --keep-baud 115200,38400,9600 %I $TERM
  - path: /etc/profile.d/vault-apps.sh
    permissions: '0644'
    content: |
      export PATH="$HOME/Apps/bin:$HOME/Apps:$PATH"
  - path: /etc/systemd/system/vault-bootinfo.service
    permissions: '0644'
    content: |
      [Unit]
      Description=Record vault boot time in shared home
      After=home-vault.mount
      Wants=home-vault.mount
      [Service]
      Type=oneshot
      ExecStart=/bin/sh -c 'mkdir -p /home/vault/Documents /home/vault/Downloads /home/vault/Apps; date -u > /home/vault/LAST_BOOT.txt'
      [Install]
      WantedBy=multi-user.target
runcmd:
  - systemctl daemon-reload
  - systemctl enable home-vault.mount vault-bootinfo.service
  - systemctl start home-vault.mount || true
  - mkdir -p /home/vault/Documents /home/vault/Downloads /home/vault/Apps || true
  - systemctl disable --now ssh || true
  - usermod -L -s /usr/sbin/nologin debian || true
  - usermod -L root || true
  - touch /etc/cloud/cloud-init.disabled
  - truncate -s 0 /etc/machine-id
  - rm -f /etc/ssh/ssh_host_*
  - echo "VAULT-BAKE-DONE" > /dev/console
  - poweroff -f
"""

META_DATA = """\
instance-id: vault-bake-001
local-hostname: vault
"""


def log(message: str) -> None:
    print(f">> {message}", flush=True)


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "vault-image-builder"})
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with destination.open("wb") as out:
            while True:
                block = response.read(CHUNK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if total and (done % (32 * CHUNK) < CHUNK or done == total):
                    sys.stderr.write(
                        f"\r   {vaultlib.human_size(done)} / {vaultlib.human_size(total)} "
                        f"({100.0 * done / total:5.1f}%)"
                    )
                    sys.stderr.flush()
    sys.stderr.write("\n")


def find_tool(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def make_seed(work: Path) -> Path:
    (work / "user-data").write_text(USER_DATA, encoding="utf-8")
    (work / "meta-data").write_text(META_DATA, encoding="utf-8")
    seed = work / "seed.iso"

    genisoimage = find_tool("genisoimage")
    if genisoimage:
        cmd = [genisoimage, "-output", str(seed), "-volid", "cidata", "-joliet", "-rock",
               "user-data", "meta-data"]
    else:
        xorriso = find_tool("xorriso", "mkisofs")
        if not xorriso:
            raise SystemExit(
                "ERROR: need genisoimage, xorriso or mkisofs to create the cloud-init seed.\n"
                "  Debian/Ubuntu: sudo apt install genisoimage"
            )
        cmd = [xorriso, "-as", "mkisofs", "-output", str(seed), "-volid", "cidata",
               "-joliet", "-rock", "user-data", "meta-data"]

    subprocess.run(cmd, cwd=str(work), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return seed


def accel_for(qemu: str) -> str:
    accel = vaultlib.choose_accel(qemu)
    if accel == "kvm":
        try:
            if not (os.access("/dev/kvm", os.R_OK | os.W_OK)):
                return "tcg"
        except OSError:
            return "tcg"
    return accel


def bake(qemu: str, image: Path, shared: Path, seed: Path, serial: Path,
         *, memory: int, cpus: int, timeout: int, firmware: str = "") -> None:
    accel = accel_for(qemu)
    log(f"booting base image (accel={accel})")
    cmd = [
        qemu, "-name", "vault-bake",
        "-machine", f"q35,accel={accel}",
        "-cpu", "host" if accel == "kvm" else "max",
        "-m", str(memory), "-smp", str(cpus),
        "-drive", f"file={image},if=none,id=disk,format=qcow2",
        "-device", "virtio-blk-pci,drive=disk,bootindex=1",
        "-drive", f"file={seed},if=none,id=seed,format=raw,readonly=on",
        "-device", "virtio-blk-pci,drive=seed,bootindex=2",
        "-virtfs",
        f"local,path={str(shared).replace(chr(92), '/')},mount_tag=vault,"
        "security_model=none,multidevs=remap",
        "-netdev", "user,id=net0",
        "-device", "virtio-net-pci,netdev=net0",
        "-device", "virtio-rng-pci",
        "-display", "none",
        "-serial", f"file:{serial}",
        "-no-reboot",
        "-boot", "order=c",
    ]
    if firmware:
        cmd[1:1] = ["-L", firmware]
    started = time.time()
    try:
        proc = subprocess.run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        tail = ""
        if serial.is_file():
            tail = "\n".join(serial.read_text(errors="replace").splitlines()[-20:])
        raise SystemExit(f"ERROR: bake timed out after {timeout}s.\n{tail}") from exc
    elapsed = time.time() - started

    text = serial.read_text(errors="replace") if serial.is_file() else ""
    if proc.returncode != 0 or "VAULT-BAKE-DONE" not in text:
        tail = "\n".join(text.splitlines()[-25:])
        raise SystemExit(
            f"ERROR: bake failed (exit {proc.returncode}, {elapsed:.1f}s).\n{tail}"
        )
    log(f"bake completed in {elapsed:.1f}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the preconfigured Vault system.img")
    parser.add_argument("--output", default=str(ROOT / "dist" / "system.img"))
    parser.add_argument("--work-dir", default=str(ROOT / "build-system"))
    parser.add_argument("--base-image", default="", help="use a local official qcow2")
    parser.add_argument("--base-url", default=vaultlib.BASE_IMAGE_URL)
    parser.add_argument("--base-sha512", default=vaultlib.BASE_IMAGE_SHA512)
    parser.add_argument("--qemu", default="")
    parser.add_argument("--firmware", default="", help="QEMU firmware directory (passes -L)")
    parser.add_argument("--memory", type=int, default=2048)
    parser.add_argument("--cpus", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--force", action="store_true", help="rebuild even if output exists")
    parser.add_argument("--keep", action="store_true", help="keep the build work directory")
    args = parser.parse_args(argv)

    output = Path(args.output)
    work = Path(args.work_dir)
    if output.is_file() and not args.force:
        log(f"{output} already exists (use --force to rebuild)")
        return 0

    qemu = vaultlib.find_qemu(args.qemu)
    if not qemu:
        raise SystemExit("ERROR: qemu-system-x86_64 not found (install qemu-system-x86).")
    qemu_img = str(Path(qemu).with_name("qemu-img" + Path(qemu).suffix))
    if not Path(qemu_img).is_file():
        qemu_img = shutil.which("qemu-img") or ""
    if not qemu_img:
        raise SystemExit("ERROR: qemu-img not found (install qemu-utils).")

    work.mkdir(parents=True, exist_ok=True)
    base = work / "base.qcow2"

    if args.base_image:
        source = Path(args.base_image)
        if not source.is_file():
            raise SystemExit(f"ERROR: base image not found: {source}")
        log(f"using local base image {source}")
        shutil.copyfile(source, base)
    else:
        expected = args.base_sha512.lower()
        if base.is_file() and expected and vaultlib.sha512_file(base) == expected:
            log("reusing verified cached base image")
        else:
            log("downloading official Debian image")
            log(args.base_url)
            partial = base.with_name("base.qcow2.part")
            download(args.base_url, partial)
            actual = vaultlib.sha512_file(partial)
            if expected and actual != expected:
                partial.unlink(missing_ok=True)
                raise SystemExit(
                    f"ERROR: base image checksum mismatch\n  expected {expected}\n  actual   {actual}"
                )
            partial.replace(base)

    system_image = work / "system.img"
    shutil.copyfile(base, system_image)

    shared = work / "Vault" / "SharedData"
    for name in vaultlib.SHARED_SUBDIRS:
        (shared / name).mkdir(parents=True, exist_ok=True)

    seed = make_seed(work)
    serial = work / "bake-serial.log"
    if serial.exists():
        serial.unlink()
    bake(qemu, system_image, shared, seed, serial,
         memory=args.memory, cpus=args.cpus, timeout=args.timeout,
         firmware=args.firmware)

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(output.name + ".tmp")
    log("compressing configured image")
    subprocess.run(
        [qemu_img, "convert", "-c", "-O", "qcow2", str(system_image), str(staging)],
        check=True,
    )
    staging.replace(output)

    digest = vaultlib.sha512_file(output)
    checksum = output.with_name(output.name + ".sha512")
    checksum.write_text(f"{digest}  {output.name}\n", encoding="utf-8")

    log(f"wrote {output} ({vaultlib.human_size(vaultlib.file_size(output))})")
    log(f"sha512 {digest}")

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

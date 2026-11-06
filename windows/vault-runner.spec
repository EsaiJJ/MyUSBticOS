# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Project MyUSBticOS Windows launcher.
# Build with:  pyinstaller --clean windows/vault-runner.spec
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
CORE = ROOT / "core"
WIN = ROOT / "windows"

a = Analysis(
    [str(WIN / "vault_runner.py")],
    pathex=[str(WIN), str(CORE)],
    binaries=[],
    datas=[],
    hiddenimports=["vaultlib"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="vault-runner",
    version=str(WIN / "version_info.txt"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    icon=None,
)

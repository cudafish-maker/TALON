# PyInstaller spec — Windows
# Run from repo root: pyinstaller build/pyinstaller-windows.spec
import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "talon" / "ui" / "kv"), "talon/ui/kv"),
    ],
    hiddenimports=["sqlcipher3", "nacl", "argon2", "RNS"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pyinstaller"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="talon",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,  # TODO: add talon.ico
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="talon-windows",
)

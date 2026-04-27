# PyInstaller spec - PySide6 Linux desktop
# Run from repo root: pyinstaller build/pyinstaller-linux-desktop.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
root = Path(SPECPATH).parent

datas = []
logo_path = root / "Images" / "talonlogo.png"
if logo_path.exists():
    datas.append((str(logo_path), "Images"))

hiddenimports = [
    "RNS",
    "argon2",
    "nacl",
    "sqlcipher3",
]
hiddenimports += collect_submodules("RNS")
hiddenimports += collect_submodules("talon_core")
hiddenimports += collect_submodules("talon_desktop")

a = Analysis(
    [str(root / "talon_desktop" / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "kivy",
        "kivymd",
        "mapview",
        "pyinstaller",
        "tkinter",
    ],
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
    name="talon-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="talon-desktop-linux",
)

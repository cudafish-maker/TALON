# PyInstaller spec — Windows
# Run from repo root: pyinstaller build/pyinstaller-windows.spec
import importlib.util
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
root = Path(SPECPATH).parent
icon_definitions_spec = importlib.util.find_spec("kivymd.icon_definitions")

datas = [
    (str(root / "talon" / "ui" / "kv"), "talon/ui/kv"),
]
datas += collect_data_files("kivy", includes=["data/**"])
logo_path = root / "Images" / "talonlogo.png"
if logo_path.exists():
    datas.append((str(logo_path), "Images"))
if icon_definitions_spec is not None and icon_definitions_spec.origin:
    datas.append((icon_definitions_spec.origin, "kivymd"))

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=["sqlcipher3", "nacl", "argon2", "RNS", "kivymd.icon_definitions"],
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

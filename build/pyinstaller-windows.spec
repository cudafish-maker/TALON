# PyInstaller spec - PySide6 Windows desktop
# Run from repo root on Windows:
#   pyinstaller --clean --noconfirm build/pyinstaller-windows.spec
from pathlib import Path

from PIL import Image
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
root = Path(SPECPATH).parent


def build_windows_icon(source_path):
    if not source_path.exists():
        return None
    generated_dir = root / "build" / ".generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    icon_path = generated_dir / "talonlogo.ico"
    with Image.open(source_path) as source:
        source = source.convert("RGBA")
        side = max(source.size)
        icon = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        offset = ((side - source.width) // 2, (side - source.height) // 2)
        icon.paste(source, offset)
        icon.save(
            icon_path,
            sizes=[
                (16, 16),
                (24, 24),
                (32, 32),
                (48, 48),
                (64, 64),
                (128, 128),
                (256, 256),
            ],
        )
    return icon_path


datas = []
logo_path = root / "Images" / "talonlogo.png"
app_icon_path = build_windows_icon(logo_path)
if logo_path.exists():
    datas.append((str(logo_path), "Images"))
if app_icon_path is not None:
    datas.append((str(app_icon_path), "Images"))

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
    console=False,
    icon=str(app_icon_path) if app_icon_path is not None else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="talon-desktop-windows",
)

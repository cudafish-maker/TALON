# build/talon-client.spec
# PyInstaller spec file for building the T.A.L.O.N. client binary.
#
# Builds the desktop client (Linux and Windows). The Android build
# uses Buildozer instead — see build/buildozer.spec.
#
# To build manually:
#   cd /path/to/talon
#   pyinstaller build/talon-client.spec
#
# The output goes to dist/talon-client/

# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    # Entry point script
    ['../src/talon/client/app.py'],

    # Where to find our source code
    pathex=['../src'],

    # Binary dependencies
    binaries=[],

    # Non-Python files to include
    datas=[
        ('../config/*.yaml', 'config'),
    ],

    # Hidden imports — Kivy and KivyMD use a lot of dynamic loading
    hiddenimports=[
        'rns',
        'lxmf',
        'nacl',
        'argon2',
        'yaml',
        'sqlcipher3',
        'kivy',
        'kivymd',
        'mapview',
        # Kivy's internal modules that PyInstaller misses
        'kivy.core.window',
        'kivy.core.text',
        'kivy.core.image',
        'kivy.core.audio',
        'kivy.graphics',
    ],

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='talon-client',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Client is a GUI app — no terminal window
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='talon-client',
)

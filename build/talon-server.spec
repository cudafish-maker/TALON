# build/talon-server.spec
# PyInstaller spec file for building the T.A.L.O.N. server binary.
#
# PyInstaller bundles the Python interpreter and all dependencies into
# a single executable (or folder). This spec file tells it exactly
# what to include.
#
# To build manually:
#   cd /path/to/talon
#   pyinstaller build/talon-server.spec
#
# The output goes to dist/talon-server/ (folder mode) or
# dist/talon-server (one-file mode).
#
# GitHub Actions uses this file automatically — see .github/workflows/build.yml

# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    # Entry point script
    ['../src/talon/server/app.py'],

    # Where to find our source code
    pathex=['../src'],

    # Binary dependencies (native libraries like libsodium, sqlcipher)
    binaries=[],

    # Non-Python files to include (configs, templates)
    datas=[
        ('../config/*.yaml', 'config'),
    ],

    # Hidden imports that PyInstaller can't detect automatically.
    # Reticulum and its dependencies use dynamic imports that
    # PyInstaller's static analysis misses.
    hiddenimports=[
        'rns',
        'lxmf',
        'nacl',
        'argon2',
        'yaml',
        'sqlcipher3',
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
    name='talon-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Server runs in a terminal
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='talon-server',
)

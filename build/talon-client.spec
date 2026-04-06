# build/talon-client.spec
# PyInstaller spec file for building the T.A.L.O.N. client binary.
#
# Builds the desktop client (Linux, Windows, macOS). The Android build
# uses Buildozer instead — see build/buildozer.spec.
#
# To build:
#   python build.py client
#   (or: cd /path/to/talon && pyinstaller build/talon-client.spec)
#
# Output: dist/talon-client/

# -*- mode: python ; coding: utf-8 -*-

import os
import sys
import platform

block_cipher = None
ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

# Collect data files
datas = [
    (os.path.join(ROOT, 'config', '*.yaml'), 'config'),
    (os.path.join(ROOT, 'src', 'talon', 'ui', 'kv', '*.kv'), os.path.join('talon', 'ui', 'kv')),
]

# On Windows, include the SQLCipher DLL if present in deps/
binaries = []
if platform.system() == 'Windows':
    dll_path = os.path.join(ROOT, 'deps', 'sqlcipher.dll')
    if os.path.isfile(dll_path):
        binaries.append((dll_path, '.'))

a = Analysis(
    [os.path.join(ROOT, 'talon-client.py')],
    pathex=[os.path.join(ROOT, 'src')],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'RNS',
        'RNS.vendor',
        'LXMF',
        'nacl',
        'nacl.bindings',
        'nacl.pwhash',
        'argon2',
        'argon2.low_level',
        'yaml',
        'sqlcipher3',
        'kivy',
        'kivymd',
        'kivymd.uix',
        'kivymd.icon_definitions',
        'kivymd.uix.boxlayout',
        'kivymd.uix.label',
        'kivymd.uix.label.label',
        'kivymd.uix.button',
        'kivymd.uix.button.button',
        'kivymd.uix.textfield',
        'kivymd.uix.textfield.textfield',
        'kivymd.uix.dialog',
        'kivymd.uix.dialog.dialog',
        'kivymd.uix.list',
        'kivymd.uix.scrollview',
        'kivymd.uix.screen',
        'kivymd.uix.screenmanager',
        'kivymd.uix.divider',
        'kivymd.uix.snackbar',
        'kivymd.uix.snackbar.snackbar',
        'materialyoucolor',
        'mapview',
        'kivy.uix.behaviors',
        'kivy.uix.behaviors.button',
        'kivy.core.window',
        'kivy.core.text',
        'kivy.core.image',
        'kivy.core.audio',
        'kivy.graphics',
        'serial',
        'serial.tools',
        'serial.tools.list_ports',
        'talon.platform',
        'talon.ui.widgets',
        'talon.ui.widgets.map_widget',
        'talon.ui.widgets.status_bar',
        'talon.db.migrations',
        'talon.db.database',
        'talon.db.models',
        'talon.crypto.keys',
        'talon.net.reticulum',
        'talon.net.link_manager',
        'talon.net.transport',
        'talon.net.heartbeat',
        'talon.net.rnode',
        'talon.net.android_usb',
        'talon.net.interfaces',
        'talon.sync.protocol',
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
    console=False,  # GUI app — no console window
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

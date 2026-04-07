# build/talon-server.spec
# PyInstaller spec file for building the T.A.L.O.N. server binary.
#
# To build:
#   python build.py server
#   (or: cd /path/to/talon && pyinstaller build/talon-server.spec)
#
# Output: dist/talon-server/

# -*- mode: python ; coding: utf-8 -*-

import os
import sys
import platform

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

# Collect data files
datas = [
    (os.path.join(ROOT, 'config', '*.yaml'), 'config'),
    (os.path.join(ROOT, 'src', 'talon', 'ui', 'kv', '*.kv'), os.path.join('talon', 'ui', 'kv')),
    (os.path.join(ROOT, 'src', 'talon', 'ui', 'server', 'kv', '*.kv'), os.path.join('talon', 'ui', 'server', 'kv')),
]

# kivy_garden.mapview ships marker icons as package data — bundle them.
datas += collect_data_files('kivy_garden.mapview')

# On Windows, include the SQLCipher DLL if present in deps/
binaries = []
if platform.system() == 'Windows':
    dll_path = os.path.join(ROOT, 'deps', 'sqlcipher.dll')
    if os.path.isfile(dll_path):
        binaries.append((dll_path, '.'))

a = Analysis(
    [os.path.join(ROOT, 'talon-server.py')],
    pathex=[os.path.join(ROOT, 'src')],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'RNS',
        'RNS.vendor',
        # RNS dynamically loads interface classes via `from RNS.Interfaces import *`,
        # which uses glob() — invisible to PyInstaller. List them explicitly.
        'RNS.Interfaces',
        'RNS.Interfaces.Interface',
        'RNS.Interfaces.LocalInterface',
        'RNS.Interfaces.AutoInterface',
        'RNS.Interfaces.BackboneInterface',
        'RNS.Interfaces.TCPInterface',
        'RNS.Interfaces.UDPInterface',
        'RNS.Interfaces.I2PInterface',
        'RNS.Interfaces.RNodeInterface',
        'RNS.Interfaces.RNodeMultiInterface',
        'RNS.Interfaces.SerialInterface',
        'RNS.Interfaces.KISSInterface',
        'RNS.Interfaces.AX25KISSInterface',
        'RNS.Interfaces.PipeInterface',
        'RNS.Interfaces.WeaveInterface',
        'RNS.Interfaces.util',
        'RNS.Interfaces.util.netinfo',
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
        # kivy_garden.mapview — tile-based map widget. The package
        # uses an implicit namespace package layout, which PyInstaller
        # cannot follow without explicit hints.
        'kivy_garden',
        'kivy_garden.mapview',
        'kivy_garden.mapview.view',
        'kivy_garden.mapview.source',
        'kivy_garden.mapview.downloader',
        'kivy_garden.mapview.utils',
        'kivy_garden.mapview.constants',
        'kivy_garden.mapview.types',
        'kivy_garden.mapview.geojson',
        'kivy_garden.mapview.mbtsource',
        'kivy_garden.mapview.clustered_marker_layer',
        'kivy.uix.behaviors',
        'kivy.uix.behaviors.button',
        'kivy.core.window',
        'kivy.core.text',
        'kivy.core.image',
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
        'talon.server.sync_engine',
        'talon.server.tile_server',
        'talon.server.client_registry',
        'talon.server.audit',
        'talon.server.auth',
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
    console=True,  # Server runs with console output
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

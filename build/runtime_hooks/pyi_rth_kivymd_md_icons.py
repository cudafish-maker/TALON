"""Expose a module shim for KivyMD icon names in PyInstaller bundles."""
from importlib import import_module
import sys
import types

try:
    icon_definitions = import_module("kivymd.icon_definitions")
except Exception:
    icon_definitions = None

if icon_definitions is not None:
    shim = types.ModuleType("kivymd.icon_definitions.md_icons")
    shim.md_icons = icon_definitions.md_icons
    sys.modules.setdefault("kivymd.icon_definitions.md_icons", shim)

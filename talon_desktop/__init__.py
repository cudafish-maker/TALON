"""PySide6 desktop client package for TALON.

The desktop package is intentionally separate from the legacy Kivy UI.  It
imports ``talon_core`` as its application boundary and keeps Qt-specific code
inside modules that are loaded only by the desktop entry point.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"

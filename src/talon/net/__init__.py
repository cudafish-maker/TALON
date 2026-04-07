# talon/net/__init__.py
# Networking subsystem for T.A.L.O.N.
# Wraps the Reticulum Network Stack (RNS) to handle:
# - Identity management (cryptographic keys for each operator)
# - Link establishment (encrypted connections between nodes)
# - Transport detection and fallback (Yggdrasil → I2P → TCP → RNode)
# - Heartbeat monitoring
# - Interface configuration (I2P, Yggdrasil, TCP, RNode 915MHz)
#
# IMPORTANT: This file patches RNS.Reticulum at import time so the
# PyInstaller-frozen build can find the interface classes.
#
# Why: RNS/Interfaces/__init__.py builds its `__all__` list with
# `glob('*.py')` against its own directory. In a PyInstaller bundle
# the source files do not exist on disk — they live inside the PYZ
# archive — so glob returns an empty list and `__all__` ends up empty.
# RNS/Reticulum.py then runs `from RNS.Interfaces import *`, which
# imports nothing, and any later reference inside that module to
# e.g. `LocalInterface.LocalServerInterface(...)` raises
# `name 'LocalInterface' is not defined`.
#
# The fix: explicitly import every interface submodule and inject
# it into both `RNS.Interfaces` and `RNS.Reticulum`'s module globals.
# `import RNS` triggers `RNS.Reticulum` loading (and its broken
# wildcard import) first, so we have to do this AFTER that runs.

import RNS  # noqa: E402 — must come before the patching below
import RNS.Interfaces  # noqa: E402
import RNS.Reticulum  # noqa: E402

# Every interface module RNS expects to find via glob().
# Wrapping each in its own try/except so a single missing optional
# interface (e.g. I2P, RNode) does not block the rest.
_RNS_INTERFACE_MODULES = (
    "Interface",
    "LocalInterface",
    "AutoInterface",
    "BackboneInterface",
    "TCPInterface",
    "UDPInterface",
    "I2PInterface",
    "RNodeInterface",
    "RNodeMultiInterface",
    "SerialInterface",
    "KISSInterface",
    "AX25KISSInterface",
    "PipeInterface",
    "WeaveInterface",
)

for _name in _RNS_INTERFACE_MODULES:
    try:
        _mod = __import__(f"RNS.Interfaces.{_name}", fromlist=[_name])
    except Exception:
        # An optional interface failed to import — skip it.
        continue
    # Bind the submodule under the package (in case glob saw nothing).
    setattr(RNS.Interfaces, _name, _mod)
    # Bind it inside RNS.Reticulum's globals too — that is where the
    # broken `from RNS.Interfaces import *` was supposed to have put it.
    setattr(RNS.Reticulum, _name, _mod)

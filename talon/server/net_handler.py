"""Compatibility alias for server net handler moved to ``talon_core``."""

import sys

from talon_core.server import net_handler as _core_net_handler

sys.modules[__name__] = _core_net_handler

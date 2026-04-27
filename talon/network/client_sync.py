"""Compatibility alias for client sync manager moved to ``talon_core``."""

import sys

from talon_core.network import client_sync as _core_client_sync

sys.modules[__name__] = _core_client_sync

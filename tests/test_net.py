# tests/test_net.py
# Tests for the networking layer (transport, heartbeat, interfaces).
#
# NOTE: These tests do NOT require a running Reticulum instance.
# They test the logic around transport selection, heartbeat timing,
# and config generation — not actual network communication.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.constants import TransportType
from talon.net.heartbeat import HeartbeatMonitor
from talon.net.interfaces import build_reticulum_config
from talon.net.transport import TransportManager

# ---------- Transport ----------


def test_transport_priority_order():
    """Transports should be sorted by priority (lower number = higher priority)."""
    tm = TransportManager()
    tm.set_available(TransportType.TCP, True)
    tm.set_available(TransportType.YGGDRASIL, True)
    tm.set_available(TransportType.I2P, True)

    # The active transport should be the highest priority (Yggdrasil)
    assert tm.get_active() == TransportType.YGGDRASIL


def test_broadband_check():
    """Yggdrasil, I2P, and TCP are broadband. RNode is not."""
    tm = TransportManager()

    # With Yggdrasil active, should be broadband
    tm.set_available(TransportType.YGGDRASIL, True)
    assert tm.is_broadband() is True

    # With only RNode active, should not be broadband
    tm2 = TransportManager()
    tm2.set_available(TransportType.RNODE, True)
    assert tm2.is_broadband() is False


# ---------- Heartbeat monitor ----------


def test_heartbeat_monitor_creation():
    """HeartbeatMonitor should initialize with the given threshold."""
    monitor = HeartbeatMonitor(missed_threshold=3)
    assert monitor.missed_threshold == 3


def test_heartbeat_monitor_tracks_clients():
    """Monitor should track when clients send heartbeats."""
    monitor = HeartbeatMonitor(missed_threshold=3)
    monitor.record_heartbeat("client-1", {"position": None, "transport": None})

    # Client should be tracked
    assert monitor.get_client_info("client-1") is not None


# ---------- Reticulum interface fallback ----------


def test_no_interfaces_configured_falls_back_to_autointerface():
    """A config with no enabled interfaces should still produce an
    AutoInterface so RNS has somewhere to send packets — otherwise
    the node logs `No interfaces could process the outbound packet`."""
    config = {"interfaces": {}}
    interfaces = build_reticulum_config(config, is_server=False)
    assert "Default" in interfaces
    assert interfaces["Default"]["type"] == "AutoInterface"


def test_explicit_interface_does_not_get_autointerface_fallback():
    """If the operator has configured a real interface, the fallback
    must NOT be added — that would silently broadcast on the LAN."""
    config = {
        "interfaces": {
            "yggdrasil": {
                "enabled": True,
                "target_host": "200::1",
                "target_port": 4243,
            },
        },
    }
    interfaces = build_reticulum_config(config, is_server=False)
    assert "Yggdrasil" in interfaces
    assert "Default" not in interfaces


def test_rns_interfaces_are_preloaded_on_talon_net_import():
    """Importing talon.net must bind every interface module on the
    RNS.Reticulum *module* so the wildcard import inside RNS does
    not leave `LocalInterface` undefined in PyInstaller-frozen
    builds. Note we check sys.modules['RNS.Reticulum'], not
    RNS.Reticulum: the latter is bound to the *class* via the
    re-export in RNS/__init__.py, and class attributes do not
    satisfy the module-globals lookup that RNS/Reticulum.py's
    interface instantiation code uses at runtime."""
    import sys

    # Importing talon.net runs the patching as a side effect, and
    # internally imports RNS.Reticulum which registers the module in
    # sys.modules.
    import talon.net  # noqa: F401

    rns_reticulum_module = sys.modules["RNS.Reticulum"]
    for name in (
        "LocalInterface",
        "AutoInterface",
        "TCPInterface",
    ):
        assert name in rns_reticulum_module.__dict__, f"RNS.Reticulum module missing {name} after talon.net import"

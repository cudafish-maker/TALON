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

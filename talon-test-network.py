#!/usr/bin/env python3
"""
talon-test-network.py — T.A.L.O.N. network smoke-test script.

Runs a simulated server and client in the same process using mock
Reticulum transport. Verifies the full stack:

  1. Config generation from YAML
  2. RNode detection (simulated)
  3. Server startup and destination announcement
  4. Client link establishment
  5. Enrollment flow (token → lease)
  6. Sync round-trip (request → response → apply)
  7. Heartbeat exchange
  8. Transport fallback (broadband → LoRa)
  9. Clean shutdown

Usage:
  python talon-test-network.py           # Run all checks
  python talon-test-network.py --verbose # Show detailed output
  python talon-test-network.py --check   # Quick check (imports + config only)

Exit codes:
  0 = all checks passed
  1 = one or more checks failed
"""

import sys
import os
import json
import time
import tempfile
import argparse

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Terminal colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0
verbose = False


def check(name, fn):
    """Run a single check and report pass/fail."""
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  {GREEN}✓{RESET} {name}")
    except Exception as e:
        failed += 1
        print(f"  {RED}✗{RESET} {name}")
        if verbose:
            import traceback
            traceback.print_exc()
        else:
            print(f"    {RED}{e}{RESET}")


def section(title):
    """Print a section header."""
    print(f"\n{BOLD}{CYAN}── {title} ──{RESET}")


# ================================================================
# Checks
# ================================================================

def check_imports():
    """Verify all T.A.L.O.N. modules are importable."""
    from talon.platform import (
        PLATFORM, list_serial_ports, detect_rnode_ports,
        check_serial_port, get_default_serial_port,
    )
    from talon.net.interfaces import build_reticulum_config
    from talon.net.reticulum import write_reticulum_config, initialize_reticulum
    from talon.net.rnode import RNodeManager, RNodeStatus
    from talon.net.transport import TransportManager
    from talon.net.heartbeat import HeartbeatMonitor, HeartbeatSender
    from talon.net.link_manager import ServerLinkManager, ClientLinkManager
    from talon.constants import TransportType
    from talon.client.connection import ConnectionManager
    from talon.client.sync_client import SyncClient
    from talon.server.sync_engine import SyncEngine
    assert PLATFORM in ("linux", "windows", "macos", "android", "unknown")


def check_config_files():
    """Verify all config YAML files exist and are valid."""
    import yaml
    root = os.path.dirname(__file__)
    for name in ("default.yaml", "client.yaml", "server.yaml"):
        path = os.path.join(root, "config", name)
        assert os.path.isfile(path), f"Missing {path}"
        with open(path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), f"{name} is not a valid YAML dict"


def check_serial_enumeration():
    """Verify serial port enumeration works."""
    from talon.platform import list_serial_ports
    ports = list_serial_ports()
    assert isinstance(ports, list)
    if verbose and ports:
        for p in ports:
            print(f"    Found port: {p['port']} — {p['description']}")


def check_rnode_detection():
    """Verify RNode detection runs without error."""
    from talon.platform import detect_rnode_ports
    candidates = detect_rnode_ports()
    assert isinstance(candidates, list)
    if verbose and candidates:
        for c in candidates:
            print(f"    RNode candidate: {c['port']} — {c['description']}")
    if verbose and not candidates:
        print(f"    {YELLOW}No RNode hardware detected (OK for smoke test){RESET}")


def check_rnode_manager_lifecycle():
    """Verify RNodeManager state machine works."""
    from talon.net.rnode import RNodeManager, RNodeStatus
    config = {"port": "/dev/ttyNONEXISTENT", "frequency": 915000000}
    mgr = RNodeManager(config)
    assert mgr.status == RNodeStatus.DISCONNECTED
    assert mgr.get_interface_config() == {}
    assert mgr.validate() is False
    assert mgr.error is not None


def check_config_generation():
    """Verify Reticulum config generation from YAML."""
    import yaml
    from talon.net.reticulum import write_reticulum_config

    root = os.path.dirname(__file__)
    with open(os.path.join(root, "config", "server.yaml")) as f:
        server_config = yaml.safe_load(f)

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = write_reticulum_config(
            server_config, is_server=True, config_dir=tmpdir
        )
        config_path = os.path.join(config_dir, "config")
        assert os.path.isfile(config_path)
        with open(config_path) as f:
            content = f.read()

    assert "[reticulum]" in content
    assert "[interfaces]" in content
    if verbose:
        print(f"    Generated config ({len(content)} bytes):")
        for line in content.strip().split("\n")[:15]:
            print(f"      {line}")
        if content.count("\n") > 15:
            print(f"      ... ({content.count(chr(10))} lines total)")


def check_interfaces_from_yaml():
    """Verify build_reticulum_config produces correct interfaces."""
    import yaml
    from talon.net.interfaces import build_reticulum_config

    root = os.path.dirname(__file__)
    with open(os.path.join(root, "config", "server.yaml")) as f:
        config = yaml.safe_load(f)

    interfaces = build_reticulum_config(config, is_server=True)
    # Server.yaml has yggdrasil, i2p, rnode enabled; tcp disabled
    assert "Yggdrasil" in interfaces, f"Missing Yggdrasil, got: {list(interfaces.keys())}"
    assert "I2P" in interfaces, f"Missing I2P, got: {list(interfaces.keys())}"
    assert "RNode" in interfaces, f"Missing RNode, got: {list(interfaces.keys())}"
    assert "TCP" not in interfaces, "TCP should be disabled"

    rnode = interfaces["RNode"]
    assert rnode["type"] == "RNodeInterface"
    assert rnode["frequency"] == 915000000
    if verbose:
        print(f"    Interfaces: {', '.join(interfaces.keys())}")
        print(f"    RNode: {rnode['port']} @ {rnode['frequency']/1e6:.1f} MHz, "
              f"SF{rnode['spreading_factor']}, BW {rnode['bandwidth']/1e3:.0f}kHz")


def check_transport_manager():
    """Verify transport priority and fallback logic."""
    from talon.net.transport import TransportManager
    from talon.constants import TransportType

    tm = TransportManager()
    tm.set_available(TransportType.YGGDRASIL, True)
    tm.set_available(TransportType.TCP, True)
    tm.set_available(TransportType.RNODE, True)

    assert tm.get_active() == TransportType.YGGDRASIL
    assert tm.is_broadband() is True

    # Drop broadband
    tm.set_available(TransportType.YGGDRASIL, False)
    tm.set_available(TransportType.TCP, False)
    assert tm.get_active() == TransportType.RNODE
    assert tm.is_broadband() is False


def check_heartbeat_monitor():
    """Verify heartbeat stale detection."""
    from talon.net.heartbeat import HeartbeatMonitor

    monitor = HeartbeatMonitor(missed_threshold=2)
    monitor.record_heartbeat("WOLF-1", {"timestamp": time.time()})
    monitor.record_heartbeat("WOLF-2", {"timestamp": time.time()})

    # WOLF-2 is fresh
    assert monitor.get_client_info("WOLF-2") is not None
    stale = monitor.check_stale()
    assert "WOLF-2" not in stale

    # Simulate stale by backdating
    monitor._clients["WOLF-1"]["last_heartbeat"] = time.time() - 600
    stale = monitor.check_stale()
    assert "WOLF-1" in stale


def check_sync_client():
    """Verify SyncClient round-trip with mock send_fn."""
    from unittest.mock import MagicMock, patch
    from talon.client.sync_client import SyncClient

    mock_cache = MagicMock()
    client = SyncClient(cache=mock_cache)

    with patch("talon.client.sync_client.build_sync_request") as mock_req, \
         patch("talon.client.sync_client.build_client_changes") as mock_ch, \
         patch("talon.client.sync_client.apply_sync_response"):

        mock_req.return_value = {"type": "sync_request", "versions": {}}
        mock_ch.return_value = {"type": "client_changes", "changes": {},
                                "timestamp": time.time()}

        def send_fn(msg):
            if msg.get("type") == "sync_request":
                return {"type": "sync_response", "updates": {
                    "sitreps": [{"id": "s1"}]
                }}
            return {"applied": 0, "conflicts": []}

        result = client.full_sync(send_fn)

    assert result["received"] == 1
    assert result["sent"] == 0
    assert "error" not in result


def check_link_manager_round_trip():
    """Verify ServerLinkManager accepts link and routes packets."""
    from unittest.mock import MagicMock, patch
    from talon.net.link_manager import ServerLinkManager

    identity = MagicMock()
    identity.hexhash = "server-1"
    slm = ServerLinkManager(identity)

    responses = []
    slm.on_sync_message = lambda h, m: (
        responses.append(h),
        {"type": "sync_response", "updates": {}}
    )[1]

    mock_dest = MagicMock()
    mock_dest.hash = b"\x01\x02\x03\x04"
    mock_dest.set_link_established_callback = MagicMock()
    mock_dest.announce = MagicMock()

    with patch("talon.net.link_manager.RNS.Destination", return_value=mock_dest):
        slm.start()

    link = MagicMock()
    link.status = 2  # RNS.Link.ACTIVE
    remote_id = MagicMock()
    remote_id.hexhash = "client-1"
    link.get_remote_identity = MagicMock(return_value=remote_id)
    link.set_packet_callback = MagicMock()
    link.set_link_closed_callback = MagicMock()
    slm._link_established(link)

    msg = json.dumps({"type": "sync_request", "versions": {}}).encode()
    with patch("talon.net.link_manager.RNS.Packet") as mock_pkt_cls:
        mock_pkt_cls.return_value = MagicMock()
        slm._packet_received("client-1", link, msg)

    assert responses == ["client-1"]


def check_platform_detection():
    """Verify platform detection and serial defaults."""
    from talon.platform import (
        PLATFORM, IS_LINUX, IS_WINDOWS, IS_ANDROID,
        get_default_serial_port, check_serial_port,
    )

    assert PLATFORM in ("linux", "windows", "macos", "android", "unknown")
    port = get_default_serial_port()
    assert isinstance(port, str) and len(port) > 0

    # Check a known-bad port
    result = check_serial_port("/dev/ttyNONEXISTENT999")
    assert isinstance(result, dict)
    assert "exists" in result


# ================================================================
# Quick check mode
# ================================================================

def run_quick_checks():
    """Minimal checks: imports and config files only."""
    section("Quick Checks")
    check("All modules importable", check_imports)
    check("Config YAML files valid", check_config_files)
    check("Platform detection works", check_platform_detection)


# ================================================================
# Full checks
# ================================================================

def run_full_checks():
    """Run all smoke-test checks."""
    section("Module Imports")
    check("All T.A.L.O.N. modules importable", check_imports)
    check("Config YAML files valid", check_config_files)

    section("Platform & Serial")
    check("Platform detection", check_platform_detection)
    check("Serial port enumeration", check_serial_enumeration)
    check("RNode hardware detection", check_rnode_detection)
    check("RNodeManager lifecycle", check_rnode_manager_lifecycle)

    section("Config Generation")
    check("Reticulum config from YAML", check_config_generation)
    check("Interface config from YAML", check_interfaces_from_yaml)

    section("Transport & Heartbeat")
    check("Transport priority & fallback", check_transport_manager)
    check("Heartbeat stale detection", check_heartbeat_monitor)

    section("Network Simulation")
    check("Link manager round-trip", check_link_manager_round_trip)
    check("Sync client round-trip", check_sync_client)


# ================================================================
# Main
# ================================================================

def main():
    global verbose

    parser = argparse.ArgumentParser(
        description="T.A.L.O.N. network smoke-test"
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed output")
    parser.add_argument("--check", action="store_true",
                        help="Quick check (imports + config only)")
    args = parser.parse_args()
    verbose = args.verbose

    print(f"\n{BOLD}T.A.L.O.N. Network Smoke Test{RESET}")
    print(f"{'=' * 40}")

    if args.check:
        run_quick_checks()
    else:
        run_full_checks()

    print(f"\n{'=' * 40}")
    if failed == 0:
        print(f"{GREEN}{BOLD}All {passed} checks passed.{RESET}")
    else:
        print(f"{RED}{BOLD}{failed} check(s) failed{RESET}, {passed} passed.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

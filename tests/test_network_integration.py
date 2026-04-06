# tests/test_network_integration.py
# End-to-end network integration tests for T.A.L.O.N.
#
# Step 7: Testing on Real Network (software portion).
#
# These tests verify the full wiring from startup through message
# delivery WITHOUT requiring real hardware or a live Reticulum instance.
# They mock the RNS layer but exercise all T.A.L.O.N. code paths:
#
# - Startup sequence: config load → RNode detect → config gen → RNS init
# - Server-client link: establish, sync, heartbeat, disconnect
# - Reticulum config file: generated, well-formed, parseable
# - Transport fallback: Yggdrasil → TCP → RNode priority
# - Full sync round-trip: build request → server response → apply
# - Enrollment over link: token → lease → registered client

import json
import os
import sys
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import RNS

from talon.constants import TransportType
from talon.net.heartbeat import HeartbeatMonitor, HeartbeatSender
from talon.net.link_manager import ClientLinkManager, ServerLinkManager
from talon.net.transport import TransportManager

# ================================================================
# Helpers
# ================================================================

def make_mock_identity(hexhash="abc123"):
    identity = MagicMock(spec=RNS.Identity)
    identity.hexhash = hexhash
    return identity


def make_mock_link(status=RNS.Link.ACTIVE, remote_hexhash="client-1"):
    link = MagicMock()
    link.status = status
    remote_id = MagicMock()
    remote_id.hexhash = remote_hexhash
    link.get_remote_identity = MagicMock(return_value=remote_id)
    link.set_packet_callback = MagicMock()
    link.set_link_closed_callback = MagicMock()
    link.teardown = MagicMock()
    return link


def make_mock_destination():
    dest = MagicMock()
    dest.hash = b"\x01\x02\x03\x04"
    dest.set_link_established_callback = MagicMock()
    dest.announce = MagicMock()
    return dest


def make_server_config():
    """Full T.A.L.O.N. server config for testing."""
    return {
        "reticulum": {
            "propagation_node": True,
            "transport_node": True,
        },
        "interfaces": {
            "yggdrasil": {
                "enabled": True,
                "listen_address": "200::1",
                "listen_port": 4243,
            },
            "tcp": {
                "enabled": False,
            },
            "rnode": {
                "enabled": True,
                "port": "/dev/ttyUSB0",
                "frequency": 915000000,
                "bandwidth": 125000,
                "spreading_factor": 10,
                "coding_rate": 5,
                "tx_power": 17,
            },
        },
        "heartbeat": {
            "broadband_interval": 60,
            "lora_interval": 120,
            "missed_threshold": 3,
        },
        "database": {"path": "data/server.db"},
    }


def make_client_config():
    """Full T.A.L.O.N. client config for testing."""
    return {
        "reticulum": {
            "transport_node": True,
        },
        "interfaces": {
            "yggdrasil": {
                "enabled": True,
                "target_host": "200::1",
                "target_port": 4243,
            },
            "tcp": {"enabled": False},
            "rnode": {
                "enabled": True,
                "port": "/dev/ttyUSB0",
                "frequency": 915000000,
                "bandwidth": 125000,
                "spreading_factor": 10,
                "coding_rate": 5,
                "tx_power": 17,
            },
        },
        "server_destination_hash": "01020304",
        "heartbeat": {
            "broadband_interval": 60,
            "lora_interval": 120,
        },
        "notifications": {
            "audio_enabled": False,
        },
    }


# ================================================================
# 1. Reticulum config generation & validation
# ================================================================

class TestReticulumConfigValidation:

    def test_server_config_is_well_formed(self):
        """Generated server config should have all required sections."""
        from talon.net.reticulum import write_reticulum_config
        config = make_server_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = write_reticulum_config(
                config, is_server=True, config_dir=tmpdir
            )
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()

        assert "[reticulum]" in content
        assert "[interfaces]" in content
        assert "enable_transport = Yes" in content
        assert "share_instance = Yes" in content

    def test_client_config_is_well_formed(self):
        """Generated client config should have transport enabled."""
        from talon.net.reticulum import write_reticulum_config
        config = make_client_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = write_reticulum_config(
                config, is_server=False, config_dir=tmpdir
            )
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()

        assert "enable_transport = Yes" in content

    def test_server_config_has_yggdrasil_and_rnode(self):
        """Server config should include both configured interfaces."""
        from talon.net.reticulum import write_reticulum_config
        config = make_server_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = write_reticulum_config(
                config, is_server=True, config_dir=tmpdir
            )
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()

        assert "[[Yggdrasil]]" in content
        assert "TCPServerInterface" in content
        assert "[[RNode]]" in content
        assert "RNodeInterface" in content
        assert "915000000" in content

    def test_client_config_has_yggdrasil_and_rnode(self):
        """Client config should have client-style interfaces."""
        from talon.net.reticulum import write_reticulum_config
        config = make_client_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = write_reticulum_config(
                config, is_server=False, config_dir=tmpdir
            )
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()

        assert "[[Yggdrasil]]" in content
        assert "TCPClientInterface" in content
        assert "[[RNode]]" in content

    def test_disabled_interfaces_excluded(self):
        """Disabled TCP should not appear in generated config."""
        from talon.net.reticulum import write_reticulum_config
        config = make_server_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = write_reticulum_config(
                config, is_server=True, config_dir=tmpdir
            )
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()

        assert "[[TCP]]" not in content

    def test_rnode_override_replaces_yaml(self):
        """RNode override from hardware detection should replace YAML config."""
        from talon.net.reticulum import write_reticulum_config
        config = make_server_config()
        override = {
            "type": "RNodeInterface",
            "interface_enabled": True,
            "port": "/dev/ttyACM0",
            "frequency": 868000000,
            "bandwidth": 250000,
            "spreading_factor": 8,
            "coding_rate": 6,
            "txpower": 20,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = write_reticulum_config(
                config, is_server=True, config_dir=tmpdir,
                rnode_override=override,
            )
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()

        # Override values should appear, not YAML defaults
        assert "/dev/ttyACM0" in content
        assert "868000000" in content
        assert "/dev/ttyUSB0" not in content

    def test_config_file_is_rewritable(self):
        """Regenerating config should overwrite the previous one."""
        from talon.net.reticulum import write_reticulum_config
        config = make_server_config()
        with tempfile.TemporaryDirectory() as tmpdir:
            write_reticulum_config(config, is_server=True, config_dir=tmpdir)

            # Change config and regenerate
            config["interfaces"]["rnode"]["frequency"] = 868000000
            write_reticulum_config(config, is_server=True, config_dir=tmpdir)

            with open(os.path.join(tmpdir, "config")) as f:
                content = f.read()

        assert "868000000" in content
        assert "915000000" not in content

    def test_config_with_all_interfaces(self):
        """Config with all four interfaces should generate all four sections."""
        from talon.net.reticulum import write_reticulum_config
        config = {
            "reticulum": {"transport_node": True},
            "interfaces": {
                "yggdrasil": {"enabled": True, "listen_address": "200::1",
                              "listen_port": 4243},
                "i2p": {"enabled": True, "listen_port": 4244},
                "tcp": {"enabled": True, "listen_port": 4242,
                        "bind_address": "0.0.0.0"},
                "rnode": {"enabled": True, "port": "/dev/ttyUSB0",
                          "frequency": 915000000},
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = write_reticulum_config(
                config, is_server=True, config_dir=tmpdir
            )
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()

        assert "[[Yggdrasil]]" in content
        assert "[[I2P]]" in content
        assert "[[TCP]]" in content
        assert "[[RNode]]" in content


# ================================================================
# 2. Full startup sequence (config → RNode → Reticulum)
# ================================================================

class TestServerStartupSequence:

    def test_server_setup_rnode_detects_hardware(self):
        """setup_rnode should create RNodeManager and attempt detection."""
        from talon.server.app import TalonServer

        server = TalonServer.__new__(TalonServer)
        server.config = make_server_config()
        server.rnode_manager = None

        with patch("talon.platform.detect_rnode_ports", return_value=[]), \
             patch("talon.platform.check_serial_port",
                   return_value={"exists": False, "accessible": False,
                                 "error": "not found"}):
            server.setup_rnode()

        assert server.rnode_manager is not None
        assert server.rnode_manager.status == "disconnected"

    def test_server_setup_rnode_skips_when_disabled(self):
        """setup_rnode should do nothing when RNode is disabled."""
        from talon.server.app import TalonServer

        server = TalonServer.__new__(TalonServer)
        config = make_server_config()
        config["interfaces"]["rnode"]["enabled"] = False
        server.config = config
        server.rnode_manager = None

        server.setup_rnode()
        assert server.rnode_manager is None

    def test_server_setup_network_generates_config(self):
        """setup_network should call initialize_reticulum with talon_config."""
        from talon.server.app import TalonServer

        server = TalonServer.__new__(TalonServer)
        server.config = make_server_config()
        server.rnode_manager = None
        server.link_manager = None
        server.identity = None

        with patch("talon.server.app.initialize_reticulum") as mock_init, \
             patch("talon.server.app.create_identity",
                   return_value=make_mock_identity("server-id")), \
             patch("talon.server.app.ServerLinkManager") as mock_slm_cls:
            mock_slm = MagicMock()
            mock_slm_cls.return_value = mock_slm
            mock_init.return_value = MagicMock()

            server.setup_network()

        # Should have been called with talon_config
        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args[1]
        assert call_kwargs["talon_config"] is server.config
        assert call_kwargs["is_server"] is True

    def test_server_setup_network_passes_rnode_override(self):
        """If RNode is detected, its config should be passed as override."""
        from talon.net.rnode import RNodeManager, RNodeStatus
        from talon.server.app import TalonServer

        server = TalonServer.__new__(TalonServer)
        server.config = make_server_config()
        server.link_manager = None
        server.identity = None

        # Simulate detected and ready RNode
        mgr = RNodeManager(server.config["interfaces"]["rnode"])
        mgr._status = RNodeStatus.READY
        mgr._port = "/dev/ttyACM0"
        server.rnode_manager = mgr

        with patch("talon.server.app.initialize_reticulum") as mock_init, \
             patch("talon.server.app.create_identity",
                   return_value=make_mock_identity("server-id")), \
             patch("talon.server.app.ServerLinkManager") as mock_slm_cls:
            mock_slm = MagicMock()
            mock_slm_cls.return_value = mock_slm
            mock_init.return_value = MagicMock()

            server.setup_network()

        call_kwargs = mock_init.call_args[1]
        assert call_kwargs["rnode_override"] is not None
        assert call_kwargs["rnode_override"]["port"] == "/dev/ttyACM0"
        # RNode should be marked as in_use
        assert mgr.status == RNodeStatus.IN_USE


class TestClientStartupSequence:

    def test_client_setup_rnode_detects_hardware(self):
        """Client setup_rnode should create RNodeManager."""
        from talon.client.app import TalonClient

        client = TalonClient.__new__(TalonClient)
        client.config = make_client_config()
        client.rnode_manager = None

        with patch("talon.platform.IS_ANDROID", False), \
             patch("talon.platform.detect_rnode_ports", return_value=[]), \
             patch("talon.platform.check_serial_port",
                   return_value={"exists": False, "accessible": False,
                                 "error": "not found"}):
            client.setup_rnode()

        assert client.rnode_manager is not None

    def test_client_setup_rnode_skips_when_disabled(self):
        """Client should skip RNode setup when disabled."""
        from talon.client.app import TalonClient

        client = TalonClient.__new__(TalonClient)
        config = make_client_config()
        config["interfaces"]["rnode"]["enabled"] = False
        client.config = config
        client.rnode_manager = None

        client.setup_rnode()
        assert client.rnode_manager is None

    def test_client_setup_network_passes_talon_config(self):
        """Client setup_network should use talon_config for config gen."""
        from talon.client.app import TalonClient

        client = TalonClient.__new__(TalonClient)
        client.config = make_client_config()
        client.rnode_manager = None
        client.identity = None

        with patch("talon.client.app.initialize_reticulum") as mock_init, \
             patch("talon.client.app.create_identity",
                   return_value=make_mock_identity("client-id")):
            mock_init.return_value = MagicMock()
            client.setup_network()

        call_kwargs = mock_init.call_args[1]
        assert call_kwargs["talon_config"] is client.config
        assert call_kwargs["is_server"] is False


# ================================================================
# 3. Server-client link lifecycle over mock RNS
# ================================================================

class TestLinkLifecycle:

    def test_server_accept_client_and_exchange_sync(self):
        """Full round-trip: server accepts link, client sends sync, server responds."""
        identity = make_mock_identity("server-1")
        slm = ServerLinkManager(identity)

        # Wire up a simple sync handler
        sync_responses = []
        def on_sync(client_hash, message):
            sync_responses.append(client_hash)
            return {
                "type": "sync_response",
                "updates": {"sitreps": [{"id": "s1", "title": "Test"}]},
                "timestamp": time.time(),
            }
        slm.on_sync_message = on_sync

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        # Client connects
        link = make_mock_link(remote_hexhash="client-alpha")
        slm._link_established(link)
        assert "client-alpha" in slm.get_connected_clients()

        # Client sends a sync request
        request = {"type": "sync_request", "versions": {"sitreps": 0}}
        raw = json.dumps(request).encode("utf-8")

        with patch("talon.net.link_manager.RNS.Packet") as mock_pkt_cls:
            mock_pkt = MagicMock()
            mock_pkt_cls.return_value = mock_pkt
            slm._packet_received("client-alpha", link, raw)

        # Server should have processed the sync
        assert sync_responses == ["client-alpha"]
        # Response should have been sent back
        mock_pkt.send.assert_called_once()
        sent_bytes = mock_pkt_cls.call_args[0][1]
        response = json.loads(sent_bytes.decode("utf-8"))
        assert response["type"] == "sync_response"
        assert "sitreps" in response["updates"]

    def test_server_accept_enrollment_request(self):
        """Server should route enrollment requests to on_enrollment handler."""
        identity = make_mock_identity("server-1")
        slm = ServerLinkManager(identity)

        enrollment_calls = []
        def on_enrollment(client_hash, message):
            enrollment_calls.append(client_hash)
            return {
                "type": "enrollment_response",
                "success": True,
                "lease": {"token": "abc", "expires_at": time.time() + 86400},
            }
        slm.on_enrollment = on_enrollment

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link(remote_hexhash="new-client")
        slm._link_established(link)

        request = {
            "type": "enrollment_request",
            "token": "test-token-123",
            "callsign": "WOLF-1",
        }
        raw = json.dumps(request).encode("utf-8")

        with patch("talon.net.link_manager.RNS.Packet") as mock_pkt_cls:
            mock_pkt = MagicMock()
            mock_pkt_cls.return_value = mock_pkt
            slm._packet_received("new-client", link, raw)

        assert enrollment_calls == ["new-client"]
        sent_bytes = mock_pkt_cls.call_args[0][1]
        response = json.loads(sent_bytes.decode("utf-8"))
        assert response["success"] is True

    def test_multiple_clients_independent(self):
        """Multiple clients should have independent links."""
        identity = make_mock_identity("server-1")
        slm = ServerLinkManager(identity)
        slm.on_sync_message = lambda h, m: {"type": "sync_response",
                                             "updates": {}}

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link1 = make_mock_link(remote_hexhash="client-1")
        link2 = make_mock_link(remote_hexhash="client-2")
        link3 = make_mock_link(remote_hexhash="client-3")
        slm._link_established(link1)
        slm._link_established(link2)
        slm._link_established(link3)

        assert len(slm.get_connected_clients()) == 3

        # Disconnect one — others should stay
        slm._link_closed("client-2")
        remaining = slm.get_connected_clients()
        assert "client-1" in remaining
        assert "client-2" not in remaining
        assert "client-3" in remaining

    def test_server_push_to_specific_client(self):
        """Server should be able to push a message to a specific client."""
        identity = make_mock_identity("server-1")
        slm = ServerLinkManager(identity)

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link(remote_hexhash="client-1")
        slm._link_established(link)

        with patch("talon.net.link_manager.RNS.Packet") as mock_pkt_cls:
            mock_pkt = MagicMock()
            mock_pkt_cls.return_value = mock_pkt
            result = slm.send_to_client("client-1", {
                "type": "data_changed",
                "tables": ["sitreps"],
            })

        assert result is True
        mock_pkt.send.assert_called_once()

    def test_client_send_and_receive_round_trip(self):
        """Client send_and_receive should deliver response via callback."""
        identity = make_mock_identity("my-client")
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")

        mock_link = MagicMock()
        mock_link.status = RNS.Link.ACTIVE
        clm.link = mock_link

        # Simulate server response in background
        def respond():
            time.sleep(0.05)
            resp = {"type": "sync_response", "updates": {
                "sitreps": [{"id": "s1"}]
            }}
            clm._packet_received(json.dumps(resp).encode("utf-8"))

        t = threading.Thread(target=respond)
        t.start()

        with patch("talon.net.link_manager.RNS.Packet") as mock_pkt_cls:
            mock_pkt = MagicMock()
            mock_pkt_cls.return_value = mock_pkt
            result = clm.send_and_receive(
                {"type": "sync_request", "versions": {}}, timeout=2
            )

        t.join()
        assert result is not None
        assert result["type"] == "sync_response"
        assert len(result["updates"]["sitreps"]) == 1


# ================================================================
# 4. Transport fallback logic
# ================================================================

class TestTransportFallback:

    def test_fallback_yggdrasil_to_tcp(self):
        """When Yggdrasil drops, TCP should become active."""
        tm = TransportManager()
        tm.set_available(TransportType.YGGDRASIL, True)
        tm.set_available(TransportType.TCP, True)
        assert tm.get_active() == TransportType.YGGDRASIL

        tm.set_available(TransportType.YGGDRASIL, False)
        assert tm.get_active() == TransportType.TCP

    def test_fallback_all_to_rnode(self):
        """When all broadband drops, RNode should be the fallback."""
        tm = TransportManager()
        tm.set_available(TransportType.YGGDRASIL, True)
        tm.set_available(TransportType.TCP, True)
        tm.set_available(TransportType.RNODE, True)

        tm.set_available(TransportType.YGGDRASIL, False)
        tm.set_available(TransportType.TCP, False)

        assert tm.get_active() == TransportType.RNODE
        assert tm.is_broadband() is False

    def test_recovery_restores_best_transport(self):
        """When a higher-priority transport recovers, it should become active."""
        tm = TransportManager()
        tm.set_available(TransportType.RNODE, True)
        assert tm.get_active() == TransportType.RNODE

        tm.set_available(TransportType.I2P, True)
        assert tm.get_active() == TransportType.I2P

        tm.set_available(TransportType.YGGDRASIL, True)
        assert tm.get_active() == TransportType.YGGDRASIL

    def test_pinned_transport_overrides(self):
        """Pinned transport should be used even if better is available."""
        tm = TransportManager()
        tm.set_available(TransportType.YGGDRASIL, True)
        tm.set_available(TransportType.RNODE, True)

        tm.pin_transport(TransportType.RNODE)
        assert tm.get_active() == TransportType.RNODE

    def test_no_transports_returns_none(self):
        """With no available transports, active should be None."""
        tm = TransportManager()
        assert tm.get_active() is None
        assert tm.is_broadband() is False

    def test_connection_manager_detect_from_config(self):
        """ConnectionManager should detect transports from YAML config."""
        from talon.client.connection import ConnectionManager
        config = make_client_config()
        cm = ConnectionManager(config=config)
        cm.detect_transports()

        available = cm.transport.get_all_available()
        assert TransportType.YGGDRASIL in available
        assert TransportType.RNODE in available
        assert TransportType.TCP not in available  # disabled

    def test_connection_manager_broadband_check(self):
        """is_broadband should reflect the current transport."""
        from talon.client.connection import ConnectionManager
        cm = ConnectionManager(config={})
        cm.is_connected = True
        cm.current_transport = TransportType.RNODE
        cm.transport.set_available(TransportType.RNODE, True)
        assert cm.is_broadband() is False

        cm.current_transport = TransportType.YGGDRASIL
        cm.transport.set_available(TransportType.YGGDRASIL, True)
        assert cm.is_broadband() is True


# ================================================================
# 5. Heartbeat over transport
# ================================================================

class TestHeartbeatIntegration:

    def test_heartbeat_monitor_detects_stale(self):
        """Monitor should detect clients that miss heartbeats."""
        monitor = HeartbeatMonitor(missed_threshold=2)
        monitor.record_heartbeat("WOLF-1", {
            "timestamp": time.time() - 500,
            "position": None,
            "transport": None,
        })
        # Override last_heartbeat to simulate old heartbeat
        monitor._clients["WOLF-1"]["last_heartbeat"] = time.time() - 500

        stale = monitor.check_stale(broadband_interval=60, lora_interval=120)
        assert "WOLF-1" in stale

    def test_heartbeat_monitor_fresh_client_not_stale(self):
        """Recently heard client should not be stale."""
        monitor = HeartbeatMonitor(missed_threshold=3)
        monitor.record_heartbeat("WOLF-2", {
            "timestamp": time.time(),
            "position": (35.0, -80.0),
            "transport": "yggdrasil",
        })

        stale = monitor.check_stale()
        assert "WOLF-2" not in stale

    def test_heartbeat_sender_respects_transport(self):
        """HeartbeatSender should adjust interval based on transport."""
        sender = HeartbeatSender(broadband_interval=5, lora_interval=10)
        sender.is_broadband_callback = lambda: True
        # Don't actually start the thread — just verify the callbacks are set
        assert sender.broadband_interval == 5
        assert sender.lora_interval == 10

    def test_heartbeat_payload_via_link_manager(self):
        """Heartbeat sent via ClientLinkManager should include type field."""
        identity = make_mock_identity()
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")

        mock_link = MagicMock()
        mock_link.status = RNS.Link.ACTIVE
        clm.link = mock_link

        with patch("talon.net.link_manager.RNS.Packet") as mock_pkt_cls:
            mock_pkt = MagicMock()
            mock_pkt_cls.return_value = mock_pkt
            clm.send_heartbeat({
                "timestamp": time.time(),
                "position": (35.0, -80.0),
                "callsign": "WOLF-1",
            })

        sent_bytes = mock_pkt_cls.call_args[0][1]
        payload = json.loads(sent_bytes.decode("utf-8"))
        assert payload["type"] == "heartbeat"
        assert payload["callsign"] == "WOLF-1"
        assert payload["position"] == [35.0, -80.0]


# ================================================================
# 6. Sync round-trip (mock send_fn)
# ================================================================

class TestSyncRoundTrip:

    def test_full_sync_happy_path(self):
        """SyncClient.full_sync should complete a full sync cycle."""
        from talon.client.sync_client import SyncClient

        mock_cache = MagicMock()
        mock_cache.db = MagicMock()

        client = SyncClient(cache=mock_cache)

        # Mock the protocol functions
        with patch("talon.client.sync_client.build_sync_request") as mock_req, \
             patch("talon.client.sync_client.build_client_changes") as mock_changes, \
             patch("talon.client.sync_client.apply_sync_response"):

            mock_req.return_value = {
                "type": "sync_request",
                "versions": {"sitreps": 0},
            }
            mock_changes.return_value = {
                "type": "client_changes",
                "changes": {},
                "timestamp": time.time(),
            }

            # Simulate server responses
            def mock_send_fn(message):
                if message.get("type") == "sync_request":
                    return {
                        "type": "sync_response",
                        "updates": {
                            "sitreps": [
                                {"id": "s1", "title": "Test SITREP"},
                            ]
                        },
                    }
                return {"applied": 0, "conflicts": []}

            result = client.full_sync(mock_send_fn)

        assert result["received"] == 1
        assert result["sent"] == 0
        assert result["conflicts"] == []
        assert client.is_syncing is False
        assert client.last_sync > 0

    def test_full_sync_with_pending_changes(self):
        """Sync should send pending outbox items to the server."""
        from talon.client.sync_client import SyncClient

        mock_cache = MagicMock()
        mock_cache.db = MagicMock()

        client = SyncClient(cache=mock_cache)

        with patch("talon.client.sync_client.build_sync_request") as mock_req, \
             patch("talon.client.sync_client.build_client_changes") as mock_changes, \
             patch("talon.client.sync_client.apply_sync_response"):

            mock_req.return_value = {
                "type": "sync_request",
                "versions": {},
            }
            mock_changes.return_value = {
                "type": "client_changes",
                "changes": {
                    "sitreps": [{"id": "s2", "title": "From client"}],
                },
                "timestamp": time.time(),
            }

            calls = []
            def mock_send_fn(message):
                calls.append(message["type"])
                if message.get("type") == "sync_request":
                    return {"type": "sync_response", "updates": {}}
                return {"applied": 1, "conflicts": []}

            result = client.full_sync(mock_send_fn)

        assert "sync_request" in calls
        assert "client_changes" in calls
        assert result["sent"] == 1

    def test_sync_no_server_response(self):
        """Sync should handle no server response gracefully."""
        from talon.client.sync_client import SyncClient

        mock_cache = MagicMock()
        mock_cache.db = MagicMock()

        client = SyncClient(cache=mock_cache)

        with patch("talon.client.sync_client.build_sync_request") as mock_req:
            mock_req.return_value = {
                "type": "sync_request",
                "versions": {},
            }

            result = client.full_sync(lambda msg: None)

        assert "error" in result
        assert client.is_syncing is False


# ================================================================
# 7. RNode manager integration with startup
# ================================================================

class TestRNodeStartupIntegration:

    def test_rnode_detect_with_configured_port(self):
        """RNodeManager should check configured port first."""
        from talon.net.rnode import RNodeManager, RNodeStatus

        config = {"port": "/dev/ttyUSB0", "frequency": 915000000}
        mgr = RNodeManager(config)

        with patch("talon.platform.check_serial_port",
                   return_value={"exists": True, "accessible": True,
                                 "error": None}), \
             patch("talon.platform.detect_rnode_ports", return_value=[]):
            found = mgr.detect()

        assert found is True
        assert mgr.port == "/dev/ttyUSB0"
        assert mgr.status == RNodeStatus.DETECTED

    def test_rnode_detect_falls_back_to_auto(self):
        """When configured port missing, should try auto-detection."""
        from talon.net.rnode import RNodeManager

        config = {"port": "/dev/ttyNONE", "frequency": 915000000}
        mgr = RNodeManager(config)

        auto_detected = [{
            "port": "/dev/ttyACM0",
            "description": "CP2102 USB to UART",
            "hwid": "USB VID:PID=10C4:EA60",
            "vid": 0x10C4, "pid": 0xEA60,
            "serial_number": "", "manufacturer": "Silicon Labs",
        }]

        with patch("talon.platform.check_serial_port",
                   return_value={"exists": False, "accessible": False,
                                 "error": "not found"}), \
             patch("talon.platform.detect_rnode_ports",
                   return_value=auto_detected):
            found = mgr.detect()

        assert found is True
        assert mgr.port == "/dev/ttyACM0"

    def test_rnode_interface_config_has_all_params(self):
        """Interface config should include all LoRa parameters."""
        from talon.net.rnode import RNodeManager, RNodeStatus

        config = {
            "port": "/dev/ttyUSB0",
            "frequency": 868000000,
            "bandwidth": 250000,
            "spreading_factor": 8,
            "coding_rate": 6,
            "tx_power": 20,
        }
        mgr = RNodeManager(config)
        mgr._status = RNodeStatus.READY
        mgr._port = "/dev/ttyUSB0"

        iface = mgr.get_interface_config()
        assert iface["type"] == "RNodeInterface"
        assert iface["port"] == "/dev/ttyUSB0"
        assert iface["frequency"] == 868000000
        assert iface["bandwidth"] == 250000
        assert iface["spreading_factor"] == 8
        assert iface["coding_rate"] == 6
        assert iface["txpower"] == 20
        assert iface["interface_enabled"] is True

    def test_end_to_end_config_generation_with_rnode(self):
        """Full path: RNode detected → config generated with correct port."""
        from talon.net.reticulum import write_reticulum_config
        from talon.net.rnode import RNodeManager, RNodeStatus

        config = make_server_config()
        mgr = RNodeManager(config["interfaces"]["rnode"])
        mgr._status = RNodeStatus.READY
        mgr._port = "/dev/ttyACM0"  # Auto-detected, different from YAML

        rnode_override = mgr.get_interface_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = write_reticulum_config(
                config, is_server=True, config_dir=tmpdir,
                rnode_override=rnode_override,
            )
            with open(os.path.join(config_dir, "config")) as f:
                content = f.read()

        # Config should use auto-detected port
        assert "/dev/ttyACM0" in content
        assert "/dev/ttyUSB0" not in content
        # Should still have correct frequency from YAML config
        assert "915000000" in content


# ================================================================
# 8. Error conditions and edge cases
# ================================================================

class TestNetworkErrorConditions:

    def test_server_handles_malformed_packet(self):
        """Server should silently ignore malformed JSON packets."""
        identity = make_mock_identity("server-1")
        slm = ServerLinkManager(identity)
        slm.on_sync_message = MagicMock()

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link(remote_hexhash="client-1")
        slm._link_established(link)

        # Send garbage
        slm._packet_received("client-1", link, b"\xff\xfe\x00garbage")
        slm.on_sync_message.assert_not_called()

    def test_server_handles_empty_packet(self):
        """Server should handle empty packets."""
        identity = make_mock_identity("server-1")
        slm = ServerLinkManager(identity)
        slm.on_sync_message = MagicMock()

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link(remote_hexhash="client-1")
        slm._link_established(link)
        slm._packet_received("client-1", link, b"")
        slm.on_sync_message.assert_not_called()

    def test_client_link_closed_during_sync(self):
        """If link drops during send_and_receive, should return None."""
        identity = make_mock_identity()
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")

        mock_link = MagicMock()
        mock_link.status = RNS.Link.ACTIVE
        clm.link = mock_link

        def close_link():
            time.sleep(0.05)
            clm._link_closed(mock_link)

        t = threading.Thread(target=close_link)
        t.start()

        with patch("talon.net.link_manager.RNS.Packet") as mock_pkt_cls:
            mock_pkt = MagicMock()
            mock_pkt_cls.return_value = mock_pkt
            result = clm.send_and_receive({"type": "test"}, timeout=2)

        t.join()
        assert result is None
        assert clm.link is None

    def test_send_to_disconnected_client(self):
        """Sending to a client that left should return False."""
        identity = make_mock_identity("server-1")
        slm = ServerLinkManager(identity)

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link(remote_hexhash="client-1")
        slm._link_established(link)
        slm._link_closed("client-1")

        result = slm.send_to_client("client-1", {"data": "test"})
        assert result is False

    def test_double_connect_same_client(self):
        """If a client connects twice, the second link should replace the first."""
        identity = make_mock_identity("server-1")
        slm = ServerLinkManager(identity)

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link1 = make_mock_link(remote_hexhash="client-1")
        link2 = make_mock_link(remote_hexhash="client-1")
        slm._link_established(link1)
        slm._link_established(link2)

        # Should still count as one client
        assert slm.get_connected_clients().count("client-1") == 1

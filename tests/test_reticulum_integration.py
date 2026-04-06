# tests/test_reticulum_integration.py
# Tests for the Reticulum integration layer:
#   - ServerLinkManager / ClientLinkManager lifecycle
#   - ConnectionManager wiring (send_message, heartbeat, reconnect)
#   - TalonServer / TalonClient app wiring
#
# These tests mock the RNS objects (Identity, Destination, Link, Packet)
# so no real network or hardware is needed.

import sys
import os
import json
import time
import threading
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import RNS
from talon.net.link_manager import ServerLinkManager, ClientLinkManager
from talon.net.transport import TransportManager
from talon.constants import TransportType


# ================================================================
# Helpers
# ================================================================

def make_mock_identity(hexhash="abc123"):
    """Create a mock RNS.Identity."""
    identity = MagicMock(spec=RNS.Identity)
    identity.hexhash = hexhash
    return identity


def make_mock_link(status=RNS.Link.ACTIVE, remote_hexhash="client-1"):
    """Create a mock RNS.Link with configurable status."""
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
    """Create a mock RNS.Destination."""
    dest = MagicMock()
    dest.hash = b"\x01\x02\x03\x04"
    dest.set_link_established_callback = MagicMock()
    dest.announce = MagicMock()
    return dest


# ================================================================
# ServerLinkManager
# ================================================================

class TestServerLinkManager:

    def test_start_creates_destination_and_announces(self):
        identity = make_mock_identity()
        slm = ServerLinkManager(identity)

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()) as mock_dest_cls:
            slm.start()

        assert slm.destination is not None
        slm.destination.set_link_established_callback.assert_called_once()
        slm.destination.announce.assert_called_once()

    def test_get_destination_hash(self):
        identity = make_mock_identity()
        slm = ServerLinkManager(identity)

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        assert slm.get_destination_hash() == b"\x01\x02\x03\x04"

    def test_get_destination_hash_before_start(self):
        slm = ServerLinkManager(make_mock_identity())
        assert slm.get_destination_hash() is None

    def test_link_established_tracks_client(self):
        identity = make_mock_identity()
        slm = ServerLinkManager(identity)
        connected_calls = []
        slm.on_client_connected = lambda h, l: connected_calls.append(h)

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link(remote_hexhash="client-abc")
        slm._link_established(link)

        assert "client-abc" in slm.get_connected_clients()
        assert connected_calls == ["client-abc"]

    def test_link_closed_removes_client(self):
        identity = make_mock_identity()
        slm = ServerLinkManager(identity)
        disconnected_calls = []
        slm.on_client_disconnected = lambda h: disconnected_calls.append(h)

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link(remote_hexhash="client-abc")
        slm._link_established(link)
        assert "client-abc" in slm.get_connected_clients()

        slm._link_closed("client-abc")
        assert "client-abc" not in slm.get_connected_clients()
        assert disconnected_calls == ["client-abc"]

    def test_packet_received_dispatches_sync(self):
        identity = make_mock_identity()
        slm = ServerLinkManager(identity)

        responses = []
        def on_sync(client_hash, message):
            responses.append((client_hash, message))
            return {"type": "sync_response", "updates": {}}

        slm.on_sync_message = on_sync

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link(remote_hexhash="client-1")
        slm._link_established(link)

        msg = {"type": "sync_request", "versions": {}}
        raw = json.dumps(msg).encode("utf-8")

        with patch("talon.net.link_manager.RNS.Packet") as mock_packet_cls:
            mock_pkt = MagicMock()
            mock_packet_cls.return_value = mock_pkt
            slm._packet_received("client-1", link, raw)

        assert len(responses) == 1
        assert responses[0][0] == "client-1"
        assert responses[0][1]["type"] == "sync_request"
        mock_pkt.send.assert_called_once()

    def test_packet_received_dispatches_heartbeat(self):
        identity = make_mock_identity()
        slm = ServerLinkManager(identity)

        heartbeats = []
        slm.on_heartbeat = lambda h, p: heartbeats.append((h, p))

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link(remote_hexhash="client-1")
        slm._link_established(link)

        msg = {"type": "heartbeat", "timestamp": 12345}
        raw = json.dumps(msg).encode("utf-8")
        slm._packet_received("client-1", link, raw)

        assert len(heartbeats) == 1
        assert heartbeats[0][1]["timestamp"] == 12345

    def test_packet_received_ignores_invalid_json(self):
        identity = make_mock_identity()
        slm = ServerLinkManager(identity)
        slm.on_sync_message = MagicMock()

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link()
        slm._link_established(link)
        slm._packet_received("client-1", link, b"not json{{{")

        slm.on_sync_message.assert_not_called()

    def test_send_to_client(self):
        identity = make_mock_identity()
        slm = ServerLinkManager(identity)

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link(remote_hexhash="client-1")
        slm._link_established(link)

        with patch("talon.net.link_manager.RNS.Packet") as mock_packet_cls:
            mock_pkt = MagicMock()
            mock_packet_cls.return_value = mock_pkt
            result = slm.send_to_client("client-1", {"type": "data_changed"})

        assert result is True
        mock_pkt.send.assert_called_once()

    def test_send_to_unknown_client(self):
        slm = ServerLinkManager(make_mock_identity())
        result = slm.send_to_client("unknown", {"data": 1})
        assert result is False

    def test_stop_tears_down_links(self):
        identity = make_mock_identity()
        slm = ServerLinkManager(identity)

        with patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()):
            slm.start()

        link = make_mock_link(remote_hexhash="client-1")
        slm._link_established(link)

        slm.stop()
        assert slm.destination is None
        link.teardown.assert_called_once()
        assert slm.get_connected_clients() == []


# ================================================================
# ClientLinkManager
# ================================================================

class TestClientLinkManager:

    def test_connect_success(self):
        identity = make_mock_identity("my-client")
        server_hash = b"\x01\x02\x03\x04"
        clm = ClientLinkManager(identity, server_hash)

        mock_server_identity = make_mock_identity("server-1")
        mock_dest = make_mock_destination()

        # Create a link that is ACTIVE
        mock_link = MagicMock()
        mock_link.status = RNS.Link.ACTIVE
        mock_link.set_packet_callback = MagicMock()
        mock_link.set_link_closed_callback = MagicMock()

        connected_calls = []
        clm.on_connected = lambda: connected_calls.append(True)

        # Patch RNS.Link as a callable that returns our mock,
        # but preserve ACTIVE/CLOSED constants on the mock class
        mock_link_cls = MagicMock(return_value=mock_link)
        mock_link_cls.ACTIVE = RNS.Link.ACTIVE
        mock_link_cls.CLOSED = RNS.Link.CLOSED

        with patch("talon.net.link_manager.RNS.Identity") as mock_id_cls, \
             patch("talon.net.link_manager.RNS.Destination",
                   return_value=mock_dest), \
             patch("talon.net.link_manager.RNS.Link", mock_link_cls), \
             patch("talon.net.link_manager.RNS.Transport"):
            mock_id_cls.recall = MagicMock(return_value=mock_server_identity)
            result = clm.connect(timeout=1)

        assert result is True
        assert clm.is_active() is True
        assert connected_calls == [True]

    def test_connect_no_identity(self):
        identity = make_mock_identity("my-client")
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")

        with patch("talon.net.link_manager.RNS.Identity") as mock_id_cls, \
             patch("talon.net.link_manager.RNS.Transport") as mock_transport:
            mock_id_cls.recall = MagicMock(return_value=None)
            result = clm.connect(timeout=0.5)

        assert result is False
        assert clm.is_active() is False

    def test_connect_link_closed(self):
        identity = make_mock_identity("my-client")
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")

        mock_server_identity = make_mock_identity("server-1")
        mock_link = MagicMock()
        mock_link.status = RNS.Link.CLOSED

        mock_link_cls = MagicMock(return_value=mock_link)
        mock_link_cls.ACTIVE = RNS.Link.ACTIVE
        mock_link_cls.CLOSED = RNS.Link.CLOSED

        with patch("talon.net.link_manager.RNS.Identity") as mock_id_cls, \
             patch("talon.net.link_manager.RNS.Destination",
                   return_value=make_mock_destination()), \
             patch("talon.net.link_manager.RNS.Link", mock_link_cls), \
             patch("talon.net.link_manager.RNS.Transport"):
            mock_id_cls.recall = MagicMock(return_value=mock_server_identity)
            result = clm.connect(timeout=1)

        assert result is False
        assert clm.link is None

    def test_disconnect(self):
        identity = make_mock_identity()
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")
        mock_link = MagicMock()
        mock_link.status = RNS.Link.ACTIVE
        clm.link = mock_link

        clm.disconnect()

        mock_link.teardown.assert_called_once()
        assert clm.link is None

    def test_send_and_receive(self):
        identity = make_mock_identity()
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")

        mock_link = MagicMock()
        mock_link.status = RNS.Link.ACTIVE
        clm.link = mock_link

        # Simulate server responding in a separate thread
        def simulate_response():
            time.sleep(0.05)
            resp = {"type": "sync_response", "updates": {"sitreps": []}}
            clm._packet_received(json.dumps(resp).encode("utf-8"))

        t = threading.Thread(target=simulate_response)
        t.start()

        with patch("talon.net.link_manager.RNS.Packet") as mock_packet_cls:
            mock_pkt = MagicMock()
            mock_packet_cls.return_value = mock_pkt
            result = clm.send_and_receive(
                {"type": "sync_request", "versions": {}}, timeout=2
            )

        t.join()
        assert result is not None
        assert result["type"] == "sync_response"
        mock_pkt.send.assert_called_once()

    def test_send_and_receive_timeout(self):
        identity = make_mock_identity()
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")

        mock_link = MagicMock()
        mock_link.status = RNS.Link.ACTIVE
        clm.link = mock_link

        with patch("talon.net.link_manager.RNS.Packet") as mock_packet_cls:
            mock_pkt = MagicMock()
            mock_packet_cls.return_value = mock_pkt
            result = clm.send_and_receive({"type": "test"}, timeout=0.1)

        assert result is None

    def test_send_and_receive_not_connected(self):
        identity = make_mock_identity()
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")
        result = clm.send_and_receive({"type": "test"})
        assert result is None

    def test_send_heartbeat(self):
        identity = make_mock_identity()
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")

        mock_link = MagicMock()
        mock_link.status = RNS.Link.ACTIVE
        clm.link = mock_link

        with patch("talon.net.link_manager.RNS.Packet") as mock_packet_cls:
            mock_pkt = MagicMock()
            mock_packet_cls.return_value = mock_pkt
            clm.send_heartbeat({"timestamp": 999})

        mock_pkt.send.assert_called_once()
        # Verify the payload includes type=heartbeat
        sent_bytes = mock_packet_cls.call_args[0][1]
        sent = json.loads(sent_bytes.decode("utf-8"))
        assert sent["type"] == "heartbeat"
        assert sent["timestamp"] == 999

    def test_send_heartbeat_not_connected(self):
        identity = make_mock_identity()
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")
        # Should not raise
        clm.send_heartbeat({"timestamp": 999})

    def test_link_closed_callback(self):
        identity = make_mock_identity()
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")

        disconnected = []
        clm.on_disconnected = lambda: disconnected.append(True)

        mock_link = MagicMock()
        mock_link.status = RNS.Link.ACTIVE
        clm.link = mock_link

        clm._link_closed(mock_link)

        assert clm.link is None
        assert disconnected == [True]

    def test_link_closed_unblocks_send_and_receive(self):
        identity = make_mock_identity()
        clm = ClientLinkManager(identity, b"\x01\x02\x03\x04")

        mock_link = MagicMock()
        mock_link.status = RNS.Link.ACTIVE
        clm.link = mock_link

        result_holder = [None]

        def do_send():
            with patch("talon.net.link_manager.RNS.Packet") as mock_packet_cls:
                mock_pkt = MagicMock()
                mock_packet_cls.return_value = mock_pkt
                result_holder[0] = clm.send_and_receive(
                    {"type": "test"}, timeout=5
                )

        t = threading.Thread(target=do_send)
        t.start()

        time.sleep(0.05)
        clm._link_closed(mock_link)
        t.join(timeout=2)

        # Should have unblocked with None (no actual response)
        assert result_holder[0] is None


# ================================================================
# ConnectionManager
# ================================================================

class TestConnectionManager:

    def test_send_message_delegates_to_link_manager(self):
        from talon.client.connection import ConnectionManager

        cm = ConnectionManager(config={})
        cm.link_manager = MagicMock()
        cm.link_manager.is_active.return_value = True
        cm.link_manager.send_and_receive.return_value = {"ok": True}

        result = cm.send_message({"type": "sync_request"})
        assert result == {"ok": True}
        cm.link_manager.send_and_receive.assert_called_once_with(
            {"type": "sync_request"}
        )

    def test_send_message_returns_none_when_no_link(self):
        from talon.client.connection import ConnectionManager

        cm = ConnectionManager(config={})
        result = cm.send_message({"type": "test"})
        assert result is None

    def test_try_connect_creates_link_manager(self):
        from talon.client.connection import ConnectionManager

        config = {"server_destination_hash": "01020304"}
        identity = make_mock_identity()
        cm = ConnectionManager(config=config, identity=identity)

        mock_clm = MagicMock()
        mock_clm.connect.return_value = True

        with patch("talon.client.connection.ClientLinkManager",
                   return_value=mock_clm):
            result = cm._try_connect(TransportType.YGGDRASIL, {})

        assert result is True
        assert cm.link_manager is mock_clm

    def test_try_connect_no_server_hash(self):
        from talon.client.connection import ConnectionManager

        cm = ConnectionManager(config={})
        result = cm._try_connect(TransportType.YGGDRASIL, {})
        assert result is False

    def test_disconnect_tears_down_link(self):
        from talon.client.connection import ConnectionManager

        cm = ConnectionManager(config={})
        mock_lm = MagicMock()
        cm.link_manager = mock_lm
        cm.is_connected = True
        cm.current_transport = TransportType.YGGDRASIL

        disconnected = []
        cm.on_disconnected = lambda: disconnected.append(True)

        cm.disconnect()

        mock_lm.disconnect.assert_called_once()
        assert cm.is_connected is False
        assert cm.link_manager is None
        assert disconnected == [True]

    def test_on_link_lost_callback(self):
        from talon.client.connection import ConnectionManager

        cm = ConnectionManager(config={})
        cm.is_connected = True
        cm.current_transport = TransportType.TCP
        cm.link_manager = MagicMock()

        disconnected = []
        cm.on_disconnected = lambda: disconnected.append(True)

        cm._on_link_lost()

        assert cm.is_connected is False
        assert cm.link_manager is None
        assert disconnected == [True]

    def test_is_broadband(self):
        from talon.client.connection import ConnectionManager

        cm = ConnectionManager(config={})
        cm.is_connected = True
        cm.current_transport = TransportType.YGGDRASIL
        cm.transport.set_available(TransportType.YGGDRASIL, True)
        assert cm.is_broadband() is True

    def test_send_heartbeat_via_link_manager(self):
        from talon.client.connection import ConnectionManager

        cm = ConnectionManager(config={})
        cm.link_manager = MagicMock()
        cm.link_manager.is_active.return_value = True

        cm._send_heartbeat({"timestamp": 42})
        cm.link_manager.send_heartbeat.assert_called_once_with(
            {"timestamp": 42}
        )

    def test_send_heartbeat_default_payload(self):
        from talon.client.connection import ConnectionManager

        cm = ConnectionManager(config={})
        cm.link_manager = MagicMock()
        cm.link_manager.is_active.return_value = True

        cm._send_heartbeat()
        payload = cm.link_manager.send_heartbeat.call_args[0][0]
        assert "timestamp" in payload


# ================================================================
# Server app wiring
# ================================================================

class TestServerAppWiring:

    def _make_server(self):
        """Create a TalonServer with mocked dependencies."""
        with patch("talon.server.app.initialize_reticulum"), \
             patch("talon.server.app.create_identity",
                   return_value=make_mock_identity("server-id")), \
             patch("talon.server.app.ServerLinkManager") as mock_slm_cls, \
             patch("talon.server.app.HeartbeatMonitor"), \
             patch("talon.server.app.TileServer"):

            from talon.server.app import TalonServer
            server = TalonServer.__new__(TalonServer)
            server.config = {}
            server.db = MagicMock()
            server.reticulum = MagicMock()
            server.identity = make_mock_identity("server-id")
            server.client_registry = MagicMock()

            mock_slm = MagicMock()
            mock_slm_cls.return_value = mock_slm

            server.link_manager = None
            server.sync_engine = None
            server.tile_server = None
            server.heartbeat_monitor = MagicMock()
            server.running = False

            return server

    def test_on_sync_message_routes_to_engine(self):
        server = self._make_server()
        server.sync_engine = MagicMock()
        server.sync_engine.handle_message.return_value = {
            "type": "sync_response"
        }
        server.client_registry.get_client.return_value = None

        from talon.server.app import TalonServer
        result = TalonServer._on_sync_message(
            server, "client-1", {"type": "sync_request", "versions": {}}
        )

        server.sync_engine.handle_message.assert_called_once()
        assert result["type"] == "sync_response"

    def test_on_heartbeat_updates_monitor(self):
        server = self._make_server()
        server.heartbeat_monitor = MagicMock()
        server.client_registry = MagicMock()

        from talon.server.app import TalonServer
        TalonServer._on_heartbeat(
            server, "client-1",
            {"type": "heartbeat", "callsign": "WOLF-1", "timestamp": 42}
        )

        server.heartbeat_monitor.record_heartbeat.assert_called_once_with(
            "WOLF-1", {"type": "heartbeat", "callsign": "WOLF-1",
                       "timestamp": 42}
        )
        server.client_registry.update_heartbeat.assert_called_once_with(
            "client-1"
        )

    def test_on_client_link_registers(self):
        server = self._make_server()
        server.sync_engine = MagicMock()
        server.client_registry.get_client.return_value = {
            "callsign": "WOLF-1"
        }

        from talon.server.app import TalonServer
        TalonServer._on_client_link(server, "client-1", MagicMock())

        server.sync_engine.register_client.assert_called_once_with(
            "client-1", "WOLF-1", "reticulum"
        )

    def test_on_client_unlink_unregisters(self):
        server = self._make_server()
        server.sync_engine = MagicMock()

        from talon.server.app import TalonServer
        TalonServer._on_client_unlink(server, "client-1")

        server.sync_engine.unregister_client.assert_called_once_with(
            "client-1"
        )

    def test_on_data_changed_notifies_other_clients(self):
        server = self._make_server()
        server.link_manager = MagicMock()
        server.link_manager.get_connected_clients.return_value = [
            "client-1", "client-2", "client-3"
        ]

        from talon.server.app import TalonServer
        TalonServer._on_data_changed(
            server, "client-1", {"sitreps": [{"id": "s1"}]}
        )

        # Should notify client-2 and client-3 but NOT client-1
        calls = server.link_manager.send_to_client.call_args_list
        notified = [c[0][0] for c in calls]
        assert "client-1" not in notified
        assert "client-2" in notified
        assert "client-3" in notified

    def test_shutdown_stops_link_manager(self):
        server = self._make_server()
        server.link_manager = MagicMock()
        server.running = True

        with patch("talon.server.app.log_event"):
            from talon.server.app import TalonServer
            TalonServer.shutdown(server)

        server.link_manager.stop.assert_called_once()
        assert server.running is False


# ================================================================
# Client app wiring
# ================================================================

class TestClientAppWiring:

    def test_trigger_sync_calls_full_sync(self):
        from talon.client.app import TalonClient

        client = TalonClient.__new__(TalonClient)
        client.sync = MagicMock()
        client.sync.is_syncing = False
        client.connection = MagicMock()
        client._sync_thread = None

        client._trigger_sync()

        # Wait for the background thread
        if client._sync_thread:
            client._sync_thread.join(timeout=2)

        client.sync.full_sync.assert_called_once_with(
            client.connection.send_message
        )

    def test_trigger_sync_skips_when_already_syncing(self):
        from talon.client.app import TalonClient

        client = TalonClient.__new__(TalonClient)
        client.sync = MagicMock()
        client.sync.is_syncing = True
        client._sync_thread = None

        client._trigger_sync()

        client.sync.full_sync.assert_not_called()

    def test_on_connected_triggers_sync(self):
        from talon.client.app import TalonClient

        client = TalonClient.__new__(TalonClient)
        client.sync = MagicMock()
        client.sync.is_syncing = False
        client.connection = MagicMock()
        client.is_online = False
        client._sync_thread = None

        client._on_connected(TransportType.YGGDRASIL)

        assert client.is_online is True
        # Wait for sync thread
        if client._sync_thread:
            client._sync_thread.join(timeout=2)
        client.sync.full_sync.assert_called_once()

    def test_on_disconnected_sets_offline(self):
        from talon.client.app import TalonClient

        client = TalonClient.__new__(TalonClient)
        client.is_online = True

        client._on_disconnected()

        assert client.is_online is False

    def test_trigger_sync_public_api(self):
        from talon.client.app import TalonClient

        client = TalonClient.__new__(TalonClient)
        client.sync = MagicMock()
        client.sync.is_syncing = False
        client.connection = MagicMock()
        client.is_online = True
        client._sync_thread = None

        client.trigger_sync()

        if client._sync_thread:
            client._sync_thread.join(timeout=2)
        client.sync.full_sync.assert_called_once()

    def test_trigger_sync_public_api_offline(self):
        from talon.client.app import TalonClient

        client = TalonClient.__new__(TalonClient)
        client.sync = MagicMock()
        client.is_online = False

        client.trigger_sync()

        client.sync.full_sync.assert_not_called()

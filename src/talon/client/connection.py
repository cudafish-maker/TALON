# talon/client/connection.py
# Client connection manager.
#
# Detects available transports and maintains the connection to the
# server. The client is online-first: it always tries to connect
# to the server and only falls back to cached data when no uplink
# is available.
#
# Connection priority (same as transport.py):
#   1. Yggdrasil (fastest, most reliable overlay)
#   2. I2P (good privacy, slower)
#   3. TCP (fast but exposes IP — only if enabled)
#   4. RNode / LoRa (last resort, low bandwidth)
#
# When connected, the client sends heartbeats at the configured
# interval so the server knows we're alive.

import time

from talon.net.heartbeat import HeartbeatSender
from talon.net.link_manager import ClientLinkManager
from talon.net.transport import TransportManager


class ConnectionManager:
    """Manages the client's connection to the server.

    Attributes:
        transport: The TransportManager for selecting transports.
        heartbeat: The HeartbeatSender for keepalives.
        is_connected: Whether we currently have a server link.
        current_transport: Which transport is active (or None).
        link_manager: The ClientLinkManager for the active RNS link.
        on_connected: Callback when connection is established.
        on_disconnected: Callback when connection is lost.
    """

    def __init__(self, config: dict, identity=None, on_connected=None, on_disconnected=None):
        self.config = config
        self.identity = identity
        self.transport = TransportManager()
        self.heartbeat = None
        self.link_manager = None
        self.is_connected = False
        self.current_transport = None
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        self.on_lease_renewal = None
        self.on_data_changed = None
        self._last_attempt = 0

    def detect_transports(self):
        """Probe which transports are available.

        Checks each configured transport to see if the server is
        reachable through it. Updates the transport manager with
        the results.
        """
        from talon.constants import TransportType

        interfaces = self.config.get("interfaces", {})

        # Map config names to TransportType enum values
        name_to_type = {
            "yggdrasil": TransportType.YGGDRASIL,
            "i2p": TransportType.I2P,
            "tcp": TransportType.TCP,
            "rnode": TransportType.RNODE,
        }

        for name, iface_config in interfaces.items():
            if not iface_config.get("enabled", True):
                continue
            transport_type = name_to_type.get(name.lower())
            if transport_type:
                self.transport.set_available(transport_type, True)

    def connect(self) -> bool:
        """Attempt to connect to the server.

        Tries transports in priority order until one works.

        Returns:
            True if a connection was established.
        """
        self._last_attempt = time.time()

        # Get available transports (already sorted by priority internally)
        available = self.transport.get_all_available()

        for transport_type in available:
            success = self._try_connect(transport_type, {})
            if success:
                self.is_connected = True
                self.current_transport = transport_type
                self._start_heartbeat()
                if self.on_connected:
                    self.on_connected(transport_type)
                return True

        return False

    def disconnect(self):
        """Disconnect from the server."""
        if self.heartbeat:
            self.heartbeat.stop()
            self.heartbeat = None
        if self.link_manager:
            self.link_manager.disconnect()
            self.link_manager = None
        self.is_connected = False
        self.current_transport = None
        if self.on_disconnected:
            self.on_disconnected()

    def is_broadband(self) -> bool:
        """Check if the current connection is broadband (not LoRa).

        Returns:
            True if connected via Yggdrasil, I2P, or TCP.
            False if connected via RNode or not connected.
        """
        if not self.is_connected or not self.current_transport:
            return False
        return self.transport.is_broadband()

    def reconnect(self) -> bool:
        """Try to reconnect after a disconnection.

        Returns:
            True if reconnection succeeded.
        """
        self.disconnect()
        return self.connect()

    def send_message(self, message: dict) -> dict:
        """Send a message to the server and wait for the response.

        This is the send_fn bridge for SyncClient.full_sync().

        Args:
            message: The message dict to send.

        Returns:
            The server's response dict, or None on failure.
        """
        if not self.link_manager or not self.link_manager.is_active():
            return None
        return self.link_manager.send_and_receive(message)

    def _try_connect(self, transport_name, config: dict) -> bool:
        """Attempt a connection over a specific transport.

        Creates a ClientLinkManager and tries to establish an
        RNS link to the server.

        Args:
            transport_name: Which transport to use.
            config: Transport configuration dict.

        Returns:
            True if the connection was established.
        """
        server_hash = self.config.get("server_destination_hash")
        if not server_hash:
            return False

        if isinstance(server_hash, str):
            server_hash = bytes.fromhex(server_hash)

        self.link_manager = ClientLinkManager(
            identity=self.identity,
            server_dest_hash=server_hash,
        )
        self.link_manager.on_disconnected = self._on_link_lost
        self.link_manager.on_push_message = self._on_push_message

        return self.link_manager.connect()

    def _start_heartbeat(self):
        """Start sending heartbeats to the server."""
        heartbeat_config = self.config.get("heartbeat", {})

        self.heartbeat = HeartbeatSender(
            broadband_interval=heartbeat_config.get("broadband_interval", 60),
            lora_interval=heartbeat_config.get("lora_interval", 120),
        )
        self.heartbeat.send_callback = self._send_heartbeat
        self.heartbeat.is_broadband_callback = self.is_broadband
        self.heartbeat.start()

    def _send_heartbeat(self, payload=None):
        """Send a heartbeat packet to the server.

        Args:
            payload: Optional heartbeat payload dict. If None, sends
                     a minimal heartbeat with just a timestamp.
        """
        if not self.link_manager or not self.link_manager.is_active():
            return
        if payload is None:
            payload = {"timestamp": time.time()}
        self.link_manager.send_heartbeat(payload)

    def _on_push_message(self, message: dict):
        """Handle a server-pushed message (not a response to our request).

        Currently handles:
        - lease_renewal: server approved re-auth, save new lease
        - data_changed: another client pushed data, trigger sync
        """
        msg_type = message.get("type", "")
        if msg_type == "lease_renewal":
            if self.on_lease_renewal:
                self.on_lease_renewal(message)
        elif msg_type == "data_changed":
            if self.on_data_changed:
                self.on_data_changed(message)

    def _on_link_lost(self):
        """Called when the RNS link drops unexpectedly."""
        self.is_connected = False
        self.current_transport = None
        self.link_manager = None
        if self.on_disconnected:
            self.on_disconnected()

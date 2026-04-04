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
from talon.net.transport import TransportManager
from talon.net.heartbeat import HeartbeatSender


class ConnectionManager:
    """Manages the client's connection to the server.

    Attributes:
        transport: The TransportManager for selecting transports.
        heartbeat: The HeartbeatSender for keepalives.
        is_connected: Whether we currently have a server link.
        current_transport: Which transport is active (or None).
        on_connected: Callback when connection is established.
        on_disconnected: Callback when connection is lost.
    """

    def __init__(self, config: dict, on_connected=None, on_disconnected=None):
        self.config = config
        self.transport = TransportManager()
        self.heartbeat = None
        self.is_connected = False
        self.current_transport = None
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
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
            # Attempt connection over this transport
            # (Actual Reticulum link establishment will be implemented
            # when we wire up the network layer)
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

    def _try_connect(self, transport_name: str, config: dict) -> bool:
        """Attempt a connection over a specific transport.

        Args:
            transport_name: Which transport to use.
            config: Transport configuration dict.

        Returns:
            True if the connection was established.
        """
        # Placeholder — actual Reticulum link will go here
        # For now, return False (no real network yet)
        return False

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

    def _send_heartbeat(self):
        """Send a heartbeat packet to the server."""
        # Placeholder — will send over Reticulum link
        pass

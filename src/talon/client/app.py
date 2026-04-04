# talon/client/app.py
# Main client application entry point.
#
# This is the top-level orchestrator that wires together all client
# components: Reticulum networking, local cache, sync, notifications,
# and the operator's UI.
#
# Startup sequence:
#   1. Load config (client.yaml merged with default.yaml)
#   2. Prompt for passphrase
#   3. Open local encrypted cache
#   4. Check lease status (enrolled? expired? revoked?)
#   5. Initialize Reticulum (as transport node if RNode present)
#   6. Attempt server connection (online-first)
#   7. If connected: sync immediately, start heartbeat
#   8. If not connected: load cached data, show offline indicator
#   9. Launch the operator UI (Kivy)

import os
import yaml

from talon.client.auth import ClientAuth
from talon.client.cache import ClientCache
from talon.client.sync_client import SyncClient
from talon.client.connection import ConnectionManager
from talon.client.notifications import NotificationHandler
from talon.net.reticulum import initialize_reticulum, create_identity


class TalonClient:
    """Main client application.

    This class owns all client-side resources and coordinates startup,
    shutdown, and the main event loop.
    """

    def __init__(self, config_path: str = None):
        self.config = {}
        self.config_path = config_path
        self.auth = None
        self.cache = None
        self.sync = None
        self.connection = None
        self.notifications = None
        self.reticulum = None
        self.identity = None
        self.running = False
        self.is_online = False

    def load_config(self):
        """Load and merge configuration files.

        Loads default.yaml first, then overlays client.yaml on top.
        """
        config_dir = self.config_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "config"
        )

        # Load defaults
        default_path = os.path.join(config_dir, "default.yaml")
        if os.path.isfile(default_path):
            with open(default_path, "r") as f:
                self.config = yaml.safe_load(f) or {}

        # Overlay client-specific config
        client_path = os.path.join(config_dir, "client.yaml")
        if os.path.isfile(client_path):
            with open(client_path, "r") as f:
                client_config = yaml.safe_load(f) or {}
            self.config.update(client_config)

    def setup_auth(self, data_dir: str):
        """Initialize authentication and check lease.

        Args:
            data_dir: Path to the client's data directory.
        """
        self.auth = ClientAuth(data_dir)
        self.auth.load_lease()

    def setup_cache(self, data_dir: str, passphrase: str):
        """Open the local encrypted data cache.

        Args:
            data_dir: Path to the client's data directory.
            passphrase: The operator's passphrase.
        """
        self.cache = ClientCache(data_dir)
        self.cache.open(passphrase)

    def setup_network(self):
        """Initialize Reticulum.

        The client runs as a transport node if an RNode is connected.
        This enables mesh relay — other RNodes out of server range can
        route through us to reach the server.
        """
        net_config = self.config.get("reticulum", {})
        self.reticulum = initialize_reticulum(
            config_path=net_config.get("config_path")
        )
        self.identity = create_identity(
            identity_path=net_config.get("identity_path")
        )

    def setup_services(self):
        """Start sync, connection manager, and notification handler."""
        # Connection manager
        self.connection = ConnectionManager(
            config=self.config,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
        )

        # Sync client
        self.sync = SyncClient(
            cache=self.cache,
            on_sync_complete=self._on_sync_complete,
            on_sync_error=self._on_sync_error,
        )

        # Notification handler (audio OFF by default — opt-in only)
        notif_config = self.config.get("notifications", {})
        self.notifications = NotificationHandler(
            settings={
                "audio_enabled": notif_config.get("audio_enabled", False),
                "audio_threshold": notif_config.get("audio_threshold", "FLASH"),
                "lock_screen": notif_config.get("lock_screen", False),
                "visual_threshold": notif_config.get("visual_threshold", "ROUTINE"),
            },
        )

    def start(self, passphrase: str, data_dir: str = None):
        """Full startup sequence.

        Args:
            passphrase: The operator's passphrase.
            data_dir: Path to store local data (default: from config).
        """
        self.load_config()

        if not data_dir:
            data_dir = self.config.get("database", {}).get(
                "path", "data/client"
            )
            # Use the directory containing the database file
            data_dir = os.path.dirname(data_dir) or "data"

        self.setup_auth(data_dir)
        self.setup_cache(data_dir, passphrase)
        self.setup_network()
        self.setup_services()

        # Check lease before going online
        lease_status = self.auth.check_lease()
        if lease_status["locked"]:
            # Soft-locked — show lock screen, wait for server re-auth
            self.is_online = False
            self.running = True
            return

        # Try to connect to the server (online-first)
        self.connection.detect_transports()
        connected = self.connection.connect()

        if connected:
            self.is_online = True
            # Immediate sync on connect
            # (Actual sync call will happen via the Reticulum link)
        else:
            # No server available — fall back to cached data
            self.is_online = False

        self.running = True

    def shutdown(self):
        """Clean shutdown."""
        self.running = False
        if self.connection:
            self.connection.disconnect()
        if self.cache:
            self.cache.close()

    # ---------- Internal callbacks ----------

    def _on_connected(self, transport_name: str):
        """Called when a server connection is established."""
        self.is_online = True

    def _on_disconnected(self):
        """Called when the server connection is lost."""
        self.is_online = False

    def _on_sync_complete(self, result: dict):
        """Called after a successful sync."""
        pass

    def _on_sync_error(self, error: str):
        """Called when a sync attempt fails."""
        pass

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
from talon.net.rnode import RNodeManager


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
        self.rnode_manager = None
        self.running = False
        self.is_online = False
        self._sync_thread = None

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

    def setup_rnode(self):
        """Detect and validate RNode hardware if configured.

        On Android, also handles USB OTG permission requests.
        Called before setup_network().
        """
        rnode_config = self.config.get("interfaces", {}).get("rnode", {})
        if not rnode_config.get("enabled"):
            return

        # On Android, check USB permission first
        from talon.platform import IS_ANDROID
        if IS_ANDROID:
            from talon.net.android_usb import (
                find_usb_serial_device, has_usb_permission,
                request_usb_permission,
            )
            usb_dev = find_usb_serial_device()
            if usb_dev and not has_usb_permission(usb_dev["device_name"]):
                request_usb_permission(usb_dev["device_name"])

        self.rnode_manager = RNodeManager(rnode_config)
        if self.rnode_manager.detect():
            self.rnode_manager.validate()

    def setup_network(self):
        """Initialize Reticulum.

        The client runs as a transport node if an RNode is connected.
        This enables mesh relay — other RNodes out of server range can
        route through us to reach the server.

        Generates a Reticulum config from T.A.L.O.N.'s YAML settings,
        including auto-detected RNode port if available.
        """
        net_config = self.config.get("reticulum", {})

        # Get RNode override from hardware detection
        rnode_override = None
        if self.rnode_manager and self.rnode_manager.status == "ready":
            rnode_override = self.rnode_manager.get_interface_config()

        self.reticulum = initialize_reticulum(
            config_path=net_config.get("config_path"),
            talon_config=self.config,
            is_server=False,
            rnode_override=rnode_override,
        )

        if self.rnode_manager and self.rnode_manager.status == "ready":
            self.rnode_manager.mark_in_use()

        self.identity = create_identity(
            identity_path=net_config.get("identity_path")
        )

    def setup_services(self):
        """Start sync, connection manager, and notification handler."""
        # Connection manager (pass identity for RNS link establishment)
        self.connection = ConnectionManager(
            config=self.config,
            identity=self.identity,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
        )
        self.connection.on_lease_renewal = self._on_lease_renewal
        self.connection.on_data_changed = lambda msg: self._trigger_sync()

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
        self.setup_rnode()
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
            self._trigger_sync()
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

    def trigger_sync(self):
        """Public API for forcing a sync (e.g., from UI button)."""
        if self.is_online:
            self._trigger_sync()

    # ---------- Internal callbacks ----------

    def _trigger_sync(self):
        """Run a full sync cycle in a background thread.

        Uses connection.send_message as the transport function —
        this sends over the active RNS link and waits for the
        server's response.
        """
        import threading

        if self.sync.is_syncing:
            return

        def _run():
            self.sync.full_sync(self.connection.send_message)

        self._sync_thread = threading.Thread(target=_run, daemon=True)
        self._sync_thread.start()

    def _on_lease_renewal(self, message: dict):
        """Called when the server pushes a new lease (re-auth approved)."""
        if self.auth and "lease" in message:
            self.auth.save_lease(message["lease"])

    def _on_connected(self, transport_name):
        """Called when a server connection is established."""
        self.is_online = True
        self._trigger_sync()

    def _on_disconnected(self):
        """Called when the server connection is lost."""
        self.is_online = False

    def _on_sync_complete(self, result: dict):
        """Called after a successful sync."""
        pass

    def _on_sync_error(self, error: str):
        """Called when a sync attempt fails."""
        pass

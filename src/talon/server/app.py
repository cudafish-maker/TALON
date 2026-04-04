# talon/server/app.py
# Main server application entry point.
#
# This is the top-level orchestrator that wires together all server
# components: Reticulum networking, database, sync engine, heartbeat
# monitor, tile server, audit logging, and the server operator's UI.
#
# Startup sequence:
#   1. Load config (server.yaml merged with default.yaml)
#   2. Derive database key from passphrase
#   3. Open encrypted database and run migrations
#   4. Initialize Reticulum as propagation + transport node
#   5. Start heartbeat monitor
#   6. Start sync engine
#   7. Launch the server UI (Kivy)

import os
import yaml

from talon.crypto.keys import derive_master_key, derive_subkey, generate_salt
from talon.db.database import open_database, initialize_tables
from talon.db.migrations import run_migrations
from talon.net.reticulum import initialize_reticulum, create_identity
from talon.net.heartbeat import HeartbeatMonitor
from talon.server.sync_engine import SyncEngine
from talon.server.tile_server import TileServer
from talon.server.client_registry import ClientRegistry
from talon.server.audit import log_event


class TalonServer:
    """Main server application.

    This class owns all server-side resources and coordinates startup,
    shutdown, and the main event loop.
    """

    def __init__(self, config_path: str = None):
        self.config = {}
        self.config_path = config_path
        self.db = None
        self.reticulum = None
        self.identity = None
        self.sync_engine = None
        self.tile_server = None
        self.heartbeat_monitor = None
        self.client_registry = ClientRegistry()
        self.running = False

    def load_config(self):
        """Load and merge configuration files.

        Loads default.yaml first, then overlays server.yaml on top.
        This means server.yaml only needs to contain overrides.
        """
        config_dir = self.config_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "config"
        )

        # Load defaults
        default_path = os.path.join(config_dir, "default.yaml")
        if os.path.isfile(default_path):
            with open(default_path, "r") as f:
                self.config = yaml.safe_load(f) or {}

        # Overlay server-specific config
        server_path = os.path.join(config_dir, "server.yaml")
        if os.path.isfile(server_path):
            with open(server_path, "r") as f:
                server_config = yaml.safe_load(f) or {}
            self.config.update(server_config)

    def setup_database(self, passphrase: str):
        """Initialize the encrypted database.

        Args:
            passphrase: The server operator's passphrase for deriving
                        the database encryption key.
        """
        db_config = self.config.get("database", {})
        db_path = db_config.get("path", "data/server.db")

        # Check if this is a fresh install (no existing salt)
        salt_path = db_path + ".salt"
        if os.path.isfile(salt_path):
            with open(salt_path, "rb") as f:
                salt = f.read()
        else:
            salt = generate_salt()
            os.makedirs(os.path.dirname(salt_path) or ".", exist_ok=True)
            with open(salt_path, "wb") as f:
                f.write(salt)

        # Derive the database encryption key from the passphrase
        master_key = derive_master_key(passphrase, salt)
        db_key = derive_subkey(master_key, "database")

        # Open the encrypted database
        self.db = open_database(db_path, db_key.hex())
        initialize_tables(self.db)
        run_migrations(self.db)

    def setup_network(self):
        """Initialize Reticulum as a propagation and transport node."""
        net_config = self.config.get("reticulum", {})
        self.reticulum = initialize_reticulum(
            config_path=net_config.get("config_path")
        )
        self.identity = create_identity(
            identity_path=net_config.get("identity_path")
        )

    def setup_services(self):
        """Start background services: sync, heartbeat, tile server."""
        # Sync engine
        self.sync_engine = SyncEngine(
            db=self.db,
            on_data_changed=self._on_data_changed,
        )

        # Tile server
        tile_config = self.config.get("tiles", {})
        cache_dir = tile_config.get("cache_dir", "data/tiles")
        self.tile_server = TileServer(cache_dir)

        # Heartbeat monitor
        heartbeat_config = self.config.get("heartbeat", {})
        self.heartbeat_monitor = HeartbeatMonitor(
            missed_threshold=heartbeat_config.get("missed_threshold", 3),
        )
        self.heartbeat_monitor.status_change_callback = self._on_client_stale

    def start(self, passphrase: str):
        """Full startup sequence.

        Args:
            passphrase: Server operator's passphrase.
        """
        self.load_config()
        self.setup_database(passphrase)
        self.setup_network()
        self.setup_services()
        self.running = True

        log_event("SERVER_STARTED", "SYSTEM",
                  details="T.A.L.O.N. server started")

    def shutdown(self):
        """Clean shutdown of all services."""
        self.running = False
        if self.heartbeat_monitor:
            self.heartbeat_monitor.stop()
        log_event("SERVER_STOPPED", "SYSTEM",
                  details="T.A.L.O.N. server stopped")

    # ---------- Internal callbacks ----------

    def _on_data_changed(self, source_client: str, changes: dict):
        """Called when a client pushes new data."""
        # Notify all other connected clients
        self.sync_engine.notify_clients(source_client, {
            "type": "data_changed",
            "tables": list(changes.keys()),
        })

    def _on_client_stale(self, callsign: str, status: str):
        """Called when a client's heartbeat status changes."""
        self.client_registry.mark_stale(callsign)
        log_event("CLIENT_STALE", "SYSTEM",
                  target=callsign, details="Missed heartbeat threshold")

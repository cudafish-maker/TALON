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
from talon.db.database import open_database
from talon.db.migrations import run_migrations
from talon.net.heartbeat import HeartbeatMonitor
from talon.net.link_manager import ServerLinkManager
from talon.net.reticulum import create_identity, initialize_reticulum
from talon.net.rnode import RNodeManager
from talon.server.audit import log_event
from talon.server.auth import enroll_client, generate_enrollment_token
from talon.server.client_registry import ClientRegistry
from talon.server.sync_engine import SyncEngine
from talon.server.tile_server import TileServer


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
        self.link_manager = None
        self.client_registry = ClientRegistry()
        self.rnode_manager = None
        self.server_secret = None
        self.running = False

    def load_config(self):
        """Load and merge configuration files.

        Loads default.yaml first, then overlays server.yaml on top.
        This means server.yaml only needs to contain overrides.
        """
        config_dir = self.config_path or os.path.join(os.path.dirname(__file__), "..", "..", "..", "config")

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

    def is_first_run(self) -> bool:
        """Return True if no server database has been initialised yet.

        First run is detected by the absence of the salt file that
        setup_database() writes on first launch. The UI calls this
        before showing a login screen so it can route a fresh install
        through the setup (passphrase + confirm) screen instead.
        """
        if not self.config:
            self.load_config()
        db_config = self.config.get("database", {})
        db_path = db_config.get("path", "data/server.db")
        return not os.path.isfile(db_path + ".salt")

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

        # Derive the server secret for signing leases
        self.server_secret = derive_subkey(master_key, "server_secret")

        # Open the encrypted database and ensure schema is current.
        # run_migrations handles both fresh DBs (creates tables) and
        # existing DBs (applies pending migrations).
        self.db = open_database(db_path, db_key.hex())
        run_migrations(self.db)

    def setup_rnode(self):
        """Detect and validate RNode hardware if configured.

        Called before setup_network() so the detected port can be
        passed to Reticulum's config generator.
        """
        rnode_config = self.config.get("interfaces", {}).get("rnode", {})
        if not rnode_config.get("enabled"):
            return

        self.rnode_manager = RNodeManager(rnode_config)
        if self.rnode_manager.detect():
            self.rnode_manager.validate()

    def setup_network(self):
        """Initialize Reticulum as a propagation and transport node.

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
            is_server=True,
            rnode_override=rnode_override,
        )

        if self.rnode_manager and self.rnode_manager.status == "ready":
            self.rnode_manager.mark_in_use()

        self.identity = create_identity(identity_path=net_config.get("identity_path"))

        # Start the link manager — accepts incoming client connections
        self.link_manager = ServerLinkManager(self.identity)
        self.link_manager.on_sync_message = self._on_sync_message
        self.link_manager.on_heartbeat = self._on_heartbeat
        self.link_manager.on_enrollment = self.handle_enrollment
        self.link_manager.on_client_connected = self._on_client_link
        self.link_manager.on_client_disconnected = self._on_client_unlink
        self.link_manager.start()

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
        self.setup_rnode()
        self.setup_network()
        self.setup_services()
        self.running = True

        log_event("SERVER_STARTED", "SYSTEM", details="T.A.L.O.N. server started")

    def shutdown(self):
        """Clean shutdown of all services."""
        self.running = False
        if self.link_manager:
            self.link_manager.stop()
        log_event("SERVER_STOPPED", "SYSTEM", details="T.A.L.O.N. server stopped")

    # ---------- Enrollment token management ----------

    def create_enrollment_token(self, callsign: str, description: str = "") -> str:
        """Generate and persist an enrollment token for a new operator.

        Args:
            callsign: The callsign the token is intended for.
            description: Optional note (e.g., "for Alpha team lead").

        Returns:
            The 32-character hex token string.
        """
        import time

        token = generate_enrollment_token()
        self.db.execute(
            "INSERT INTO enrollment_tokens (token, callsign, generated_at, description) VALUES (?, ?, ?, ?)",
            (token, callsign, time.time(), description),
        )
        self.db.commit()
        log_event("ENROLLMENT_TOKEN_GENERATED", "Server", details=f"Token generated for {callsign}")
        return token

    def get_pending_tokens(self) -> list:
        """Get all unused enrollment tokens.

        Returns:
            List of dicts with token, callsign, generated_at.
        """
        cursor = self.db.execute(
            "SELECT token, callsign, generated_at FROM enrollment_tokens WHERE used = 0 ORDER BY generated_at DESC"
        )
        return [{"token": row[0], "callsign": row[1], "generated_at": row[2]} for row in cursor.fetchall()]

    def _get_valid_tokens_dict(self) -> dict:
        """Build a valid_tokens dict from DB for enroll_client().

        Returns:
            Dict of {token: {"used": bool, "callsign": str}}.
        """
        cursor = self.db.execute("SELECT token, callsign, used FROM enrollment_tokens")
        return {row[0]: {"used": bool(row[2]), "callsign": row[1]} for row in cursor.fetchall()}

    def _mark_token_used(self, token: str, client_identity: str):
        """Mark an enrollment token as used in the DB."""
        import time

        self.db.execute(
            "UPDATE enrollment_tokens SET used = 1, used_by = ?, used_at = ? WHERE token = ?",
            (client_identity, time.time(), token),
        )
        self.db.commit()

    def handle_enrollment(self, client_hash: str, message: dict) -> dict:
        """Process an enrollment request from a client.

        Args:
            client_hash: The client's Reticulum identity hash.
            message: The enrollment_request message dict.

        Returns:
            Response dict with lease (on success) or error.
        """
        token = message.get("token", "")
        callsign = message.get("callsign", "")

        if not token or not callsign:
            return {"type": "enrollment_response", "success": False, "error": "Missing token or callsign"}

        valid_tokens = self._get_valid_tokens_dict()
        result = enroll_client(token, client_hash, callsign, valid_tokens, self.server_secret)

        if result["success"]:
            self._mark_token_used(token, client_hash)

            # Register the client
            import time

            self.db.execute(
                "INSERT OR REPLACE INTO client_registry "
                "(id, callsign, reticulum_identity, status, enrolled_at, "
                "lease_expires_at) VALUES (?, ?, ?, 'active', ?, ?)",
                (client_hash, callsign, client_hash, time.time(), result["lease"]["expires_at"]),
            )
            self.db.commit()
            self.client_registry.register(client_hash, callsign, "reticulum")

            log_event("CLIENT_ENROLLED", "Server", target=client_hash, details=f"Enrolled as {callsign}")

            # Hex-encode bytes for JSON transport
            lease = result["lease"]
            if isinstance(lease.get("token"), bytes):
                lease["token"] = lease["token"].hex()
            sig = result["signature"]
            if isinstance(sig, bytes):
                sig = sig.hex()

            return {
                "type": "enrollment_response",
                "success": True,
                "lease": lease,
                "signature": sig,
                "callsign": callsign,
            }
        else:
            log_event("ENROLLMENT_FAILED", "Server", target=client_hash, details=result.get("error", "Unknown error"))
            return {
                "type": "enrollment_response",
                "success": False,
                "error": result.get("error", "Enrollment failed"),
            }

    # ---------- Internal callbacks ----------

    def _on_sync_message(self, client_hash: str, message: dict) -> dict:
        """Route a sync message from a client to the sync engine.

        Args:
            client_hash: The client's identity hash.
            message: The decoded message dict.

        Returns:
            Response dict to send back to the client.
        """
        is_broadband = self._client_is_broadband(client_hash)
        return self.sync_engine.handle_message(client_hash, message, is_broadband)

    def _on_heartbeat(self, client_hash: str, payload: dict):
        """Process a heartbeat from a client.

        Updates the heartbeat monitor and client registry.
        """
        callsign = payload.get("callsign", client_hash)
        self.heartbeat_monitor.record_heartbeat(callsign, payload)
        self.client_registry.update_heartbeat(client_hash)

    def _on_client_link(self, client_hash: str, link):
        """Called when a client establishes an RNS link."""
        record = self.client_registry.get_client(client_hash)
        callsign = record["callsign"] if record else client_hash
        self.sync_engine.register_client(client_hash, callsign, "reticulum")
        log_event("CLIENT_CONNECTED", "SYSTEM", target=client_hash, details="Link established")

    def _on_client_unlink(self, client_hash: str):
        """Called when a client's RNS link is torn down."""
        self.sync_engine.unregister_client(client_hash)
        log_event("CLIENT_DISCONNECTED", "SYSTEM", target=client_hash, details="Link closed")

    def _on_data_changed(self, source_client: str, changes: dict):
        """Called when a client pushes new data.

        Sends a notification to all other connected clients over
        their active RNS links.
        """
        notification = {
            "type": "data_changed",
            "tables": list(changes.keys()),
        }
        if self.link_manager:
            for client_hash in self.link_manager.get_connected_clients():
                if client_hash != source_client:
                    self.link_manager.send_to_client(client_hash, notification)

    def _on_client_stale(self, callsign: str, status: str):
        """Called when a client's heartbeat status changes."""
        self.client_registry.mark_stale(callsign)
        log_event("CLIENT_STALE", "SYSTEM", target=callsign, details="Missed heartbeat threshold")

    def _client_is_broadband(self, client_hash: str) -> bool:
        """Check if a client is on a broadband transport.

        Looks up the client's transport type in the registry.
        Defaults to True (broadband) if unknown.
        """
        record = self.client_registry.get_client(client_hash)
        if record:
            transport = record.get("transport", "")
            return transport != "rnode"
        return True

# talon/server/sync_engine.py
# Server-side sync engine.
#
# This module orchestrates the delta sync protocol from the server's
# perspective. When a client connects and requests a sync:
#   1. Server receives the client's version numbers (per table)
#   2. Server finds all records newer than those versions
#   3. Server sends the delta (only changed records) to the client
#   4. Client sends back its own pending changes
#   5. Server applies those changes (with conflict detection)
#   6. Server notifies all OTHER connected clients about new data
#
# Over LoRa (RNode), sync is filtered to only essential tables and
# data is compressed. See talon.sync.priority and talon.sync.compression.

from talon.sync.protocol import (
    build_sync_response,
    apply_sync_response,
    ConflictError,
)
from talon.sync.priority import sort_by_priority, filter_for_transport
from talon.sync.compression import compress, decompress


class SyncEngine:
    """Server-side sync coordinator.

    Attributes:
        db: Database connection (SQLCipher).
        connected_clients: Dict of {client_id: client_info} for online clients.
        on_conflict: Callback when a sync conflict is detected.
        on_data_changed: Callback when new data arrives (triggers notifications).
    """

    def __init__(self, db, on_conflict=None, on_data_changed=None):
        self.db = db
        self.connected_clients = {}
        self.on_conflict = on_conflict
        self.on_data_changed = on_data_changed

    def handle_sync_request(self, client_id: str, client_versions: dict,
                            is_broadband: bool = True) -> dict:
        """Process an incoming sync request from a client.

        Args:
            client_id: The requesting client's identity hash.
            client_versions: Dict of {table_name: version_number} from client.
            is_broadband: True if this is a broadband connection (not LoRa).

        Returns:
            Dict of records to send to the client, filtered and sorted
            by priority, compressed if on LoRa.
        """
        # Build the full delta response
        response = build_sync_response(client_versions, self.db)

        # Filter out broadband-only tables if on LoRa
        if not is_broadband:
            from talon.constants import TransportType
            allowed = filter_for_transport(
                list(response.keys()), TransportType.RNODE
            )
            response = {k: v for k, v in response.items() if k in allowed}

        # Sort by sync priority (system records first, map tiles last)
        sorted_keys = sort_by_priority(list(response.keys()))
        response = {k: response[k] for k in sorted_keys}

        return response

    def handle_client_changes(self, client_id: str,
                              changes: dict) -> dict:
        """Apply changes received from a client.

        Args:
            client_id: Who sent the changes.
            changes: Dict of {table_name: [records]} from the client.

        Returns:
            Dict with results: {"applied": count, "conflicts": [...]}
        """
        applied = 0
        conflicts = []

        for table_name, records in changes.items():
            for record in records:
                try:
                    apply_sync_response({table_name: [record]}, self.db)
                    applied += 1
                except ConflictError as e:
                    conflicts.append({
                        "table": table_name,
                        "record_id": record.get("id"),
                        "error": str(e),
                    })
                    if self.on_conflict:
                        self.on_conflict(client_id, table_name, record, e)

        # Notify other clients about the new data
        if applied > 0 and self.on_data_changed:
            self.on_data_changed(client_id, changes)

        return {"applied": applied, "conflicts": conflicts}

    def register_client(self, client_id: str, callsign: str,
                        transport_type: str):
        """Track a client that has connected.

        Args:
            client_id: The client's identity hash.
            callsign: The operator's callsign.
            transport_type: How they connected (Yggdrasil, I2P, TCP, RNODE).
        """
        self.connected_clients[client_id] = {
            "callsign": callsign,
            "transport": transport_type,
            "connected_at": __import__("time").time(),
        }

    def unregister_client(self, client_id: str):
        """Remove a client that has disconnected."""
        self.connected_clients.pop(client_id, None)

    def get_connected_clients(self) -> dict:
        """Get all currently connected clients."""
        return dict(self.connected_clients)

    def notify_clients(self, exclude_client: str, notification: dict):
        """Send a notification to all connected clients except one.

        Used when new data arrives — we want to tell everyone EXCEPT
        the client that sent the data.

        Args:
            exclude_client: Client ID to skip (the sender).
            notification: Dict describing what changed.
        """
        # Actual Reticulum message sending will be implemented when
        # we wire up the network layer. For now, this is the interface.
        for client_id in self.connected_clients:
            if client_id != exclude_client:
                # TODO: Send notification over Reticulum link
                pass

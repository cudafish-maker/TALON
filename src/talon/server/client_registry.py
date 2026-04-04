# talon/server/client_registry.py
# Tracks all enrolled clients and their current status.
#
# The client registry is the server's view of every client that has
# ever enrolled. It tracks:
#   - Identity and callsign
#   - Current status (ONLINE, STALE, SOFT_LOCKED, REVOKED)
#   - Last heartbeat time
#   - Transport type (how they're connected)
#   - Lease expiry
#
# The heartbeat monitor (talon.net.heartbeat) updates statuses here.

import time
from talon.constants import ClientStatus


class ClientRegistry:
    """Server-side registry of all enrolled clients.

    Attributes:
        clients: Dict of {client_id: client_record}.
        deny_list: Set of revoked client IDs that can never reconnect.
    """

    def __init__(self):
        self.clients = {}
        self.deny_list = set()

    def register(self, client_id: str, callsign: str,
                 transport_type: str = "") -> dict:
        """Register a newly enrolled client.

        Args:
            client_id: The client's Reticulum identity hash.
            callsign: The operator's chosen callsign.
            transport_type: How they connected.

        Returns:
            The client record dict.
        """
        record = {
            "client_id": client_id,
            "callsign": callsign,
            "status": ClientStatus.ONLINE.name,
            "transport": transport_type,
            "enrolled_at": time.time(),
            "last_heartbeat": time.time(),
            "lease_expiry": 0,  # Set when lease is issued
        }
        self.clients[client_id] = record
        return record

    def update_heartbeat(self, client_id: str, transport_type: str = ""):
        """Record a heartbeat from a client.

        Args:
            client_id: Who sent the heartbeat.
            transport_type: Current transport (may change if they switch).
        """
        if client_id in self.clients:
            self.clients[client_id]["last_heartbeat"] = time.time()
            self.clients[client_id]["status"] = ClientStatus.ONLINE.name
            if transport_type:
                self.clients[client_id]["transport"] = transport_type

    def mark_stale(self, client_id: str):
        """Mark a client as stale (missed heartbeats)."""
        if client_id in self.clients:
            self.clients[client_id]["status"] = ClientStatus.STALE.name

    def mark_soft_locked(self, client_id: str):
        """Mark a client as soft-locked (lease expired)."""
        if client_id in self.clients:
            self.clients[client_id]["status"] = ClientStatus.SOFT_LOCKED.name

    def revoke(self, client_id: str, reason: str = ""):
        """Revoke a client permanently.

        Args:
            client_id: The client to revoke.
            reason: Why (stored in audit log, not here).
        """
        if client_id in self.clients:
            self.clients[client_id]["status"] = ClientStatus.REVOKED.name
        self.deny_list.add(client_id)

    def is_denied(self, client_id: str) -> bool:
        """Check if a client is on the deny list."""
        return client_id in self.deny_list

    def get_client(self, client_id: str) -> dict:
        """Get a client's record, or None if not enrolled."""
        return self.clients.get(client_id)

    def get_by_callsign(self, callsign: str) -> dict:
        """Find a client record by callsign."""
        for record in self.clients.values():
            if record["callsign"] == callsign:
                return record
        return None

    def get_online_clients(self) -> list:
        """Get all clients with ONLINE status."""
        return [r for r in self.clients.values()
                if r["status"] == ClientStatus.ONLINE.name]

    def get_all_clients(self) -> list:
        """Get all client records."""
        return list(self.clients.values())

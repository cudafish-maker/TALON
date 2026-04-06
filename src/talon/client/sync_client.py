# talon/client/sync_client.py
# Client-side sync logic.
#
# This module handles the client's half of the delta sync protocol:
#   1. Build a sync request (our version numbers per table)
#   2. Send it to the server over the current Reticulum link
#   3. Receive the delta response (records we're missing)
#   4. Apply those records to our local cache
#   5. Send our pending outbox changes to the server
#   6. Clear the outbox on success
#
# Sync is triggered:
#   - On startup (catch up with everything we missed)
#   - Periodically (heartbeat interval)
#   - When the server pushes a notification that data changed
#   - Manually by the operator (force sync button)

import time
from talon.sync.protocol import (
    build_sync_request, build_client_changes, apply_sync_response,
)
from talon.sync.priority import filter_for_transport


class SyncClient:
    """Client-side sync coordinator.

    Attributes:
        cache: The ClientCache instance (local database + outbox).
        is_syncing: True while a sync operation is in progress.
        last_sync: Unix timestamp of the last successful sync.
        on_sync_complete: Callback after successful sync.
        on_sync_error: Callback when sync fails.
    """

    def __init__(self, cache, on_sync_complete=None, on_sync_error=None):
        self.cache = cache
        self.is_syncing = False
        self.last_sync = 0
        self.on_sync_complete = on_sync_complete
        self.on_sync_error = on_sync_error

    def build_request(self, is_broadband: bool = True) -> dict:
        """Build a sync request to send to the server.

        Args:
            is_broadband: Whether we're on a broadband transport.

        Returns:
            Dict with our version numbers per table, ready to send.
        """
        request = build_sync_request(self.cache.db)

        # If on LoRa, filter out broadband-only tables from the request
        if not is_broadband:
            from talon.constants import TransportType
            allowed = filter_for_transport(
                list(request.get("versions", {}).keys()),
                TransportType.RNODE,
            )
            versions = request.get("versions", {})
            request["versions"] = {
                k: v for k, v in versions.items() if k in allowed
            }

        return request

    def apply_response(self, response: dict) -> int:
        """Apply the server's sync response to our local cache.

        Args:
            response: Sync response dict with "updates" key.

        Returns:
            Number of records applied.
        """
        apply_sync_response(self.cache.db, response)
        updates = response.get("updates", {})
        count = sum(len(recs) for recs in updates.values())
        return count

    def queue_change(self, table: str, operation: str, record: dict):
        """Queue a local change for sync when we're back online.

        Called by UI screens when the operator creates or modifies data.

        Args:
            table: Which table (e.g. "sitreps", "assets").
            operation: "insert", "update", or "delete".
            record: The record dict to sync.
        """
        self.cache.queue_change(table, operation, record)

    def get_pending_changes(self) -> dict:
        """Collect locally modified records to push to the server.

        Returns:
            Dict with "type", "changes", and "timestamp" keys.
            The "changes" value maps table names to lists of records.
        """
        return build_client_changes(self.cache.db)

    def send_pending(self) -> list:
        """Get outbox items (queued while offline).

        Returns:
            List of outbox entries.
        """
        return self.cache.get_pending_changes()

    def full_sync(self, send_fn) -> dict:
        """Run a complete sync cycle.

        This orchestrates the full client-side sync flow:
        1. Build and send a sync request
        2. Apply the server's response
        3. Send our pending changes
        4. Process the server's ack

        Args:
            send_fn: A callable that takes a message dict and returns
                     the server's response dict. This abstracts the
                     transport layer (Reticulum, mock, etc.).

        Returns:
            Dict with sync results: {"received": N, "sent": N, "conflicts": []}
        """
        if self.is_syncing:
            return {"error": "Sync already in progress"}

        self.is_syncing = True
        try:
            # Step 1: Send our version numbers, get server's delta
            request = self.build_request()
            server_response = send_fn(request)
            if not server_response:
                self.sync_failed("No response from server")
                return {"error": "No response from server"}

            # Step 2: Apply server's updates to local cache
            received = self.apply_response(server_response)

            # Step 3: Send our pending changes to the server
            client_changes = self.get_pending_changes()
            changes_payload = client_changes.get("changes", {})
            sent = sum(len(recs) for recs in changes_payload.values())

            ack = {}
            if sent > 0:
                ack = send_fn(client_changes) or {}

            # Step 4: Process acknowledgement
            conflicts = ack.get("conflicts", [])
            self.cache.clear_synced()
            self.last_sync = time.time()
            self.is_syncing = False

            result = {
                "received": received,
                "sent": sent,
                "conflicts": conflicts,
            }
            if self.on_sync_complete:
                self.on_sync_complete(result)

            return result

        except Exception as e:
            self.sync_failed(str(e))
            return {"error": str(e)}

    def on_server_ack(self, result: dict):
        """Called when the server acknowledges our pushed changes.

        Args:
            result: The server's response (applied count, conflicts).
        """
        self.cache.clear_synced()
        self.last_sync = time.time()
        self.is_syncing = False

        if self.on_sync_complete:
            self.on_sync_complete(result)

    def sync_failed(self, error: str):
        """Called when a sync attempt fails.

        Changes stay in the outbox for the next attempt.

        Args:
            error: Description of what went wrong.
        """
        self.is_syncing = False
        if self.on_sync_error:
            self.on_sync_error(error)

    def needs_sync(self, interval: int = 60) -> bool:
        """Check if it's time for a sync.

        Args:
            interval: Seconds between syncs (60 for broadband, 120 for LoRa).

        Returns:
            True if enough time has passed since the last sync.
        """
        return (time.time() - self.last_sync) >= interval

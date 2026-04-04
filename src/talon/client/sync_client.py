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
from talon.sync.protocol import build_sync_request, apply_sync_response
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
                list(request.keys()), TransportType.RNODE
            )
            request = {k: v for k, v in request.items() if k in allowed}

        return request

    def apply_response(self, response: dict) -> int:
        """Apply the server's sync response to our local cache.

        Args:
            response: Dict of {table_name: [records]} from the server.

        Returns:
            Number of records applied.
        """
        count = 0
        for table_name, records in response.items():
            for record in records:
                apply_sync_response({table_name: [record]}, self.cache.db)
                count += 1
        return count

    def send_pending(self) -> dict:
        """Get our pending outbox changes to send to the server.

        Returns:
            Dict of {table_name: [records]} to push to the server.
        """
        return self.cache.get_pending_changes()

    def on_server_ack(self, result: dict):
        """Called when the server acknowledges our pushed changes.

        Args:
            result: The server's response (applied count, conflicts).
        """
        if result.get("conflicts"):
            # Log conflicts but still clear — server's version wins
            pass

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

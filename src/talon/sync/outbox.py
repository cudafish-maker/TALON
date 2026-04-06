# talon/sync/outbox.py
# Outbox management for cached mode.
#
# When the client has no connection to the server, any changes
# the operator makes (SITREPs, assets, messages, etc.) are stored
# in the outbox. When the connection is restored, the outbox is
# replayed to the server in the order the changes were made.
#
# The operator can see how many pending changes are queued:
# "3 pending changes waiting for uplink"

import json
import time


class Outbox:
    """Manages queued operations while the client is disconnected.

    Changes are stored in order and replayed when connection returns.
    Each entry records what was changed, when, and what the data was.
    """

    def __init__(self):
        # List of pending operations in chronological order.
        # Each entry is a dict with: table, operation, record, timestamp
        self._queue = []

    def add(self, table: str, operation: str, record: dict) -> None:
        """Add a change to the outbox.

        Called whenever the operator creates or modifies data
        while in cached mode (no server connection).

        Args:
            table: Which database table was affected (e.g., "sitreps").
            operation: What happened — "insert", "update", or "delete".
            record: The full record data as a dictionary.
        """
        self._queue.append(
            {
                "table": table,
                "operation": operation,
                "record": record,
                "timestamp": time.time(),
                "sequence": len(self._queue),
            }
        )

    def get_pending(self) -> list:
        """Get all pending operations in order.

        Returns:
            List of queued operations, oldest first.
        """
        return list(self._queue)

    def count(self) -> int:
        """How many operations are waiting to be synced.

        Returns:
            Number of pending operations. Displayed in the UI as
            "X pending changes waiting for uplink".
        """
        return len(self._queue)

    def clear(self) -> None:
        """Clear the outbox after successful sync.

        Called once all queued operations have been sent to the
        server and acknowledged.
        """
        self._queue.clear()

    def remove(self, sequence: int) -> None:
        """Remove a specific operation after it's been acknowledged.

        Used when replaying operations one by one — each operation
        is removed as the server acknowledges it.

        Args:
            sequence: The sequence number of the operation to remove.
        """
        self._queue = [op for op in self._queue if op["sequence"] != sequence]

    def to_json(self) -> str:
        """Serialize the outbox to JSON for persistent storage.

        The outbox should be saved to disk so it survives app restarts.

        Returns:
            JSON string of all queued operations.
        """
        return json.dumps(self._queue)

    @classmethod
    def from_json(cls, data: str) -> "Outbox":
        """Create an Outbox from a JSON string.

        Called on app startup to restore any pending operations
        from the last session.

        Args:
            data: JSON string from to_json().

        Returns:
            A new Outbox with the restored queue.
        """
        outbox = cls()
        outbox._queue = json.loads(data)
        return outbox

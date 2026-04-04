# talon/client/auth.py
# Client-side authentication and lease management.
#
# Handles:
#   - Initial enrollment (presenting the enrollment token to the server)
#   - Lease storage and renewal
#   - Soft-lock detection (lease expired → lock the UI, keep data)
#   - Hard shred on revocation (destroy all local data)
#
# The client checks its lease on startup and periodically during
# operation. If the lease expires, the client enters soft-lock mode:
# the UI is locked but data is preserved. The server operator can
# approve re-authentication to unlock the client.

import os
import time
import json

from talon.crypto.lease import is_lease_valid, time_remaining


class ClientAuth:
    """Manages the client's authentication state.

    Attributes:
        lease: The current lease token dict (or None if not enrolled).
        lease_path: Where the lease is stored on disk.
        is_enrolled: Whether this client has completed enrollment.
        is_locked: Whether the client is in soft-lock mode.
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.lease_path = os.path.join(data_dir, "lease.json")
        self.lease = None
        self.is_enrolled = False
        self.is_locked = False

    def load_lease(self) -> bool:
        """Load the lease from disk.

        Returns:
            True if a valid lease was loaded, False otherwise.
        """
        if not os.path.isfile(self.lease_path):
            return False

        with open(self.lease_path, "r") as f:
            self.lease = json.load(f)

        self.is_enrolled = True

        # Check if the lease is still valid
        if not is_lease_valid(self.lease):
            self.is_locked = True
            return False

        return True

    def save_lease(self, lease: dict):
        """Save a lease to disk.

        Args:
            lease: The lease token dict from the server.
        """
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.lease_path, "w") as f:
            json.dump(lease, f)
        self.lease = lease
        self.is_enrolled = True
        self.is_locked = False

    def check_lease(self) -> dict:
        """Check the current lease status.

        Returns:
            Dict with:
            - "valid": bool
            - "remaining_seconds": float (0 if expired)
            - "locked": bool
        """
        if not self.lease:
            return {"valid": False, "remaining_seconds": 0, "locked": False}

        valid = is_lease_valid(self.lease)
        remaining = time_remaining(self.lease) if valid else 0

        if not valid and self.is_enrolled:
            self.is_locked = True

        return {
            "valid": valid,
            "remaining_seconds": remaining,
            "locked": self.is_locked,
        }

    def request_enrollment(self, enrollment_token: str,
                           callsign: str) -> dict:
        """Build an enrollment request to send to the server.

        Args:
            enrollment_token: The token given by the server operator.
            callsign: The operator's chosen callsign.

        Returns:
            Dict to send to the server over Reticulum.
        """
        return {
            "type": "enrollment_request",
            "token": enrollment_token,
            "callsign": callsign,
            "timestamp": time.time(),
        }

    def shred_local_data(self):
        """Destroy all local data (revocation response).

        This is the nuclear option — called when the server revokes
        this client. Overwrites the database and all cached files
        with random data before deleting them.

        WARNING: This is irreversible.
        """
        # Overwrite lease file with random data, then delete
        if os.path.isfile(self.lease_path):
            size = os.path.getsize(self.lease_path)
            with open(self.lease_path, "wb") as f:
                f.write(os.urandom(max(size, 1024)))
            os.remove(self.lease_path)

        # Overwrite the database file if it exists
        db_path = os.path.join(self.data_dir, "client.db")
        if os.path.isfile(db_path):
            size = os.path.getsize(db_path)
            with open(db_path, "wb") as f:
                f.write(os.urandom(size))
            os.remove(db_path)

        self.lease = None
        self.is_enrolled = False
        self.is_locked = False

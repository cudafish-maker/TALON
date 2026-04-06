# talon/crypto/lease.py
# Lease token management for T.A.L.O.N.
#
# A "lease" is like a time-limited pass that lets a client access
# its local data. Here's how it works:
#
# 1. When a client syncs with the server, the server issues a
#    lease token — a signed, timestamped token.
# 2. The client needs this token (along with the operator's passphrase)
#    to unlock its local encrypted database.
# 3. After 24 hours without syncing, the lease expires.
# 4. When the lease expires:
#    - The app LOCKS (soft-lock) — data is still on disk but
#      inaccessible without a valid lease.
#    - The operator sees "Contact server operator for re-auth."
#    - NO data is destroyed (unlike revocation, which shreds everything).
# 5. To unlock, the server operator approves the re-auth request,
#    and a new lease token is issued.
#
# This prevents a stolen device from being useful after 24 hours
# even if the attacker knows the passphrase.

import hashlib
import hmac
import os
import time

# Lease token is 32 bytes of random data
LEASE_TOKEN_LENGTH = 32


def generate_lease_token() -> dict:
    """Generate a new lease token on the server.

    Called every time a client successfully syncs with the server.
    The token is sent to the client, which stores it locally.

    Returns:
        Dictionary with:
        - "token": 32 random bytes
        - "issued_at": timestamp when the token was created
        - "expires_at": timestamp when the token expires
    """
    now = time.time()
    return {
        "token": os.urandom(LEASE_TOKEN_LENGTH),
        "issued_at": now,
        # Default 24-hour expiry — can be overridden by config
        "expires_at": now + (24 * 60 * 60),
    }


def is_lease_valid(lease: dict) -> bool:
    """Check if a lease token is still valid (not expired).

    Args:
        lease: The lease dictionary from generate_lease_token().

    Returns:
        True if the current time is before the expiry time.
        False if the lease has expired (soft-lock should activate).
    """
    if lease is None:
        return False
    return time.time() < lease.get("expires_at", 0)


def time_remaining(lease: dict) -> float:
    """Get how many seconds remain on the lease.

    Used to display "Lease: 22h remaining" in the status bar.

    Args:
        lease: The lease dictionary.

    Returns:
        Seconds remaining. Negative if already expired.
    """
    if lease is None:
        return -1
    return lease.get("expires_at", 0) - time.time()


def sign_lease(lease_token: bytes, server_key: bytes) -> bytes:
    """Server signs a lease token to prevent forgery.

    The signature proves the token was issued by the real server.
    A client cannot create or extend their own lease.

    Args:
        lease_token: The 32-byte token to sign.
        server_key: The server's signing key.

    Returns:
        HMAC-SHA256 signature bytes.
    """
    return hmac.new(server_key, lease_token, hashlib.sha256).digest()


def verify_lease_signature(lease_token: bytes, signature: bytes, server_key: bytes) -> bool:
    """Verify that a lease token was signed by the server.

    Args:
        lease_token: The token to verify.
        signature: The signature to check.
        server_key: The server's signing key.

    Returns:
        True if the signature is valid (token is authentic).
    """
    expected = hmac.new(server_key, lease_token, hashlib.sha256).digest()
    return hmac.compare_digest(signature, expected)

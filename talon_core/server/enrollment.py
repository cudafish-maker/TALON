"""
Operator enrollment — server exclusive.

Enrollment flow:
  1. Server operator generates a one-time token via generate_enrollment_token().
  2. Token is delivered out-of-band to the new operator (QR code, verbal, etc.).
  3. New operator enters token in the client app; client sends it to the server
     over an RNS link.
  4. Server calls create_operator() which validates the token and provisions
     the operator record.

Tokens expire after the requested duration, defaulting to
ENROLLMENT_TOKEN_EXPIRY_S seconds, or at a requested absolute timestamp.
Each token can only be consumed once.
"""
import hashlib
import os
import time
import uuid as _uuid_mod

from talon_core.constants import (
    ENROLLMENT_TOKEN_EXPIRY_S,
    ENROLLMENT_TOKEN_MAX_EXPIRY_S,
    ENROLLMENT_TOKEN_MIN_EXPIRY_S,
    LEASE_DURATION_S,
)
from talon_core.db.connection import Connection
from talon_core.db.models import EnrollmentToken, Operator
from talon_core.utils.logging import audit, get_logger

_log = get_logger("server.enrollment")


def generate_enrollment_token(
    conn: Connection,
    *,
    expires_in_s: int | None = None,
    expires_at: int | None = None,
) -> str:
    """
    Generate a cryptographically random one-time enrollment token,
    persist it, and return the hex string to present to the operator.
    """
    now = int(time.time())
    expiry_s, expires_at = normalise_enrollment_token_expiration(
        expires_in_s=expires_in_s,
        expires_at=expires_at,
        now=now,
    )
    token = os.urandom(32).hex()
    token_hash = _hash_token(token)
    conn.execute(
        "INSERT INTO enrollment_tokens "
        "(token, token_preview, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_stored_token_key(token), _token_preview(token), now, expires_at),
    )
    conn.commit()
    # BUG-009: log a hash of the token so it can be correlated later without
    # exposing the raw token value in the audit record.
    audit(
        "enrollment_token_generated",
        expires_at=expires_at,
        expires_in_s=expiry_s,
        token_hash=token_hash,
    )
    _log.info("Enrollment token generated (expires in %ds)", expiry_s)
    return token


def normalise_enrollment_token_expiration(
    *,
    expires_in_s: int | None = None,
    expires_at: int | None = None,
    now: int | None = None,
) -> tuple[int, int]:
    """Validate and return an enrollment token duration and expiration time."""
    current_time = int(time.time()) if now is None else int(now)
    if expires_in_s is not None and expires_at is not None:
        raise ValueError(
            "Specify enrollment token expiration as either a duration or timestamp, not both."
        )
    if expires_at is None:
        expiry_s = normalise_enrollment_token_expiry_s(expires_in_s)
        return expiry_s, current_time + expiry_s
    try:
        requested_expires_at = int(expires_at)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Enrollment token expiration must be a whole-number timestamp."
        ) from exc
    expiry_s = normalise_enrollment_token_expiry_s(
        requested_expires_at - current_time
    )
    return expiry_s, requested_expires_at


def normalise_enrollment_token_expiry_s(expires_in_s: int | None = None) -> int:
    """Validate and return an enrollment token expiry duration in seconds."""
    if expires_in_s is None:
        return ENROLLMENT_TOKEN_EXPIRY_S
    try:
        expiry_s = int(expires_in_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enrollment token expiration must be a whole number of seconds.") from exc
    if expiry_s < ENROLLMENT_TOKEN_MIN_EXPIRY_S:
        raise ValueError("Enrollment token expiration must be at least 1 minute.")
    if expiry_s > ENROLLMENT_TOKEN_MAX_EXPIRY_S:
        raise ValueError("Enrollment token expiration must be no more than 7 days.")
    return expiry_s


def list_pending_tokens(conn: Connection) -> list[EnrollmentToken]:
    """Return all tokens that have not yet been consumed and are not expired."""
    now = int(time.time())
    rows = conn.execute(
        "SELECT token, token_preview, created_at, expires_at, used_at, operator_id "
        "FROM enrollment_tokens WHERE used_at IS NULL AND expires_at > ?",
        (now,),
    ).fetchall()
    return [
        EnrollmentToken(
            token_hash=r[0],
            token_preview=r[1] or _hash_preview(r[0]),
            created_at=r[2],
            expires_at=r[3],
            used_at=r[4],
            operator_id=r[5],
        )
        for r in rows
    ]


def create_operator(
    conn: Connection,
    callsign: str,
    rns_hash: str,
    token: str,
) -> Operator:
    """
    Validate a token and provision a new operator record.

    Raises ValueError if the token is invalid, expired, or already used.
    Raises ValueError if the callsign or rns_hash is already registered.
    """
    now = int(time.time())

    # BUG-030: acquire the write lock BEFORE reading the token row so the
    # full read-validate-write sequence is atomic.  Previously the SELECT ran
    # outside the transaction, creating a TOCTOU window where two simultaneous
    # requests for the same token could both pass validation.
    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            "SELECT token, expires_at, used_at FROM enrollment_tokens WHERE token = ?",
            (_stored_token_key(token),),
        ).fetchone()

        if row is None:
            raise ValueError("Enrollment token not found.")
        if row[2] is not None:
            raise ValueError("Enrollment token has already been used.")
        if row[1] < now:
            raise ValueError("Enrollment token has expired.")

        lease_expires = now + LEASE_DURATION_S

        cursor = conn.execute(
            "INSERT INTO operators "
            "(callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked, uuid) "
            "VALUES (?, ?, '[]', '{}', ?, ?, 0, ?)",
            (callsign, rns_hash, now, lease_expires, _uuid_mod.uuid4().hex),
        )
        operator_id = cursor.lastrowid
        conn.execute(
            "UPDATE enrollment_tokens SET used_at = ?, operator_id = ? WHERE token = ?",
            (now, operator_id, _stored_token_key(token)),
        )
        conn.commit()
    except ValueError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise ValueError(f"Could not create operator: {exc}") from exc

    audit("operator_enrolled", callsign=callsign, rns_hash=rns_hash, operator_id=operator_id)
    _log.info("Operator enrolled: callsign=%s id=%s", callsign, operator_id)

    return Operator(
        id=operator_id,
        callsign=callsign,
        rns_hash=rns_hash,
        skills=[],
        profile={},
        enrolled_at=now,
        lease_expires_at=lease_expires,
        revoked=False,
    )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _stored_token_key(token: str) -> str:
    return f"sha256:{_hash_token(token)}"


def _token_preview(token: str) -> str:
    return f"{token[:8]}...{token[-8:]}"


def _hash_preview(stored_token: str) -> str:
    value = str(stored_token)
    if value.startswith("sha256:"):
        value = value[len("sha256:"):]
    return f"hash:{value[:12]}..."


def renew_lease(conn: Connection, operator_id: int, duration_s: int) -> int:
    """
    Extend an operator's lease. Returns the new expiry timestamp.
    Called by the server when re-authorising a soft-locked client.
    """
    new_expiry = int(time.time()) + duration_s
    cursor = conn.execute(
        "UPDATE operators SET lease_expires_at = ?, version = version + 1 WHERE id = ?",
        (new_expiry, operator_id),
    )
    if cursor.rowcount == 0:
        raise ValueError(f"Operator {operator_id} not found.")
    conn.commit()
    audit("lease_renewed", operator_id=operator_id, new_expiry=new_expiry)
    _log.info("Lease renewed: operator_id=%s new_expiry=%s", operator_id, new_expiry)
    return new_expiry

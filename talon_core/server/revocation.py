"""
Operator revocation — server exclusive.

Hard revocation performs three steps in order:
  1. DB shred  — marks the operator revoked and clears their identity hash.
  2. Identity burn — overwrites and deletes the cached identity file (if present).
  3. Group key rotation — invokes the supplied rotator callback so all remaining
     operators receive a new group encryption key on next sync.

The function is intentionally destructive and irreversible.
Never call it without an explicit server-operator action.
"""
import hashlib
import pathlib
import time
import typing

from talon_core.crypto.identity import destroy_identity
from talon_core.db.connection import Connection
from talon_core.utils.logging import audit, get_logger

_log = get_logger("server.revocation")


def revoke_operator(
    conn: Connection,
    operator_id: int,
    identity_path: typing.Optional[pathlib.Path] = None,
    group_key_rotator: typing.Optional[typing.Callable[[], None]] = None,
) -> None:
    """
    Hard-revoke an operator.

    Parameters
    ----------
    conn:
        Open database connection.
    operator_id:
        Primary key of the operator row to revoke.
    identity_path:
        Path to the operator's RNS identity file on disk.
        If supplied, the file is securely overwritten then deleted.
        Pass None when the identity file is not locally accessible
        (e.g. remote client — the revocation still proceeds; the client
        will be denied on its next sync attempt via the revoked flag).
    group_key_rotator:
        Zero-argument callable that triggers group key rotation for all
        remaining operators.  Pass None during testing or when rotation
        is handled by the caller after this function returns.

    Raises
    ------
    ValueError
        If operator_id does not exist or is already revoked.
    """
    now = int(time.time())

    # --- 1. Verify the operator exists and is not already revoked ----------
    row = conn.execute(
        "SELECT callsign, rns_hash, revoked FROM operators WHERE id = ?",
        (operator_id,),
    ).fetchone()

    if row is None:
        raise ValueError(f"Operator {operator_id} not found.")
    if row[2]:  # already revoked
        raise ValueError(f"Operator {operator_id} is already revoked.")

    callsign = row[0]
    rns_hash = row[1]

    # --- 2. DB shred -------------------------------------------------------
    # Keep the row for audit continuity but mark revoked and wipe the
    # active identity hash so it cannot be reused in a new enrollment.
    conn.execute(
        "UPDATE operators SET revoked = 1, rns_hash = '', lease_expires_at = ?, "
        "version = version + 1 "
        "WHERE id = ?",
        (now, operator_id),
    )

    # Invalidate any outstanding enrollment tokens tied to this operator.
    conn.execute(
        "UPDATE enrollment_tokens SET used_at = ? "
        "WHERE operator_id = ? AND used_at IS NULL",
        (now, operator_id),
    )

    conn.commit()

    # BUG-012: log a hash of the rns_hash rather than the raw value to avoid
    # unnecessary identity exposure within the encrypted audit store.
    audit(
        "operator_revoked",
        operator_id=operator_id,
        callsign=callsign,
        rns_hash_was=hashlib.sha256(rns_hash.encode()).hexdigest(),
    )
    # BUG-032: log callsign + id only — omit rns_hash to avoid exposing the
    # operator's Reticulum identity in plaintext log files or aggregators.
    # The encrypted audit entry already records sha256(rns_hash) for correlation.
    _log.warning("Operator revoked: callsign=%s id=%s", callsign, operator_id)

    # --- 3. Identity burn --------------------------------------------------
    if identity_path is not None:
        destroy_identity(identity_path)
        _log.info("Identity file destroyed: %s", identity_path)

    # --- 4. Group key rotation ---------------------------------------------
    if group_key_rotator is not None:
        try:
            group_key_rotator()
        except Exception:
            # Rotation failure must not undo the revocation — log and continue.
            _log.exception(
                "Group key rotation failed after revoking operator %s — "
                "manual rotation required.",
                operator_id,
            )

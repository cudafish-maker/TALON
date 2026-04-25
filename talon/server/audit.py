"""
Encrypted audit log — server exclusive.

Audit entries are field-encrypted with the server's audit key, a 32-byte
symmetric key derived from the same Argon2id passphrase as the DB key but with
a domain-separation suffix (``passphrase + ":audit"``).  This ensures that a
compromised DB key does not also expose audit content — the two keys are
cryptographically independent despite sharing the same salt.

The SQLCipher database provides a second layer of encryption; field encryption
provides defence-in-depth so that even an attacker who recovers the raw DB file
cannot read audit entries without separately deriving the audit key.

The audit key is derived in ``login_screen._do_login()`` and passed here via
``install_hook()`` — it is never stored on disk.

Public API
----------
append_entry(conn, key, event, payload)   — write one encrypted entry
query_entries(conn, key, ...)             — read and decrypt entries
install_hook(conn, key)                   — wire audit() calls to this module
"""
import json
import time
import typing

from talon.crypto.fields import decrypt_field, encrypt_field
from talon.db.connection import Connection
from talon.db.models import AuditEntry
from talon.utils.logging import set_audit_hook, get_logger

_log = get_logger("server.audit")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def append_entry(conn: Connection, key: bytes, event: str, payload: dict) -> int:
    """
    Encrypt and persist one audit entry.

    Parameters
    ----------
    conn:    Open database connection.
    key:     32-byte symmetric key for field encryption.
    event:   Short event name (e.g. "operator_enrolled").
    payload: Arbitrary dict of event metadata.

    Returns
    -------
    The new row's primary key.
    """
    now = int(time.time())
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    blob = encrypt_field(raw, key)
    cursor = conn.execute(
        "INSERT INTO audit_log (event, payload, occurred_at) VALUES (?, ?, ?)",
        (event, blob, now),
    )
    # BUG-035: commit is the caller's responsibility so that the hook closure
    # (install_hook) can own the commit boundary.  Direct callers must commit
    # themselves.  This avoids a per-event fsync when multiple audit entries are
    # written in quick succession during e.g. bulk enrollment.
    _log.debug("Audit entry written: event=%s id=%s", event, cursor.lastrowid)
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def query_entries(
    conn: Connection,
    key: bytes,
    *,
    since: typing.Optional[int] = None,
    until: typing.Optional[int] = None,
    event_filter: typing.Optional[str] = None,
    limit: int = 500,
) -> list[AuditEntry]:
    """
    Retrieve and decrypt audit entries.

    Parameters
    ----------
    conn:         Open database connection.
    key:          32-byte symmetric key used when entries were written.
    since:        Return only entries with occurred_at >= since (Unix ts).
    until:        Return only entries with occurred_at <= until (Unix ts).
    event_filter: If given, return only entries whose event equals this string.
    limit:        Maximum number of entries to return (newest first).

    Returns
    -------
    List of AuditEntry dataclasses, ordered newest → oldest.
    """
    clauses: list[str] = []
    params: list[object] = []

    if since is not None:
        clauses.append("occurred_at >= ?")
        params.append(since)
    if until is not None:
        clauses.append("occurred_at <= ?")
        params.append(until)
    if event_filter is not None:
        clauses.append("event = ?")
        params.append(event_filter)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT id, event, payload, occurred_at "
        f"FROM audit_log {where} ORDER BY occurred_at DESC LIMIT ?",
        params,
    ).fetchall()

    entries: list[AuditEntry] = []
    for row in rows:
        try:
            raw = decrypt_field(row[2], key)
            payload = json.loads(raw.decode())
        except Exception:
            _log.error("Failed to decrypt audit entry id=%s — skipping", row[0])
            continue
        entries.append(
            AuditEntry(
                id=row[0],
                event=row[1],
                payload=payload,
                occurred_at=row[3],
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Hook integration
# ---------------------------------------------------------------------------

def install_hook(conn: Connection, key: bytes) -> None:
    """
    Register a closure as the global audit hook so that every audit() call
    in utils/logging.py is automatically persisted to the encrypted log.

    Call this once during server startup, after the DB is open and the audit
    key is derived.
    """
    def _hook(event: str, payload: dict) -> None:
        try:
            append_entry(conn, key, event, payload)
            conn.commit()
        except Exception:
            # Must not raise — callers of audit() don't expect exceptions.
            _log.exception("Audit hook failed for event=%s", event)

    set_audit_hook(_hook)
    _log.info("Audit hook installed.")

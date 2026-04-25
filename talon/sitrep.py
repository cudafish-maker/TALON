"""
SITREP data access — create and query SITREPs.

The body field is field-encrypted at rest using the DB key (same key as
the SQLCipher encryption layer; field-encryption adds defence-in-depth so
that an operator who can read the raw DB still cannot read SITREP bodies
without the derived key).

SERVER_AUTHOR_ID (1) is the sentinel seeded by migration 0002.  It is used
as author_id for SITREPs composed on the server before operator enrollment
is implemented.  See wiki/decisions.md — "Server Operator Sentinel".
"""
import time
import typing
import uuid as _uuid_mod

from talon.constants import SITREP_LEVELS
from talon.crypto.fields import decrypt_field, encrypt_field
from talon.db.connection import Connection
from talon.db.models import Sitrep

# Sentinel operator record seeded by migration 0002.
# TODO: replace with the real server operator id once enrollment is wired.
SERVER_AUTHOR_ID: int = 1


def create_sitrep(
    conn: Connection,
    key: bytes,
    *,
    author_id: int,
    level: str,
    template: str = "",
    body: str,
    mission_id: typing.Optional[int] = None,
    asset_id: typing.Optional[int] = None,
    sync_status: str = "synced",
) -> int:
    """
    Encrypt and insert a new SITREP.  Returns the new row id.

    Pass sync_status='pending' when creating while offline (client mode only);
    the record will be pushed to the server on next reconnect.

    Raises ValueError for unknown level strings.
    """
    if level not in SITREP_LEVELS:
        raise ValueError(f"Unknown SITREP level: {level!r}")
    now = int(time.time())
    blob = encrypt_field(body.encode(), key)
    cursor = conn.execute(
        "INSERT INTO sitreps "
        "(level, template, body, author_id, mission_id, asset_id, created_at, uuid, sync_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (level, template, blob, author_id, mission_id, asset_id, now,
         _uuid_mod.uuid4().hex, sync_status),
    )
    conn.commit()
    return cursor.lastrowid


def delete_sitrep(conn: Connection, sitrep_id: int) -> None:
    """Permanently delete a SITREP.  Server operator only."""
    conn.execute("DELETE FROM sitreps WHERE id = ?", (sitrep_id,))
    conn.commit()


def link_sitreps_to_mission(
    conn: Connection,
    mission_id: int,
    sitrep_ids: list[int],
) -> None:
    """Set mission_id on the specified SITREPs, linking them to a mission.

    Existing links on other SITREPs for this mission are not disturbed — this
    only sets the given rows.  Pass an empty list to no-op.
    """
    if not sitrep_ids:
        return
    placeholders = ",".join("?" * len(sitrep_ids))
    conn.execute(
        f"UPDATE sitreps SET mission_id = ?, version = version + 1 WHERE id IN ({placeholders})",
        [mission_id, *sitrep_ids],
    )
    conn.commit()


def load_sitreps(
    conn: Connection,
    key: bytes,
    *,
    limit: int = 200,
    mission_id: typing.Optional[int] = None,
    asset_id: typing.Optional[int] = None,
) -> list[tuple[Sitrep, str, typing.Optional[str]]]:
    """
    Load and decrypt SITREPs, newest first.

    Returns (Sitrep, author_callsign, asset_label) triples.
    - author_callsign: operator display name, or 'UNKNOWN' if row removed.
    - asset_label: label of the linked asset, or None if no asset linked.
    - Entries that fail decryption return body=b'[encrypted]' rather than
      being dropped, so the feed always shows the full history.

    Optional filters:
      mission_id — return only SITREPs for that mission.
      asset_id   — return only SITREPs linked to that asset.
    """
    clauses: list[str] = []
    params: list[object] = []
    if mission_id is not None:
        clauses.append("s.mission_id = ?")
        params.append(mission_id)
    if asset_id is not None:
        clauses.append("s.asset_id = ?")
        params.append(asset_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    rows = conn.execute(
        f"SELECT s.id, s.level, s.template, s.body, s.author_id, "
        f"s.mission_id, s.asset_id, s.created_at, s.version, "
        f"COALESCE(o.callsign, 'UNKNOWN'), "
        f"a.label "
        f"FROM sitreps s "
        f"LEFT JOIN operators o ON s.author_id = o.id "
        f"LEFT JOIN assets a ON s.asset_id = a.id "
        f"{where} ORDER BY s.created_at DESC LIMIT ?",
        params,
    ).fetchall()

    result: list[tuple[Sitrep, str, typing.Optional[str]]] = []
    for row in rows:
        try:
            body_bytes = decrypt_field(row[3], key)
        except Exception:
            body_bytes = b"[encrypted]"
        sitrep = Sitrep(
            id=row[0],
            level=row[1],
            template=row[2],
            body=body_bytes,
            author_id=row[4],
            mission_id=row[5],
            asset_id=row[6],
            created_at=row[7],
            version=row[8],
        )
        result.append((sitrep, row[9], row[10]))
    return result

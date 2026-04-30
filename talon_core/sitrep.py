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

from talon_core.constants import SITREP_LEVELS
from talon_core.crypto.fields import decrypt_field, encrypt_field
from talon_core.db.connection import Connection
from talon_core.db.models import Sitrep, SitrepDocumentLink, SitrepFollowUp

# Sentinel operator record seeded by migration 0002.
# TODO: replace with the real server operator id once enrollment is wired.
SERVER_AUTHOR_ID: int = 1

SITREP_STATUSES: tuple[str, ...] = (
    "open",
    "acknowledged",
    "assigned",
    "resolved",
    "closed",
)

SITREP_FOLLOWUP_ACTIONS: tuple[str, ...] = (
    "note",
    "acknowledged",
    "assigned",
    "status",
    "resolved",
    "document_linked",
)

SITREP_LOCATION_PRECISIONS: tuple[str, ...] = (
    "",
    "general",
    "approximate",
    "exact",
)

SITREP_LOCATION_SOURCES: tuple[str, ...] = (
    "",
    "manual",
    "device",
    "map",
    "asset",
    "assignment",
)

SITREP_SENSITIVITIES: tuple[str, ...] = (
    "team",
    "mission",
    "command",
    "protected",
)

_SITREP_SELECT = (
    "SELECT s.id, s.level, s.template, s.body, s.author_id,"
    " s.mission_id, s.asset_id, s.created_at, s.version,"
    " s.location_label, s.lat, s.lon, s.location_precision, s.location_source,"
    " s.assignment_id, s.status, s.assigned_to, s.resolved_at,"
    " s.disposition, s.sensitivity,"
    " COALESCE(o.callsign, 'UNKNOWN'), a.label"
    " FROM sitreps s"
    " LEFT JOIN operators o ON s.author_id = o.id"
    " LEFT JOIN assets a ON s.asset_id = a.id"
)

_FOLLOWUP_SELECT = (
    "SELECT id, sitrep_id, action, note, author_id, assigned_to, status,"
    " created_at, version FROM sitrep_followups"
)

_DOCUMENT_LINK_SELECT = (
    "SELECT id, sitrep_id, document_id, description, created_by, created_at,"
    " version FROM sitrep_documents"
)


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
    assignment_id: typing.Optional[int] = None,
    location_label: str = "",
    lat: typing.Optional[float] = None,
    lon: typing.Optional[float] = None,
    location_precision: str = "",
    location_source: str = "",
    status: str = "open",
    assigned_to: str = "",
    disposition: str = "",
    sensitivity: str = "team",
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
    status = _clean_choice(status or "open", SITREP_STATUSES, "SITREP status")
    location_precision = _clean_choice(
        location_precision or "",
        SITREP_LOCATION_PRECISIONS,
        "location precision",
    )
    location_source = _clean_choice(
        location_source or "",
        SITREP_LOCATION_SOURCES,
        "location source",
    )
    sensitivity = _clean_choice(
        sensitivity or "team",
        SITREP_SENSITIVITIES,
        "SITREP sensitivity",
    )
    _require_fk(conn, "operators", int(author_id))
    _require_fk(conn, "missions", mission_id)
    _require_fk(conn, "assets", asset_id)
    _require_fk(conn, "assignments", assignment_id)
    lat = _optional_float(lat, "lat", -90.0, 90.0)
    lon = _optional_float(lon, "lon", -180.0, 180.0)
    if (lat is None) != (lon is None):
        raise ValueError("Both lat and lon are required for a SITREP location.")
    now = int(time.time())
    blob = encrypt_field(body.encode(), key)
    cursor = conn.execute(
        "INSERT INTO sitreps "
        "(level, template, body, author_id, mission_id, asset_id, created_at,"
        " uuid, sync_status, location_label, lat, lon, location_precision,"
        " location_source, assignment_id, status, assigned_to, disposition,"
        " sensitivity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            level,
            template,
            blob,
            author_id,
            mission_id,
            asset_id,
            now,
            _uuid_mod.uuid4().hex,
            sync_status,
            location_label.strip(),
            lat,
            lon,
            location_precision,
            location_source,
            assignment_id,
            status,
            assigned_to.strip(),
            disposition.strip(),
            sensitivity,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def delete_sitrep(conn: Connection, sitrep_id: int) -> tuple[int, ...]:
    """Permanently delete a SITREP.  Server operator only."""
    sitrep_id = int(sitrep_id)
    with conn.transaction():
        incident_rows = conn.execute(
            "SELECT id FROM incidents WHERE linked_sitrep_id = ?",
            (sitrep_id,),
        ).fetchall()
        conn.execute(
            "UPDATE incidents SET linked_sitrep_id = NULL, version = version + 1 "
            "WHERE linked_sitrep_id = ?",
            (sitrep_id,),
        )
        conn.execute("DELETE FROM sitrep_documents WHERE sitrep_id = ?", (sitrep_id,))
        conn.execute("DELETE FROM sitrep_followups WHERE sitrep_id = ?", (sitrep_id,))
        conn.execute("DELETE FROM sitreps WHERE id = ?", (sitrep_id,))
    return tuple(int(row[0]) for row in incident_rows)


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
    assignment_id: typing.Optional[int] = None,
    status_filter: typing.Optional[str] = None,
    unresolved_only: bool = False,
    level_filter: typing.Optional[str] = None,
    author_id: typing.Optional[int] = None,
    has_location: bool = False,
    pending_sync_only: bool = False,
    min_created_at: typing.Optional[int] = None,
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
    if assignment_id is not None:
        clauses.append("s.assignment_id = ?")
        params.append(assignment_id)
    if status_filter:
        clauses.append("s.status = ?")
        params.append(status_filter)
    if unresolved_only:
        clauses.append("s.status NOT IN ('resolved', 'closed')")
    if level_filter:
        clauses.append("s.level = ?")
        params.append(level_filter)
    if author_id is not None:
        clauses.append("s.author_id = ?")
        params.append(author_id)
    if has_location:
        clauses.append(
            "((s.lat IS NOT NULL AND s.lon IS NOT NULL) OR s.asset_id IS NOT NULL "
            "OR EXISTS (SELECT 1 FROM assignments assignment_location "
            "WHERE assignment_location.id = s.assignment_id "
            "AND assignment_location.lat IS NOT NULL "
            "AND assignment_location.lon IS NOT NULL))"
        )
    if pending_sync_only:
        clauses.append("s.sync_status = 'pending'")
    if min_created_at is not None:
        clauses.append("s.created_at >= ?")
        params.append(int(min_created_at))
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    rows = conn.execute(
        f"{_SITREP_SELECT} {where} ORDER BY s.created_at DESC LIMIT ?",
        params,
    ).fetchall()

    return [_row_to_sitrep_entry(row, key) for row in rows]


def get_sitrep(
    conn: Connection,
    key: bytes,
    sitrep_id: int,
) -> tuple[Sitrep, str, typing.Optional[str]]:
    row = conn.execute(
        f"{_SITREP_SELECT} WHERE s.id = ?",
        (int(sitrep_id),),
    ).fetchone()
    if row is None:
        raise ValueError(f"SITREP {sitrep_id} not found.")
    return _row_to_sitrep_entry(row, key)


def create_sitrep_followup(
    conn: Connection,
    *,
    sitrep_id: int,
    action: str,
    author_id: int,
    note: str = "",
    assigned_to: str = "",
    status: str = "",
    sync_status: str = "synced",
) -> SitrepFollowUp:
    action = _clean_choice(action, SITREP_FOLLOWUP_ACTIONS, "SITREP follow-up action")
    _require_fk(conn, "sitreps", int(sitrep_id))
    _require_fk(conn, "operators", int(author_id))
    if status:
        status = _clean_choice(status, SITREP_STATUSES, "SITREP status")
    now = int(time.time())
    with conn.transaction():
        cursor = conn.execute(
            "INSERT INTO sitrep_followups ("
            " sitrep_id, action, note, author_id, assigned_to, status,"
            " created_at, uuid, sync_status"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(sitrep_id),
                action,
                note.strip(),
                int(author_id),
                assigned_to.strip(),
                status,
                now,
                _uuid_mod.uuid4().hex,
                sync_status,
            ),
        )
        _apply_followup_effect_fields(
            conn,
            sitrep_id=int(sitrep_id),
            action=action,
            note=note.strip(),
            assigned_to=assigned_to.strip(),
            status=status,
            now=now,
        )
    return typing.cast(SitrepFollowUp, get_sitrep_followup(conn, int(cursor.lastrowid)))


def get_sitrep_followup(
    conn: Connection,
    followup_id: int,
) -> typing.Optional[SitrepFollowUp]:
    row = conn.execute(
        f"{_FOLLOWUP_SELECT} WHERE id = ?",
        (int(followup_id),),
    ).fetchone()
    return _row_to_followup(row) if row else None


def list_sitrep_followups(
    conn: Connection,
    *,
    sitrep_id: int,
    limit: int = 100,
) -> list[SitrepFollowUp]:
    rows = conn.execute(
        f"{_FOLLOWUP_SELECT} WHERE sitrep_id = ? "
        "ORDER BY created_at ASC, id ASC LIMIT ?",
        (int(sitrep_id), int(limit)),
    ).fetchall()
    return [_row_to_followup(row) for row in rows]


def apply_sitrep_followup_effect(conn: Connection, followup_id: int) -> int:
    """Apply parent summary fields for a client-pushed follow-up row.

    Returns the linked SITREP id. The original encrypted SITREP body is never
    edited; only state summary fields are updated from append-only child data.
    """
    followup = get_sitrep_followup(conn, followup_id)
    if followup is None:
        raise ValueError(f"SITREP follow-up {followup_id} not found.")
    _apply_followup_effect_fields(
        conn,
        sitrep_id=followup.sitrep_id,
        action=followup.action,
        note=followup.note,
        assigned_to=followup.assigned_to,
        status=followup.status,
        now=followup.created_at,
    )
    conn.commit()
    return followup.sitrep_id


def link_sitrep_document(
    conn: Connection,
    *,
    sitrep_id: int,
    document_id: int,
    created_by: int,
    description: str = "",
    sync_status: str = "synced",
) -> SitrepDocumentLink:
    _require_fk(conn, "sitreps", int(sitrep_id))
    _require_fk(conn, "documents", int(document_id))
    _require_fk(conn, "operators", int(created_by))
    now = int(time.time())
    cursor = conn.execute(
        "INSERT OR IGNORE INTO sitrep_documents ("
        " sitrep_id, document_id, description, created_by, created_at,"
        " uuid, sync_status"
        ") VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            int(sitrep_id),
            int(document_id),
            description.strip(),
            int(created_by),
            now,
            _uuid_mod.uuid4().hex,
            sync_status,
        ),
    )
    inserted = cursor.rowcount > 0
    if inserted:
        link_id = int(cursor.lastrowid)
    else:
        row = conn.execute(
            "SELECT id FROM sitrep_documents WHERE sitrep_id = ? AND document_id = ?",
            (int(sitrep_id), int(document_id)),
        ).fetchone()
        if row is None:
            raise ValueError("Could not link SITREP document.")
        link_id = int(row[0])
    if inserted:
        create_sitrep_followup(
            conn,
            sitrep_id=int(sitrep_id),
            action="document_linked",
            author_id=int(created_by),
            note=description.strip() or f"Document #{document_id} linked.",
            sync_status=sync_status,
        )
    conn.commit()
    return typing.cast(SitrepDocumentLink, get_sitrep_document_link(conn, link_id))


def get_sitrep_document_link(
    conn: Connection,
    link_id: int,
) -> typing.Optional[SitrepDocumentLink]:
    row = conn.execute(
        f"{_DOCUMENT_LINK_SELECT} WHERE id = ?",
        (int(link_id),),
    ).fetchone()
    return _row_to_document_link(row) if row else None


def list_sitrep_document_links(
    conn: Connection,
    *,
    sitrep_id: int,
) -> list[SitrepDocumentLink]:
    rows = conn.execute(
        f"{_DOCUMENT_LINK_SELECT} WHERE sitrep_id = ? "
        "ORDER BY created_at ASC, id ASC",
        (int(sitrep_id),),
    ).fetchall()
    return [_row_to_document_link(row) for row in rows]


def _apply_followup_effect_fields(
    conn: Connection,
    *,
    sitrep_id: int,
    action: str,
    note: str,
    assigned_to: str,
    status: str,
    now: int,
) -> None:
    fields: list[str] = []
    params: list[object] = []
    if action == "acknowledged":
        fields.append(
            "status = CASE WHEN status = 'open' THEN 'acknowledged' ELSE status END"
        )
    elif action == "assigned":
        fields.append("status = 'assigned'")
        fields.append("assigned_to = ?")
        params.append(assigned_to or note)
    elif action in {"status", "resolved"} and status:
        fields.append("status = ?")
        params.append(status)
        if status in {"resolved", "closed"}:
            fields.append("resolved_at = COALESCE(resolved_at, ?)")
            params.append(now)
            if note:
                fields.append("disposition = ?")
                params.append(note)
    if not fields:
        return
    fields.append("version = version + 1")
    params.append(int(sitrep_id))
    conn.execute(
        f"UPDATE sitreps SET {', '.join(fields)} WHERE id = ?",
        params,
    )


def _row_to_sitrep_entry(
    row: tuple,
    key: bytes,
) -> tuple[Sitrep, str, typing.Optional[str]]:
    try:
        body_bytes = decrypt_field(row[3], key)
    except Exception:
        body_bytes = b"[encrypted]"
    sitrep = Sitrep(
        id=int(row[0]),
        level=str(row[1]),
        template=str(row[2] or ""),
        body=body_bytes,
        author_id=int(row[4]),
        mission_id=_maybe_int(row[5]),
        asset_id=_maybe_int(row[6]),
        created_at=int(row[7]),
        version=int(row[8]),
        location_label=str(row[9] or ""),
        lat=_maybe_float(row[10]),
        lon=_maybe_float(row[11]),
        location_precision=str(row[12] or ""),
        location_source=str(row[13] or ""),
        assignment_id=_maybe_int(row[14]),
        status=str(row[15] or "open"),
        assigned_to=str(row[16] or ""),
        resolved_at=_maybe_int(row[17]),
        disposition=str(row[18] or ""),
        sensitivity=str(row[19] or "team"),
    )
    return (sitrep, str(row[20]), typing.cast(typing.Optional[str], row[21]))


def _row_to_followup(row: tuple) -> SitrepFollowUp:
    return SitrepFollowUp(
        id=int(row[0]),
        sitrep_id=int(row[1]),
        action=str(row[2] or ""),
        note=str(row[3] or ""),
        author_id=int(row[4]),
        assigned_to=str(row[5] or ""),
        status=str(row[6] or ""),
        created_at=int(row[7]),
        version=int(row[8]),
    )


def _row_to_document_link(row: tuple) -> SitrepDocumentLink:
    return SitrepDocumentLink(
        id=int(row[0]),
        sitrep_id=int(row[1]),
        document_id=int(row[2]),
        description=str(row[3] or ""),
        created_by=int(row[4]),
        created_at=int(row[5]),
        version=int(row[6]),
    )


def _clean_choice(value: str, choices: tuple[str, ...], label: str) -> str:
    cleaned = str(value or "").strip()
    if cleaned not in choices:
        raise ValueError(f"Unknown {label}: {cleaned!r}.")
    return cleaned


def _require_fk(
    conn: Connection,
    table: str,
    record_id: typing.Optional[int],
) -> None:
    if record_id is None:
        return
    row = conn.execute(
        f"SELECT id FROM {table} WHERE id = ?",  # noqa: S608
        (int(record_id),),
    ).fetchone()
    if row is None:
        raise ValueError(f"{table} record {record_id} not found.")


def _optional_float(
    value: typing.Any,
    field: str,
    minimum: float,
    maximum: float,
) -> typing.Optional[float]:
    if value is None or value == "":
        return None
    result = float(value)
    if result < minimum or result > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}.")
    return result


def _maybe_int(value: typing.Any) -> typing.Optional[int]:
    if value is None:
        return None
    return int(value)


def _maybe_float(value: typing.Any) -> typing.Optional[float]:
    if value is None:
        return None
    return float(value)

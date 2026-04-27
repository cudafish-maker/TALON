"""
Zone data access — create, query, and delete map zones.

Zones are named polygon overlays on the tactical map:
  AO          — Area of Operations
  DANGER      — Danger area
  RESTRICTED  — Restricted area
  FRIENDLY    — Friendly controlled area
  OBJECTIVE   — Objective marker
  custom      — Operator-defined

A zone is typically linked to a mission (mission_id).  Standalone zones
(mission_id IS NULL) are also valid and persist independently.

The polygon is stored as a JSON array of [lat, lon] pairs.
"""
import json
import time
import typing
import uuid as _uuid_mod

from talon_core.db.connection import Connection
from talon_core.db.models import Zone

ZONE_TYPES: tuple[str, ...] = (
    "AO", "DANGER", "RESTRICTED", "FRIENDLY", "OBJECTIVE",
)


def create_zone(
    conn: Connection,
    *,
    zone_type: str,
    label: str,
    polygon: list[list[float]],
    mission_id: typing.Optional[int] = None,
    created_by: int,
) -> Zone:
    """
    Insert a new zone.

    polygon must be [[lat, lon], ...] with at least 3 vertices.
    Raises ValueError for unknown zone_type or too few vertices.
    """
    if zone_type not in (*ZONE_TYPES, "custom"):
        raise ValueError(f"Unknown zone type: {zone_type!r}")
    if len(polygon) < 3:
        raise ValueError("A zone polygon requires at least 3 vertices.")
    for i, (vlat, vlon) in enumerate(polygon):
        if not (-90.0 <= vlat <= 90.0):
            raise ValueError(f"Vertex {i}: latitude {vlat} out of range (−90 to +90).")
        if not (-180.0 <= vlon <= 180.0):
            raise ValueError(f"Vertex {i}: longitude {vlon} out of range (−180 to +180).")
    now = int(time.time())
    poly_json = json.dumps(polygon)
    cursor = conn.execute(
        "INSERT INTO zones (label, zone_type, polygon, mission_id, created_by, created_at, uuid) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (label, zone_type, poly_json, mission_id, created_by, now, _uuid_mod.uuid4().hex),
    )
    conn.commit()
    return Zone(
        id=cursor.lastrowid,
        label=label,
        zone_type=zone_type,
        polygon=polygon,
        mission_id=mission_id,
        created_by=created_by,
        created_at=now,
        version=1,
    )


def load_zones(
    conn: Connection,
    *,
    mission_id: typing.Optional[int] = None,
    limit: int = 500,
) -> list[Zone]:
    """Load zones, optionally filtered to a specific mission, newest first."""
    clauses: list[str] = []
    params: list[object] = []
    if mission_id is not None:
        clauses.append("mission_id = ?")
        params.append(mission_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT id, label, zone_type, polygon, mission_id, created_by, created_at, version "
        f"FROM zones {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [_row_to_zone(r) for r in rows]


def get_zone(conn: Connection, zone_id: int) -> typing.Optional[Zone]:
    """Fetch a single zone by id, or None if not found."""
    row = conn.execute(
        "SELECT id, label, zone_type, polygon, mission_id, created_by, created_at, version "
        "FROM zones WHERE id = ?",
        (zone_id,),
    ).fetchone()
    return _row_to_zone(row) if row else None


def delete_zone(conn: Connection, zone_id: int) -> None:
    """Permanently delete a zone.  Server operator only."""
    conn.execute("DELETE FROM zones WHERE id = ?", (zone_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_zone(row: tuple) -> Zone:
    try:
        polygon = json.loads(row[3]) if row[3] else []
    except (json.JSONDecodeError, TypeError):
        polygon = []
    return Zone(
        id=row[0],
        label=row[1],
        zone_type=row[2],
        polygon=polygon,
        mission_id=row[4],
        created_by=row[5],
        created_at=row[6],
        version=row[7],
    )

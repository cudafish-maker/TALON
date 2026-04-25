"""
Waypoint data access — create and query ordered route waypoints for missions.

Waypoints are an ordered sequence of named lat/lon points that form a tactical
route for a mission.  They are always linked to a mission (mission_id NOT NULL).

Sequence numbers are 1-based and contiguous.  Replacing a route deletes all
existing waypoints for the mission and inserts the new set.
"""
import typing
import uuid as _uuid_mod

from talon.db.connection import Connection
from talon.db.models import Waypoint


def create_waypoints_for_mission(
    conn: Connection,
    mission_id: int,
    waypoints: list[tuple[float, float]],
    *,
    labels: typing.Optional[list[str]] = None,
) -> list[Waypoint]:
    """
    Bulk-insert an ordered set of waypoints for a mission.

    waypoints — ordered list of (lat, lon) pairs.
    labels    — optional display labels (same length); auto-generates "WP-N" if
                None or shorter than the waypoints list.

    Raises ValueError if waypoints is empty or the insert fails.
    """
    if not waypoints:
        raise ValueError("At least one waypoint is required.")
    if labels is None:
        labels = []
    resolved: list[str] = [
        labels[i] if i < len(labels) and labels[i].strip() else f"WP-{i + 1}"
        for i in range(len(waypoints))
    ]
    created: list[Waypoint] = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        for i, (lat, lon) in enumerate(waypoints):
            if not (-90.0 <= lat <= 90.0):
                raise ValueError(
                    f"Waypoint {i + 1}: latitude {lat} out of range (−90 to +90)."
                )
            if not (-180.0 <= lon <= 180.0):
                raise ValueError(
                    f"Waypoint {i + 1}: longitude {lon} out of range (−180 to +180)."
                )
            cursor = conn.execute(
                "INSERT INTO waypoints (mission_id, sequence, label, lat, lon, uuid) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (mission_id, i + 1, resolved[i], lat, lon, _uuid_mod.uuid4().hex),
            )
            created.append(Waypoint(
                id=cursor.lastrowid,
                mission_id=mission_id,
                sequence=i + 1,
                label=resolved[i],
                lat=lat,
                lon=lon,
                version=1,
            ))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise ValueError(f"Could not save waypoints: {exc}") from exc
    return created


def load_waypoints(conn: Connection, mission_id: int) -> list[Waypoint]:
    """Return all waypoints for a mission, ordered by sequence (1-based)."""
    rows = conn.execute(
        "SELECT id, mission_id, sequence, label, lat, lon, version "
        "FROM waypoints WHERE mission_id = ? ORDER BY sequence ASC",
        (mission_id,),
    ).fetchall()
    return [
        Waypoint(
            id=r[0], mission_id=r[1], sequence=r[2],
            label=r[3], lat=r[4], lon=r[5], version=r[6],
        )
        for r in rows
    ]

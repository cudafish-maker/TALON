"""Operator location ping creation and read models."""
from __future__ import annotations

import math
import time
import typing
import uuid

from talon_core.constants import OPERATOR_LOCATION_PING_TTL_S
from talon_core.db.connection import Connection
from talon_core.db.models import OperatorLocationPing


def create_operator_location_ping(
    conn: Connection,
    *,
    operator_id: int,
    lat: float,
    lon: float,
    accuracy_m: typing.Optional[float] = None,
    source: str = "manual_map",
    note: str = "",
    mission_id: typing.Optional[int] = None,
    created_at: typing.Optional[int] = None,
    expires_at: typing.Optional[int] = None,
    ttl_s: int = OPERATOR_LOCATION_PING_TTL_S,
    sync_status: str = "synced",
) -> int:
    """Create a durable operator map ping and return its record id."""
    operator_id = _required_int(operator_id, "operator_id")
    lat = _required_float(lat, "lat", -90.0, 90.0)
    lon = _required_float(lon, "lon", -180.0, 180.0)
    accuracy = _optional_accuracy(accuracy_m)
    mission = _optional_int(mission_id, "mission_id")
    created = int(created_at if created_at is not None else time.time())
    expires = int(expires_at if expires_at is not None else created + int(ttl_s))
    if expires <= created:
        raise ValueError("expires_at must be after created_at.")
    clean_source = str(source or "manual_map").strip() or "manual_map"
    clean_note = str(note or "").strip()

    cursor = conn.execute(
        "INSERT INTO operator_location_pings "
        "(operator_id, lat, lon, accuracy_m, source, note, created_at, "
        "expires_at, mission_id, uuid, sync_status, version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (
            operator_id,
            lat,
            lon,
            accuracy,
            clean_source,
            clean_note,
            created,
            expires,
            mission,
            uuid.uuid4().hex,
            sync_status,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def load_latest_operator_location_pings(
    conn: Connection,
    *,
    mission_id: typing.Optional[int] = None,
    active_only: bool = True,
    now: typing.Optional[int] = None,
    limit: int = 500,
) -> list[OperatorLocationPing]:
    """Return latest pings, normally one non-expired ping per operator."""
    query_now = int(now if now is not None else time.time())
    clauses: list[str] = []
    params: list[object] = []
    if active_only:
        clauses.append("p.expires_at > ?")
        params.append(query_now)
    if mission_id is not None:
        clauses.append("p.mission_id = ?")
        params.append(int(mission_id))
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, int(limit)))
    rows = conn.execute(
        "SELECT p.id, p.operator_id, COALESCE(o.callsign, 'UNKNOWN'), "
        "p.lat, p.lon, p.accuracy_m, p.source, p.note, p.created_at, "
        "p.expires_at, p.mission_id, p.version "
        "FROM operator_location_pings p "
        "LEFT JOIN operators o ON o.id = p.operator_id "
        f"{where} "
        "ORDER BY p.created_at DESC, p.id DESC "
        "LIMIT ?",
        params,
    ).fetchall()

    latest: dict[int, OperatorLocationPing] = {}
    for row in rows:
        operator_id = int(row[1])
        if operator_id in latest:
            continue
        latest[operator_id] = OperatorLocationPing(
            id=int(row[0]),
            operator_id=operator_id,
            operator_callsign=str(row[2]),
            lat=float(row[3]),
            lon=float(row[4]),
            accuracy_m=float(row[5]) if row[5] is not None else None,
            source=str(row[6] or ""),
            note=str(row[7] or ""),
            created_at=int(row[8]),
            expires_at=int(row[9]),
            mission_id=int(row[10]) if row[10] is not None else None,
            version=int(row[11]),
        )
    return sorted(latest.values(), key=lambda item: item.created_at, reverse=True)


def _required_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer.") from exc


def _optional_int(value: object, field: str) -> int | None:
    if value is None or value == "":
        return None
    return _required_int(value, field)


def _required_float(value: object, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number.") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{field} out of range.")
    return number


def _optional_accuracy(value: object) -> float | None:
    if value is None or value == "":
        return None
    number = _required_float(value, "accuracy_m", 0.0, 1_000_000.0)
    return number

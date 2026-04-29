"""
Asset data access — create, query, and update assets.

Assets represent real-world entities: people, safe houses, caches, rally
points, vehicles, and custom items.  They start as unverified; a second
operator or the server must physically confirm them to set verified=True.
"""
import time
import typing
import uuid as _uuid_mod

from talon_core.constants import ASSET_CATEGORIES
from talon_core.db.connection import Connection
from talon_core.db.models import Asset

# Sentinel: pass as a field value to explicitly write NULL (distinct from "not supplied").
_CLEAR = object()

# All valid category strings (predefined + custom).
_ALL_CATEGORIES: frozenset[str] = frozenset((*ASSET_CATEGORIES, "custom"))

# Display helpers shared with UI layers (canonical source — import from here, don't copy).
CATEGORY_LABEL: dict[str, str] = {
    "person":      "Person",
    "safe_house":  "Safe House",
    "cache":       "Cache",
    "rally_point": "Rally Point",
    "vehicle":     "Vehicle",
    "custom":      "Custom",
}

CATEGORY_COLOR: dict[str, tuple] = {
    "person":      (0.13, 0.59, 0.95, 1),   # blue
    "safe_house":  (0.18, 0.49, 0.20, 1),   # green
    "cache":       (1.00, 0.76, 0.03, 1),   # amber
    "rally_point": (0.00, 0.75, 0.75, 1),   # cyan
    "vehicle":     (1.00, 0.50, 0.00, 1),   # orange
    "custom":      (0.60, 0.60, 0.60, 1),   # grey
}


def create_asset(
    conn: Connection,
    *,
    author_id: int,
    category: str,
    label: str,
    description: str = "",
    lat: typing.Optional[float] = None,
    lon: typing.Optional[float] = None,
    sync_status: str = "synced",
) -> int:
    """
    Insert a new asset.  Returns the new row id.

    Pass sync_status='pending' when creating while offline (client mode only);
    the record will be pushed to the server on next reconnect.

    Raises ValueError for unknown category or empty label.
    """
    if category not in _ALL_CATEGORIES:
        raise ValueError(f"Unknown asset category: {category!r}")
    if not label.strip():
        raise ValueError("Asset label is required.")
    if lat is not None and not (-90.0 <= lat <= 90.0):
        raise ValueError(f"Latitude {lat} out of range (−90 to +90).")
    if lon is not None and not (-180.0 <= lon <= 180.0):
        raise ValueError(f"Longitude {lon} out of range (−180 to +180).")
    now = int(time.time())
    cursor = conn.execute(
        "INSERT INTO assets "
        "(category, label, description, lat, lon, verified, created_by, created_at, uuid, sync_status) "
        "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
        (category, label.strip(), description.strip(), lat, lon, author_id, now,
         _uuid_mod.uuid4().hex, sync_status),
    )
    conn.commit()
    return cursor.lastrowid


def load_assets(
    conn: Connection,
    *,
    category: typing.Optional[str] = None,
    available_only: bool = False,
    limit: int = 500,
) -> list[Asset]:
    """Load assets, optionally filtered by category or availability, newest first.

    available_only=True returns only assets not currently requested/allocated
    to any mission (mission_id IS NULL).
    """
    clauses: list[str] = []
    params: list[object] = []
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    if available_only:
        clauses.append("mission_id IS NULL")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT id, category, label, description, lat, lon, verified, "
        f"created_by, confirmed_by, created_at, version, mission_id, deletion_requested "
        f"FROM assets {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [_row_to_asset(r) for r in rows]


def get_asset(conn: Connection, asset_id: int) -> typing.Optional[Asset]:
    """Fetch a single asset by id, or None if not found."""
    row = conn.execute(
        "SELECT id, category, label, description, lat, lon, verified, "
        "created_by, confirmed_by, created_at, version, mission_id, deletion_requested "
        "FROM assets WHERE id = ?",
        (asset_id,),
    ).fetchone()
    return _row_to_asset(row) if row else None


def update_asset(
    conn: Connection,
    asset_id: int,
    *,
    label: typing.Optional[str] = None,
    description: typing.Optional[str] = None,
    lat: typing.Optional[float] = None,
    lon: typing.Optional[float] = None,
    verified: typing.Optional[bool] = None,
    confirmed_by: typing.Optional[int] = None,
) -> None:
    """
    Update mutable fields on an existing asset.  Only supplied (non-None)
    fields are written; omitted fields are left unchanged.

    Pass verified=True together with confirmed_by=<operator_id> when
    physically confirming an asset.
    """
    fields: list[str] = []
    params: list[object] = []
    if label is not None:
        if not label.strip():
            raise ValueError("Asset label is required.")
        fields.append("label = ?")
        params.append(label.strip())
    if description is not None:
        fields.append("description = ?")
        params.append(description.strip())
    if lat is _CLEAR:
        fields.append("lat = NULL")
    elif lat is not None:
        fields.append("lat = ?")
        params.append(lat)
    if lon is _CLEAR:
        fields.append("lon = NULL")
    elif lon is not None:
        fields.append("lon = ?")
        params.append(lon)
    if verified is not None:
        fields.append("verified = ?")
        params.append(1 if verified else 0)
    if confirmed_by is _CLEAR:
        fields.append("confirmed_by = NULL")
    elif confirmed_by is not None:
        fields.append("confirmed_by = ?")
        params.append(confirmed_by)
    if not fields:
        return
    fields.append("version = version + 1")
    params.append(asset_id)
    conn.execute(
        f"UPDATE assets SET {', '.join(fields)} WHERE id = ?",
        params,
    )
    conn.commit()


def request_asset_deletion(conn: Connection, asset_id: int) -> None:
    """Flag an asset as deletion-requested.  Client-callable; server acts on it.

    Sets deletion_requested=1 and bumps version so the flag syncs to the server.
    Does NOT delete the record — only the server operator can hard-delete.
    """
    conn.execute(
        "UPDATE assets SET deletion_requested = 1, version = version + 1 WHERE id = ?",
        (asset_id,),
    )
    conn.commit()


def delete_asset(conn: Connection, asset_id: int) -> None:
    """Permanently delete an asset.  Server operator only.

    Any SITREPs linked to this asset have their asset_id set to NULL first so
    the FK constraint (enforced by PRAGMA foreign_keys=ON) does not block the
    delete.  Both writes are committed together.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE sitreps SET asset_id = NULL, version = version + 1 WHERE asset_id = ?",
            (asset_id,),
        )
        conn.execute(
            "UPDATE incidents SET linked_asset_id = NULL, version = version + 1 "
            "WHERE linked_asset_id = ?",
            (asset_id,),
        )
        conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise ValueError(f"Could not delete asset: {exc}") from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_asset(row: tuple) -> Asset:
    return Asset(
        id=row[0],
        category=row[1],
        label=row[2],
        description=row[3],
        lat=row[4],
        lon=row[5],
        verified=bool(row[6]),
        created_by=row[7],
        confirmed_by=row[8],
        created_at=row[9],
        version=row[10],
        mission_id=row[11],
        deletion_requested=bool(row[12]) if len(row) > 12 else False,
    )

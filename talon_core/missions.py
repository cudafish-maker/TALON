"""
Mission data access — create, query, and manage tactical missions.

Workflow:
  1. Any operator calls create_mission() → status: pending_approval
     Requested assets have mission_id set immediately so others see "REQUESTED".
  2. Server operator calls approve_mission() → status: active
     Server may modify the asset list before approving.
     #mission-<slug> channel is created at this point.
  3. Mission ends via complete_mission() or abort_mission() → assets released.
     Or server calls reject_mission() on a pending mission → assets released.
  4. Server may delete_mission() at any time → all linked data unlinked, row removed.
"""
import json
import re
import time
import typing
import uuid as _uuid_mod

from talon_core.db.connection import Connection
from talon_core.db.models import Asset, Mission

MISSION_STATUSES: tuple[str, ...] = (
    "pending_approval",
    "active",
    "rejected",
    "completed",
    "aborted",
)


def _slugify(title: str) -> str:
    """Convert a mission title to a lowercase channel-safe slug."""
    slug = re.sub(r"[^a-zA-Z0-9\-_]", "-", title.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "mission"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def create_mission(
    conn: Connection,
    *,
    title: str,
    description: str = "",
    created_by: int,
    asset_ids: typing.Optional[list[int]] = None,
    # Extended fields (migration 0013)
    mission_type: str = "",
    priority: str = "ROUTINE",
    lead_coordinator: str = "",
    organization: str = "",
    activation_time: str = "",
    operation_window: str = "",
    max_duration: str = "",
    staging_area: str = "",
    demob_point: str = "",
    standdown_criteria: str = "",
    phases: typing.Optional[list] = None,
    constraints: typing.Optional[list] = None,
    support_medical: str = "",
    support_logistics: str = "",
    support_comms: str = "",
    support_equipment: str = "",
    custom_resources: typing.Optional[list] = None,
    objectives: typing.Optional[list] = None,
    key_locations: typing.Optional[dict] = None,
) -> Mission:
    """
    Submit a new mission for server approval.

    Requested assets have their mission_id set immediately so other operators
    can see they are pending allocation.  The channel is NOT created yet —
    that happens on approval.

    Raises ValueError for empty title, or if any requested asset is already
    allocated to another mission.
    """
    if not title.strip():
        raise ValueError("Mission title is required.")
    asset_ids = list(asset_ids or [])
    phases_json = json.dumps(phases or [])
    constraints_json = json.dumps(constraints or [])
    custom_resources_json = json.dumps(custom_resources or [])
    objectives_json = json.dumps(objectives or [])
    key_locations_json = json.dumps(key_locations or {})

    now = int(time.time())
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "INSERT INTO missions ("
            "  title, description, status, created_by, created_at, uuid,"
            "  mission_type, priority, lead_coordinator, organization,"
            "  activation_time, operation_window, max_duration,"
            "  staging_area, demob_point, standdown_criteria,"
            "  phases, constraints,"
            "  support_medical, support_logistics, support_comms, support_equipment,"
            "  custom_resources,"
            "  objectives, key_locations"
            ") VALUES (?,?,'pending_approval',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                title.strip(), description.strip(), created_by, now, _uuid_mod.uuid4().hex,
                mission_type, priority, lead_coordinator, organization,
                activation_time, operation_window, max_duration,
                staging_area, demob_point, standdown_criteria,
                phases_json, constraints_json,
                support_medical, support_logistics, support_comms, support_equipment,
                custom_resources_json,
                objectives_json, key_locations_json,
            ),
        )
        mission_id = cursor.lastrowid

        if asset_ids:
            placeholders = ",".join("?" * len(asset_ids))
            taken = conn.execute(
                f"SELECT id, label FROM assets "
                f"WHERE id IN ({placeholders}) AND mission_id IS NOT NULL",
                asset_ids,
            ).fetchall()
            if taken:
                labels = ", ".join(r[1] for r in taken)
                raise ValueError(
                    f"The following assets are already allocated to another mission: {labels}"
                )
            conn.executemany(
                "UPDATE assets SET mission_id = ?, version = version + 1 WHERE id = ?",
                [(mission_id, aid) for aid in asset_ids],
            )
        conn.commit()
    except ValueError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise ValueError(f"Could not create mission: {exc}") from exc

    return Mission(
        id=mission_id,
        title=title.strip(),
        description=description.strip(),
        status="pending_approval",
        created_by=created_by,
        created_at=now,
        version=1,
        mission_type=mission_type,
        priority=priority,
        lead_coordinator=lead_coordinator,
        organization=organization,
        activation_time=activation_time,
        operation_window=operation_window,
        max_duration=max_duration,
        staging_area=staging_area,
        demob_point=demob_point,
        standdown_criteria=standdown_criteria,
        phases=phases or [],
        constraints=constraints or [],
        support_medical=support_medical,
        support_logistics=support_logistics,
        support_comms=support_comms,
        support_equipment=support_equipment,
        custom_resources=custom_resources or [],
        objectives=objectives or [],
        key_locations=key_locations or {},
    )


def approve_mission(
    conn: Connection,
    mission_id: int,
    *,
    asset_ids: typing.Optional[list[int]] = None,
) -> str:
    """
    Approve a pending mission.  Server operator only.

    asset_ids — if supplied, replaces the operator's requested asset list.
    If None, the originally requested assets are kept as-is.

    Returns the channel name that was created (e.g. "#mission-op-northwest").
    Raises ValueError if the mission is not in pending_approval state, or if
    any of the new asset_ids are already allocated to a different mission.
    """
    channel_name: str

    try:
        # BEGIN IMMEDIATE before the status read — eliminates the TOCTOU window
        # where two concurrent calls could both pass the pending_approval guard.
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            "SELECT title, status FROM missions WHERE id = ?", (mission_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Mission {mission_id} not found.")
        if row[1] != "pending_approval":
            raise ValueError(f"Mission is '{row[1]}', not pending_approval.")

        channel_name = f"#mission-{_slugify(row[0])}-{mission_id}"

        if asset_ids is not None:
            requested_ids = set(asset_ids)
            current_ids = {
                r[0] for r in conn.execute(
                    "SELECT id FROM assets WHERE mission_id = ?", (mission_id,)
                ).fetchall()
            }
            if requested_ids:
                placeholders = ",".join("?" * len(requested_ids))
                taken = conn.execute(
                    f"SELECT id, label FROM assets "
                    f"WHERE id IN ({placeholders}) "
                    f"AND mission_id IS NOT NULL AND mission_id != ?",
                    [*requested_ids, mission_id],
                ).fetchall()
                if taken:
                    labels = ", ".join(r[1] for r in taken)
                    raise ValueError(
                        f"Assets already allocated to another mission: {labels}"
                    )
            release_ids = sorted(current_ids - requested_ids)
            assign_ids = sorted(requested_ids - current_ids)
            if release_ids:
                conn.executemany(
                    "UPDATE assets SET mission_id = NULL, version = version + 1 WHERE id = ?",
                    [(aid,) for aid in release_ids],
                )
            if assign_ids:
                conn.executemany(
                    "UPDATE assets SET mission_id = ?, version = version + 1 WHERE id = ?",
                    [(mission_id, aid) for aid in assign_ids],
                )

        # Create the mission channel
        conn.execute(
            "INSERT OR IGNORE INTO channels (name, mission_id, is_dm, version) "
            "VALUES (?, ?, 0, 1)",
            (channel_name, mission_id),
        )

        conn.execute(
            "UPDATE missions SET status = 'active', version = version + 1 "
            "WHERE id = ?",
            (mission_id,),
        )
        conn.commit()
    except ValueError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise ValueError(f"Could not approve mission: {exc}") from exc

    return channel_name  # set inside the try block before any raises


def update_mission(
    conn: Connection,
    mission_id: int,
    *,
    title: str,
    description: str = "",
    asset_ids: typing.Optional[list[int]] = None,
    mission_type: str = "",
    priority: str = "ROUTINE",
    lead_coordinator: str = "",
    organization: str = "",
    activation_time: str = "",
    operation_window: str = "",
    max_duration: str = "",
    staging_area: str = "",
    demob_point: str = "",
    standdown_criteria: str = "",
    phases: typing.Optional[list] = None,
    constraints: typing.Optional[list] = None,
    support_medical: str = "",
    support_logistics: str = "",
    support_comms: str = "",
    support_equipment: str = "",
    custom_resources: typing.Optional[list] = None,
    objectives: typing.Optional[list] = None,
    key_locations: typing.Optional[dict] = None,
) -> Mission:
    """Update server-controlled mission parameters without changing lifecycle state."""
    if not title.strip():
        raise ValueError("Mission title is required.")
    selected_asset_ids = list(asset_ids) if asset_ids is not None else None
    phases_json = json.dumps(phases or [])
    constraints_json = json.dumps(constraints or [])
    custom_resources_json = json.dumps(custom_resources or [])
    objectives_json = json.dumps(objectives or [])
    key_locations_json = json.dumps(key_locations or {})

    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id FROM missions WHERE id = ?",
            (mission_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Mission {mission_id} not found.")

        if selected_asset_ids is not None:
            current_ids = {
                r[0] for r in conn.execute(
                    "SELECT id FROM assets WHERE mission_id = ?",
                    (mission_id,),
                ).fetchall()
            }
            requested_ids = set(selected_asset_ids)
            if requested_ids:
                placeholders = ",".join("?" * len(requested_ids))
                taken = conn.execute(
                    f"SELECT id, label FROM assets "
                    f"WHERE id IN ({placeholders}) "
                    f"AND mission_id IS NOT NULL AND mission_id != ?",
                    [*requested_ids, mission_id],
                ).fetchall()
                if taken:
                    labels = ", ".join(r[1] for r in taken)
                    raise ValueError(
                        f"Assets already allocated to another mission: {labels}"
                    )
            release_ids = sorted(current_ids - requested_ids)
            assign_ids = sorted(requested_ids - current_ids)
            if release_ids:
                conn.executemany(
                    "UPDATE assets SET mission_id = NULL, version = version + 1 WHERE id = ?",
                    [(aid,) for aid in release_ids],
                )
            if assign_ids:
                conn.executemany(
                    "UPDATE assets SET mission_id = ?, version = version + 1 WHERE id = ?",
                    [(mission_id, aid) for aid in assign_ids],
                )

        conn.execute(
            "UPDATE missions SET "
            "title = ?, description = ?, mission_type = ?, priority = ?, "
            "lead_coordinator = ?, organization = ?, activation_time = ?, "
            "operation_window = ?, max_duration = ?, staging_area = ?, "
            "demob_point = ?, standdown_criteria = ?, phases = ?, constraints = ?, "
            "support_medical = ?, support_logistics = ?, support_comms = ?, "
            "support_equipment = ?, custom_resources = ?, objectives = ?, "
            "key_locations = ?, version = version + 1 "
            "WHERE id = ?",
            (
                title.strip(),
                description.strip(),
                mission_type,
                priority,
                lead_coordinator,
                organization,
                activation_time,
                operation_window,
                max_duration,
                staging_area,
                demob_point,
                standdown_criteria,
                phases_json,
                constraints_json,
                support_medical,
                support_logistics,
                support_comms,
                support_equipment,
                custom_resources_json,
                objectives_json,
                key_locations_json,
                mission_id,
            ),
        )
        conn.commit()
    except ValueError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise ValueError(f"Could not update mission: {exc}") from exc

    mission = get_mission(conn, mission_id)
    if mission is None:
        raise ValueError(f"Mission {mission_id} not found.")
    return mission


def reject_mission(conn: Connection, mission_id: int) -> None:
    """Reject a pending mission.  Server operator only.  Releases asset allocations."""
    _transition(conn, mission_id, "rejected",
                valid_from={"pending_approval"}, release_assets=True)


def abort_mission(conn: Connection, mission_id: int) -> None:
    """Abort an active (or still-pending) mission.  Server operator only."""
    _transition(conn, mission_id, "aborted",
                valid_from={"pending_approval", "active"}, release_assets=True)


def complete_mission(conn: Connection, mission_id: int) -> None:
    """Mark a mission completed.  Server operator only.  Releases asset allocations."""
    _transition(conn, mission_id, "completed",
                valid_from={"active"}, release_assets=True)


def delete_mission(conn: Connection, mission_id: int) -> None:
    """
    Permanently delete a mission.  Server operator only.

    Order of operations (all in one transaction):
      1. NULL sitrep.mission_id     (nullable FK)
      2. DELETE zones               (zones are deleted with the mission, not unlinked)
      3. DELETE waypoints           (mission_id NOT NULL — must delete, not null)
      4. NULL asset.mission_id      (nullable FK)
      5. DELETE channel             (nullable mission_id FK)
      6. DELETE mission row
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE sitreps SET mission_id = NULL, version = version + 1 WHERE mission_id = ?",
            (mission_id,),
        )
        conn.execute(
            "UPDATE assignments SET mission_id = NULL, version = version + 1 "
            "WHERE mission_id = ?",
            (mission_id,),
        )
        conn.execute("DELETE FROM zones     WHERE mission_id = ?",                 (mission_id,))
        conn.execute("DELETE FROM waypoints WHERE mission_id = ?",                 (mission_id,))
        conn.execute(
            "UPDATE assets SET mission_id = NULL, version = version + 1 WHERE mission_id = ?",
            (mission_id,),
        )
        conn.execute(
            "DELETE FROM messages WHERE channel_id IN "
            "(SELECT id FROM channels WHERE mission_id = ?)",
            (mission_id,),
        )
        conn.execute("DELETE FROM channels WHERE mission_id = ?",                  (mission_id,))
        conn.execute("DELETE FROM missions WHERE id = ?",                          (mission_id,))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise ValueError(f"Could not delete mission: {exc}") from exc


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

_MISSION_COLS = (
    "id, title, description, status, created_by, created_at, version,"
    " mission_type, priority, lead_coordinator, organization,"
    " activation_time, operation_window, max_duration,"
    " staging_area, demob_point, standdown_criteria,"
    " phases, constraints,"
    " support_medical, support_logistics, support_comms, support_equipment,"
    " custom_resources,"
    " objectives, key_locations"
)


def load_missions(
    conn: Connection,
    *,
    status_filter: typing.Optional[str] = None,
    limit: int = 200,
) -> list[Mission]:
    """Load missions, optionally filtered by status, newest first."""
    clauses: list[str] = []
    params: list[object] = []
    if status_filter is not None:
        clauses.append("status = ?")
        params.append(status_filter)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT {_MISSION_COLS} FROM missions {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    return [_row_to_mission(r) for r in rows]


def get_mission(conn: Connection, mission_id: int) -> typing.Optional[Mission]:
    """Fetch a single mission by id, or None if not found."""
    row = conn.execute(
        f"SELECT {_MISSION_COLS} FROM missions WHERE id = ?",
        (mission_id,),
    ).fetchone()
    return _row_to_mission(row) if row else None


def get_mission_assets(conn: Connection, mission_id: int) -> list[Asset]:
    """Load assets currently requested or allocated to a mission."""
    rows = conn.execute(
        "SELECT id, category, label, description, lat, lon, verified, "
        "created_by, confirmed_by, created_at, version, mission_id "
        "FROM assets WHERE mission_id = ? ORDER BY label ASC",
        (mission_id,),
    ).fetchall()
    return [
        Asset(
            id=r[0], category=r[1], label=r[2], description=r[3],
            lat=r[4], lon=r[5], verified=bool(r[6]),
            created_by=r[7], confirmed_by=r[8], created_at=r[9],
            version=r[10], mission_id=r[11],
        )
        for r in rows
    ]


def get_channel_for_mission(conn: Connection, mission_id: int) -> typing.Optional[str]:
    """Return the channel name for an approved mission, or None."""
    row = conn.execute(
        "SELECT name FROM channels WHERE mission_id = ?", (mission_id,)
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _transition(
    conn: Connection,
    mission_id: int,
    new_status: str,
    *,
    valid_from: set[str],
    release_assets: bool = False,
) -> None:
    try:
        # BEGIN IMMEDIATE before the status read — prevents two concurrent
        # abort/complete calls from both passing the valid_from guard.
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status FROM missions WHERE id = ?", (mission_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Mission {mission_id} not found.")
        if row[0] not in valid_from:
            raise ValueError(
                f"Cannot transition mission from '{row[0]}' to '{new_status}'."
            )
        if release_assets:
            conn.execute(
                "UPDATE assets SET mission_id = NULL, version = version + 1 WHERE mission_id = ?",
                (mission_id,),
            )
        conn.execute(
            "UPDATE missions SET status = ?, version = version + 1 WHERE id = ?",
            (new_status, mission_id),
        )
        conn.commit()
    except ValueError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise ValueError(f"Could not update mission status: {exc}") from exc


def _row_to_mission(row: tuple) -> Mission:
    def _jlist(val: typing.Any) -> list:
        if not val:
            return []
        try:
            result = json.loads(val)
            return result if isinstance(result, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def _jdict(val: typing.Any) -> dict:
        if not val:
            return {}
        try:
            result = json.loads(val)
            return result if isinstance(result, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    return Mission(
        id=row[0],
        title=row[1],
        description=row[2],
        status=row[3],
        created_by=row[4],
        created_at=row[5],
        version=row[6],
        mission_type=row[7] or "",
        priority=row[8] or "ROUTINE",
        lead_coordinator=row[9] or "",
        organization=row[10] or "",
        activation_time=row[11] or "",
        operation_window=row[12] or "",
        max_duration=row[13] or "",
        staging_area=row[14] or "",
        demob_point=row[15] or "",
        standdown_criteria=row[16] or "",
        phases=_jlist(row[17]),
        constraints=_jlist(row[18]),
        support_medical=row[19] or "",
        support_logistics=row[20] or "",
        support_comms=row[21] or "",
        support_equipment=row[22] or "",
        custom_resources=_jlist(row[23]),
        objectives=_jlist(row[24]),
        key_locations=_jdict(row[25]),
    )

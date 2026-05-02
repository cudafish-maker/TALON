"""Mission workflow commands that return notification-ready domain events."""
from __future__ import annotations

import dataclasses
import typing

from talon_core.db.connection import Connection
from talon_core.db.models import Mission
from talon_core.missions import (
    abort_mission,
    approve_mission,
    complete_mission,
    create_mission,
    delete_mission,
    reject_mission,
    update_mission,
)
from talon_core.services.events import (
    DomainEvent,
    linked_records_changed,
    record_changed,
    record_deleted,
)
from talon_core.utils.logging import get_logger
from talon_core.waypoints import create_waypoints_for_mission
from talon_core.zones import create_zone

_log = get_logger("services.missions")


@dataclasses.dataclass(frozen=True)
class MissionCreateResult:
    mission: Mission
    events: tuple[DomainEvent, ...]


@dataclasses.dataclass(frozen=True)
class MissionCommandResult:
    mission_id: int
    events: tuple[DomainEvent, ...]
    channel_name: typing.Optional[str] = None


def create_mission_command(
    conn: Connection,
    *,
    title: str,
    created_by: int,
    asset_ids: typing.Optional[list[int]] = None,
    description: str = "",
    ao_polygon: typing.Optional[list[list[float]]] = None,
    route: typing.Optional[list[tuple[float, float]]] = None,
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
) -> MissionCreateResult:
    selected_asset_ids = list(asset_ids or [])
    mission = create_mission(
        conn,
        title=title,
        description=description,
        created_by=created_by,
        asset_ids=selected_asset_ids,
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
        phases=phases,
        constraints=constraints,
        support_medical=support_medical,
        support_logistics=support_logistics,
        support_comms=support_comms,
        support_equipment=support_equipment,
        custom_resources=custom_resources,
        objectives=objectives,
        key_locations=key_locations,
    )

    events: list[DomainEvent] = [record_changed("missions", mission.id)]
    events.extend(record_changed("assets", aid) for aid in selected_asset_ids)

    if ao_polygon:
        try:
            zone = create_zone(
                conn,
                label=f"AO - {title}",
                zone_type="AO",
                polygon=ao_polygon,
                mission_id=mission.id,
                created_by=created_by,
            )
            events.append(record_changed("zones", zone.id))
        except Exception as exc:
            _log.warning("create_mission_command: AO zone creation failed: %s", exc)

    if route:
        try:
            waypoints = create_waypoints_for_mission(conn, mission.id, route)
            events.extend(record_changed("waypoints", wp.id) for wp in waypoints)
        except Exception as exc:
            _log.warning("create_mission_command: waypoint creation failed: %s", exc)

    return MissionCreateResult(mission, tuple(events))


def approve_mission_command(
    conn: Connection,
    mission_id: int,
    *,
    asset_ids: typing.Optional[list[int]] = None,
) -> MissionCommandResult:
    before_asset_ids = set(_asset_ids_for_mission(conn, mission_id))
    requested_asset_ids = set(asset_ids or []) if asset_ids is not None else before_asset_ids
    channel_name = approve_mission(conn, mission_id, asset_ids=asset_ids)
    channel_id = _channel_id_for_mission(conn, mission_id)

    events: list[DomainEvent] = [record_changed("missions", mission_id)]
    if channel_id is not None:
        events.append(record_changed("channels", channel_id))
    events.extend(
        record_changed("assets", aid)
        for aid in sorted(before_asset_ids | requested_asset_ids)
    )
    return MissionCommandResult(mission_id, tuple(events), channel_name=channel_name)


def update_mission_command(
    conn: Connection,
    mission_id: int,
    *,
    title: str,
    asset_ids: typing.Optional[list[int]] = None,
    ao_polygon: typing.Optional[list[list[float]]] = None,
    route: typing.Optional[list[tuple[float, float]]] = None,
    replace_ao: bool = False,
    replace_route: bool = False,
    created_by: int,
    **fields: typing.Any,
) -> MissionCommandResult:
    before_asset_ids = set(_asset_ids_for_mission(conn, mission_id))
    before_ao_ids = _ids(
        conn,
        "SELECT id FROM zones WHERE mission_id = ? AND zone_type = 'AO' ORDER BY id ASC",
        mission_id,
    )
    before_waypoint_ids = _ids(
        conn,
        "SELECT id FROM waypoints WHERE mission_id = ? ORDER BY id ASC",
        mission_id,
    )

    update_mission(
        conn,
        mission_id,
        title=title,
        asset_ids=asset_ids,
        **fields,
    )

    events: list[DomainEvent] = [record_changed("missions", mission_id)]
    after_asset_ids = set(_asset_ids_for_mission(conn, mission_id))
    events.extend(record_changed("assets", aid) for aid in sorted(before_asset_ids | after_asset_ids))

    if replace_ao:
        conn.execute(
            "DELETE FROM zones WHERE mission_id = ? AND zone_type = 'AO'",
            (mission_id,),
        )
        conn.commit()
        events.extend(record_deleted("zones", zone_id) for zone_id in before_ao_ids)
        if ao_polygon:
            try:
                zone = create_zone(
                    conn,
                    label=f"AO - {title}",
                    zone_type="AO",
                    polygon=ao_polygon,
                    mission_id=mission_id,
                    created_by=created_by,
                )
                events.append(record_changed("zones", zone.id))
            except Exception as exc:
                _log.warning("update_mission_command: AO zone update failed: %s", exc)

    if replace_route:
        conn.execute("DELETE FROM waypoints WHERE mission_id = ?", (mission_id,))
        conn.commit()
        events.extend(record_deleted("waypoints", waypoint_id) for waypoint_id in before_waypoint_ids)
        if route:
            try:
                waypoints = create_waypoints_for_mission(conn, mission_id, route)
                events.extend(record_changed("waypoints", wp.id) for wp in waypoints)
            except Exception as exc:
                _log.warning("update_mission_command: waypoint update failed: %s", exc)

    return MissionCommandResult(mission_id, tuple(events))


def reject_mission_command(conn: Connection, mission_id: int) -> MissionCommandResult:
    affected_asset_ids = _asset_ids_for_mission(conn, mission_id)
    reject_mission(conn, mission_id)
    events = [record_changed("missions", mission_id)]
    events.extend(record_changed("assets", aid) for aid in affected_asset_ids)
    return MissionCommandResult(mission_id, tuple(events))


def abort_mission_command(conn: Connection, mission_id: int) -> MissionCommandResult:
    affected_asset_ids = _asset_ids_for_mission(conn, mission_id)
    abort_mission(conn, mission_id)
    events = [record_changed("missions", mission_id)]
    events.extend(record_changed("assets", aid) for aid in affected_asset_ids)
    return MissionCommandResult(mission_id, tuple(events))


def complete_mission_command(conn: Connection, mission_id: int) -> MissionCommandResult:
    affected_asset_ids = _asset_ids_for_mission(conn, mission_id)
    complete_mission(conn, mission_id)
    events = [record_changed("missions", mission_id)]
    events.extend(record_changed("assets", aid) for aid in affected_asset_ids)
    return MissionCommandResult(mission_id, tuple(events))


def delete_mission_command(conn: Connection, mission_id: int) -> MissionCommandResult:
    linked = _linked_ids_for_mission_delete(conn, mission_id)
    delete_mission(conn, mission_id)

    event = linked_records_changed(
        *(record_deleted("messages", mid) for mid in linked["messages"]),
        *(record_deleted("channels", cid) for cid in linked["channels"]),
        *(record_deleted("waypoints", wid) for wid in linked["waypoints"]),
        *(record_deleted("zones", zid) for zid in linked["zones"]),
        record_deleted("missions", mission_id),
        *(record_changed("sitreps", sid) for sid in linked["sitreps"]),
        *(record_changed("assets", aid) for aid in linked["assets"]),
        *(record_changed("assignments", aid) for aid in linked["assignments"]),
    )
    return MissionCommandResult(mission_id, (event,))


def _asset_ids_for_mission(conn: Connection, mission_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM assets WHERE mission_id = ? ORDER BY id ASC",
        (mission_id,),
    ).fetchall()
    return [r[0] for r in rows]


def _channel_id_for_mission(conn: Connection, mission_id: int) -> typing.Optional[int]:
    row = conn.execute(
        "SELECT id FROM channels WHERE mission_id = ? ORDER BY id ASC LIMIT 1",
        (mission_id,),
    ).fetchone()
    return row[0] if row else None


def _linked_ids_for_mission_delete(
    conn: Connection,
    mission_id: int,
) -> dict[str, list[int]]:
    linked: dict[str, list[int]] = {
        "zones": _ids(conn, "SELECT id FROM zones WHERE mission_id = ? ORDER BY id ASC", mission_id),
        "waypoints": _ids(conn, "SELECT id FROM waypoints WHERE mission_id = ? ORDER BY id ASC", mission_id),
        "channels": _ids(conn, "SELECT id FROM channels WHERE mission_id = ? ORDER BY id ASC", mission_id),
        "sitreps": _ids(conn, "SELECT id FROM sitreps WHERE mission_id = ? ORDER BY id ASC", mission_id),
        "assets": _ids(conn, "SELECT id FROM assets WHERE mission_id = ? ORDER BY id ASC", mission_id),
        "assignments": _ids(conn, "SELECT id FROM assignments WHERE mission_id = ? ORDER BY id ASC", mission_id),
        "messages": [],
    }
    if linked["channels"]:
        placeholders = ",".join("?" * len(linked["channels"]))
        linked["messages"] = [
            r[0]
            for r in conn.execute(
                f"SELECT id FROM messages WHERE channel_id IN ({placeholders}) ORDER BY id ASC",
                linked["channels"],
            ).fetchall()
        ]
    return linked


def _ids(conn: Connection, sql: str, key: int) -> list[int]:
    return [r[0] for r in conn.execute(sql, (key,)).fetchall()]

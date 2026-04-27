"""Qt-free mission helpers for the PySide6 desktop client."""
from __future__ import annotations

import dataclasses
import typing

from talon_core.constants import SITREP_LEVELS


@dataclasses.dataclass(frozen=True)
class DesktopMissionItem:
    id: int
    title: str
    description: str
    status: str
    priority: str
    mission_type: str
    created_by: int

    @property
    def status_label(self) -> str:
        return self.status.replace("_", " ").title()


MISSION_STATUS_OPTIONS: tuple[tuple[str | None, str], ...] = (
    (None, "All"),
    ("pending_approval", "Pending Approval"),
    ("active", "Active"),
    ("completed", "Completed"),
    ("aborted", "Aborted"),
    ("rejected", "Rejected"),
)


def item_from_mission(mission: object) -> DesktopMissionItem:
    return DesktopMissionItem(
        id=int(_field(mission, "id")),
        title=str(_field(mission, "title")),
        description=str(_field(mission, "description", default="") or ""),
        status=str(_field(mission, "status", default="")),
        priority=str(_field(mission, "priority", default="ROUTINE") or "ROUTINE"),
        mission_type=str(_field(mission, "mission_type", default="") or ""),
        created_by=int(_field(mission, "created_by")),
    )


def items_from_missions(missions: typing.Iterable[object]) -> list[DesktopMissionItem]:
    return [item_from_mission(mission) for mission in missions]


def build_create_payload(
    *,
    title: str,
    description: str,
    asset_ids: typing.Iterable[int],
    mission_type: str = "",
    priority: str = "ROUTINE",
    lead_coordinator: str = "",
    organization: str = "",
    ao_text: str = "",
    route_text: str = "",
) -> dict[str, object]:
    title = title.strip()
    if not title:
        raise ValueError("Mission title is required.")
    priority = priority.strip() or "ROUTINE"
    if priority not in SITREP_LEVELS:
        raise ValueError(f"Unknown priority: {priority!r}")

    payload: dict[str, object] = {
        "title": title,
        "description": description.strip(),
        "asset_ids": [int(asset_id) for asset_id in asset_ids],
        "mission_type": mission_type.strip(),
        "priority": priority,
        "lead_coordinator": lead_coordinator.strip(),
        "organization": organization.strip(),
    }
    ao_polygon = parse_coordinate_lines(
        ao_text,
        label="AO polygon",
        minimum_points=3,
        empty_ok=True,
    )
    route = parse_coordinate_lines(
        route_text,
        label="Route",
        minimum_points=1,
        empty_ok=True,
    )
    if ao_polygon:
        payload["ao_polygon"] = [[lat, lon] for lat, lon in ao_polygon]
    if route:
        payload["route"] = route
    return payload


def parse_coordinate_lines(
    text: str,
    *,
    label: str,
    minimum_points: int,
    empty_ok: bool,
) -> list[tuple[float, float]]:
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        if empty_ok:
            return []
        raise ValueError(f"{label} requires at least {minimum_points} point(s).")

    points: list[tuple[float, float]] = []
    for index, line in enumerate(raw_lines, start=1):
        parts = [part.strip() for part in line.replace(" ", ",").split(",") if part.strip()]
        if len(parts) != 2:
            raise ValueError(f"{label} line {index} must be 'lat, lon'.")
        try:
            lat = float(parts[0])
            lon = float(parts[1])
        except ValueError as exc:
            raise ValueError(f"{label} line {index} must contain numbers.") from exc
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"{label} line {index} latitude out of range.")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"{label} line {index} longitude out of range.")
        points.append((lat, lon))

    if len(points) < minimum_points:
        raise ValueError(f"{label} requires at least {minimum_points} point(s).")
    return points


def server_actions_for_status(status: str) -> tuple[str, ...]:
    if status == "pending_approval":
        return ("approve", "reject", "abort", "delete")
    if status == "active":
        return ("complete", "abort", "delete")
    return ("delete",)


def _field(obj: object, name: str, *, default: object = None) -> object:
    if isinstance(obj, dict) and name in obj:
        return obj[name]
    if hasattr(obj, name):
        return getattr(obj, name)
    return default

"""Qt-free mission helpers for the PySide6 desktop client."""
from __future__ import annotations

import dataclasses
import typing
from collections.abc import Mapping

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
    activation_time: str = "",
    operation_window: str = "",
    max_duration: str = "",
    staging_area: str = "",
    demob_point: str = "",
    standdown_criteria: str = "",
    phases: typing.Iterable[Mapping[str, object] | str] = (),
    constraints: typing.Iterable[str] = (),
    support_medical: str = "",
    support_logistics: str = "",
    support_comms: str = "",
    support_equipment: str = "",
    custom_resources: typing.Iterable[Mapping[str, object] | str] = (),
    objectives: typing.Iterable[Mapping[str, object] | str] = (),
    key_locations: Mapping[str, object] | None = None,
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
        "activation_time": activation_time.strip(),
        "operation_window": operation_window.strip(),
        "max_duration": max_duration.strip(),
        "staging_area": staging_area.strip(),
        "demob_point": demob_point.strip(),
        "standdown_criteria": standdown_criteria.strip(),
        "phases": _phase_items(phases),
        "constraints": _clean_lines(constraints),
        "support_medical": support_medical.strip(),
        "support_logistics": support_logistics.strip(),
        "support_comms": support_comms.strip(),
        "support_equipment": support_equipment.strip(),
        "custom_resources": _custom_resource_items(custom_resources),
        "objectives": _objective_items(objectives),
        "key_locations": _compact_mapping(key_locations or {}),
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


def line_items(text: str) -> list[str]:
    """Return non-empty stripped lines from a multi-line desktop editor."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def format_coordinate_lines(points: typing.Iterable[tuple[float, float]]) -> str:
    return "\n".join(f"{lat:.6f}, {lon:.6f}" for lat, lon in points)


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


def _clean_lines(values: typing.Iterable[object]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _phase_items(
    values: typing.Iterable[Mapping[str, object] | str],
) -> list[dict[str, str]]:
    phases: list[dict[str, str]] = []
    for index, value in enumerate(values, start=1):
        if isinstance(value, Mapping):
            name = str(value.get("name", "") or "").strip()
            objective = str(value.get("objective", "") or "").strip()
            duration = str(value.get("duration", "") or "").strip()
        else:
            name = str(value).strip()
            objective = ""
            duration = ""
        if not (name or objective or duration):
            continue
        phases.append(
            {
                "name": name or f"Phase {index}",
                "objective": objective,
                "duration": duration,
            }
        )
    return phases


def _objective_items(
    values: typing.Iterable[Mapping[str, object] | str],
) -> list[dict[str, str]]:
    objectives: list[dict[str, str]] = []
    for index, value in enumerate(values, start=1):
        if isinstance(value, Mapping):
            label = str(value.get("label", "") or "").strip()
            criteria = str(value.get("criteria", "") or "").strip()
        else:
            label = str(value).strip()
            criteria = ""
        if not (label or criteria):
            continue
        objectives.append(
            {
                "label": label or ("Primary objective" if index == 1 else f"Objective {index}"),
                "criteria": criteria,
            }
        )
    return objectives


def _custom_resource_items(
    values: typing.Iterable[Mapping[str, object] | str],
) -> list[dict[str, str]]:
    resources: list[dict[str, str]] = []
    for index, value in enumerate(values, start=1):
        if isinstance(value, Mapping):
            label = str(value.get("label", "") or "").strip()
            details = str(value.get("details", "") or "").strip()
        else:
            label = f"Custom Resource {index}"
            details = str(value).strip()
        if not (label or details):
            continue
        resources.append({"label": label or f"Custom Resource {index}", "details": details})
    return resources


def _compact_mapping(values: Mapping[str, object]) -> dict[str, str]:
    compact: dict[str, str] = {}
    for key, value in values.items():
        name = str(key).strip()
        text = str(value).strip()
        if name and text:
            compact[name] = text
    return compact

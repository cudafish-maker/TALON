"""SITREP helpers for the PySide6 desktop client.

This module stays free of Qt imports so behavior and safety policy can be
tested without PySide6 installed.
"""
from __future__ import annotations

import dataclasses
import datetime
import typing

from talon_core.constants import SITREP_LEVELS
from talon_core.sitrep import SITREP_STATUSES

FLASH_LEVELS = frozenset({"FLASH", "FLASH_OVERRIDE"})
ATTENTION_LEVELS = frozenset(SITREP_LEVELS)


@dataclasses.dataclass(frozen=True)
class SitrepFeedItem:
    id: int
    level: str
    body: str
    callsign: str
    asset_label: str | None
    mission_id: int | None
    asset_id: int | None
    assignment_id: int | None
    status: str
    assigned_to: str
    location_label: str
    lat: float | None
    lon: float | None
    location_source: str
    created_at: int

    @property
    def is_flash(self) -> bool:
        return self.level in FLASH_LEVELS

    @property
    def needs_attention(self) -> bool:
        return self.level in ATTENTION_LEVELS and self.status not in {"resolved", "closed"}

    @property
    def has_location(self) -> bool:
        return (
            (self.lat is not None and self.lon is not None)
            or self.asset_id is not None
            or self.assignment_id is not None
        )

    @property
    def unresolved(self) -> bool:
        return self.status not in {"resolved", "closed"}


@dataclasses.dataclass(frozen=True)
class SitrepTemplate:
    key: str
    label: str
    level: str
    body: str


@dataclasses.dataclass(frozen=True)
class AvailableOperatorItem:
    id: int
    callsign: str
    skills: tuple[str, ...]


DEFAULT_TEMPLATE_KEY = "free_text"
SITREP_TEMPLATES = (
    SitrepTemplate(
        key=DEFAULT_TEMPLATE_KEY,
        label="Free text",
        level="ROUTINE",
        body="",
    ),
    SitrepTemplate(
        key="contact",
        label="Contact",
        level="IMMEDIATE",
        body=(
            "Location:\n"
            "Contact type:\n"
            "Direction/range:\n"
            "Activity:\n"
            "Action taken:\n"
            "Support needed:"
        ),
    ),
    SitrepTemplate(
        key="medical",
        label="Medical",
        level="PRIORITY",
        body=(
            "Location:\n"
            "Patient count:\n"
            "Condition:\n"
            "Care given:\n"
            "Evacuation need:\n"
            "Requested support:"
        ),
    ),
    SitrepTemplate(
        key="logistics",
        label="Logistics",
        level="ROUTINE",
        body=(
            "Location:\n"
            "Supply status:\n"
            "Shortfalls:\n"
            "Transport status:\n"
            "ETA/request:"
        ),
    ),
    SitrepTemplate(
        key="infrastructure",
        label="Infrastructure",
        level="PRIORITY",
        body=(
            "Location:\n"
            "System affected:\n"
            "Observed damage:\n"
            "Operational impact:\n"
            "Immediate hazard:\n"
            "Requested action:"
        ),
    ),
    SitrepTemplate(
        key="weather",
        label="Weather",
        level="ROUTINE",
        body=(
            "Location:\n"
            "Conditions:\n"
            "Visibility:\n"
            "Wind/precipitation:\n"
            "Impact on operations:"
        ),
    ),
    SitrepTemplate(
        key="welfare_concern",
        label="Welfare concern",
        level="PRIORITY",
        body=(
            "Location:\n"
            "Concern observed:\n"
            "Immediate needs:\n"
            "Consent/source of request:\n"
            "Action taken:\n"
            "Follow-up needed:"
        ),
    ),
    SitrepTemplate(
        key="overdose_response",
        label="Overdose response",
        level="FLASH",
        body=(
            "Location:\n"
            "Patient count:\n"
            "Breathing/alertness:\n"
            "Care given:\n"
            "Medical services notified:\n"
            "Support needed:"
        ),
    ),
    SitrepTemplate(
        key="unsafe_area",
        label="Unsafe area",
        level="IMMEDIATE",
        body=(
            "Location:\n"
            "Hazard/condition:\n"
            "People affected:\n"
            "Area marked or avoided:\n"
            "Route impact:\n"
            "Requested support:"
        ),
    ),
    SitrepTemplate(
        key="need_support",
        label="Need support",
        level="FLASH_OVERRIDE",
        body=(
            "Location:\n"
            "Need:\n"
            "Current action:\n"
            "Hazards:\n"
            "Requested support:\n"
            "Acknowledgement needed:"
        ),
    ),
    SitrepTemplate(
        key="protective_handoff",
        label="Protective handoff",
        level="ROUTINE",
        body=(
            "Location:\n"
            "Assignment/detail:\n"
            "Outgoing team:\n"
            "Incoming team:\n"
            "Access notes:\n"
            "Follow-up:"
        ),
    ),
)


def sitrep_template_for_key(key: str) -> SitrepTemplate:
    for template in SITREP_TEMPLATES:
        if template.key == key:
            return template
    raise KeyError(f"Unknown SITREP template: {key!r}")


def feed_item_from_entry(entry: object) -> SitrepFeedItem:
    """Normalize a core ``sitreps.list`` row for desktop display."""
    if isinstance(entry, tuple):
        sitrep = entry[0]
        callsign = str(entry[1]) if len(entry) > 1 else "UNKNOWN"
        asset_label = typing.cast(str | None, entry[2] if len(entry) > 2 else None)
    else:
        sitrep = entry
        callsign = str(_field(sitrep, "callsign", default="UNKNOWN"))
        asset_label = typing.cast(str | None, _field(sitrep, "asset_label", default=None))

    return SitrepFeedItem(
        id=int(_field(sitrep, "id")),
        level=str(_field(sitrep, "level")),
        body=body_text(_field(sitrep, "body")),
        callsign=callsign,
        asset_label=asset_label,
        mission_id=_optional_int(_field(sitrep, "mission_id", default=None)),
        asset_id=_optional_int(_field(sitrep, "asset_id", default=None)),
        assignment_id=_optional_int(_field(sitrep, "assignment_id", default=None)),
        status=str(_field(sitrep, "status", default="open") or "open"),
        assigned_to=str(_field(sitrep, "assigned_to", default="") or ""),
        location_label=str(_field(sitrep, "location_label", default="") or ""),
        lat=_optional_float(_field(sitrep, "lat", default=None)),
        lon=_optional_float(_field(sitrep, "lon", default=None)),
        location_source=str(_field(sitrep, "location_source", default="") or ""),
        created_at=int(_field(sitrep, "created_at", default=0) or 0),
    )


def feed_items_from_entries(entries: typing.Iterable[object]) -> list[SitrepFeedItem]:
    return [feed_item_from_entry(entry) for entry in entries]


def body_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)


def build_create_payload(
    *,
    level: str,
    body: str,
    template: str = "",
    asset_id: int | None = None,
    mission_id: int | None = None,
    assignment_id: int | None = None,
    location_label: str = "",
    lat_text: str = "",
    lon_text: str = "",
    location_precision: str = "",
    location_source: str = "",
    status: str = "open",
    assigned_to: str = "",
    sensitivity: str = "team",
) -> dict[str, object]:
    """Validate desktop composer state and build a core command payload."""
    if level not in SITREP_LEVELS:
        raise ValueError(f"Unknown SITREP level: {level!r}")
    stripped = body.strip()
    if not stripped:
        raise ValueError("SITREP body is required.")
    if status not in SITREP_STATUSES:
        raise ValueError("Select a valid SITREP status.")
    lat = _parse_optional_float(lat_text, "Latitude", -90.0, 90.0)
    lon = _parse_optional_float(lon_text, "Longitude", -180.0, 180.0)
    if (lat is None) != (lon is None):
        raise ValueError("Both latitude and longitude are required for a map point.")
    payload: dict[str, object] = {
        "level": level,
        "body": stripped,
        "asset_id": asset_id,
        "mission_id": mission_id,
    }
    if assignment_id is not None:
        payload["assignment_id"] = assignment_id
    if location_label.strip():
        payload["location_label"] = location_label.strip()
    if lat is not None and lon is not None:
        payload["lat"] = lat
        payload["lon"] = lon
    if location_precision.strip():
        payload["location_precision"] = location_precision.strip()
    if location_source.strip():
        payload["location_source"] = location_source.strip()
    if status != "open":
        payload["status"] = status
    if assigned_to.strip():
        payload["assigned_to"] = assigned_to.strip()
    sensitivity_value = sensitivity.strip() or "team"
    if sensitivity_value != "team":
        payload["sensitivity"] = sensitivity_value
    if template:
        payload["template"] = template
    return payload


def build_filter_payload(
    *,
    level_filter: str = "",
    status_filter: str = "",
    unresolved_only: bool = False,
    has_location: bool = False,
    pending_sync_only: bool = False,
    assignment_id: int | None = None,
) -> dict[str, object]:
    filters: dict[str, object] = {}
    if level_filter:
        if level_filter not in SITREP_LEVELS:
            raise ValueError("Select a valid severity filter.")
        filters["level_filter"] = level_filter
    if status_filter:
        if status_filter not in SITREP_STATUSES:
            raise ValueError("Select a valid status filter.")
        filters["status_filter"] = status_filter
    if unresolved_only:
        filters["unresolved_only"] = True
    if has_location:
        filters["has_location"] = True
    if pending_sync_only:
        filters["pending_sync_only"] = True
    if assignment_id is not None:
        filters["assignment_id"] = int(assignment_id)
    return filters


def severity_counts(items: typing.Iterable[SitrepFeedItem]) -> dict[str, int]:
    counts = {level: 0 for level in SITREP_LEVELS}
    for item in items:
        counts[item.level] = counts.get(item.level, 0) + 1
    return counts


def available_operator_items(
    operators: typing.Iterable[object],
    *,
    assignments: typing.Iterable[object] = (),
    sitreps: typing.Iterable[object] = (),
    missions: typing.Iterable[object] = (),
    current_sitrep_id: int | None = None,
) -> list[AvailableOperatorItem]:
    """Return operators not already committed to active work."""
    assigned_operator_ids: set[int] = set()
    for assignment in assignments:
        status = str(_field(assignment, "status", default="") or "")
        if status in {"completed", "aborted"}:
            continue
        for operator_id in _field(assignment, "assigned_operator_ids", default=[]) or []:
            assigned_operator_ids.add(int(operator_id))

    busy_callsigns: set[str] = set()
    for entry in sitreps:
        sitrep = entry[0] if isinstance(entry, tuple) else entry
        sitrep_id = _optional_int(_field(sitrep, "id", default=None))
        if current_sitrep_id is not None and sitrep_id == int(current_sitrep_id):
            continue
        status = str(_field(sitrep, "status", default="open") or "open")
        if status in {"resolved", "closed"}:
            continue
        assigned_to = str(_field(sitrep, "assigned_to", default="") or "").strip()
        if assigned_to:
            busy_callsigns.add(assigned_to.casefold())

    for mission in missions:
        status = str(_field(mission, "status", default="") or "")
        if status in {"completed", "aborted", "rejected"}:
            continue
        for callsign in mission_operator_callsigns(mission):
            busy_callsigns.add(callsign.casefold())

    available: list[AvailableOperatorItem] = []
    for operator in operators:
        operator_id = _optional_int(_field(operator, "id", default=None))
        if operator_id is None or operator_id == 1:
            continue
        if bool(_field(operator, "revoked", default=False)):
            continue
        callsign = str(_field(operator, "callsign", default="") or f"#{operator_id}").strip()
        if operator_id in assigned_operator_ids or callsign.casefold() in busy_callsigns:
            continue
        raw_skills = _field(operator, "skills", default=[]) or []
        skills = tuple(str(skill) for skill in raw_skills if str(skill).strip())
        available.append(
            AvailableOperatorItem(
                id=operator_id,
                callsign=callsign,
                skills=skills,
            )
        )
    return available


def mission_operator_callsigns(mission: object) -> tuple[str, ...]:
    """Return operator callsigns encoded in current mission team fields."""
    values: list[str] = []
    lead = str(_field(mission, "lead_coordinator", default="") or "").strip()
    if lead:
        values.append(lead)
    members = str(_field(mission, "organization", default="") or "").strip()
    for piece in members.replace("\n", ",").replace(";", ",").split(","):
        callsign = piece.strip()
        if callsign:
            values.append(callsign)

    seen: set[str] = set()
    unique: list[str] = []
    for callsign in values:
        folded = callsign.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        unique.append(callsign)
    return tuple(unique)


def should_play_audio(level: str, audio_enabled: bool) -> bool:
    """Return True only for opt-in FLASH audio eligibility."""
    return bool(audio_enabled and level in FLASH_LEVELS)


def format_created_at(timestamp: int) -> str:
    if timestamp <= 0:
        return "--:--"
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def _field(obj: object, name: str, *, default: object = "") -> object:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(typing.cast(float, value))


def _parse_optional_float(
    value: str,
    label: str,
    minimum: float,
    maximum: float,
) -> float | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = float(stripped)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    return parsed

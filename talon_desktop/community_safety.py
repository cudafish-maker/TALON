"""Qt-free helpers for desktop community safety views."""
from __future__ import annotations

import dataclasses
import time
import typing

from talon_core.community_safety import (
    ASSIGNMENT_STATUSES,
    ASSIGNMENT_TYPES,
    CHECKIN_STATES,
)
from talon_core.constants import SITREP_LEVELS
from talon_core.utils.formatting import format_ts

ASSIGNMENT_TYPE_LABELS: dict[str, str] = {
    "foot_patrol": "Foot patrol",
    "vehicle_patrol": "Vehicle patrol",
    "escort": "Escort",
    "fixed_post": "Fixed post",
    "welfare_check": "Welfare check",
    "supply_run": "Supply run",
    "event_support": "Event support",
    "protective_detail": "Protective detail",
    "custom": "Custom",
}

ASSIGNMENT_STATUS_LABELS: dict[str, str] = {
    "planned": "Planned",
    "active": "Active",
    "paused": "Paused",
    "completed": "Completed",
    "aborted": "Aborted",
    "needs_support": "Needs support",
}

CHECKIN_STATE_LABELS: dict[str, str] = {
    "ok": "OK",
    "delayed": "Delayed",
    "leaving_area": "Leaving area",
    "need_backup": "Need backup",
    "medical_support": "Medical support",
    "unsafe_deescalating": "Unsafe, de-escalating",
    "emergency": "Emergency",
}

ACTIVE_ASSIGNMENT_STATUSES = frozenset({"planned", "active", "paused", "needs_support"})
SUPPORT_STATES = frozenset({"need_backup", "medical_support", "unsafe_deescalating", "emergency"})


@dataclasses.dataclass(frozen=True)
class DesktopAssignmentItem:
    id: int
    title: str
    assignment_type: str
    type_label: str
    status: str
    status_label: str
    priority: str
    team_lead: str
    backup_operator: str
    next_checkin_label: str
    overdue: bool
    needs_support: bool
    assigned_operator_ids: tuple[int, ...]
    last_checkin_label: str
    support_reason: str
    location_label: str


@dataclasses.dataclass(frozen=True)
class DesktopOperatorStatusItem:
    id: int
    callsign: str
    status_label: str
    assignment_title: str
    skills_label: str
    sort_key: tuple[int, str]


@dataclasses.dataclass(frozen=True)
class _OperatorCommitment:
    status_label: str
    assignment_title: str
    severity_rank: int


def assignment_items_from_board(
    board: typing.Mapping[str, typing.Any],
    *,
    now: int | None = None,
) -> list[DesktopAssignmentItem]:
    return [
        assignment_item_from_assignment(assignment, now=now)
        for assignment in board.get("assignments", [])
    ]


def assignment_item_from_assignment(
    assignment: object,
    *,
    now: int | None = None,
) -> DesktopAssignmentItem:
    generated_at = int(now if now is not None else time.time())
    status = str(getattr(assignment, "status", ""))
    last_at = getattr(assignment, "last_checkin_at", None)
    interval_s = int(getattr(assignment, "checkin_interval_min", 20) or 20) * 60
    threshold_s = int(getattr(assignment, "overdue_threshold_min", 5) or 5) * 60
    base_at = int(last_at or getattr(assignment, "created_at", generated_at))
    due_at = base_at + interval_s
    overdue = status in ACTIVE_ASSIGNMENT_STATUSES and generated_at > due_at + threshold_s
    if status == "needs_support":
        next_label = "Needs acknowledgement"
    elif overdue:
        minutes = max(1, int((generated_at - due_at) / 60))
        next_label = f"Overdue {minutes} min"
    elif status in ACTIVE_ASSIGNMENT_STATUSES:
        next_label = format_ts(due_at)
    else:
        next_label = ASSIGNMENT_STATUS_LABELS.get(status, status.title())
    state = str(getattr(assignment, "last_checkin_state", "") or "")
    last_label = CHECKIN_STATE_LABELS.get(state, state.replace("_", " ").title())
    if last_at:
        last_label = f"{last_label or 'Check-in'} at {format_ts(int(last_at))}"
    elif not last_label:
        last_label = "No check-in yet"
    return DesktopAssignmentItem(
        id=int(getattr(assignment, "id")),
        title=str(getattr(assignment, "title", "")),
        assignment_type=str(getattr(assignment, "assignment_type", "")),
        type_label=ASSIGNMENT_TYPE_LABELS.get(
            str(getattr(assignment, "assignment_type", "")),
            str(getattr(assignment, "assignment_type", "")).replace("_", " ").title(),
        ),
        status=status,
        status_label=ASSIGNMENT_STATUS_LABELS.get(status, status.replace("_", " ").title()),
        priority=str(getattr(assignment, "priority", "ROUTINE")),
        team_lead=str(getattr(assignment, "team_lead", "")) or "Unassigned",
        backup_operator=str(getattr(assignment, "backup_operator", "")) or "Open",
        next_checkin_label=next_label,
        overdue=overdue,
        needs_support=status == "needs_support" or state in SUPPORT_STATES,
        assigned_operator_ids=tuple(int(v) for v in getattr(assignment, "assigned_operator_ids", []) or []),
        last_checkin_label=last_label,
        support_reason=str(getattr(assignment, "support_reason", "")),
        location_label=str(getattr(assignment, "location_label", "")),
    )


def operator_status_items_from_board(
    board: typing.Mapping[str, typing.Any],
    assignments: typing.Sequence[DesktopAssignmentItem],
) -> list[DesktopOperatorStatusItem]:
    commitments_by_operator: dict[int, _OperatorCommitment] = {}
    commitments_by_callsign: dict[str, _OperatorCommitment] = {}
    for assignment in assignments:
        if assignment.status not in ACTIVE_ASSIGNMENT_STATUSES:
            continue
        commitment = _commitment_from_assignment(assignment)
        for operator_id in assignment.assigned_operator_ids:
            _remember_commitment(commitments_by_operator, operator_id, commitment)

    for mission in board.get("missions", []) or []:
        status = str(_field(mission, "status", default="") or "")
        if status in {"completed", "aborted", "rejected"}:
            continue
        title = str(_field(mission, "title", default="") or "")
        mission_id = _optional_int(_field(mission, "id", default=None))
        mission_label = title or (
            f"#{mission_id}" if mission_id is not None else "mission"
        )
        commitment = _OperatorCommitment(
            status_label="Assigned",
            assignment_title=f"Mission: {mission_label}",
            severity_rank=2,
        )
        for callsign in _mission_operator_callsigns(mission):
            _remember_commitment(
                commitments_by_callsign,
                callsign.casefold(),
                commitment,
            )

    for entry in board.get("sitreps", []) or []:
        sitrep = entry[0] if isinstance(entry, tuple) else entry
        status = str(_field(sitrep, "status", default="open") or "open")
        if status in {"resolved", "closed"}:
            continue
        assigned_to = str(_field(sitrep, "assigned_to", default="") or "").strip()
        if not assigned_to:
            continue
        commitment = _OperatorCommitment(
            status_label="Assigned",
            assignment_title=_sitrep_assignment_title(sitrep),
            severity_rank=2,
        )
        _remember_commitment(
            commitments_by_callsign,
            assigned_to.casefold(),
            commitment,
        )

    items: list[DesktopOperatorStatusItem] = []
    for operator in board.get("operators", []):
        if bool(getattr(operator, "revoked", False)):
            continue
        operator_id = int(getattr(operator, "id"))
        callsign = str(getattr(operator, "callsign", "") or f"#{operator_id}")
        commitment = commitments_by_operator.get(operator_id)
        callsign_commitment = commitments_by_callsign.get(callsign.casefold())
        if (
            callsign_commitment is not None
            and (
                commitment is None
                or callsign_commitment.severity_rank < commitment.severity_rank
            )
        ):
            commitment = callsign_commitment
        profile = getattr(operator, "profile", {}) or {}
        role = str(profile.get("role", "")) if isinstance(profile, dict) else ""
        skills = ", ".join(str(skill) for skill in getattr(operator, "skills", [])[:3])
        if commitment is None:
            status_label = "Available"
            assignment_title = role
            severity_rank = 3
        else:
            status_label = commitment.status_label
            assignment_title = commitment.assignment_title
            severity_rank = commitment.severity_rank
        items.append(
            DesktopOperatorStatusItem(
                id=operator_id,
                callsign=callsign,
                status_label=status_label,
                assignment_title=assignment_title,
                skills_label=skills,
                sort_key=(severity_rank, callsign.lower()),
            )
        )
    return sorted(items, key=lambda item: item.sort_key)


def _commitment_from_assignment(assignment: DesktopAssignmentItem) -> _OperatorCommitment:
    if assignment.needs_support:
        return _OperatorCommitment("Needs support", assignment.title, 0)
    if assignment.overdue:
        return _OperatorCommitment("Overdue", assignment.title, 1)
    return _OperatorCommitment("Assigned", assignment.title, 2)


def _remember_commitment(
    commitments: dict[typing.Any, _OperatorCommitment],
    key: typing.Any,
    commitment: _OperatorCommitment,
) -> None:
    existing = commitments.get(key)
    if existing is None or commitment.severity_rank < existing.severity_rank:
        commitments[key] = commitment


def _mission_operator_callsigns(mission: object) -> tuple[str, ...]:
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


def _sitrep_assignment_title(sitrep: object) -> str:
    sitrep_id = _optional_int(_field(sitrep, "id", default=None))
    body = _as_text(_field(sitrep, "body", default="")).strip()
    first_line = body.splitlines()[0].strip() if body else ""
    if len(first_line) > 60:
        first_line = first_line[:57].rstrip() + "..."
    sitrep_label = f"SITREP #{sitrep_id}" if sitrep_id is not None else "SITREP"
    if first_line:
        return f"{sitrep_label}: {first_line}"
    return sitrep_label


def build_assignment_payload(
    *,
    assignment_type: str,
    title: str,
    status: str = "planned",
    priority: str = "ROUTINE",
    protected_label: str = "",
    location_label: str = "",
    location_precision: str = "general",
    support_reason: str = "",
    consent_source: str = "",
    assigned_operator_ids: typing.Iterable[int] = (),
    team_lead: str = "",
    backup_operator: str = "",
    escalation_contact: str = "",
    required_skills: typing.Iterable[str] = (),
    shift_start: str = "",
    shift_end: str = "",
    checkin_interval_min: int = 20,
    overdue_threshold_min: int = 5,
    handoff_notes: str = "",
    risk_notes: str = "",
    mission_id: int | None = None,
    lat_text: str = "",
    lon_text: str = "",
) -> dict[str, object]:
    if assignment_type not in ASSIGNMENT_TYPES:
        raise ValueError("Select a valid assignment type.")
    if status not in ASSIGNMENT_STATUSES:
        raise ValueError("Select a valid status.")
    if priority not in SITREP_LEVELS:
        raise ValueError("Select a valid priority.")
    if not title.strip():
        raise ValueError("Assignment title is required.")
    lat = _optional_coordinate(lat_text, "latitude", -90.0, 90.0)
    lon = _optional_coordinate(lon_text, "longitude", -180.0, 180.0)
    if (lat is None) != (lon is None):
        raise ValueError("Both latitude and longitude are required for a map point.")
    return {
        "assignment_type": assignment_type,
        "title": title.strip(),
        "status": status,
        "priority": priority,
        "protected_label": protected_label.strip(),
        "location_label": location_label.strip(),
        "location_precision": location_precision.strip() or "general",
        "support_reason": support_reason.strip(),
        "consent_source": consent_source.strip(),
        "assigned_operator_ids": [int(value) for value in assigned_operator_ids],
        "team_lead": team_lead.strip(),
        "backup_operator": backup_operator.strip(),
        "escalation_contact": escalation_contact.strip(),
        "required_skills": [str(value).strip().lower() for value in required_skills if str(value).strip()],
        "shift_start": shift_start.strip(),
        "shift_end": shift_end.strip(),
        "checkin_interval_min": max(1, int(checkin_interval_min)),
        "overdue_threshold_min": max(1, int(overdue_threshold_min)),
        "handoff_notes": handoff_notes.strip(),
        "risk_notes": risk_notes.strip(),
        "mission_id": mission_id,
        "lat": lat,
        "lon": lon,
    }


def build_checkin_payload(
    *,
    assignment_id: int,
    state: str,
    note: str = "",
) -> dict[str, object]:
    if state not in CHECKIN_STATES:
        raise ValueError("Select a valid check-in state.")
    return {
        "assignment_id": int(assignment_id),
        "state": state,
        "note": note.strip(),
    }


def _field(obj: object, name: str, *, default: object = "") -> object:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)


def _optional_coordinate(
    value: str,
    label: str,
    minimum: float,
    maximum: float,
) -> float | None:
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ValueError(f"Assignment {label} must be a number.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(
            f"Assignment {label} must be between {minimum:g} and {maximum:g}."
        )
    return parsed

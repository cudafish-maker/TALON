"""Community safety assignment, check-in, and incident data access."""
from __future__ import annotations

import json
import time
import typing
import uuid as _uuid_mod

from talon_core.constants import SITREP_LEVELS
from talon_core.db.connection import Connection
from talon_core.db.models import (
    AssignmentCheckIn,
    CommunityAssignment,
    CommunityIncident,
)

ASSIGNMENT_TYPES: tuple[str, ...] = (
    "foot_patrol",
    "vehicle_patrol",
    "escort",
    "fixed_post",
    "welfare_check",
    "supply_run",
    "event_support",
    "protective_detail",
    "custom",
)

ASSIGNMENT_STATUSES: tuple[str, ...] = (
    "planned",
    "active",
    "paused",
    "completed",
    "aborted",
    "needs_support",
)

CHECKIN_STATES: tuple[str, ...] = (
    "ok",
    "delayed",
    "leaving_area",
    "need_backup",
    "medical_support",
    "unsafe_deescalating",
    "emergency",
)

SUPPORT_CHECKIN_STATES: frozenset[str] = frozenset(
    {"need_backup", "medical_support", "unsafe_deescalating", "emergency"}
)

INCIDENT_CATEGORIES: tuple[str, ...] = (
    "welfare_concern",
    "harassment_or_intimidation",
    "theft_or_property_damage",
    "unsafe_area",
    "overdose_or_medical_emergency",
    "domestic_violence_concern",
    "missing_person_concern",
    "fire_flood_weather_infrastructure",
    "community_conflict",
    "other",
)

INCIDENT_FOLLOW_UP_TYPES: tuple[str, ...] = (
    "welfare_check",
    "transport",
    "medical_support",
    "notify_party",
    "outside_service",
    "documentation",
    "revisit_location",
    "closeout_review",
    "other",
)

INCIDENT_FOLLOW_UP_URGENCIES: tuple[str, ...] = (
    "routine",
    "priority",
    "immediate",
)

TERMINAL_ASSIGNMENT_STATUSES: frozenset[str] = frozenset({"completed", "aborted"})

_ASSIGNMENT_COLS = (
    "id, mission_id, assignment_type, title, status, priority,"
    " protected_label, location_label, location_precision, support_reason,"
    " consent_source, assigned_operator_ids, team_lead, backup_operator,"
    " escalation_contact, required_skills, shift_start, shift_end,"
    " checkin_interval_min, overdue_threshold_min, handoff_notes, risk_notes,"
    " lat, lon, last_checkin_state, last_checkin_at, last_checkin_operator_id,"
    " created_by, created_at, version"
)

_CHECKIN_COLS = (
    "id, assignment_id, state, note, operator_id, lat, lon,"
    " acknowledged_by, acknowledged_at, created_at, version"
)

_INCIDENT_COLS = (
    "id, category, severity, title, occurred_at, location_label, lat, lon,"
    " narrative, actions_taken, outcome, follow_up_needed,"
    " follow_up_type, follow_up_action, follow_up_responsible,"
    " follow_up_due, follow_up_urgency, follow_up_assignment_id,"
    " notified_services,"
    " linked_mission_id, linked_assignment_id, linked_asset_id, linked_sitrep_id,"
    " created_by, created_at, version"
)


def create_assignment(
    conn: Connection,
    *,
    assignment_type: str,
    title: str,
    created_by: int,
    mission_id: typing.Optional[int] = None,
    status: str = "planned",
    priority: str = "ROUTINE",
    protected_label: str = "",
    location_label: str = "",
    location_precision: str = "general",
    support_reason: str = "",
    consent_source: str = "",
    assigned_operator_ids: typing.Optional[typing.Iterable[int]] = None,
    team_lead: str = "",
    backup_operator: str = "",
    escalation_contact: str = "",
    required_skills: typing.Optional[typing.Iterable[str]] = None,
    shift_start: str = "",
    shift_end: str = "",
    checkin_interval_min: int = 20,
    overdue_threshold_min: int = 5,
    handoff_notes: str = "",
    risk_notes: str = "",
    lat: typing.Optional[float] = None,
    lon: typing.Optional[float] = None,
    sync_status: str = "synced",
) -> CommunityAssignment:
    assignment_type = _clean_choice(assignment_type, ASSIGNMENT_TYPES, "assignment type")
    status = _clean_choice(status, ASSIGNMENT_STATUSES, "assignment status")
    priority = _clean_choice(priority or "ROUTINE", SITREP_LEVELS, "priority")
    title = title.strip()
    if not title:
        raise ValueError("Assignment title is required.")
    if mission_id is not None:
        _require_fk(conn, "missions", int(mission_id))
    operator_ids = _normalise_int_list(assigned_operator_ids)
    for operator_id in operator_ids:
        _require_fk(conn, "operators", operator_id)
    _require_fk(conn, "operators", int(created_by))
    skills = _normalise_str_list(required_skills)
    interval = max(1, int(checkin_interval_min))
    threshold = max(1, int(overdue_threshold_min))
    lat = _optional_float(lat, "lat", -90.0, 90.0)
    lon = _optional_float(lon, "lon", -180.0, 180.0)
    now = int(time.time())
    cursor = conn.execute(
        "INSERT INTO assignments ("
        " mission_id, assignment_type, title, status, priority,"
        " protected_label, location_label, location_precision, support_reason,"
        " consent_source, assigned_operator_ids, team_lead, backup_operator,"
        " escalation_contact, required_skills, shift_start, shift_end,"
        " checkin_interval_min, overdue_threshold_min, handoff_notes, risk_notes,"
        " lat, lon, created_by, created_at, uuid, sync_status"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            mission_id,
            assignment_type,
            title,
            status,
            priority,
            protected_label.strip(),
            location_label.strip(),
            location_precision.strip() or "general",
            support_reason.strip(),
            consent_source.strip(),
            json.dumps(operator_ids),
            team_lead.strip(),
            backup_operator.strip(),
            escalation_contact.strip(),
            json.dumps(skills),
            shift_start.strip(),
            shift_end.strip(),
            interval,
            threshold,
            handoff_notes.strip(),
            risk_notes.strip(),
            lat,
            lon,
            created_by,
            now,
            _uuid_mod.uuid4().hex,
            sync_status,
        ),
    )
    conn.commit()
    return typing.cast(CommunityAssignment, get_assignment(conn, int(cursor.lastrowid)))


def update_assignment_status(
    conn: Connection,
    assignment_id: int,
    *,
    status: str,
) -> None:
    status = _clean_choice(status, ASSIGNMENT_STATUSES, "assignment status")
    row = conn.execute("SELECT id FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if row is None:
        raise ValueError(f"Assignment {assignment_id} not found.")
    conn.execute(
        "UPDATE assignments SET status = ?, version = version + 1 WHERE id = ?",
        (status, assignment_id),
    )
    conn.commit()


def create_checkin(
    conn: Connection,
    *,
    assignment_id: int,
    state: str,
    operator_id: int,
    note: str = "",
    lat: typing.Optional[float] = None,
    lon: typing.Optional[float] = None,
    require_assigned_operator: bool = True,
    sync_status: str = "synced",
) -> AssignmentCheckIn:
    state = _clean_choice(state, CHECKIN_STATES, "check-in state")
    _require_fk(conn, "operators", int(operator_id))
    assignment = get_assignment(conn, int(assignment_id))
    if assignment is None:
        raise ValueError(f"Assignment {assignment_id} not found.")
    assigned_ids = {int(value) for value in assignment.assigned_operator_ids}
    if require_assigned_operator and assigned_ids and int(operator_id) not in assigned_ids:
        raise ValueError("Only an operator assigned to this assignment can check in.")
    lat = _optional_float(lat, "lat", -90.0, 90.0)
    lon = _optional_float(lon, "lon", -180.0, 180.0)
    now = int(time.time())
    next_status = _status_for_checkin(assignment.status, state)
    with conn.transaction():
        cursor = conn.execute(
            "INSERT INTO checkins ("
            " assignment_id, state, note, operator_id, lat, lon, created_at,"
            " uuid, sync_status"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                int(assignment_id),
                state,
                note.strip(),
                int(operator_id),
                lat,
                lon,
                now,
                _uuid_mod.uuid4().hex,
                sync_status,
            ),
        )
        conn.execute(
            "UPDATE assignments SET last_checkin_state = ?, last_checkin_at = ?,"
            " last_checkin_operator_id = ?, status = ?, version = version + 1"
            " WHERE id = ?",
            (state, now, int(operator_id), next_status, int(assignment_id)),
        )
    return typing.cast(AssignmentCheckIn, get_checkin(conn, int(cursor.lastrowid)))


def acknowledge_checkin(
    conn: Connection,
    checkin_id: int,
    *,
    acknowledged_by: int,
) -> None:
    _require_fk(conn, "operators", int(acknowledged_by))
    row = conn.execute("SELECT id FROM checkins WHERE id = ?", (checkin_id,)).fetchone()
    if row is None:
        raise ValueError(f"Check-in {checkin_id} not found.")
    conn.execute(
        "UPDATE checkins SET acknowledged_by = ?, acknowledged_at = ?,"
        " version = version + 1 WHERE id = ?",
        (int(acknowledged_by), int(time.time()), int(checkin_id)),
    )
    conn.commit()


def apply_checkin_effect(conn: Connection, checkin_id: int) -> int:
    """Update the parent assignment after a synced check-in row is inserted."""
    checkin = get_checkin(conn, int(checkin_id))
    if checkin is None:
        raise ValueError(f"Check-in {checkin_id} not found.")
    assignment = get_assignment(conn, checkin.assignment_id)
    if assignment is None:
        raise ValueError(f"Assignment {checkin.assignment_id} not found.")
    assigned_ids = {int(value) for value in assignment.assigned_operator_ids}
    if assigned_ids and int(checkin.operator_id) not in assigned_ids:
        raise ValueError("Only an operator assigned to this assignment can check in.")
    next_status = _status_for_checkin(assignment.status, checkin.state)
    conn.execute(
        "UPDATE assignments SET last_checkin_state = ?, last_checkin_at = ?,"
        " last_checkin_operator_id = ?, status = ?, version = version + 1"
        " WHERE id = ?",
        (
            checkin.state,
            checkin.created_at,
            checkin.operator_id,
            next_status,
            checkin.assignment_id,
        ),
    )
    conn.commit()
    return checkin.assignment_id


def create_incident(
    conn: Connection,
    *,
    category: str,
    severity: str,
    created_by: int,
    title: str = "",
    occurred_at: typing.Optional[int] = None,
    location_label: str = "",
    lat: typing.Optional[float] = None,
    lon: typing.Optional[float] = None,
    narrative: str = "",
    actions_taken: str = "",
    outcome: str = "",
    follow_up_needed: bool = False,
    follow_up_type: str = "",
    follow_up_action: str = "",
    follow_up_responsible: str = "",
    follow_up_due: str = "",
    follow_up_urgency: str = "",
    follow_up_assignment_id: typing.Optional[int] = None,
    notified_services: str = "",
    linked_mission_id: typing.Optional[int] = None,
    linked_assignment_id: typing.Optional[int] = None,
    linked_asset_id: typing.Optional[int] = None,
    linked_sitrep_id: typing.Optional[int] = None,
    sync_status: str = "synced",
) -> CommunityIncident:
    category = _clean_choice(category, INCIDENT_CATEGORIES, "incident category")
    severity = _clean_choice(severity or "ROUTINE", SITREP_LEVELS, "severity")
    _require_fk(conn, "operators", int(created_by))
    _require_fk(conn, "missions", linked_mission_id)
    _require_fk(conn, "assignments", linked_assignment_id)
    _require_fk(conn, "assignments", follow_up_assignment_id)
    _require_fk(conn, "assets", linked_asset_id)
    _require_fk(conn, "sitreps", linked_sitrep_id)
    (
        follow_up_type,
        follow_up_action,
        follow_up_responsible,
        follow_up_due,
        follow_up_urgency,
    ) = _normalise_follow_up_fields(
        follow_up_needed=follow_up_needed,
        follow_up_type=follow_up_type,
        follow_up_action=follow_up_action,
        follow_up_responsible=follow_up_responsible,
        follow_up_due=follow_up_due,
        follow_up_urgency=follow_up_urgency,
    )
    lat = _optional_float(lat, "lat", -90.0, 90.0)
    lon = _optional_float(lon, "lon", -180.0, 180.0)
    now = int(time.time())
    occurred = int(occurred_at or now)
    cursor = conn.execute(
        "INSERT INTO incidents ("
        " category, severity, title, occurred_at, location_label, lat, lon,"
        " narrative, actions_taken, outcome, follow_up_needed,"
        " follow_up_type, follow_up_action, follow_up_responsible,"
        " follow_up_due, follow_up_urgency, follow_up_assignment_id,"
        " notified_services,"
        " linked_mission_id, linked_assignment_id, linked_asset_id, linked_sitrep_id,"
        " created_by, created_at, uuid, sync_status"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            category,
            severity,
            title.strip(),
            occurred,
            location_label.strip(),
            lat,
            lon,
            narrative.strip(),
            actions_taken.strip(),
            outcome.strip(),
            1 if follow_up_needed else 0,
            follow_up_type,
            follow_up_action,
            follow_up_responsible,
            follow_up_due,
            follow_up_urgency,
            follow_up_assignment_id,
            notified_services.strip(),
            linked_mission_id,
            linked_assignment_id,
            linked_asset_id,
            linked_sitrep_id,
            int(created_by),
            now,
            _uuid_mod.uuid4().hex,
            sync_status,
        ),
    )
    conn.commit()
    return typing.cast(CommunityIncident, get_incident(conn, int(cursor.lastrowid)))


def clear_incident_follow_up(
    conn: Connection,
    incident_id: int,
    *,
    outcome_note: str,
) -> CommunityIncident:
    incident = get_incident(conn, int(incident_id))
    if incident is None:
        raise ValueError(f"Incident {incident_id} not found.")
    note = outcome_note.strip()
    if not note:
        raise ValueError("Follow-up closeout note is required.")
    outcome = incident.outcome.strip()
    outcome = f"{outcome}\n\nFollow-up closeout: {note}" if outcome else note
    conn.execute(
        "UPDATE incidents SET follow_up_needed = 0, outcome = ?, version = version + 1 "
        "WHERE id = ?",
        (outcome, int(incident_id)),
    )
    conn.commit()
    updated = get_incident(conn, int(incident_id))
    assert updated is not None
    return updated


def list_assignments(
    conn: Connection,
    *,
    status_filter: typing.Optional[str] = None,
    active_only: bool = False,
    limit: int = 200,
) -> list[CommunityAssignment]:
    clauses: list[str] = []
    params: list[object] = []
    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter)
    if active_only:
        clauses.append("status NOT IN ('completed', 'aborted')")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(int(limit))
    rows = conn.execute(
        f"SELECT {_ASSIGNMENT_COLS} FROM assignments {where} "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        params,
    ).fetchall()
    return [_row_to_assignment(row) for row in rows]


def get_assignment(
    conn: Connection,
    assignment_id: int,
) -> typing.Optional[CommunityAssignment]:
    row = conn.execute(
        f"SELECT {_ASSIGNMENT_COLS} FROM assignments WHERE id = ?",
        (int(assignment_id),),
    ).fetchone()
    return _row_to_assignment(row) if row else None


def list_checkins(
    conn: Connection,
    *,
    assignment_id: typing.Optional[int] = None,
    limit: int = 100,
) -> list[AssignmentCheckIn]:
    params: list[object] = []
    where = ""
    if assignment_id is not None:
        where = "WHERE assignment_id = ?"
        params.append(int(assignment_id))
    params.append(int(limit))
    rows = conn.execute(
        f"SELECT {_CHECKIN_COLS} FROM checkins {where} "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        params,
    ).fetchall()
    return [_row_to_checkin(row) for row in rows]


def get_checkin(conn: Connection, checkin_id: int) -> typing.Optional[AssignmentCheckIn]:
    row = conn.execute(
        f"SELECT {_CHECKIN_COLS} FROM checkins WHERE id = ?",
        (int(checkin_id),),
    ).fetchone()
    return _row_to_checkin(row) if row else None


def list_incidents(
    conn: Connection,
    *,
    category_filter: typing.Optional[str] = None,
    severity_filter: typing.Optional[str] = None,
    follow_up_only: bool = False,
    limit: int = 200,
) -> list[CommunityIncident]:
    clauses: list[str] = []
    params: list[object] = []
    if category_filter:
        clauses.append("category = ?")
        params.append(category_filter)
    if severity_filter:
        clauses.append("severity = ?")
        params.append(severity_filter)
    if follow_up_only:
        clauses.append("follow_up_needed != 0")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(int(limit))
    rows = conn.execute(
        f"SELECT {_INCIDENT_COLS} FROM incidents {where} "
        "ORDER BY occurred_at DESC, id DESC LIMIT ?",
        params,
    ).fetchall()
    return [_row_to_incident(row) for row in rows]


def get_incident(conn: Connection, incident_id: int) -> typing.Optional[CommunityIncident]:
    row = conn.execute(
        f"SELECT {_INCIDENT_COLS} FROM incidents WHERE id = ?",
        (int(incident_id),),
    ).fetchone()
    return _row_to_incident(row) if row else None


def _status_for_checkin(current_status: str, state: str) -> str:
    if current_status in TERMINAL_ASSIGNMENT_STATUSES:
        return current_status
    if state in SUPPORT_CHECKIN_STATES:
        return "needs_support"
    if state == "delayed":
        return "paused"
    return "active"


def _row_to_assignment(row: tuple) -> CommunityAssignment:
    return CommunityAssignment(
        id=int(row[0]),
        mission_id=_maybe_int(row[1]),
        assignment_type=str(row[2] or ""),
        title=str(row[3] or ""),
        status=str(row[4] or ""),
        priority=str(row[5] or "ROUTINE"),
        protected_label=str(row[6] or ""),
        location_label=str(row[7] or ""),
        location_precision=str(row[8] or "general"),
        support_reason=str(row[9] or ""),
        consent_source=str(row[10] or ""),
        assigned_operator_ids=_json_int_list(row[11]),
        team_lead=str(row[12] or ""),
        backup_operator=str(row[13] or ""),
        escalation_contact=str(row[14] or ""),
        required_skills=_json_str_list(row[15]),
        shift_start=str(row[16] or ""),
        shift_end=str(row[17] or ""),
        checkin_interval_min=int(row[18] or 20),
        overdue_threshold_min=int(row[19] or 5),
        handoff_notes=str(row[20] or ""),
        risk_notes=str(row[21] or ""),
        lat=_maybe_float(row[22]),
        lon=_maybe_float(row[23]),
        last_checkin_state=str(row[24] or ""),
        last_checkin_at=_maybe_int(row[25]),
        last_checkin_operator_id=_maybe_int(row[26]),
        created_by=int(row[27]),
        created_at=int(row[28]),
        version=int(row[29]),
    )


def _row_to_checkin(row: tuple) -> AssignmentCheckIn:
    return AssignmentCheckIn(
        id=int(row[0]),
        assignment_id=int(row[1]),
        state=str(row[2] or ""),
        note=str(row[3] or ""),
        operator_id=int(row[4]),
        lat=_maybe_float(row[5]),
        lon=_maybe_float(row[6]),
        acknowledged_by=_maybe_int(row[7]),
        acknowledged_at=_maybe_int(row[8]),
        created_at=int(row[9]),
        version=int(row[10]),
    )


def _row_to_incident(row: tuple) -> CommunityIncident:
    return CommunityIncident(
        id=int(row[0]),
        category=str(row[1] or ""),
        severity=str(row[2] or "ROUTINE"),
        title=str(row[3] or ""),
        occurred_at=int(row[4]),
        location_label=str(row[5] or ""),
        lat=_maybe_float(row[6]),
        lon=_maybe_float(row[7]),
        narrative=str(row[8] or ""),
        actions_taken=str(row[9] or ""),
        outcome=str(row[10] or ""),
        follow_up_needed=bool(row[11]),
        follow_up_type=str(row[12] or ""),
        follow_up_action=str(row[13] or ""),
        follow_up_responsible=str(row[14] or ""),
        follow_up_due=str(row[15] or ""),
        follow_up_urgency=str(row[16] or ""),
        follow_up_assignment_id=_maybe_int(row[17]),
        notified_services=str(row[18] or ""),
        linked_mission_id=_maybe_int(row[19]),
        linked_assignment_id=_maybe_int(row[20]),
        linked_asset_id=_maybe_int(row[21]),
        linked_sitrep_id=_maybe_int(row[22]),
        created_by=int(row[23]),
        created_at=int(row[24]),
        version=int(row[25]),
    )


def _clean_choice(value: str, choices: tuple[str, ...], label: str) -> str:
    cleaned = str(value or "").strip()
    if cleaned not in choices:
        raise ValueError(f"Unknown {label}: {cleaned!r}.")
    return cleaned


def _normalise_follow_up_fields(
    *,
    follow_up_needed: bool,
    follow_up_type: str,
    follow_up_action: str,
    follow_up_responsible: str,
    follow_up_due: str,
    follow_up_urgency: str,
) -> tuple[str, str, str, str, str]:
    if not follow_up_needed:
        return "", "", "", "", ""
    follow_type = _clean_choice(
        follow_up_type or "other",
        INCIDENT_FOLLOW_UP_TYPES,
        "follow-up type",
    )
    urgency = _clean_choice(
        follow_up_urgency or "routine",
        INCIDENT_FOLLOW_UP_URGENCIES,
        "follow-up urgency",
    )
    action = follow_up_action.strip()
    responsible = follow_up_responsible.strip()
    due = follow_up_due.strip()
    if not action:
        raise ValueError("Follow-up next action is required.")
    if not responsible:
        raise ValueError("Follow-up responsible party is required.")
    if not due:
        raise ValueError("Follow-up due time is required.")
    return follow_type, action, responsible, due, urgency


def _require_fk(
    conn: Connection,
    table: str,
    record_id: typing.Optional[int],
) -> None:
    if record_id is None:
        return
    row = conn.execute(
        f"SELECT id FROM {table} WHERE id = ?",  # noqa: S608
        (int(record_id),),
    ).fetchone()
    if row is None:
        raise ValueError(f"{table} record {record_id} not found.")


def _normalise_int_list(values: typing.Optional[typing.Iterable[int]]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values or ():
        integer = int(value)
        if integer in seen:
            continue
        seen.add(integer)
        result.append(integer)
    return result


def _normalise_str_list(values: typing.Optional[typing.Iterable[str]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        cleaned = str(value).strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _json_int_list(value: typing.Any) -> list[int]:
    if not value:
        return []
    try:
        raw = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    result: list[int] = []
    for item in raw:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _json_str_list(value: typing.Any) -> list[str]:
    if not value:
        return []
    try:
        raw = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def _optional_float(
    value: typing.Any,
    field: str,
    minimum: float,
    maximum: float,
) -> typing.Optional[float]:
    if value is None or value == "":
        return None
    result = float(value)
    if result < minimum or result > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}.")
    return result


def _maybe_int(value: typing.Any) -> typing.Optional[int]:
    if value is None:
        return None
    return int(value)


def _maybe_float(value: typing.Any) -> typing.Optional[float]:
    if value is None:
        return None
    return float(value)

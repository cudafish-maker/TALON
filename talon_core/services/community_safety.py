"""Community safety service commands with domain events."""
from __future__ import annotations

import dataclasses
import typing

from talon_core.community_safety import (
    acknowledge_checkin,
    clear_incident_follow_up,
    create_assignment,
    create_checkin,
    create_incident,
    delete_incident,
    get_assignment,
    get_incident,
    update_assignment_status,
)
from talon_core.db.connection import Connection
from talon_core.db.models import (
    AssignmentCheckIn,
    CommunityAssignment,
    CommunityIncident,
)
from talon_core.services.events import (
    DomainEvent,
    linked_records_changed,
    record_changed,
    record_deleted,
)


@dataclasses.dataclass(frozen=True)
class AssignmentCommandResult:
    assignment_id: int
    assignment: typing.Optional[CommunityAssignment]
    events: tuple[DomainEvent, ...]


@dataclasses.dataclass(frozen=True)
class CheckInCommandResult:
    checkin_id: int
    assignment_id: int
    checkin: typing.Optional[AssignmentCheckIn]
    events: tuple[DomainEvent, ...]


@dataclasses.dataclass(frozen=True)
class IncidentCommandResult:
    incident_id: int
    incident: typing.Optional[CommunityIncident]
    events: tuple[DomainEvent, ...]
    assignment_id: typing.Optional[int] = None
    assignment: typing.Optional[CommunityAssignment] = None


def create_assignment_command(
    conn: Connection,
    *,
    created_by: int,
    assignment_type: str,
    title: str,
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
) -> AssignmentCommandResult:
    assignment = create_assignment(
        conn,
        created_by=created_by,
        assignment_type=assignment_type,
        title=title,
        mission_id=mission_id,
        status=status,
        priority=priority,
        protected_label=protected_label,
        location_label=location_label,
        location_precision=location_precision,
        support_reason=support_reason,
        consent_source=consent_source,
        assigned_operator_ids=assigned_operator_ids,
        team_lead=team_lead,
        backup_operator=backup_operator,
        escalation_contact=escalation_contact,
        required_skills=required_skills,
        shift_start=shift_start,
        shift_end=shift_end,
        checkin_interval_min=checkin_interval_min,
        overdue_threshold_min=overdue_threshold_min,
        handoff_notes=handoff_notes,
        risk_notes=risk_notes,
        lat=lat,
        lon=lon,
        sync_status=sync_status,
    )
    events: list[DomainEvent] = [record_changed("assignments", assignment.id)]
    if assignment.mission_id is not None:
        events.append(record_changed("missions", assignment.mission_id))
    return AssignmentCommandResult(assignment.id, assignment, tuple(events))


def update_assignment_status_command(
    conn: Connection,
    *,
    assignment_id: int,
    status: str,
) -> AssignmentCommandResult:
    update_assignment_status(conn, assignment_id, status=status)
    return AssignmentCommandResult(
        assignment_id,
        None,
        (record_changed("assignments", assignment_id),),
    )


def create_checkin_command(
    conn: Connection,
    *,
    assignment_id: int,
    operator_id: int,
    state: str,
    note: str = "",
    lat: typing.Optional[float] = None,
    lon: typing.Optional[float] = None,
    require_assigned_operator: bool = True,
    sync_status: str = "synced",
) -> CheckInCommandResult:
    checkin = create_checkin(
        conn,
        assignment_id=assignment_id,
        operator_id=operator_id,
        state=state,
        note=note,
        lat=lat,
        lon=lon,
        require_assigned_operator=require_assigned_operator,
        sync_status=sync_status,
    )
    return CheckInCommandResult(
        checkin.id,
        assignment_id,
        checkin,
        (
            linked_records_changed(
                record_changed("checkins", checkin.id),
                record_changed("assignments", assignment_id),
            ),
        ),
    )


def acknowledge_checkin_command(
    conn: Connection,
    *,
    checkin_id: int,
    acknowledged_by: int,
    assignment_id: typing.Optional[int] = None,
) -> CheckInCommandResult:
    if assignment_id is None:
        row = conn.execute(
            "SELECT assignment_id FROM checkins WHERE id = ?",
            (int(checkin_id),),
        ).fetchone()
        if row is None:
            raise ValueError(f"Check-in {checkin_id} not found.")
        assignment_id = int(row[0])
    acknowledge_checkin(conn, checkin_id, acknowledged_by=acknowledged_by)
    return CheckInCommandResult(
        checkin_id,
        int(assignment_id),
        None,
        (
            linked_records_changed(
                record_changed("checkins", checkin_id),
                record_changed("assignments", int(assignment_id)),
            ),
        ),
    )


def create_incident_command(
    conn: Connection,
    *,
    created_by: int,
    category: str,
    severity: str,
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
    create_follow_up_assignment: bool = False,
    notified_services: str = "",
    linked_mission_id: typing.Optional[int] = None,
    linked_assignment_id: typing.Optional[int] = None,
    linked_asset_id: typing.Optional[int] = None,
    linked_sitrep_id: typing.Optional[int] = None,
    sync_status: str = "synced",
) -> IncidentCommandResult:
    if create_follow_up_assignment and not follow_up_needed:
        raise ValueError("A linked assignment requires follow-up to be needed.")
    if linked_mission_id is None and linked_assignment_id is not None:
        linked_assignment = get_assignment(conn, int(linked_assignment_id))
        if linked_assignment is not None:
            linked_mission_id = linked_assignment.mission_id
    incident = create_incident(
        conn,
        created_by=created_by,
        category=category,
        severity=severity,
        title=title,
        occurred_at=occurred_at,
        location_label=location_label,
        lat=lat,
        lon=lon,
        narrative=narrative,
        actions_taken=actions_taken,
        outcome=outcome,
        follow_up_needed=follow_up_needed,
        follow_up_type=follow_up_type,
        follow_up_action=follow_up_action,
        follow_up_responsible=follow_up_responsible,
        follow_up_due=follow_up_due,
        follow_up_urgency=follow_up_urgency,
        notified_services=notified_services,
        linked_mission_id=linked_mission_id,
        linked_assignment_id=linked_assignment_id,
        linked_asset_id=linked_asset_id,
        linked_sitrep_id=linked_sitrep_id,
        sync_status=sync_status,
    )
    follow_up_assignment: CommunityAssignment | None = None
    if create_follow_up_assignment:
        follow_up_assignment = create_assignment(
            conn,
            created_by=created_by,
            assignment_type="custom",
            title=incident.follow_up_action or incident.title or "Incident follow-up",
            status="active",
            priority=incident.severity,
            mission_id=incident.linked_mission_id,
            location_label=incident.location_label,
            location_precision="general",
            support_reason=incident.follow_up_type.replace("_", " ").title(),
            team_lead=incident.follow_up_responsible,
            handoff_notes=(
                f"Incident #{incident.id} follow-up"
                + (f": {incident.follow_up_action}" if incident.follow_up_action else "")
            ),
            lat=incident.lat,
            lon=incident.lon,
            sync_status=sync_status,
        )
        conn.execute(
            "UPDATE incidents SET follow_up_assignment_id = ?, version = version + 1 WHERE id = ?",
            (follow_up_assignment.id, incident.id),
        )
        conn.commit()
        incident = typing.cast(CommunityIncident, get_incident(conn, incident.id))
    events: list[DomainEvent] = [record_changed("incidents", incident.id)]
    if follow_up_assignment is not None:
        events.append(record_changed("assignments", follow_up_assignment.id))
        if follow_up_assignment.mission_id is not None:
            events.append(record_changed("missions", follow_up_assignment.mission_id))
    if incident.linked_assignment_id is not None:
        events.append(record_changed("assignments", incident.linked_assignment_id))
    if incident.linked_mission_id is not None:
        events.append(record_changed("missions", incident.linked_mission_id))
    if incident.linked_asset_id is not None:
        events.append(record_changed("assets", incident.linked_asset_id))
    if incident.linked_sitrep_id is not None:
        events.append(record_changed("sitreps", incident.linked_sitrep_id))
    return IncidentCommandResult(
        incident.id,
        incident,
        tuple(events),
        follow_up_assignment.id if follow_up_assignment is not None else None,
        follow_up_assignment,
    )


def clear_incident_follow_up_command(
    conn: Connection,
    *,
    incident_id: int,
    outcome_note: str,
) -> IncidentCommandResult:
    incident = clear_incident_follow_up(
        conn,
        incident_id,
        outcome_note=outcome_note,
    )
    assignment: CommunityAssignment | None = None
    events: list[DomainEvent] = [record_changed("incidents", incident.id)]
    if incident.follow_up_assignment_id is not None:
        update_assignment_status(
            conn,
            int(incident.follow_up_assignment_id),
            status="completed",
        )
        assignment = get_assignment(conn, int(incident.follow_up_assignment_id))
        events.append(record_changed("assignments", int(incident.follow_up_assignment_id)))
        if assignment is not None and assignment.mission_id is not None:
            events.append(record_changed("missions", assignment.mission_id))
    return IncidentCommandResult(
        incident.id,
        incident,
        tuple(events),
        incident.follow_up_assignment_id,
        assignment,
    )


def delete_incident_command(
    conn: Connection,
    *,
    incident_id: int,
) -> IncidentCommandResult:
    delete_incident(conn, incident_id)
    return IncidentCommandResult(
        int(incident_id),
        None,
        (record_deleted("incidents", int(incident_id)),),
    )

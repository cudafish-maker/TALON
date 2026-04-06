# talon/models/mission.py
# Business logic for Missions and Objectives.
#
# A mission groups together operators, assets, routes, zones, and
# objectives into a coordinated operation.
#
# Rules:
# - Any operator can create a mission
# - Assigned operators can update objective status
# - Any operator can append notes (append-only, like SITREPs)
# - Only server operator can delete or abort a mission
# - A mission auto-creates a chat channel for assigned operators

from talon.db.models import Mission, MissionNote, Objective


def create_mission(name: str, created_by: str, description: str = "", priority: str = "ROUTINE") -> Mission:
    """Create a new mission."""
    return Mission(
        name=name,
        created_by=created_by,
        description=description,
        priority=priority,
    )


def add_objective(mission_id: str, description: str, assigned_to: str = None) -> Objective:
    """Add an objective to a mission."""
    return Objective(
        mission_id=mission_id,
        description=description,
        assigned_to=assigned_to,
    )


def append_note(mission_id: str, author: str, content: str) -> MissionNote:
    """Append a note to a mission (append-only)."""
    return MissionNote(
        mission_id=mission_id,
        author=author,
        content=content,
    )


def can_update_objective(operator_callsign: str, objective: Objective, operator_role: str) -> bool:
    """Check if an operator can update an objective's status.

    Allowed if the operator is assigned to the objective or is the server.
    """
    if operator_role == "server":
        return True
    return operator_callsign == objective.assigned_to


def can_abort_mission(operator_role: str) -> bool:
    """Only the server operator can abort a mission."""
    return operator_role == "server"

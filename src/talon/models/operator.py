# talon/models/operator.py
# Business logic for Operator profiles.
#
# Operators are the people using T.A.L.O.N. This module handles
# profile validation, skill management, and permission checks.
#
# Rules:
# - An operator can edit THEIR OWN profile only
# - The server operator can edit ANY profile
# - Skills come from a predefined list + custom skills
# - Custom skills created by one operator are synced and available to all

from talon.constants import DEFAULT_SKILLS
from talon.db.models import Operator


def validate_profile(operator: Operator) -> list:
    """Check that an operator profile has all required fields.

    Args:
        operator: The Operator to validate.

    Returns:
        List of error messages. Empty list means valid.
    """
    errors = []
    if not operator.callsign:
        errors.append("Callsign is required")
    if not operator.reticulum_identity:
        errors.append("Reticulum identity is required")
    if operator.role not in ("operator", "server"):
        errors.append("Role must be 'operator' or 'server'")
    return errors


def can_edit_profile(editor_callsign: str, target_callsign: str, editor_role: str) -> bool:
    """Check if one operator is allowed to edit another's profile.

    Args:
        editor_callsign: Who is trying to edit.
        target_callsign: Whose profile is being edited.
        editor_role: The editor's role ("operator" or "server").

    Returns:
        True if the edit is allowed.
    """
    # Server operator can edit anyone
    if editor_role == "server":
        return True
    # Operators can only edit themselves
    return editor_callsign == target_callsign


def get_available_skills(custom_skills: list = None) -> list:
    """Get the full list of available skills (default + custom).

    Args:
        custom_skills: List of custom skill names added by operators.

    Returns:
        Combined list of all available skills.
    """
    all_skills = list(DEFAULT_SKILLS)
    if custom_skills:
        for skill in custom_skills:
            if skill not in all_skills:
                all_skills.append(skill)
    return all_skills

# talon/models/sitrep.py
# Business logic for SITREPs (Situation Reports).
#
# SITREPs are the core information sharing tool in T.A.L.O.N.
# They can be predefined (structured template) or freeform (blank).
#
# Rules:
# - Any operator can CREATE a SITREP
# - Any operator can APPEND entries to a SITREP
# - Operators CANNOT edit or delete previous entries (append-only)
# - Only the server operator can delete a SITREP (with reason logged)
# - Creating or appending triggers notifications to all other clients

from talon.db.models import SITREP, SITREPEntry

# Predefined SITREP templates.
# Each template defines the sections an operator fills out.
# They can leave sections blank if not applicable.
SITREP_TEMPLATES = {
    "standard": {
        "name": "Standard SITREP",
        "sections": [
            "Situation",
            "Enemy Activity",
            "Friendly Activity",
            "Weather / Terrain",
            "Casualties",
            "Supplies / Equipment",
            "Remarks",
        ],
    },
    "contact": {
        "name": "Contact Report",
        "sections": [
            "Size of Enemy Force",
            "Activity Observed",
            "Location (Grid Reference)",
            "Unit / Equipment Identified",
            "Time of Observation",
            "Remarks",
        ],
    },
    "medevac": {
        "name": "MEDEVAC Request",
        "sections": [
            "Location (Grid Reference)",
            "Frequency / Callsign",
            "Number of Patients",
            "Special Equipment Needed",
            "Number of Walking / Litter",
            "Security at Pickup Site",
            "Marking Method",
            "Patient Nationality / Status",
            "Terrain Description",
        ],
    },
}


def create_sitrep(
    created_by: str,
    importance: str = "ROUTINE",
    sitrep_type: str = "freeform",
    template_name: str = None,
) -> SITREP:
    """Create a new SITREP.

    Args:
        created_by: Callsign of the operator filing the report.
        importance: How urgent this report is (ROUTINE through FLASH_OVERRIDE).
        sitrep_type: "predefined" (uses a template) or "freeform" (blank).
        template_name: If predefined, which template to use.

    Returns:
        A new SITREP object ready to be saved.
    """
    return SITREP(
        created_by=created_by,
        importance=importance,
        type=sitrep_type,
        template_name=template_name,
    )


def append_entry(sitrep_id: str, author: str, content: str) -> SITREPEntry:
    """Append a new entry to an existing SITREP.

    This is the ONLY way to add information to a SITREP after creation.
    Previous entries cannot be edited or removed.

    Args:
        sitrep_id: The ID of the SITREP to append to.
        author: Callsign of the operator writing this entry.
        content: The text content of the entry.

    Returns:
        A new SITREPEntry object ready to be saved.
    """
    return SITREPEntry(
        sitrep_id=sitrep_id,
        author=author,
        content=content,
    )


def can_delete_sitrep(operator_role: str) -> bool:
    """Check if an operator is allowed to delete SITREPs.

    Args:
        operator_role: The operator's role ("operator" or "server").

    Returns:
        True only for the server operator.
    """
    return operator_role == "server"


def get_template(template_name: str) -> dict:
    """Get a predefined SITREP template by name.

    Args:
        template_name: The template key (e.g., "standard", "contact").

    Returns:
        Template dictionary with "name" and "sections", or None.
    """
    return SITREP_TEMPLATES.get(template_name)


def get_available_templates() -> dict:
    """Get all available SITREP templates.

    Returns:
        Dictionary of all templates keyed by their short name.
    """
    return dict(SITREP_TEMPLATES)

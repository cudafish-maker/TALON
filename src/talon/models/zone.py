# talon/models/zone.py
# Business logic for Zones.
#
# Zones are named geographic areas drawn on the map. They can represent
# areas of operation, danger zones, no-go areas, objectives, or any
# custom region the team needs to visualise.
#
# Rules:
# - Any operator can create zones
# - Zones are defined by a list of polygon vertices (lat/lon pairs)
# - Only the creating operator or server can delete a zone
# - Zone types control how they render on the map (colour, pattern)

from talon.db.models import Zone


def create_zone(name: str, created_by: str, zone_type: str = "AO",
                boundary: str = "", description: str = "") -> Zone:
    """Create a new zone.

    Args:
        name: Human-readable label (e.g., "AO Eagle", "Danger Zone Alpha").
        created_by: Callsign of the operator who drew this zone.
        zone_type: One of the ZoneType enum values (AO, DANGER, NO_GO, etc.).
        boundary: JSON string of polygon points, e.g.
                  '[{"lat": 34.05, "lon": -118.24}, ...]'
                  Stored as text so it survives SQLite round-trips.
        description: Optional notes about the zone.

    Returns:
        A new Zone object ready to be saved.
    """
    return Zone(
        name=name,
        created_by=created_by,
        type=zone_type,
        boundary=boundary,
        notes=description,
    )


def validate_zone(zone: Zone) -> list:
    """Check that a zone has all required fields.

    Args:
        zone: The Zone to validate.

    Returns:
        List of error messages. Empty list means valid.
    """
    errors = []
    if not zone.name:
        errors.append("Zone name is required")
    if not zone.created_by:
        errors.append("Creator callsign is required")
    if not zone.boundary:
        errors.append("Zone must have at least one vertex")
    return errors


def can_delete_zone(operator_callsign: str, zone: Zone,
                    operator_role: str) -> bool:
    """Check if an operator can delete a zone.

    Allowed for the zone creator or the server operator.
    """
    if operator_role == "server":
        return True
    return operator_callsign == zone.created_by

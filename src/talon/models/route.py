# talon/models/route.py
# Business logic for Routes and Waypoints.
#
# A route is an ordered sequence of waypoints that operators follow.
# Routes can be planned (not yet traveled), active, or completed.
#
# Rules:
# - Any operator can create routes and waypoints
# - Routes are ordered lists of waypoints (sequence matters)
# - Distance calculations use the Haversine formula (GPS coordinates)
# - Only the creating operator or server can delete a route

import math

from talon.db.models import Route, Waypoint

# ---------- Haversine distance ----------

# Earth's mean radius in metres.
EARTH_RADIUS_M = 6_371_000


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two GPS points.

    Uses the Haversine formula, which gives good accuracy for the
    distances we care about (metres to tens of kilometres).

    Args:
        lat1, lon1: First point in decimal degrees.
        lat2, lon2: Second point in decimal degrees.

    Returns:
        Distance in metres.
    """
    # Convert degrees → radians (math.radians does this)
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    # Haversine formula
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_M * c


# ---------- Factory helpers ----------


def create_waypoint(
    name: str, lat: float, lon: float, created_by: str, waypoint_type: str = "CHECKPOINT", description: str = ""
) -> Waypoint:
    """Create a new waypoint.

    Args:
        name: Human-readable label (e.g., "Alpha", "LZ North").
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        created_by: Callsign of the operator who placed this waypoint.
        waypoint_type: One of the WaypointType enum values.
        description: Optional notes about this waypoint.

    Returns:
        A new Waypoint object ready to be saved.
    """
    return Waypoint(
        name=name,
        latitude=lat,
        longitude=lon,
        created_by=created_by,
        type=waypoint_type,
        notes=description,
    )


def create_route(name: str, created_by: str, description: str = "") -> Route:
    """Create a new route (initially empty — add waypoints separately).

    Args:
        name: Route name (e.g., "MSR Tampa", "Exfil Route B").
        created_by: Callsign of the operator who planned this route.
        description: Optional purpose or notes.

    Returns:
        A new Route object ready to be saved.
    """
    return Route(
        name=name,
        created_by=created_by,
        notes=description,
    )


# ---------- Distance helpers ----------


def calculate_leg_distance(wp_a: Waypoint, wp_b: Waypoint) -> float:
    """Distance in metres between two consecutive waypoints."""
    return _haversine(wp_a.latitude, wp_a.longitude, wp_b.latitude, wp_b.longitude)


def calculate_route_distance(waypoints: list) -> float:
    """Total distance of a route given its ordered list of waypoints.

    Args:
        waypoints: List of Waypoint objects in route order.

    Returns:
        Total distance in metres. Returns 0.0 for routes with < 2 points.
    """
    if len(waypoints) < 2:
        return 0.0

    total = 0.0
    for i in range(len(waypoints) - 1):
        total += calculate_leg_distance(waypoints[i], waypoints[i + 1])
    return total


# ---------- Permission helpers ----------


def can_delete_route(operator_callsign: str, route: Route, operator_role: str) -> bool:
    """Check if an operator can delete a route.

    Allowed for the route creator or the server operator.
    """
    if operator_role == "server":
        return True
    return operator_callsign == route.created_by

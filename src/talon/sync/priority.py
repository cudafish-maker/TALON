# talon/sync/priority.py
# Sync priority ordering for T.A.L.O.N.
#
# Not all data is equally urgent. When syncing (especially over
# low-bandwidth LoRa), we need to send the most critical data first.
#
# Priority order:
# 1. SYSTEM — lease renewal, revocation, auth (keeps the system working)
# 2. ALERTS — FLASH SITREPs (life-safety information)
# 3. CHAT — text messages (coordination)
# 4. SITREPS — situation reports
# 5. ASSETS — position and status updates
# 6. MISSIONS — objective status
# 7. ROUTES/ZONES — map geometry
# 8. PROFILES — operator info
# 9. DOCUMENTS — files (broadband only)
# 10. MAP TILES — bulk downloads (broadband only)

from talon.constants import TransportType


# Maps data types to their sync priority number.
# Lower number = syncs first.
SYNC_PRIORITY = {
    "system": 1,
    "alerts": 2,
    "chat": 3,
    "sitreps": 4,
    "sitrep_entries": 4,
    "assets": 5,
    "asset_categories": 5,
    "missions": 6,
    "objectives": 6,
    "mission_notes": 6,
    "routes": 7,
    "route_waypoints": 7,
    "waypoints": 7,
    "zones": 7,
    "operators": 8,
    "channels": 3,
    "messages": 3,
    "documents": 9,
    "map_tiles": 10,
}

# Data types that should NOT be synced over LoRa due to size.
# These are queued and synced when a broadband connection is available.
BROADBAND_ONLY = {"documents", "map_tiles"}


def sort_by_priority(data_types: list) -> list:
    """Sort a list of data type names by sync priority.

    Args:
        data_types: List of table/data type names.

    Returns:
        The same list sorted by priority (most critical first).
    """
    return sorted(data_types, key=lambda t: SYNC_PRIORITY.get(t, 99))


def filter_for_transport(data_types: list, transport: TransportType) -> list:
    """Filter data types based on the current transport.

    Over LoRa, large data types (documents, map tiles) are excluded.
    Over broadband, everything is included.

    Args:
        data_types: List of table/data type names.
        transport: The current transport type.

    Returns:
        Filtered list with broadband-only items removed if on LoRa.
    """
    if transport == TransportType.RNODE:
        return [t for t in data_types if t not in BROADBAND_ONLY]
    return data_types

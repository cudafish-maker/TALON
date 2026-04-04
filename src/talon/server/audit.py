# talon/server/audit.py
# Audit logging for the server.
#
# Every significant action is recorded in the audit log. This creates
# an immutable record of who did what and when. The audit log is:
#   - Append-only (entries are never modified or deleted)
#   - Stored in the server's encrypted database
#   - Available for review by the server operator
#
# Audit events are defined in talon.constants.AuditEvent.

import time
from talon.db.models import AuditEntry


def log_event(event_type: str, client_callsign: str, target: str = "",
              details: str = "", transport: str = "") -> AuditEntry:
    """Create an audit log entry.

    Args:
        event_type: One of the AuditEvent enum values (e.g., "CLIENT_ENROLLED").
        client_callsign: Callsign of the operator who performed the action.
        target: What was affected — folded into the details string.
        details: Human-readable description of what happened.
        transport: Transport address of the client (if available).

    Returns:
        An AuditEntry object ready to be saved to the database.
    """
    full_details = details
    if target:
        full_details = f"{target}: {details}" if details else target
    return AuditEntry(
        event_type=event_type,
        client_callsign=client_callsign,
        details=full_details,
        transport=transport,
    )


def format_audit_entry(entry: AuditEntry) -> str:
    """Format an audit entry as a human-readable string.

    Used for display in the server operator's audit log viewer.

    Args:
        entry: The AuditEntry to format.

    Returns:
        Formatted string like "[2024-01-15 14:30:00] SITREP_CREATED by Alpha → SR-123"
    """
    # Convert Unix timestamp to readable format
    ts = time.strftime("%Y-%m-%d %H:%M:%S",
                       time.localtime(entry.timestamp))

    parts = [f"[{ts}]", entry.event_type]

    if entry.client_callsign:
        parts.extend(["by", entry.client_callsign])
    if entry.details:
        parts.append(f"({entry.details})")

    return " ".join(parts)


# Common audit helper functions.
# These wrap log_event() for the most frequent actions so callers
# don't have to remember the event type strings.

def log_client_enrolled(callsign: str) -> AuditEntry:
    """Log a new client enrollment."""
    return log_event("CLIENT_ENROLLED", callsign,
                     details="New client enrolled")


def log_client_revoked(server_callsign: str, revoked_callsign: str,
                       reason: str) -> AuditEntry:
    """Log a client revocation."""
    return log_event("CLIENT_REVOKED", server_callsign,
                     target=revoked_callsign, details=reason)


def log_lease_renewed(callsign: str) -> AuditEntry:
    """Log a lease renewal."""
    return log_event("LEASE_RENEWED", callsign)


def log_lease_expired(callsign: str) -> AuditEntry:
    """Log a lease expiration (soft-lock triggered)."""
    return log_event("LEASE_EXPIRED", callsign,
                     details="Client soft-locked")


def log_sitrep_created(callsign: str, sitrep_id: str,
                       importance: str) -> AuditEntry:
    """Log a new SITREP creation."""
    return log_event("SITREP_CREATED", callsign,
                     target=sitrep_id, details=f"Importance: {importance}")


def log_mission_created(callsign: str, mission_id: str) -> AuditEntry:
    """Log a new mission creation."""
    return log_event("MISSION_CREATED", callsign, target=mission_id)


def log_asset_created(callsign: str, asset_id: str,
                      category: str) -> AuditEntry:
    """Log a new asset creation."""
    return log_event("ASSET_CREATED", callsign,
                     target=asset_id, details=f"Category: {category}")


def log_asset_verified(callsign: str, asset_id: str) -> AuditEntry:
    """Log an asset verification."""
    return log_event("ASSET_VERIFIED", callsign, target=asset_id)


def log_group_key_rotated(reason: str) -> AuditEntry:
    """Log a group key rotation."""
    return log_event("GROUP_KEY_ROTATED", "SYSTEM",
                     details=reason)

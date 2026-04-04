# talon/server/notifications.py
# Server-side notification dispatcher.
#
# When something happens that other operators need to know about
# (new SITREP, mission update, chat message, etc.), this module
# builds the notification and queues it for delivery to all
# connected clients.
#
# Notification flow:
#   1. An action happens (e.g., SITREP created)
#   2. This module builds a notification dict
#   3. The sync engine delivers it to all connected clients
#   4. Each client decides how to display it (based on their settings)
#
# IMPORTANT: Audio alerts are opt-in on the CLIENT side.
# The server only sends the notification data and importance level.
# It is the client's responsibility to decide whether to play sound.

import time


def build_notification(event_type: str, source_callsign: str,
                       importance: str = "ROUTINE",
                       title: str = "", body: str = "",
                       target_id: str = "") -> dict:
    """Build a notification payload.

    Args:
        event_type: What happened (e.g., "SITREP_CREATED", "MESSAGE_NEW").
        source_callsign: Who triggered this event.
        importance: How urgent — used by client to decide visual/audio alert.
        title: Short summary for the notification banner.
        body: Longer description (optional).
        target_id: ID of the related object (SITREP ID, message ID, etc.).

    Returns:
        Notification dict ready to be sent to clients.
    """
    return {
        "type": "notification",
        "event": event_type,
        "source": source_callsign,
        "importance": importance,
        "title": title,
        "body": body,
        "target_id": target_id,
        "timestamp": time.time(),
    }


def sitrep_notification(callsign: str, sitrep_id: str,
                        importance: str, is_append: bool = False) -> dict:
    """Build a notification for SITREP creation or append.

    Args:
        callsign: Who created/appended.
        sitrep_id: The SITREP ID.
        importance: SITREP importance level.
        is_append: True if this is an append, False if new creation.
    """
    action = "appended to" if is_append else "created"
    return build_notification(
        event_type="SITREP_APPENDED" if is_append else "SITREP_CREATED",
        source_callsign=callsign,
        importance=importance,
        title=f"SITREP {importance}",
        body=f"{callsign} {action} SITREP",
        target_id=sitrep_id,
    )


def mission_notification(callsign: str, mission_id: str,
                         event: str) -> dict:
    """Build a notification for mission events.

    Args:
        callsign: Who triggered the event.
        mission_id: The mission ID.
        event: What happened (e.g., "created", "updated", "aborted").
    """
    return build_notification(
        event_type=f"MISSION_{event.upper()}",
        source_callsign=callsign,
        importance="PRIORITY" if event == "aborted" else "ROUTINE",
        title=f"Mission {event}",
        body=f"{callsign} {event} a mission",
        target_id=mission_id,
    )


def chat_notification(callsign: str, channel_id: str,
                      channel_name: str) -> dict:
    """Build a notification for a new chat message."""
    return build_notification(
        event_type="MESSAGE_NEW",
        source_callsign=callsign,
        importance="ROUTINE",
        title=f"Message in {channel_name}",
        body=f"{callsign} sent a message",
        target_id=channel_id,
    )


def asset_notification(callsign: str, asset_id: str,
                       event: str) -> dict:
    """Build a notification for asset events (created, verified)."""
    return build_notification(
        event_type=f"ASSET_{event.upper()}",
        source_callsign=callsign,
        importance="ROUTINE",
        title=f"Asset {event}",
        body=f"{callsign} {event} an asset",
        target_id=asset_id,
    )


def client_notification(callsign: str, event: str) -> dict:
    """Build a notification for client events (enrolled, revoked, stale)."""
    return build_notification(
        event_type=f"CLIENT_{event.upper()}",
        source_callsign=callsign,
        importance="PRIORITY" if event == "revoked" else "ROUTINE",
        title=f"Operator {event}",
        body=f"{callsign} has {event}",
    )

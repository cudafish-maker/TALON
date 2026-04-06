# talon/models/chat.py
# Business logic for Chat (Channels, Messages, DMs).
#
# Chat provides real-time and cached text communication between operators.
# There are three channel types:
#   - GROUP:  visible to all operators (default channels like "General")
#   - TEAM:   created by operators for subsets of the team
#   - DIRECT: private 1-on-1 between two operators
#
# Rules:
# - Any operator can create team channels
# - Any operator can send messages to channels they belong to
# - Messages are append-only (operators cannot edit or delete)
# - Only the server operator can delete messages or channels
# - Missions auto-create a channel for assigned operators
# - Operators can pin messages (useful for key info in the field)

from talon.constants import ChannelType
from talon.db.models import Channel, Message


def create_channel(name: str, created_by: str, channel_type: str = "GROUP", description: str = "") -> Channel:
    """Create a new chat channel.

    Args:
        name: Channel name (e.g., "General", "Alpha Team").
        created_by: Callsign of the operator who created it.
        channel_type: GROUP, TEAM, or DIRECT.
        description: Optional purpose description.

    Returns:
        A new Channel object ready to be saved.
    """
    return Channel(
        name=name,
        created_by=created_by,
        type=channel_type,
    )


def create_message(channel_id: str, author: str, content: str, message_type: str = "TEXT") -> Message:
    """Create a new chat message.

    Args:
        channel_id: Which channel this message belongs to.
        author: Callsign of the sender.
        content: The message text.
        message_type: TEXT, SYSTEM, ALERT, or IMAGE.

    Returns:
        A new Message object ready to be saved.
    """
    return Message(
        channel_id=channel_id,
        sender=author,
        body=content,
        type=message_type,
    )


def can_send_message(operator_callsign: str, channel_members: list) -> bool:
    """Check if an operator is allowed to send messages to a channel.

    Args:
        operator_callsign: Who wants to send.
        channel_members: List of callsigns that belong to the channel.

    Returns:
        True if the operator is a member of the channel.
    """
    return operator_callsign in channel_members


def can_delete_message(operator_role: str) -> bool:
    """Only the server operator can delete messages."""
    return operator_role == "server"


def can_delete_channel(operator_role: str) -> bool:
    """Only the server operator can delete channels."""
    return operator_role == "server"


def create_direct_channel(operator_a: str, operator_b: str) -> Channel:
    """Create a direct-message channel between two operators.

    The channel name is built from both callsigns so it's easy to find.

    Args:
        operator_a: First operator's callsign.
        operator_b: Second operator's callsign.

    Returns:
        A new DIRECT Channel object.
    """
    # Sort callsigns so the channel name is consistent regardless
    # of who initiates the conversation.
    pair = sorted([operator_a, operator_b])
    name = f"DM: {pair[0]} / {pair[1]}"

    return Channel(
        name=name,
        created_by=operator_a,
        type=ChannelType.DIRECT.name,
    )

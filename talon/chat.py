"""
Chat data access — channels and messages.

Encryption model:
  Transport:  RNS handles link-layer encryption for all message traffic.
  At rest:    SQLCipher encrypts the entire database — no additional field-level
              encryption is needed for group channel messages.
  DM bodies:  Stored as plaintext within SQLCipher in Phase 1.
              TODO Phase 2: encrypt DM bodies with nacl.public.Box(
                sender_privkey, recipient_rns_identity_pubkey) before storing,
                so the server routing node cannot read DM content even after
                RNS transport decryption.

Channel naming conventions:
  #general, #sitrep-feed, #alerts  — default system channels (seeded at startup)
  #mission-<slug>                  — auto-created on mission approval (missions.py)
  dm:<op_a_id>:<op_b_id>           — DM channels; IDs sorted ascending
  any other #name                  — operator-created custom channels

SERVER_AUTHOR_ID (1) is the operator sentinel from migration 0002.  Used as
sender_id for messages composed at the server before enrollment is wired.
"""
import re
import time
import typing
import uuid as _uuid_mod

from talon.constants import DEFAULT_CHANNELS
from talon.db.connection import Connection
from talon.db.models import Channel, Message

# Sentinel operator record seeded by migration 0002.
# TODO: replace with the real server operator id once enrollment is wired.
SERVER_AUTHOR_ID: int = 1


# ---------------------------------------------------------------------------
# Channel management
# ---------------------------------------------------------------------------

_DEFAULT_GROUP_TYPES: dict[str, str] = {
    "#flash": "emergency",
    "#general": "allhands",
    "#sitrep-feed": "allhands",
    "#alerts": "allhands",
}


def ensure_default_channels(conn: Connection) -> None:
    """Create default channels (#flash, #general, #sitrep-feed, #alerts) if they do not exist."""
    for name in DEFAULT_CHANNELS:
        gtype = _DEFAULT_GROUP_TYPES.get(name, "allhands")
        conn.execute(
            "INSERT OR IGNORE INTO channels (name, mission_id, is_dm, version, group_type) "
            "VALUES (?, NULL, 0, 1, ?)",
            (name, gtype),
        )
    conn.commit()


def create_channel(conn: Connection, name: str) -> Channel:
    """
    Create a new custom group channel.

    Name is normalised: stripped and prefixed with '#' if missing.
    Raises ValueError on empty name, duplicate, reserved prefix, or invalid chars.
    """
    name = name.strip()
    if not name:
        raise ValueError("Channel name is required.")
    if not name.startswith("#"):
        name = f"#{name}"
    # Reject names that mimic the DM channel naming convention.
    if name.lower().startswith("#dm:"):
        raise ValueError("Channel names cannot use the reserved 'dm:' prefix.")
    # Enforce a maximum length (64 chars excluding the leading '#').
    if len(name) > 65:
        raise ValueError("Channel name must be 64 characters or fewer (excluding '#').")
    # Reject control characters (null bytes, newlines, etc.).
    if re.search(r"[\x00-\x1f\x7f]", name):
        raise ValueError("Channel name contains invalid control characters.")
    try:
        cursor = conn.execute(
            "INSERT INTO channels (name, mission_id, is_dm, version) "
            "VALUES (?, NULL, 0, 1)",
            (name,),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise ValueError(f"Could not create channel '{name}': {exc}") from exc
    return Channel(id=cursor.lastrowid, name=name, mission_id=None, is_dm=False, version=1)


def get_or_create_dm_channel(
    conn: Connection, op_a_id: int, op_b_id: int
) -> Channel:
    """
    Return the existing DM channel between two operators, or create one.

    Channel name format: 'dm:<min_id>:<max_id>' — IDs sorted so the name is
    deterministic regardless of argument order.
    Raises ValueError if op_a_id == op_b_id.

    Uses BEGIN IMMEDIATE to close the TOCTOU window where two concurrent calls
    for the same pair could both miss the existing row and race to insert.
    """
    if op_a_id == op_b_id:
        raise ValueError("Cannot create a DM channel with yourself.")
    a, b = min(op_a_id, op_b_id), max(op_a_id, op_b_id)
    dm_name = f"dm:{a}:{b}"
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, name, mission_id, is_dm, version FROM channels WHERE name = ?",
            (dm_name,),
        ).fetchone()
        if row:
            conn.rollback()
            return _row_to_channel(row)
        cursor = conn.execute(
            "INSERT INTO channels (name, mission_id, is_dm, version, group_type) "
            "VALUES (?, NULL, 1, 1, 'direct')",
            (dm_name,),
        )
        conn.commit()
        return Channel(id=cursor.lastrowid, name=dm_name, mission_id=None, is_dm=True, version=1,
                       group_type='direct')
    except ValueError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise ValueError(f"Could not get or create DM channel: {exc}") from exc


def delete_channel(conn: Connection, channel_id: int) -> None:
    """
    Permanently delete a channel and all its messages.  Server operator only.
    Mission channels should be cleaned up via delete_mission() in missions.py,
    but this function works for any channel.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM messages WHERE channel_id = ?", (channel_id,))
        conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise ValueError(f"Could not delete channel: {exc}") from exc


# ---------------------------------------------------------------------------
# Message management
# ---------------------------------------------------------------------------

def send_message(
    conn: Connection,
    channel_id: int,
    sender_id: int,
    body: str,
    *,
    is_urgent: bool = False,
    grid_ref: typing.Optional[str] = None,
    sync_status: str = "synced",
) -> Message:
    """
    Store a chat message.  Returns the stored Message.
    SQLCipher encrypts the row at rest; no additional field encryption is applied.
    Raises ValueError for empty body.
    """
    body = body.strip()
    if not body:
        raise ValueError("Message body is required.")
    now = int(time.time())
    grid_val = grid_ref.strip() if grid_ref and grid_ref.strip() else None
    cursor = conn.execute(
        "INSERT INTO messages (channel_id, sender_id, body, sent_at, is_urgent, grid_ref, uuid, sync_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            channel_id, sender_id, body.encode(), now, int(is_urgent), grid_val,
            _uuid_mod.uuid4().hex, sync_status,
        ),
    )
    conn.commit()
    return Message(
        id=cursor.lastrowid,
        channel_id=channel_id,
        sender_id=sender_id,
        body=body.encode(),
        sent_at=now,
        version=1,
        is_urgent=is_urgent,
        grid_ref=grid_val,
    )


def delete_message(conn: Connection, message_id: int) -> None:
    """Permanently delete a single message.  Server operator only."""
    conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def load_channels(conn: Connection) -> list[Channel]:
    """
    Load all channels ordered: group channels first (by name), then DMs.
    """
    rows = conn.execute(
        "SELECT id, name, mission_id, is_dm, version, group_type "
        "FROM channels ORDER BY is_dm ASC, name ASC"
    ).fetchall()
    return [_row_to_channel(r) for r in rows]


def load_messages(
    conn: Connection,
    channel_id: int,
    *,
    limit: int = 100,
) -> list[tuple[Message, str]]:
    """
    Load up to `limit` messages for a channel, oldest first.
    Returns (Message, sender_callsign) pairs.
    """
    rows = conn.execute(
        "SELECT m.id, m.channel_id, m.sender_id, m.body, m.sent_at, m.version, "
        "COALESCE(o.callsign, 'UNKNOWN'), m.is_urgent, m.grid_ref "
        "FROM messages m "
        "LEFT JOIN operators o ON m.sender_id = o.id "
        "WHERE m.channel_id = ? ORDER BY m.sent_at ASC LIMIT ?",
        (channel_id, limit),
    ).fetchall()

    result: list[tuple[Message, str]] = []
    for row in rows:
        body_bytes = bytes(row[3])
        msg = Message(
            id=row[0], channel_id=row[1], sender_id=row[2],
            body=body_bytes, sent_at=row[4], version=row[5],
            is_urgent=bool(row[7]), grid_ref=row[8],
        )
        result.append((msg, row[6]))
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def dm_callsigns(conn: Connection, channel: Channel) -> tuple[str, str]:
    """
    For a DM channel named 'dm:<a>:<b>', look up and return (callsign_a, callsign_b).
    Falls back to 'UNKNOWN' for missing operator rows.
    """
    try:
        _, a_str, b_str = channel.name.split(":")
        a_id, b_id = int(a_str), int(b_str)
    except (ValueError, AttributeError):
        return ("UNKNOWN", "UNKNOWN")
    rows = conn.execute(
        "SELECT id, callsign FROM operators WHERE id IN (?, ?)", (a_id, b_id)
    ).fetchall()
    lookup = {r[0]: r[1] for r in rows}
    return (lookup.get(a_id, "UNKNOWN"), lookup.get(b_id, "UNKNOWN"))


def _row_to_channel(row: tuple) -> Channel:
    return Channel(
        id=row[0], name=row[1], mission_id=row[2], is_dm=bool(row[3]), version=row[4],
        group_type=row[5] if len(row) > 5 and row[5] else ("direct" if bool(row[3]) else "squad"),
    )

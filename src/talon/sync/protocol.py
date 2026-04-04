# talon/sync/protocol.py
# Delta sync protocol for T.A.L.O.N.
#
# "Delta sync" means we only send CHANGES, not the entire database.
# Each record has a version number that increments on every change.
# During sync, the client tells the server "here's my latest version
# numbers" and the server responds with only the records that are newer.
#
# Sync flow:
# 1. Client → Server: "My latest versions are: operators=5, assets=12, ..."
# 2. Server → Client: "Here are the records newer than what you have"
# 3. Client → Server: "Here are records I created/modified locally"
# 4. Server → Client: "Acknowledged. Here's your refreshed lease token."
#
# Conflict resolution:
# - Server always wins (its version is authoritative)
# - Client's conflicting version is saved as an "amendment"
# - Both operators are notified to review
# - Exception: append-only data (SITREPs, chat) cannot conflict
# - Exception: position updates — most recent timestamp wins

import json
import time


# All the data tables that participate in sync.
# Listed in sync priority order (most critical first).
SYNC_TABLES = [
    "operators",
    "assets",
    "asset_categories",
    "sitreps",
    "sitrep_entries",
    "missions",
    "objectives",
    "mission_notes",
    "waypoints",
    "routes",
    "zones",
    "channels",
    "messages",
    "documents",
]


def build_sync_request(conn) -> dict:
    """Build a sync request containing this node's latest version numbers.

    The client calls this to tell the server what data it already has.

    Args:
        conn: An open database connection.

    Returns:
        Dictionary mapping table names to their highest version numbers.
        Example: {"operators": 5, "assets": 12, "sitreps": 3}
    """
    versions = {}
    cursor = conn.cursor()
    for table in SYNC_TABLES:
        try:
            result = cursor.execute(
                f"SELECT MAX(version) FROM {table}"
            ).fetchone()
            versions[table] = result[0] if result[0] is not None else 0
        except Exception:
            versions[table] = 0
    return {"type": "sync_request", "versions": versions, "timestamp": time.time()}


def build_sync_response(conn, client_versions: dict) -> dict:
    """Build a sync response with records newer than what the client has.

    The server calls this after receiving a sync request.

    Args:
        conn: An open database connection (server's database).
        client_versions: The version numbers from the client's sync request.

    Returns:
        Dictionary containing all records the client needs to update.
    """
    updates = {}
    cursor = conn.cursor()
    for table in SYNC_TABLES:
        client_ver = client_versions.get(table, 0)
        try:
            rows = cursor.execute(
                f"SELECT * FROM {table} WHERE version > ?",
                (client_ver,),
            ).fetchall()
            if rows:
                # Get column names for this table
                columns = [desc[0] for desc in cursor.description]
                updates[table] = [dict(zip(columns, row)) for row in rows]
        except Exception:
            pass
    return {"type": "sync_response", "updates": updates, "timestamp": time.time()}


def apply_sync_response(conn, response: dict) -> list:
    """Apply a sync response to the local database.

    The client calls this to update its local cache with data
    from the server.

    Args:
        conn: An open database connection (client's database).
        response: The sync response from the server.

    Returns:
        List of conflict descriptions (empty if no conflicts).
    """
    conflicts = []
    updates = response.get("updates", {})

    for table, records in updates.items():
        for record in records:
            try:
                _upsert_record(conn, table, record)
            except ConflictError as e:
                conflicts.append(str(e))

    conn.commit()
    return conflicts


def build_client_changes(conn) -> dict:
    """Collect all locally created/modified records to send to the server.

    Finds all records with sync_state = 'pending' — these are changes
    that haven't been sent to the server yet.

    Args:
        conn: An open database connection.

    Returns:
        Dictionary of tables and their pending records.
    """
    changes = {}
    cursor = conn.cursor()
    for table in SYNC_TABLES:
        try:
            rows = cursor.execute(
                f"SELECT * FROM {table} WHERE sync_state = 'pending'"
            ).fetchall()
            if rows:
                columns = [desc[0] for desc in cursor.description]
                changes[table] = [dict(zip(columns, row)) for row in rows]
        except Exception:
            pass
    return {"type": "client_changes", "changes": changes, "timestamp": time.time()}


def _upsert_record(conn, table: str, record: dict) -> None:
    """Insert or update a record in the local database.

    If the record doesn't exist locally, it's inserted.
    If it exists with a lower version, it's updated.
    If it exists with the same or higher version, it's a conflict.

    Args:
        conn: An open database connection.
        table: The table name.
        record: The record data as a dictionary.

    Raises:
        ConflictError: If the local version is same or higher.
    """
    cursor = conn.cursor()
    record_id = record.get("id")

    # Check if record exists locally
    existing = cursor.execute(
        f"SELECT version FROM {table} WHERE id = ?", (record_id,)
    ).fetchone()

    if existing is None:
        # New record — insert it
        columns = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        record["sync_state"] = "synced"
        cursor.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            list(record.values()),
        )
    elif existing[0] < record.get("version", 0):
        # Server has newer version — update ours
        set_clause = ", ".join([f"{k} = ?" for k in record.keys()])
        record["sync_state"] = "synced"
        cursor.execute(
            f"UPDATE {table} SET {set_clause} WHERE id = ?",
            list(record.values()) + [record_id],
        )
    else:
        # Conflict — our version is same or newer
        raise ConflictError(
            f"Conflict on {table}/{record_id}: "
            f"local version {existing[0]}, "
            f"incoming version {record.get('version', 0)}"
        )


class ConflictError(Exception):
    """Raised when a sync conflict is detected."""
    pass

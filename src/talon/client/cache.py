# talon/client/cache.py
# Client-side data caching.
#
# The client maintains a local encrypted copy of all data synced
# from the server. This allows the client to operate (read-only)
# even when there is no server connection.
#
# Cache behaviour:
#   - Online: data is synced continuously from server, cache updated
#   - Offline: UI reads from cache, writes go to the outbox
#   - When connection resumes: outbox is flushed to server
#
# The cache is stored in a SQLCipher database, same schema as the
# server but only containing data this client has been sent.

import json
import os
import time
from dataclasses import asdict, fields

from talon.crypto.keys import derive_master_key, derive_subkey, generate_salt
from talon.db.database import open_database
from talon.db.migrations import run_migrations
from talon.db.models import (
    Asset, Channel, Document, Message, Mission, MissionNote,
    Objective, Operator, SITREP, SITREPEntry,
)
from talon.sync.outbox import Outbox


# Maps table name → (dataclass, columns in DB order).
# JSON-serialized fields (lists) need special handling on read/write.
_TABLE_MAP = {
    "operators":      Operator,
    "assets":         Asset,
    "sitreps":        SITREP,
    "sitrep_entries": SITREPEntry,
    "missions":       Mission,
    "objectives":     Objective,
    "mission_notes":  MissionNote,
    "channels":       Channel,
    "messages":       Message,
    "documents":      Document,
}

# Fields stored as JSON text in SQLite but expected as Python lists.
_JSON_FIELDS = {"skills", "custom_skills", "tags", "boundary"}


def _row_to_dataclass(cls, columns, row):
    """Convert a database row tuple into a dataclass instance."""
    kwargs = {}
    for col, val in zip(columns, row):
        f_names = {f.name for f in fields(cls)}
        if col not in f_names:
            continue
        if col in _JSON_FIELDS and isinstance(val, str):
            try:
                val = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                val = []
        # SQLite stores bools as int
        if col == "deleted" and isinstance(val, int):
            val = bool(val)
        if col == "edited" and isinstance(val, int):
            val = bool(val)
        if col == "active" and isinstance(val, int):
            val = bool(val)
        kwargs[col] = val
    return cls(**kwargs)


def _dataclass_to_row(obj):
    """Convert a dataclass to a (columns, values) tuple for INSERT/UPDATE.

    JSON fields are serialized to strings. Bool fields become ints.
    """
    d = asdict(obj)
    columns = []
    values = []
    for key, val in d.items():
        if key in _JSON_FIELDS and isinstance(val, (list, dict)):
            val = json.dumps(val)
        if isinstance(val, bool):
            val = int(val)
        columns.append(key)
        values.append(val)
    return columns, values


class ClientCache:
    """Manages the client's local encrypted data cache.

    Attributes:
        db: SQLCipher database connection.
        outbox: Queue for changes made while offline.
        data_dir: Path to the client's data directory.
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.db = None
        self.outbox = Outbox()
        self._outbox_path = os.path.join(data_dir, "outbox.json")
        self._callsign = None

    def open(self, passphrase: str):
        """Open (or create) the client's local database.

        Args:
            passphrase: The operator's passphrase for key derivation.
        """
        db_path = os.path.join(self.data_dir, "client.db")
        salt_path = db_path + ".salt"

        # Load or generate salt
        if os.path.isfile(salt_path):
            with open(salt_path, "rb") as f:
                salt = f.read()
        else:
            salt = generate_salt()
            os.makedirs(self.data_dir, exist_ok=True)
            with open(salt_path, "wb") as f:
                f.write(salt)

        # Derive the database key
        master_key = derive_master_key(passphrase, salt)
        db_key = derive_subkey(master_key, "database")

        # Open encrypted database and ensure schema is current.
        # run_migrations handles both fresh DBs (creates tables) and
        # existing DBs (applies pending migrations).
        self.db = open_database(db_path, db_key.hex())
        run_migrations(self.db)

        # Load any pending outbox items from disk
        self._load_outbox()

    def close(self):
        """Close the database and persist the outbox."""
        self._save_outbox()
        if self.db:
            self.db.close()
            self.db = None

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def get_all(self, table: str) -> list:
        """Query all records from a table, returned as dataclass instances.

        Args:
            table: Table name (e.g. "sitreps", "assets", "missions").

        Returns:
            List of dataclass objects, or empty list on error.
        """
        cls = _TABLE_MAP.get(table)
        if cls is None or self.db is None:
            return []

        cursor = self.db.execute(f"SELECT * FROM {table}")
        columns = [desc[0] for desc in cursor.description]
        return [_row_to_dataclass(cls, columns, row) for row in cursor.fetchall()]

    def get_sitrep_entries(self, sitrep_id: str) -> list:
        """Get all entries for a SITREP, ordered by creation time.

        Args:
            sitrep_id: The parent SITREP's ID.
        """
        if self.db is None:
            return []
        cursor = self.db.execute(
            "SELECT * FROM sitrep_entries WHERE sitrep_id = ? "
            "ORDER BY created_at ASC",
            (sitrep_id,),
        )
        columns = [desc[0] for desc in cursor.description]
        return [_row_to_dataclass(SITREPEntry, columns, row)
                for row in cursor.fetchall()]

    def get_objectives(self, mission_id: str) -> list:
        """Get all objectives for a mission.

        Args:
            mission_id: The parent mission's ID.
        """
        if self.db is None:
            return []
        cursor = self.db.execute(
            "SELECT * FROM objectives WHERE mission_id = ? "
            "ORDER BY rowid ASC",
            (mission_id,),
        )
        columns = [desc[0] for desc in cursor.description]
        return [_row_to_dataclass(Objective, columns, row)
                for row in cursor.fetchall()]

    def get_mission_notes(self, mission_id: str) -> list:
        """Get all notes for a mission, ordered by creation time.

        Args:
            mission_id: The parent mission's ID.
        """
        if self.db is None:
            return []
        cursor = self.db.execute(
            "SELECT * FROM mission_notes WHERE mission_id = ? "
            "ORDER BY created_at ASC",
            (mission_id,),
        )
        columns = [desc[0] for desc in cursor.description]
        return [_row_to_dataclass(MissionNote, columns, row)
                for row in cursor.fetchall()]

    def get_messages(self, channel_id: str) -> list:
        """Get all messages in a channel, ordered by creation time.

        Args:
            channel_id: The channel's ID.
        """
        if self.db is None:
            return []
        cursor = self.db.execute(
            "SELECT * FROM messages WHERE channel_id = ? "
            "ORDER BY created_at ASC",
            (channel_id,),
        )
        columns = [desc[0] for desc in cursor.description]
        return [_row_to_dataclass(Message, columns, row)
                for row in cursor.fetchall()]

    def get_channel_members(self, channel_id: str) -> list:
        """Get operator IDs for a channel.

        Args:
            channel_id: The channel's ID.

        Returns:
            List of operator ID strings.
        """
        if self.db is None:
            return []
        cursor = self.db.execute(
            "SELECT operator_id FROM channel_members WHERE channel_id = ?",
            (channel_id,),
        )
        return [row[0] for row in cursor.fetchall()]

    def get_my_callsign(self) -> str:
        """Get the current operator's callsign.

        Looks up the first operator record with role='operator' in the
        local DB (the client only stores its own operator record and
        those it has synced). Falls back to a cached value if set.
        """
        if self._callsign:
            return self._callsign

        if self.db is None:
            return ""

        cursor = self.db.execute(
            "SELECT callsign FROM operators WHERE role = 'operator' LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            self._callsign = row[0]
            return self._callsign
        return ""

    def set_my_callsign(self, callsign: str):
        """Set the operator's callsign (called after enrollment)."""
        self._callsign = callsign

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    def _save_record(self, table: str, obj):
        """Insert or replace a record in the database.

        Uses INSERT OR REPLACE so it works for both new and updated
        records (all our tables have a TEXT PRIMARY KEY on id).
        """
        if self.db is None:
            return
        columns, values = _dataclass_to_row(obj)
        placeholders = ", ".join("?" for _ in values)
        col_names = ", ".join(columns)
        self.db.execute(
            f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})",
            values,
        )
        self.db.commit()

    def save_sitrep(self, sitrep: SITREP):
        """Save a SITREP to the local cache."""
        sitrep.sync_state = "pending"
        self._save_record("sitreps", sitrep)

    def save_sitrep_entry(self, entry: SITREPEntry):
        """Save a SITREP entry to the local cache."""
        entry.sync_state = "pending"
        self._save_record("sitrep_entries", entry)

    def save_asset(self, asset: Asset):
        """Save an asset to the local cache."""
        asset.updated_at = time.time()
        asset.sync_state = "pending"
        self._save_record("assets", asset)

    def save_mission(self, mission: Mission):
        """Save a mission to the local cache."""
        mission.updated_at = time.time()
        mission.sync_state = "pending"
        self._save_record("missions", mission)

    def save_objective(self, objective: Objective):
        """Save a mission objective to the local cache."""
        objective.updated_at = time.time()
        objective.sync_state = "pending"
        self._save_record("objectives", objective)

    def save_message(self, message: Message):
        """Save a chat message to the local cache."""
        message.sync_state = "pending"
        self._save_record("messages", message)

    def save_channel(self, channel: Channel):
        """Save a chat channel to the local cache."""
        channel.sync_state = "pending"
        self._save_record("channels", channel)

    def save_document(self, document: Document):
        """Save a document record to the local cache."""
        document.sync_state = "pending"
        self._save_record("documents", document)

    # ------------------------------------------------------------------
    # Outbox (offline change queue)
    # ------------------------------------------------------------------

    def queue_change(self, table: str, operation: str, record: dict):
        """Queue a change for sync when we're back online.

        Args:
            table: Which table this record belongs to.
            operation: What happened — "insert", "update", or "delete".
            record: The record dict to sync.
        """
        self.outbox.add(table, operation, record)
        self._save_outbox()

    def get_pending_changes(self) -> list:
        """Get all queued changes."""
        return self.outbox.get_pending()

    def clear_synced(self):
        """Clear the outbox after successful sync."""
        self.outbox.clear()
        self._save_outbox()

    def _load_outbox(self):
        """Load outbox from disk."""
        if os.path.isfile(self._outbox_path):
            with open(self._outbox_path, "r") as f:
                data = f.read()
            if data.strip():
                self.outbox = Outbox.from_json(data)

    def _save_outbox(self):
        """Persist outbox to disk."""
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self._outbox_path, "w") as f:
            f.write(self.outbox.to_json())

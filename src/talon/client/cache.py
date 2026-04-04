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

import os
from talon.crypto.keys import derive_master_key, derive_subkey, generate_salt
from talon.db.database import open_database, initialize_tables
from talon.db.migrations import run_migrations
from talon.sync.outbox import Outbox


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

        # Open encrypted database
        self.db = open_database(db_path, db_key.hex())
        initialize_tables(self.db)
        run_migrations(self.db)

        # Load any pending outbox items from disk
        self._load_outbox()

    def close(self):
        """Close the database and persist the outbox."""
        self._save_outbox()
        if self.db:
            self.db.close()
            self.db = None

    def queue_change(self, table: str, record: dict):
        """Queue a change for sync when we're back online.

        Args:
            table: Which table this record belongs to.
            record: The record dict to sync.
        """
        self.outbox.add(table, record)
        self._save_outbox()

    def get_pending_changes(self) -> dict:
        """Get all queued changes, grouped by table."""
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

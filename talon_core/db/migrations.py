"""
Schema migration engine.

Migrations are embedded SQL strings applied in order. The applied version is
stored in a `meta` table within the encrypted database.

To add a migration: append a new string to MIGRATIONS and bump DB_SCHEMA_VERSION
in talon/constants.py.
"""
import sqlcipher3.dbapi2 as sqlcipher  # type: ignore

from talon_core.constants import DB_SCHEMA_VERSION
from talon_core.db.connection import Connection

# Each entry is a complete SQL block applied as a transaction.
# Index 0 = migration 0001 (creates schema from scratch).
MIGRATIONS: list[str] = [
    # 0001 — initial schema
    """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS operators (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        callsign    TEXT    NOT NULL UNIQUE,
        rns_hash    TEXT    NOT NULL UNIQUE,
        skills      TEXT    NOT NULL DEFAULT '[]',  -- JSON array
        profile     TEXT    NOT NULL DEFAULT '{}',  -- JSON object
        enrolled_at INTEGER NOT NULL,               -- Unix timestamp
        lease_expires_at INTEGER NOT NULL,
        revoked     INTEGER NOT NULL DEFAULT 0      -- boolean
    );

    CREATE TABLE IF NOT EXISTS assets (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        category     TEXT    NOT NULL,
        label        TEXT    NOT NULL,
        description  TEXT    NOT NULL DEFAULT '',
        lat          REAL,
        lon          REAL,
        verified     INTEGER NOT NULL DEFAULT 0,    -- boolean
        created_by   INTEGER NOT NULL REFERENCES operators(id),
        confirmed_by INTEGER REFERENCES operators(id),
        created_at   INTEGER NOT NULL,
        version      INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS sitreps (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        level        TEXT    NOT NULL,              -- SITREP_LEVELS
        template     TEXT    NOT NULL DEFAULT '',
        body         BLOB    NOT NULL,              -- field-encrypted
        author_id    INTEGER NOT NULL REFERENCES operators(id),
        mission_id   INTEGER REFERENCES missions(id),
        created_at   INTEGER NOT NULL,
        version      INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS missions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        title        TEXT    NOT NULL,
        status       TEXT    NOT NULL DEFAULT 'active',
        created_by   INTEGER NOT NULL REFERENCES operators(id),
        created_at   INTEGER NOT NULL,
        version      INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS waypoints (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_id   INTEGER NOT NULL REFERENCES missions(id),
        sequence     INTEGER NOT NULL,
        label        TEXT    NOT NULL,
        lat          REAL    NOT NULL,
        lon          REAL    NOT NULL,
        version      INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS zones (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        label        TEXT    NOT NULL,
        zone_type    TEXT    NOT NULL,              -- AO, DANGER, RESTRICTED, etc.
        polygon      TEXT    NOT NULL,              -- JSON array of [lat, lon] pairs
        mission_id   INTEGER REFERENCES missions(id),
        created_by   INTEGER NOT NULL REFERENCES operators(id),
        created_at   INTEGER NOT NULL,
        version      INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS documents (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        filename     TEXT    NOT NULL,
        mime_type    TEXT    NOT NULL,
        size_bytes   INTEGER NOT NULL,
        data         BLOB    NOT NULL,              -- field-encrypted
        uploaded_by  INTEGER NOT NULL REFERENCES operators(id),
        uploaded_at  INTEGER NOT NULL,
        version      INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS channels (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT    NOT NULL UNIQUE,
        mission_id   INTEGER REFERENCES missions(id),
        is_dm        INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS messages (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id   INTEGER NOT NULL REFERENCES channels(id),
        sender_id    INTEGER NOT NULL REFERENCES operators(id),
        body         BLOB    NOT NULL,              -- field-encrypted for DMs
        sent_at      INTEGER NOT NULL,
        version      INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS enrollment_tokens (
        token        TEXT    PRIMARY KEY,
        created_at   INTEGER NOT NULL,
        expires_at   INTEGER NOT NULL,
        used_at      INTEGER,                       -- NULL = not yet consumed
        operator_id  INTEGER REFERENCES operators(id)
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        event        TEXT    NOT NULL,
        payload      BLOB    NOT NULL,              -- field-encrypted JSON
        occurred_at  INTEGER NOT NULL
    );

    INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '1');
    """,

    # 0002 — seed SERVER operator sentinel
    #
    # author_id in sitreps (and other tables) is a NOT NULL FK to operators.
    # In Phase 1, the server operator authenticates by passphrase only and has
    # no enrolled operator record.  This sentinel (id=1, callsign='SERVER')
    # satisfies the FK constraint for server-originated records.
    #
    # TODO: once enrollment is implemented, update this sentinel with the server
    # operator's real callsign and RNS hash, or re-attribute existing rows via a
    # follow-up migration.  See wiki/decisions.md — "Server Operator Sentinel".
    """
    INSERT OR IGNORE INTO operators
        (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked)
    VALUES
        (1, 'SERVER', 'server-identity-sentinel', '[]', '{}', 0, 9999999999, 0);
    """,

    # 0003 — link SITREPs to assets (optional, one asset per SITREP)
    #
    # nullable FK: a SITREP can be filed stand-alone or attached to a specific
    # asset (e.g. "food cache running low" → asset_id = cache row id).
    """
    ALTER TABLE sitreps ADD COLUMN asset_id INTEGER REFERENCES assets(id);
    """,

    # 0004 — BUG-029: add missing version column to channels (required for delta
    #         sync via build_version_map); BUG-033: add secondary indexes for
    #         common query patterns to avoid full table scans as data grows.
    """
    ALTER TABLE channels ADD COLUMN version INTEGER NOT NULL DEFAULT 1;

    CREATE INDEX idx_sitreps_level       ON sitreps(level);
    CREATE INDEX idx_sitreps_created_at  ON sitreps(created_at);
    CREATE INDEX idx_assets_category     ON assets(category);
    CREATE INDEX idx_assets_verified     ON assets(verified);
    CREATE INDEX idx_operators_revoked   ON operators(revoked);
    CREATE INDEX idx_messages_channel_ts ON messages(channel_id, sent_at);
    CREATE INDEX idx_audit_occurred_at   ON audit_log(occurred_at);
    CREATE INDEX idx_tokens_pending      ON enrollment_tokens(used_at, expires_at);
    """,

    # 0005 — mission approval workflow
    #
    # description: freeform context for the mission (requested by operator, editable
    #              by server before approval).
    # assets.mission_id: tracks which mission an asset is requested/allocated to.
    #   NULL      = free (available for new missions)
    #   non-NULL  = requested (if mission.status = pending_approval)
    #               or allocated (if mission.status = active)
    #   Released back to NULL on reject / abort / complete.
    """
    ALTER TABLE missions ADD COLUMN description TEXT NOT NULL DEFAULT '';
    ALTER TABLE assets   ADD COLUMN mission_id  INTEGER REFERENCES missions(id);

    CREATE INDEX idx_assets_mission_id ON assets(mission_id);
    """,

    # 0006 — document filesystem storage
    #
    # Replaces the original inline BLOB design with filesystem-backed storage:
    #   file_path   : opaque internal filename ("{id}_{uuid4}.bin") within the
    #                 configured storage directory.  Empty string = upload
    #                 incomplete (cleaned up at server startup).
    #   sha256_hash : hex SHA-256 of the plaintext content, checked on every
    #                 download to detect corruption or tampering.
    #   description : optional operator-supplied note.
    #
    # The old `data BLOB` column is dropped — no production data exists yet
    # (schema-only, no prior implementation).  Requires SQLite >= 3.35.
    """
    ALTER TABLE documents ADD COLUMN file_path   TEXT NOT NULL DEFAULT '';
    ALTER TABLE documents ADD COLUMN sha256_hash TEXT NOT NULL DEFAULT '';
    ALTER TABLE documents ADD COLUMN description TEXT NOT NULL DEFAULT '';
    ALTER TABLE documents DROP COLUMN data;

    CREATE INDEX idx_documents_uploaded_at ON documents(uploaded_at);
    CREATE INDEX idx_documents_uploaded_by ON documents(uploaded_by);
    """,

    # 0007 — seed network-identity meta keys
    #
    # server_rns_hash : hex destination hash of the server's talon.server RNS
    #                   destination.  Populated on the client after successful
    #                   enrollment; empty string on the server (unused).
    # my_operator_id  : integer operator id for the local operator.  Populated
    #                   on the client after enrollment; empty string on the server
    #                   (server uses the sentinel id=1 directly).
    #
    # INSERT OR IGNORE means these rows are no-ops on DBs that already have them
    # (e.g. a server upgrading from schema 6).
    """
    INSERT OR IGNORE INTO meta (key, value) VALUES ('server_rns_hash', '');
    INSERT OR IGNORE INTO meta (key, value) VALUES ('my_operator_id', '');
    """,

    # 0008 — add version column to operators (required for delta sync)
    #
    # Every other synced table has a version counter from the initial schema,
    # but operators was missed.  ServerNetHandler._build_delta() selects
    # `version` explicitly; without this column the query throws
    # OperationalError which aborts the entire sync exchange for all tables.
    #
    # DEFAULT 1 is applied to all existing rows (SERVER sentinel + any already-
    # enrolled operators).  New operators inserted by create_operator() pick up
    # the DEFAULT automatically since that INSERT does not set version explicitly.
    """
    ALTER TABLE operators ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
    """,

    # 0009 — deleted_records tombstone table (required for delete propagation)
    #
    # When the server deletes a record, the deletion must be propagated to
    # clients that are currently offline and will reconnect later.  A simple
    # "push_delete" RNS message handles online clients; tombstones cover
    # offline clients that reconnect after the fact.
    #
    # On reconnect the client sends last_sync_at (Unix timestamp of its last
    # successful sync).  The server returns all tombstones with deleted_at >
    # last_sync_at so the client can remove those records from its local DB.
    #
    # UNIQUE(table_name, record_id) ensures that if a record is re-created
    # and deleted again, we keep only the most recent tombstone (via
    # INSERT OR REPLACE).
    """
    CREATE TABLE IF NOT EXISTS deleted_records (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name  TEXT    NOT NULL,
        record_id   INTEGER NOT NULL,
        deleted_at  INTEGER NOT NULL,
        UNIQUE(table_name, record_id)
    );
    CREATE INDEX IF NOT EXISTS idx_deleted_records_at ON deleted_records(deleted_at);
    """,

    # 0010 — UUID-based record identity + offline intel support
    #
    # uuid: cross-network identity for each record.  Generated by the creator
    #       (server or client) using uuid4().hex.  UNIQUE enforced by index.
    #       ALTER TABLE cannot add NOT NULL without a default; rows are back-filled
    #       immediately and new inserts always supply a uuid.
    #
    # sync_status: only on tables a client can create while offline.
    #   'synced'  — server has acknowledged this record (default for all
    #               records received via sync_response or push_update).
    #   'pending' — locally created while offline, not yet pushed to server.
    #
    # amendments: stores offline edits the server rejected (server version was
    #             newer).  UI surfaces these so operators can see what was
    #             superseded by the server's authoritative version.
    """
    ALTER TABLE assets    ADD COLUMN uuid TEXT;
    ALTER TABLE sitreps   ADD COLUMN uuid TEXT;
    ALTER TABLE missions  ADD COLUMN uuid TEXT;
    ALTER TABLE waypoints ADD COLUMN uuid TEXT;
    ALTER TABLE zones     ADD COLUMN uuid TEXT;
    ALTER TABLE documents ADD COLUMN uuid TEXT;
    ALTER TABLE channels  ADD COLUMN uuid TEXT;
    ALTER TABLE messages  ADD COLUMN uuid TEXT;
    ALTER TABLE operators ADD COLUMN uuid TEXT;

    UPDATE assets    SET uuid = lower(hex(randomblob(16))) WHERE uuid IS NULL;
    UPDATE sitreps   SET uuid = lower(hex(randomblob(16))) WHERE uuid IS NULL;
    UPDATE missions  SET uuid = lower(hex(randomblob(16))) WHERE uuid IS NULL;
    UPDATE waypoints SET uuid = lower(hex(randomblob(16))) WHERE uuid IS NULL;
    UPDATE zones     SET uuid = lower(hex(randomblob(16))) WHERE uuid IS NULL;
    UPDATE documents SET uuid = lower(hex(randomblob(16))) WHERE uuid IS NULL;
    UPDATE channels  SET uuid = lower(hex(randomblob(16))) WHERE uuid IS NULL;
    UPDATE messages  SET uuid = lower(hex(randomblob(16))) WHERE uuid IS NULL;
    UPDATE operators SET uuid = lower(hex(randomblob(16))) WHERE uuid IS NULL;

    CREATE UNIQUE INDEX idx_assets_uuid    ON assets(uuid);
    CREATE UNIQUE INDEX idx_sitreps_uuid   ON sitreps(uuid);
    CREATE UNIQUE INDEX idx_missions_uuid  ON missions(uuid);
    CREATE UNIQUE INDEX idx_waypoints_uuid ON waypoints(uuid);
    CREATE UNIQUE INDEX idx_zones_uuid     ON zones(uuid);
    CREATE UNIQUE INDEX idx_documents_uuid ON documents(uuid);
    CREATE UNIQUE INDEX idx_channels_uuid  ON channels(uuid);
    CREATE UNIQUE INDEX idx_messages_uuid  ON messages(uuid);
    CREATE UNIQUE INDEX idx_operators_uuid ON operators(uuid);

    ALTER TABLE assets   ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'synced';
    ALTER TABLE sitreps  ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'synced';
    ALTER TABLE missions ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'synced';
    ALTER TABLE zones    ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'synced';

    CREATE INDEX idx_assets_sync_status   ON assets(sync_status);
    CREATE INDEX idx_sitreps_sync_status  ON sitreps(sync_status);
    CREATE INDEX idx_missions_sync_status ON missions(sync_status);
    CREATE INDEX idx_zones_sync_status    ON zones(sync_status);

    CREATE TABLE IF NOT EXISTS amendments (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name   TEXT    NOT NULL,
        record_uuid  TEXT    NOT NULL,
        client_data  TEXT    NOT NULL,
        server_data  TEXT    NOT NULL,
        created_at   INTEGER NOT NULL,
        reviewed     INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_amendments_reviewed ON amendments(reviewed);
    """,

    # 0011 — Chat UI redesign: urgent flag, grid coordinate, channel group type
    """
    ALTER TABLE messages ADD COLUMN is_urgent INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE messages ADD COLUMN grid_ref TEXT;

    ALTER TABLE channels ADD COLUMN group_type TEXT NOT NULL DEFAULT 'squad';

    UPDATE channels SET group_type = 'direct'    WHERE is_dm = 1;
    UPDATE channels SET group_type = 'mission'   WHERE mission_id IS NOT NULL AND is_dm = 0;
    UPDATE channels SET group_type = 'allhands'  WHERE name IN ('#general','#sitrep-feed','#alerts') AND is_dm = 0;
    UPDATE channels SET group_type = 'emergency' WHERE name = '#flash' AND is_dm = 0;
    """,

    # 0012 — Asset deletion requests: clients flag assets for server-side review
    """
    ALTER TABLE assets ADD COLUMN deletion_requested INTEGER NOT NULL DEFAULT 0;
    """,

    # 0013 — Mission extended fields for OPORD-style 5-step create wizard
    #
    # All new columns are TEXT with empty-string defaults so existing rows and
    # existing code paths remain valid without changes.  JSON columns (phases,
    # constraints, objectives, key_locations) store serialized JSON arrays/objects;
    # callers must json.loads() on read and json.dumps() on write.
    """
    ALTER TABLE missions ADD COLUMN mission_type       TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN priority           TEXT NOT NULL DEFAULT 'ROUTINE';
    ALTER TABLE missions ADD COLUMN lead_coordinator   TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN organization       TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN activation_time    TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN operation_window   TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN max_duration       TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN staging_area       TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN demob_point        TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN standdown_criteria TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN phases             TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE missions ADD COLUMN constraints        TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE missions ADD COLUMN support_medical    TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN support_logistics  TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN support_comms      TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN support_equipment  TEXT NOT NULL DEFAULT '';
    ALTER TABLE missions ADD COLUMN objectives         TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE missions ADD COLUMN key_locations      TEXT NOT NULL DEFAULT '{}';
    """,

    # 0014 — Custom mission resource entries
    #
    # The OPORD-style wizard has fixed support fields for common categories
    # (medical/logistics/comms/equipment).  Custom resource variants are stored
    # as a JSON array of objects, each with a caller-defined label and details.
    """
    ALTER TABLE missions ADD COLUMN custom_resources TEXT NOT NULL DEFAULT '[]';
    """,

    # 0015 — Client-pushable chat messages
    #
    # Messages already have UUIDs from migration 0010 and are part of normal
    # server->client sync. Adding sync_status lets the existing client outbox
    # carry client-authored chat messages back to the server using the same
    # push/ack path as SITREPs, missions, assets, and zones.
    """
    ALTER TABLE messages ADD COLUMN sync_status TEXT NOT NULL DEFAULT 'synced';
    CREATE INDEX idx_messages_sync_status ON messages(sync_status);
    """,
]


# BUG-034: guard against MIGRATIONS list and DB_SCHEMA_VERSION drifting out of
# sync — a mismatch would cause silent version skips or schema corruption.
assert len(MIGRATIONS) == DB_SCHEMA_VERSION, (
    f"MIGRATIONS has {len(MIGRATIONS)} entries but DB_SCHEMA_VERSION="
    f"{DB_SCHEMA_VERSION}. Update constants.py when adding a migration."
)


def get_schema_version(conn: Connection) -> int:
    # BUG-031: only catch OperationalError (meta table not yet created on a fresh
    # DB). Let DatabaseError propagate — it indicates a wrong passphrase and must
    # not be silently swallowed as version 0.
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return int(row[0]) if row else 0
    except sqlcipher.OperationalError:
        return 0  # meta table does not exist yet — fresh DB


def apply_migrations(conn: Connection) -> None:
    """Apply any unapplied migrations in order.

    Each migration SQL and the schema-version bump are wrapped in an explicit
    BEGIN/COMMIT block embedded inside the executescript() call.

    Why not SAVEPOINT: executescript() always issues an implicit COMMIT before
    running, which destroys any active savepoint.  Embedding BEGIN/COMMIT in the
    script itself is the only way to get full atomicity with executescript().
    If the script raises before COMMIT, conn.rollback() clears the open
    transaction and the schema version is left unchanged.

    executescript() does not support parameter placeholders, so migration_version
    is interpolated directly — this is safe because it is derived from enumerate().
    """
    current = get_schema_version(conn)
    for i, sql in enumerate(MIGRATIONS):
        migration_version = i + 1
        if migration_version <= current:
            continue
        script = (
            f"BEGIN;\n"
            f"{sql.strip()}\n"
            f"UPDATE meta SET value = '{migration_version}' WHERE key = 'schema_version';\n"
            f"COMMIT;\n"
        )
        try:
            conn.executescript(script)
        except Exception:
            conn.rollback()
            raise

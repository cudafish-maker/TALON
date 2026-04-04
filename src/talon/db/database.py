# talon/db/database.py
# SQLCipher database connection and setup.
#
# SQLCipher is SQLite but encrypted — the entire database file is
# encrypted with AES-256. Without the correct key, the file looks
# like random noise.
#
# Connection flow:
# 1. Open the database file
# 2. Provide the encryption key (derived from passphrase + lease)
# 3. If the key is correct, the database is accessible
# 4. If the key is wrong, you get an error (not garbage data)

import sqlcipher3 as sqlite3


def open_database(db_path: str, key: bytes) -> sqlite3.Connection:
    """Open an encrypted SQLCipher database.

    If the database file doesn't exist yet, it will be created
    and encrypted with the given key.

    Args:
        db_path: File path to the .db file (e.g., "data/talon_server.db").
        key: The encryption key as bytes. For clients, this is derived
             from the operator's passphrase. For the server, it's
             derived from the server master key.

    Returns:
        A database connection object. Use this to run SQL queries.

    Raises:
        sqlite3.DatabaseError: If the key is wrong or the file is corrupt.
    """
    conn = sqlite3.connect(db_path)

    # Pass the encryption key to SQLCipher.
    # The key must be set BEFORE any other operations on the database.
    conn.execute(f"PRAGMA key = \"x'{key.hex()}'\"")

    # Use WAL mode for better concurrent read performance.
    # WAL = Write-Ahead Logging — allows reads while writing.
    conn.execute("PRAGMA journal_mode = WAL")

    # Enable foreign keys so relationships between tables are enforced.
    # For example, a SITREP entry must belong to an existing SITREP.
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def close_database(conn: sqlite3.Connection) -> None:
    """Safely close the database connection.

    Always call this when shutting down the app to ensure all
    data is written and the file is properly closed.

    Args:
        conn: The database connection from open_database().
    """
    if conn:
        conn.close()


def initialize_tables(conn: sqlite3.Connection) -> None:
    """Create all database tables if they don't already exist.

    This is called on first run to set up the database schema.
    On subsequent runs, existing tables are left untouched.
    The "IF NOT EXISTS" clause makes this safe to call every time.

    Args:
        conn: An open database connection.
    """
    cursor = conn.cursor()

    # --- Operators ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operators (
            id TEXT PRIMARY KEY,              -- Unique identifier (UUID)
            callsign TEXT UNIQUE NOT NULL,    -- Display name (e.g., WOLF-1)
            reticulum_identity TEXT UNIQUE,   -- Reticulum public key hash
            role TEXT NOT NULL DEFAULT 'operator',  -- 'operator' or 'server'
            status TEXT NOT NULL DEFAULT 'active',  -- active/soft_locked/revoked
            skills TEXT DEFAULT '[]',         -- JSON list of skill names
            custom_skills TEXT DEFAULT '[]',  -- JSON list of custom skills
            bio TEXT DEFAULT '',              -- Free-text notes about the operator
            enrolled_at REAL NOT NULL,        -- Unix timestamp of enrollment
            last_sync REAL,                   -- Unix timestamp of last sync
            version INTEGER NOT NULL DEFAULT 1,  -- Increments on every change
            sync_state TEXT DEFAULT 'pending'     -- pending/synced/conflict
        )
    """)

    # --- Assets ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,               -- Label for the asset
            category TEXT NOT NULL,            -- AssetCategory enum value
            custom_category TEXT,              -- Name if category is CUSTOM
            latitude REAL,                    -- GPS latitude
            longitude REAL,                   -- GPS longitude
            status TEXT NOT NULL DEFAULT 'active',  -- active/inactive/compromised
            verification TEXT NOT NULL DEFAULT 'unverified',
            verified_by TEXT,                 -- Callsign of verifying operator
            created_by TEXT NOT NULL,          -- Callsign of creator
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            notes TEXT DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (created_by) REFERENCES operators(callsign)
        )
    """)

    # --- Custom Asset Categories ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS asset_categories (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,         -- Category display name
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending'
        )
    """)

    # --- SITREPs ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sitreps (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,                -- 'predefined' or 'freeform'
            template_name TEXT,                -- Which template (if predefined)
            importance TEXT NOT NULL DEFAULT 'ROUTINE',
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0,      -- 1 = deleted by server
            delete_reason TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (created_by) REFERENCES operators(callsign)
        )
    """)

    # --- SITREP Entries (append-only) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sitrep_entries (
            id TEXT PRIMARY KEY,
            sitrep_id TEXT NOT NULL,           -- Which SITREP this belongs to
            author TEXT NOT NULL,              -- Who wrote this entry
            content TEXT NOT NULL,             -- The actual report text
            created_at REAL NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (sitrep_id) REFERENCES sitreps(id),
            FOREIGN KEY (author) REFERENCES operators(callsign)
        )
    """)

    # --- Missions ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS missions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'PLANNING',
            priority TEXT NOT NULL DEFAULT 'ROUTINE',
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (created_by) REFERENCES operators(callsign)
        )
    """)

    # --- Mission Objectives ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS objectives (
            id TEXT PRIMARY KEY,
            mission_id TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            assigned_to TEXT,                  -- Operator callsign
            updated_at REAL NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (mission_id) REFERENCES missions(id),
            FOREIGN KEY (assigned_to) REFERENCES operators(callsign)
        )
    """)

    # --- Mission Notes (append-only, like SITREP entries) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mission_notes (
            id TEXT PRIMARY KEY,
            mission_id TEXT NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (mission_id) REFERENCES missions(id),
            FOREIGN KEY (author) REFERENCES operators(callsign)
        )
    """)

    # --- Linking tables for missions ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mission_operators (
            mission_id TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            PRIMARY KEY (mission_id, operator_id),
            FOREIGN KEY (mission_id) REFERENCES missions(id),
            FOREIGN KEY (operator_id) REFERENCES operators(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mission_assets (
            mission_id TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            PRIMARY KEY (mission_id, asset_id),
            FOREIGN KEY (mission_id) REFERENCES missions(id),
            FOREIGN KEY (asset_id) REFERENCES assets(id)
        )
    """)

    # --- Waypoints ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS waypoints (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            type TEXT NOT NULL DEFAULT 'CHECKPOINT',
            notes TEXT DEFAULT '',
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (created_by) REFERENCES operators(callsign)
        )
    """)

    # --- Routes ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS routes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            distance REAL,                    -- Auto-calculated in meters
            status TEXT NOT NULL DEFAULT 'PLANNED',
            mission_id TEXT,                  -- Optional link to a mission
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            notes TEXT DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (mission_id) REFERENCES missions(id),
            FOREIGN KEY (created_by) REFERENCES operators(callsign)
        )
    """)

    # --- Route-Waypoint ordering ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS route_waypoints (
            route_id TEXT NOT NULL,
            waypoint_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,         -- Order in the route (1, 2, 3...)
            PRIMARY KEY (route_id, waypoint_id),
            FOREIGN KEY (route_id) REFERENCES routes(id),
            FOREIGN KEY (waypoint_id) REFERENCES waypoints(id)
        )
    """)

    # --- Zones ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS zones (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'AO',
            boundary TEXT NOT NULL,            -- JSON list of [lat, lon] points
            color TEXT DEFAULT '#00e5a0',      -- Hex color for map display
            active INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL,
            created_at REAL NOT NULL,
            notes TEXT DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (created_by) REFERENCES operators(callsign)
        )
    """)

    # --- Chat Channels ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,                -- ChannelType enum value
            created_by TEXT,
            created_at REAL NOT NULL,
            mission_id TEXT,                   -- If type is MISSION
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (mission_id) REFERENCES missions(id)
        )
    """)

    # --- Channel Membership ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channel_members (
            channel_id TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            PRIMARY KEY (channel_id, operator_id),
            FOREIGN KEY (channel_id) REFERENCES channels(id),
            FOREIGN KEY (operator_id) REFERENCES operators(id)
        )
    """)

    # --- Chat Messages ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            sender TEXT NOT NULL,               -- Operator callsign
            type TEXT NOT NULL DEFAULT 'TEXT',   -- MessageType enum
            body TEXT NOT NULL,
            created_at REAL NOT NULL,
            edited INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (channel_id) REFERENCES channels(id),
            FOREIGN KEY (sender) REFERENCES operators(callsign)
        )
    """)

    # --- Message Read Receipts ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_reads (
            message_id TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            read_at REAL NOT NULL,
            PRIMARY KEY (message_id, operator_id),
            FOREIGN KEY (message_id) REFERENCES messages(id),
            FOREIGN KEY (operator_id) REFERENCES operators(id)
        )
    """)

    # --- Pinned Messages ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pinned_messages (
            channel_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            pinned_by TEXT NOT NULL,
            pinned_at REAL NOT NULL,
            PRIMARY KEY (channel_id, message_id),
            FOREIGN KEY (channel_id) REFERENCES channels(id),
            FOREIGN KEY (message_id) REFERENCES messages(id)
        )
    """)

    # --- Documents ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Manual',
            file_type TEXT NOT NULL,           -- PDF, image, text, etc.
            file_path TEXT NOT NULL,           -- Path to the encrypted file on disk
            file_size INTEGER NOT NULL,        -- Size in bytes
            tags TEXT DEFAULT '[]',            -- JSON list of tag strings
            access_level TEXT DEFAULT 'ALL',   -- ALL or RESTRICTED
            uploaded_by TEXT NOT NULL,
            uploaded_at REAL NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            sync_state TEXT DEFAULT 'pending',
            FOREIGN KEY (uploaded_by) REFERENCES operators(callsign)
        )
    """)

    # --- Audit Log (server only) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,          -- AuditEvent enum value
            timestamp REAL NOT NULL,
            client_callsign TEXT,              -- Which client triggered this
            details TEXT DEFAULT '',            -- Free-text details
            transport TEXT                     -- Which interface was used
        )
    """)

    # --- Client Registry (server only) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS client_registry (
            id TEXT PRIMARY KEY,
            callsign TEXT UNIQUE NOT NULL,
            reticulum_identity TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            enrolled_at REAL NOT NULL,
            last_sync REAL,
            lease_expires_at REAL,
            revoked_at REAL,
            revoke_reason TEXT
        )
    """)

    # --- Deny List (server only) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deny_list (
            reticulum_identity TEXT PRIMARY KEY,
            callsign TEXT NOT NULL,
            denied_at REAL NOT NULL,
            reason TEXT DEFAULT ''
        )
    """)

    conn.commit()

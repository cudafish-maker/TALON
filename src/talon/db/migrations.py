# talon/db/migrations.py
# Database schema versioning and migration runner.
#
# As T.A.L.O.N. evolves, we may need to add new columns or tables
# to the database. Migrations handle this automatically so that
# existing databases are upgraded without losing data.
#
# How it works:
# 1. The database stores a "schema_version" in PRAGMA user_version.
# 2. Each migration is a function that upgrades from version N to N+1.
# 3. On startup, the app checks the current version and runs any
#    migrations that haven't been applied yet.
#
# Fresh vs existing databases:
#   - Fresh DB (version 0, no tables): initialize_tables() creates
#     the latest schema. We then stamp CURRENT_VERSION directly —
#     no migrations run.
#   - Existing DB (version > 0): skip initialize_tables' IF NOT EXISTS
#     and run only the pending migrations.
#
# This avoids the conflict where a migration tries to ALTER TABLE
# ADD COLUMN on a column that initialize_tables already created.

import logging

log = logging.getLogger(__name__)


def get_schema_version(conn) -> int:
    """Get the current schema version of the database.

    Args:
        conn: An open database connection.

    Returns:
        The current version number. Returns 0 if no version is set
        (brand new database).
    """
    try:
        cursor = conn.execute("PRAGMA user_version")
        return cursor.fetchone()[0]
    except Exception:
        return 0


def set_schema_version(conn, version: int) -> None:
    """Set the schema version.

    Uses PRAGMA user_version which is stored in the database header —
    no extra table needed.

    Args:
        conn: An open database connection.
        version: The new version number to store.
    """
    conn.execute(f"PRAGMA user_version = {int(version)}")


def _is_fresh_database(conn) -> bool:
    """Check whether this is a brand new database with no tables.

    A fresh database has user_version 0 AND no application tables.
    An existing database that was created before versioning was added
    will have user_version 0 but WILL have tables — those need
    migrations applied from version 1 onward.

    Args:
        conn: An open database connection.

    Returns:
        True if the database has no application tables.
    """
    cursor = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return cursor.fetchone()[0] == 0


# --- Migration functions ---------------------------------------------------
# Each function takes a database connection and upgrades by one version.
# Migrations MUST be idempotent where possible (use IF NOT EXISTS, etc.)
# so that a retry after a partial failure doesn't break things.


def _migrate_v1_to_v2(conn):
    """v1 → v2: Add description column to enrollment_tokens.

    Allows server operators to annotate what each token is for
    (e.g., "for Alpha team lead").
    """
    conn.execute("ALTER TABLE enrollment_tokens ADD COLUMN description TEXT NOT NULL DEFAULT ''")


# The current schema version. Increment this when adding new migrations.
CURRENT_VERSION = 2

# Ordered list of migration functions.
# Index 0 = migration from v0→v1 (initial schema, None = handled by
#            initialize_tables), index 1 = v1→v2, etc.
MIGRATIONS = [
    None,  # v0 → v1: initial schema via initialize_tables
    _migrate_v1_to_v2,  # v1 → v2: enrollment_tokens.description
]


class MigrationError(Exception):
    """Raised when a migration fails."""

    pass


def run_migrations(conn) -> int:
    """Ensure the database schema is up to date.

    This is the single entry point for schema management. It handles
    three cases:

    1. **Fresh database** (version 0, no tables): calls
       initialize_tables() to create the latest schema, then stamps
       CURRENT_VERSION. No migrations run.

    2. **Existing database, behind** (version < CURRENT_VERSION):
       runs each pending migration in a transaction.

    3. **Already current** (version >= CURRENT_VERSION): no-op.

    Callers should call this INSTEAD of initialize_tables() directly.
    For backwards compatibility, calling initialize_tables() then
    run_migrations() also works — the version check prevents double
    application.

    Args:
        conn: An open database connection.

    Returns:
        The number of migrations applied (0 if already up to date
        or freshly created).

    Raises:
        MigrationError: If a migration function fails.
    """
    current = get_schema_version(conn)
    is_fresh = current == 0 and _is_fresh_database(conn)

    if is_fresh:
        # Brand new database — create the latest schema directly
        from talon.db.database import initialize_tables

        initialize_tables(conn)
        set_schema_version(conn, CURRENT_VERSION)
        conn.commit()
        log.info("Fresh database — created schema at version %d", CURRENT_VERSION)
        return 0

    if current >= CURRENT_VERSION:
        return 0  # Already up to date

    applied = 0
    for version in range(current + 1, CURRENT_VERSION + 1):
        idx = version - 1
        migration = MIGRATIONS[idx] if idx < len(MIGRATIONS) else None

        if migration is None:
            # No-op migration (e.g., v0→v1 initial schema)
            set_schema_version(conn, version)
            conn.commit()
            applied += 1
            continue

        log.info("Applying migration v%d → v%d ...", version - 1, version)
        try:
            conn.execute("BEGIN")
            migration(conn)
            set_schema_version(conn, version)
            conn.commit()
            applied += 1
            log.info("Migration v%d → v%d complete.", version - 1, version)
        except Exception as exc:
            conn.rollback()
            raise MigrationError(f"Migration v{version - 1} → v{version} failed: {exc}") from exc

    return applied

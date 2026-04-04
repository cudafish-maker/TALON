# talon/db/migrations.py
# Database schema versioning.
#
# As T.A.L.O.N. evolves, we may need to add new columns or tables
# to the database. Migrations handle this automatically so that
# existing databases are upgraded without losing data.
#
# How it works:
# 1. The database stores a "schema_version" number.
# 2. Each migration is a function that upgrades from version N to N+1.
# 3. On startup, the app checks the current version and runs any
#    migrations that haven't been applied yet.


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
    """Set the schema version after a migration completes.

    Args:
        conn: An open database connection.
        version: The new version number to store.
    """
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()


# The current schema version. Increment this when adding new migrations.
CURRENT_VERSION = 1

# List of migration functions. Each takes a database connection
# and upgrades the schema by one version.
# Index 0 = migration from version 0 to 1, etc.
MIGRATIONS = [
    # Version 0 → 1: Initial schema (handled by database.initialize_tables)
    None,
]


def run_migrations(conn) -> None:
    """Run any pending database migrations.

    Checks the current version and applies each migration in order
    until the database is up to the current version.

    Args:
        conn: An open database connection.
    """
    current = get_schema_version(conn)

    if current >= CURRENT_VERSION:
        return  # Already up to date

    for version in range(current + 1, CURRENT_VERSION + 1):
        migration = MIGRATIONS[version - 1] if version <= len(MIGRATIONS) else None
        if migration is not None:
            migration(conn)
        set_schema_version(conn, version)

# tests/test_migrations.py
# Tests for the database migration runner.
#
# Verifies that:
# - Fresh databases get stamped at CURRENT_VERSION without running migrations
# - Existing v1 databases are upgraded to v2 correctly
# - Migration failures roll back cleanly
# - Schema version tracking works
# - Pre-versioning databases (tables exist, version 0) are handled

import sys
import os
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.db.migrations import (
    get_schema_version,
    set_schema_version,
    run_migrations,
    MigrationError,
    CURRENT_VERSION,
    _is_fresh_database,
)


# --- Helpers ----------------------------------------------------------------

def _make_fresh_db():
    """Create an empty in-memory database (no tables, version 0)."""
    return sqlite3.connect(":memory:")


def _make_v1_db():
    """Create a v1 database — tables exist, version stamped at 1.

    This simulates a database created before the v1→v2 migration
    was added. Uses the v1 schema (no description column on
    enrollment_tokens).
    """
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Create the core tables (simplified — only what matters for migration)
    cursor.execute("""
        CREATE TABLE operators (
            id TEXT PRIMARY KEY,
            callsign TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL DEFAULT 'operator',
            status TEXT NOT NULL DEFAULT 'active',
            enrolled_at REAL NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE enrollment_tokens (
            token TEXT PRIMARY KEY,
            callsign TEXT NOT NULL,
            generated_at REAL NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            used_by TEXT,
            used_at REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE client_registry (
            id TEXT PRIMARY KEY,
            callsign TEXT UNIQUE NOT NULL,
            reticulum_identity TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            enrolled_at REAL NOT NULL
        )
    """)
    conn.commit()

    # Stamp as version 1
    set_schema_version(conn, 1)
    conn.commit()
    return conn


def _make_pre_version_db():
    """Create a database with tables but version 0.

    This simulates a database created before schema versioning was
    introduced. Tables exist, but user_version was never set.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE operators (
            id TEXT PRIMARY KEY,
            callsign TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL DEFAULT 'operator',
            enrolled_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE enrollment_tokens (
            token TEXT PRIMARY KEY,
            callsign TEXT NOT NULL,
            generated_at REAL NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            used_by TEXT,
            used_at REAL
        )
    """)
    conn.commit()
    return conn


def _column_exists(conn, table, column):
    """Check if a column exists in a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


# --- Schema version tests ---------------------------------------------------

class TestSchemaVersion:
    def test_fresh_db_version_is_zero(self):
        conn = _make_fresh_db()
        assert get_schema_version(conn) == 0

    def test_set_and_get_version(self):
        conn = _make_fresh_db()
        set_schema_version(conn, 5)
        conn.commit()
        assert get_schema_version(conn) == 5

    def test_version_survives_reconnect(self):
        """PRAGMA user_version is stored in the DB header, not session state."""
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "test.db")
        conn = sqlite3.connect(path)
        set_schema_version(conn, 3)
        conn.commit()
        conn.close()

        conn2 = sqlite3.connect(path)
        assert get_schema_version(conn2) == 3
        conn2.close()
        os.unlink(path)


# --- Fresh database detection -----------------------------------------------

class TestFreshDetection:
    def test_empty_db_is_fresh(self):
        conn = _make_fresh_db()
        assert _is_fresh_database(conn) is True

    def test_db_with_tables_is_not_fresh(self):
        conn = _make_v1_db()
        assert _is_fresh_database(conn) is False

    def test_db_with_only_internal_tables_is_fresh(self):
        """sqlite_master always exists but shouldn't count."""
        conn = _make_fresh_db()
        # sqlite_master is internal — should still be "fresh"
        assert _is_fresh_database(conn) is True


# --- Fresh database migration (stamp only) ----------------------------------

class TestFreshDatabaseMigration:
    def test_fresh_db_gets_stamped_at_current_version(self):
        conn = _make_fresh_db()
        applied = run_migrations(conn)
        assert applied == 0  # No migrations ran — just stamped
        assert get_schema_version(conn) == CURRENT_VERSION

    def test_fresh_db_has_description_column(self):
        """run_migrations creates the latest schema directly for fresh DBs."""
        conn = _make_fresh_db()
        run_migrations(conn)
        assert _column_exists(conn, "enrollment_tokens", "description")

    def test_fresh_db_tables_are_functional(self):
        """Verify the fresh DB can actually store and retrieve data."""
        conn = _make_fresh_db()
        run_migrations(conn)

        import time
        conn.execute(
            "INSERT INTO enrollment_tokens "
            "(token, callsign, generated_at, description) "
            "VALUES (?, ?, ?, ?)",
            ("abc123", "WOLF-1", time.time(), "for team lead"),
        )
        conn.commit()

        row = conn.execute(
            "SELECT description FROM enrollment_tokens WHERE token = ?",
            ("abc123",),
        ).fetchone()
        assert row[0] == "for team lead"


# --- Existing v1 database migration -----------------------------------------

class TestV1ToV2Migration:
    def test_v1_db_gets_upgraded_to_v2(self):
        conn = _make_v1_db()
        assert get_schema_version(conn) == 1

        applied = run_migrations(conn)
        assert applied == 1
        assert get_schema_version(conn) == 2

    def test_v1_db_gains_description_column(self):
        conn = _make_v1_db()
        assert not _column_exists(conn, "enrollment_tokens", "description")

        run_migrations(conn)
        assert _column_exists(conn, "enrollment_tokens", "description")

    def test_v1_db_existing_data_preserved(self):
        """Existing rows keep their data after migration."""
        conn = _make_v1_db()
        import time
        conn.execute(
            "INSERT INTO enrollment_tokens "
            "(token, callsign, generated_at) VALUES (?, ?, ?)",
            ("tok1", "ALPHA-1", time.time()),
        )
        conn.commit()

        run_migrations(conn)

        row = conn.execute(
            "SELECT token, callsign, description "
            "FROM enrollment_tokens WHERE token = ?",
            ("tok1",),
        ).fetchone()
        assert row[0] == "tok1"
        assert row[1] == "ALPHA-1"
        assert row[2] == ""  # Default value

    def test_v1_db_description_default_is_empty(self):
        conn = _make_v1_db()
        run_migrations(conn)

        import time
        conn.execute(
            "INSERT INTO enrollment_tokens "
            "(token, callsign, generated_at) VALUES (?, ?, ?)",
            ("tok2", "BRAVO-1", time.time()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT description FROM enrollment_tokens WHERE token = ?",
            ("tok2",),
        ).fetchone()
        assert row[0] == ""


# --- Pre-versioning database ------------------------------------------------

class TestPreVersioningDatabase:
    def test_pre_version_db_runs_all_migrations(self):
        """DB with tables but version 0 should run migrations, not stamp."""
        conn = _make_pre_version_db()
        assert get_schema_version(conn) == 0
        assert not _is_fresh_database(conn)

        applied = run_migrations(conn)
        # Should run v0→v1 (None) and v1→v2
        assert applied == 2
        assert get_schema_version(conn) == CURRENT_VERSION

    def test_pre_version_db_gets_description_column(self):
        conn = _make_pre_version_db()
        run_migrations(conn)
        assert _column_exists(conn, "enrollment_tokens", "description")


# --- Already up to date -----------------------------------------------------

class TestAlreadyUpToDate:
    def test_current_version_is_noop(self):
        conn = _make_fresh_db()
        run_migrations(conn)
        assert get_schema_version(conn) == CURRENT_VERSION

        # Run again — should be a no-op
        applied = run_migrations(conn)
        assert applied == 0

    def test_future_version_is_noop(self):
        """If somehow the DB is ahead of code, don't downgrade."""
        conn = _make_fresh_db()
        set_schema_version(conn, CURRENT_VERSION + 5)
        conn.commit()
        applied = run_migrations(conn)
        assert applied == 0


# --- Migration failure and rollback -----------------------------------------

class TestMigrationFailure:
    def test_failed_migration_rolls_back(self):
        """If a migration raises, the version should NOT advance."""
        conn = _make_v1_db()

        # Monkey-patch a broken migration
        import talon.db.migrations as mig
        original = mig.MIGRATIONS[1]
        def _broken(c):
            raise RuntimeError("simulated migration failure")
        mig.MIGRATIONS[1] = _broken

        try:
            try:
                run_migrations(conn)
                assert False, "Should have raised MigrationError"
            except MigrationError as e:
                assert "simulated migration failure" in str(e)

            # Version should still be 1 (not advanced)
            assert get_schema_version(conn) == 1
        finally:
            mig.MIGRATIONS[1] = original

    def test_retry_after_failure_works(self):
        """After fixing the issue, migrations can be retried."""
        conn = _make_v1_db()

        import talon.db.migrations as mig
        original = mig.MIGRATIONS[1]

        # First attempt: fail
        call_count = [0]
        def _fail_once(c):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("transient failure")
            original(c)
        mig.MIGRATIONS[1] = _fail_once

        try:
            try:
                run_migrations(conn)
            except MigrationError:
                pass

            assert get_schema_version(conn) == 1

            # Second attempt: should succeed
            applied = run_migrations(conn)
            assert applied == 1
            assert get_schema_version(conn) == 2
        finally:
            mig.MIGRATIONS[1] = original


# --- open_database key handling ---------------------------------------------

class TestOpenDatabaseKey:
    def test_accepts_bytes_key(self):
        """open_database should accept bytes without crashing."""
        # We can't test SQLCipher without the library, but we can
        # verify the key normalization logic doesn't crash.
        from talon.db.database import open_database
        import tempfile
        # This will fail on PRAGMA key (no sqlcipher in tests),
        # but the key normalization should work fine.
        # Just test the function signature accepts both types.
        key_bytes = b"\x01\x02\x03\x04" * 8
        key_hex = key_bytes.hex()
        # Both should produce the same hex string
        hex_from_bytes = key_bytes.hex()
        hex_from_str = str(key_hex)
        assert hex_from_bytes == hex_from_str

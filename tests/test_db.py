"""Tests for talon.db.connection and talon.db.migrations."""
import threading
import time

import pytest


class TestConnection:
    def test_open_and_close(self, tmp_db):
        conn, _ = tmp_db
        # If open_db succeeded, WAL is set
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    def test_foreign_keys_enabled(self, tmp_db):
        conn, _ = tmp_db
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1

    def test_implicit_write_failure_rolls_back_cleanly(self, tmp_db):
        conn, _ = tmp_db
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('dup_key', 'one')"
        )
        conn.commit()

        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('dup_key', 'two')"
            )

        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('after_failure', 'ok')"
        )
        conn.commit()

        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'after_failure'"
        ).fetchone()
        assert row[0] == "ok"

    def test_transaction_context_rolls_back_on_exception(self, tmp_db):
        conn, _ = tmp_db

        with pytest.raises(RuntimeError):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('tx_outer', '1')"
                )
                raise RuntimeError("boom")

        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'tx_outer'"
        ).fetchone()
        assert row is None

    def test_nested_transaction_uses_savepoint(self, tmp_db):
        conn, _ = tmp_db

        with conn.transaction():
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('outer_before', '1')"
            )
            with pytest.raises(ValueError):
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO meta (key, value) VALUES ('inner_only', '1')"
                    )
                    raise ValueError("inner rollback")
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('outer_after', '1')"
            )

        keys = {
            row[0]
            for row in conn.execute(
                "SELECT key FROM meta WHERE key IN ('outer_before', 'inner_only', 'outer_after')"
            ).fetchall()
        }
        assert keys == {"outer_before", "outer_after"}

    def test_concurrent_writes_serialize(self, tmp_db):
        conn, _ = tmp_db
        writer_started = threading.Event()
        release_writer = threading.Event()
        second_attempted = threading.Event()
        second_finished = threading.Event()
        errors: list[BaseException] = []

        def _writer_one() -> None:
            try:
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO meta (key, value) VALUES ('writer_one', '1')"
                    )
                    writer_started.set()
                    release_writer.wait(timeout=2)
            except BaseException as exc:  # pragma: no cover - test worker
                errors.append(exc)

        def _writer_two() -> None:
            try:
                writer_started.wait(timeout=2)
                second_attempted.set()
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('writer_two', '1')"
                )
                conn.commit()
            except BaseException as exc:  # pragma: no cover - test worker
                errors.append(exc)
            finally:
                second_finished.set()

        t1 = threading.Thread(target=_writer_one, daemon=True)
        t2 = threading.Thread(target=_writer_two, daemon=True)
        t1.start()
        t2.start()

        assert writer_started.wait(timeout=2)
        assert second_attempted.wait(timeout=2)
        time.sleep(0.1)
        assert second_finished.is_set() is False

        release_writer.set()
        t1.join(timeout=2)
        t2.join(timeout=2)

        assert not errors
        keys = {
            row[0]
            for row in conn.execute(
                "SELECT key FROM meta WHERE key IN ('writer_one', 'writer_two')"
            ).fetchall()
        }
        assert keys == {"writer_one", "writer_two"}

    def test_begin_shutdown_waits_for_writer_and_blocks_new_writes(self, tmp_db):
        conn, _ = tmp_db
        writer_started = threading.Event()
        release_writer = threading.Event()
        shutdown_finished = threading.Event()
        errors: list[BaseException] = []

        def _writer() -> None:
            try:
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO meta (key, value) VALUES ('shutdown_hold', '1')"
                    )
                    writer_started.set()
                    release_writer.wait(timeout=2)
            except BaseException as exc:  # pragma: no cover - test worker
                errors.append(exc)

        def _shutdown() -> None:
            try:
                writer_started.wait(timeout=2)
                conn.begin_shutdown()
            except BaseException as exc:  # pragma: no cover - test worker
                errors.append(exc)
            finally:
                shutdown_finished.set()

        writer = threading.Thread(target=_writer, daemon=True)
        stopper = threading.Thread(target=_shutdown, daemon=True)
        writer.start()
        stopper.start()

        assert writer_started.wait(timeout=2)
        time.sleep(0.1)
        assert shutdown_finished.is_set() is False

        release_writer.set()
        writer.join(timeout=2)
        stopper.join(timeout=2)

        assert not errors
        with pytest.raises(RuntimeError, match="shutting down"):
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('after_shutdown', '1')"
            )


class TestMigrations:
    def test_schema_version_after_migration(self, tmp_db):
        from talon.db.migrations import get_schema_version
        conn, _ = tmp_db
        from talon.constants import DB_SCHEMA_VERSION
        assert get_schema_version(conn) == DB_SCHEMA_VERSION

    def test_tables_exist(self, tmp_db):
        conn, _ = tmp_db
        tables_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r[0] for r in tables_row}
        expected = {
            "meta", "operators", "assets", "sitreps", "missions",
            "waypoints", "zones", "documents", "channels", "messages",
            "enrollment_tokens", "audit_log",
        }
        assert expected.issubset(table_names)

    def test_apply_migrations_idempotent(self, tmp_db):
        from talon.db.migrations import apply_migrations, get_schema_version
        conn, _ = tmp_db
        version_before = get_schema_version(conn)
        apply_migrations(conn)  # second call — should be a no-op
        assert get_schema_version(conn) == version_before

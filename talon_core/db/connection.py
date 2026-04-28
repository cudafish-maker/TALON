"""
SQLCipher connection factory.

The key is derived externally by talon.crypto.keystore and passed in as bytes.
This module never touches Argon2id — separation of concerns.

Migrations are embedded as SQL strings (not external files) so they survive
Android APK packaging without special Buildozer datas configuration.
"""
import contextlib
import itertools
import logging
import os
import pathlib
import re
import threading
import typing

import sqlcipher3.dbapi2 as sqlcipher  # type: ignore

_log = logging.getLogger("db.connection")

_RawConnection = sqlcipher.Connection

_SQL_KEYWORD_RE = re.compile(
    r"^\s*(?:(?:--[^\n]*\n)\s*|/\*.*?\*/\s*)*([A-Za-z]+)",
    re.DOTALL,
)
_WRITE_KEYWORDS = frozenset({
    "ALTER",
    "ANALYZE",
    "ATTACH",
    "BEGIN",
    "COMMIT",
    "CREATE",
    "DELETE",
    "DETACH",
    "DROP",
    "END",
    "INSERT",
    "REINDEX",
    "RELEASE",
    "REPLACE",
    "ROLLBACK",
    "SAVEPOINT",
    "UPDATE",
    "VACUUM",
})
_TXN_START_KEYWORDS = frozenset({"BEGIN", "SAVEPOINT"})
_TXN_END_KEYWORDS = frozenset({"COMMIT", "END", "RELEASE", "ROLLBACK"})


def _statement_keyword(sql: str) -> str:
    match = _SQL_KEYWORD_RE.match(sql)
    if not match:
        return ""
    return match.group(1).upper()


class DbTransaction(contextlib.AbstractContextManager["DbConnection"]):
    """Small transaction helper with nested savepoint support."""

    def __init__(self, conn: "DbConnection", *, immediate: bool = True) -> None:
        self._conn = conn
        self._immediate = immediate
        self._savepoint: typing.Optional[str] = None

    def __enter__(self) -> "DbConnection":
        if self._conn._is_owned_transaction():
            self._savepoint = f"talon_sp_{next(self._conn._savepoint_counter)}"
            self._conn.execute(f"SAVEPOINT {self._savepoint}")
        else:
            begin_sql = "BEGIN IMMEDIATE" if self._immediate else "BEGIN"
            self._conn.execute(begin_sql)
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._savepoint is not None:
            if exc_type is None:
                self._conn.execute(f"RELEASE SAVEPOINT {self._savepoint}")
            else:
                self._conn.execute(f"ROLLBACK TO SAVEPOINT {self._savepoint}")
                self._conn.execute(f"RELEASE SAVEPOINT {self._savepoint}")
            return False

        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False


class DbConnection:
    """Thread-aware wrapper around one shared SQLCipher connection."""

    def __init__(self, conn: _RawConnection) -> None:
        self._conn = conn
        self._state_lock = threading.RLock()
        self._state_changed = threading.Condition(self._state_lock)
        self._writer_owner: typing.Optional[int] = None
        self._active_calls = 0
        self._closing = False
        self._closed = False
        self._savepoint_counter = itertools.count(1)

    @property
    def in_transaction(self) -> bool:
        return bool(getattr(self._conn, "in_transaction", False))

    def transaction(self, *, immediate: bool = True) -> DbTransaction:
        return DbTransaction(self, immediate=immediate)

    def begin_shutdown(self) -> None:
        """Reject new DB work and wait for any in-flight writer to finish."""
        with self._state_changed:
            if self._closed:
                return
            self._closing = True
            self._state_changed.notify_all()
            while self._active_calls > 0 or self._writer_owner is not None:
                self._state_changed.wait()

    def execute(self, sql: str, parameters: typing.Sequence[typing.Any] = ()):
        keyword = _statement_keyword(sql)
        is_write = keyword in _WRITE_KEYWORDS
        ident, auto_begin, claimed_owner = self._enter_call(
            write_keyword=keyword,
            claim_write=is_write,
        )
        try:
            if is_write and auto_begin:
                self._conn.execute("BEGIN IMMEDIATE")
            cursor = self._conn.execute(sql, parameters)
            if is_write:
                self._finalize_write(ident)
            return cursor
        except Exception:
            if is_write:
                self._handle_write_failure(
                    ident,
                    auto_begin=auto_begin,
                    claimed_owner=claimed_owner,
                )
            raise
        finally:
            self._leave_call()

    def executemany(self, sql: str, seq_of_parameters):
        keyword = _statement_keyword(sql)
        is_write = keyword in _WRITE_KEYWORDS
        ident, auto_begin, claimed_owner = self._enter_call(
            write_keyword=keyword,
            claim_write=is_write,
        )
        try:
            if is_write and auto_begin:
                self._conn.execute("BEGIN IMMEDIATE")
            cursor = self._conn.executemany(sql, seq_of_parameters)
            if is_write:
                self._finalize_write(ident)
            return cursor
        except Exception:
            if is_write:
                self._handle_write_failure(
                    ident,
                    auto_begin=auto_begin,
                    claimed_owner=claimed_owner,
                )
            raise
        finally:
            self._leave_call()

    def executescript(self, sql_script: str):
        ident, _auto_begin, claimed_owner = self._enter_call(claim_write=True)
        try:
            cursor = self._conn.executescript(sql_script)
            self._finalize_write(ident)
            return cursor
        except Exception:
            self._handle_write_failure(
                ident,
                auto_begin=False,
                claimed_owner=claimed_owner,
            )
            raise
        finally:
            self._leave_call()

    def commit(self) -> None:
        ident, _auto_begin, _claimed_owner = self._enter_call(write_keyword="COMMIT")
        try:
            self._conn.commit()
            self._finalize_write(ident)
        except Exception:
            self._handle_write_failure(ident, auto_begin=False, claimed_owner=False)
            raise
        finally:
            self._leave_call()

    def rollback(self) -> None:
        ident, _auto_begin, _claimed_owner = self._enter_call(write_keyword="ROLLBACK")
        try:
            self._conn.rollback()
            self._finalize_write(ident)
        except Exception:
            self._handle_write_failure(ident, auto_begin=False, claimed_owner=False)
            raise
        finally:
            self._leave_call()

    def close(self) -> None:
        with self._state_changed:
            if self._closed:
                return
        self.begin_shutdown()
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            self._conn.close()
            with self._state_changed:
                self._closed = True
                self._state_changed.notify_all()

    def _enter_call(
        self,
        *,
        write_keyword: str = "",
        claim_write: bool = False,
    ) -> tuple[int, bool, bool]:
        ident = threading.get_ident()
        with self._state_changed:
            while True:
                if self._closed:
                    raise RuntimeError("Database connection is closed.")
                if self._closing and self._writer_owner != ident:
                    raise RuntimeError("Database connection is shutting down.")
                if self._writer_owner is None or self._writer_owner == ident:
                    auto_begin = False
                    claimed_owner = False
                    if (
                        self._writer_owner is None
                        and claim_write
                        and write_keyword not in _TXN_END_KEYWORDS
                    ):
                        self._writer_owner = ident
                        claimed_owner = True
                        auto_begin = bool(write_keyword) and write_keyword not in _TXN_START_KEYWORDS
                    self._active_calls += 1
                    return ident, auto_begin, claimed_owner
                self._state_changed.wait()

    def _leave_call(self) -> None:
        with self._state_changed:
            self._active_calls = max(0, self._active_calls - 1)
            self._state_changed.notify_all()

    def _finalize_write(self, ident: int) -> None:
        with self._state_changed:
            if self._writer_owner == ident and not self.in_transaction:
                self._writer_owner = None
                self._state_changed.notify_all()

    def _handle_write_failure(
        self,
        ident: int,
        *,
        auto_begin: bool,
        claimed_owner: bool,
    ) -> None:
        if auto_begin:
            try:
                self._conn.rollback()
            except Exception:
                pass
        with self._state_changed:
            if (
                self._writer_owner == ident
                and (auto_begin or claimed_owner or not self.in_transaction)
            ):
                self._writer_owner = None
                self._state_changed.notify_all()

    def _is_owned_transaction(self) -> bool:
        ident = threading.get_ident()
        with self._state_changed:
            return self._writer_owner == ident and self.in_transaction

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


Connection = DbConnection


@contextlib.contextmanager
def db_write(
    conn: typing.Union[DbConnection, _RawConnection],
    *,
    immediate: bool = True,
) -> typing.Iterator[typing.Union[DbConnection, _RawConnection]]:
    """Context-manager helper for explicit write transactions."""
    if isinstance(conn, DbConnection):
        with conn.transaction(immediate=immediate):
            yield conn
        return

    begin_sql = "BEGIN IMMEDIATE" if immediate else "BEGIN"
    conn.execute(begin_sql)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def open_db(path: pathlib.Path, key: bytes) -> Connection:
    """
    Open (or create) the SQLCipher database at path, unlocked with key.
    Applies WAL journal mode for reliability and wraps the raw connection in a
    small serializer that owns write transactions and shutdown.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except PermissionError as exc:
        raise RuntimeError(f"Could not secure database directory {path.parent}") from exc
    # check_same_thread=False: the connection is opened in the login background
    # thread then used from the Kivy UI thread.  SQLite runs in serialized mode
    # (thread-safe internally); this only disables Python's own redundant check.
    conn = sqlcipher.connect(str(path), check_same_thread=False)
    # key must be applied before any other statement
    hex_key = key.hex()
    conn.execute(f"PRAGMA key = \"x'{hex_key}'\"")
    # BUG-036: check that WAL was actually enabled — NFS/SMB and some Android
    # storage configs silently fall back to DELETE mode.
    actual_mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if actual_mode != "wal":
        _log.warning(
            "WAL journal mode unavailable (got %r) — using %s mode. "
            "Crash recovery guarantees are reduced.",
            actual_mode,
            actual_mode.upper(),
        )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        if path.exists():
            os.chmod(path, 0o600)
    except PermissionError:
        _log.warning("Could not chmod database file %s to 0600", path)
    return DbConnection(conn)


def close_db(conn: Connection) -> None:
    """Checkpoint WAL and close the connection."""
    conn.close()

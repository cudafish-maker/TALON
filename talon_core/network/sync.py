"""
Delta sync engine.

Each record type has a version counter incremented on every write.
During sync, the client sends its current version numbers; the server
replies with records whose version is greater than what the client has.

Conflict resolution: server version always wins.
Conflicts are logged; a future migration can add an amendments table if
a full audit trail of overwritten local edits is required.

Heartbeat intervals:
  - Broadband (Yggdrasil/I2P/TCP): 60 seconds
  - LoRa (RNode): 120 seconds
"""
import threading
import time
import typing

from talon_core.constants import HEARTBEAT_BROADBAND_S, HEARTBEAT_LORA_S
from talon_core.network.registry import (
    SYNC_TABLE_ALLOWLIST as _SYNC_TABLE_ALLOWLIST,
    SYNC_TABLES,
    validated_sync_table,
)
from talon_core.utils.logging import get_logger

_log = get_logger("network.sync")


def _validated_table(name: str) -> str:
    """Return *name* unchanged if it is in the sync allowlist, else raise."""
    return validated_sync_table(name)


class SyncEngine:
    def __init__(
        self,
        is_lora: bool = False,
        conn: typing.Optional[object] = None,
        operator_id: typing.Optional[int] = None,
        on_heartbeat: typing.Optional[typing.Callable[[], None]] = None,
        on_lease_expired: typing.Optional[typing.Callable[[], None]] = None,
        on_lease_renewed: typing.Optional[typing.Callable[[], None]] = None,
    ) -> None:
        self._interval = HEARTBEAT_LORA_S if is_lora else HEARTBEAT_BROADBAND_S
        self._conn = conn
        self._operator_id = operator_id
        self._on_heartbeat = on_heartbeat
        self._on_lease_expired = on_lease_expired
        self._on_lease_renewed = on_lease_renewed
        self._thread: typing.Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # Tracks whether we have already fired on_lease_expired so we only
        # fire on state transitions, not on every heartbeat tick.
        self._locked = False
        self._last_heartbeat_at: typing.Optional[int] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="talon-sync")
        self._thread.start()
        _log.info("Sync heartbeat started (interval=%ds)", self._interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                _log.warning("Sync thread did not exit within timeout — it may still be running.")
        _log.info("Sync heartbeat stopped")

    def _loop(self) -> None:
        # Fire immediately so a stale lease is detected the moment the app starts
        # rather than waiting a full interval.
        self._do_heartbeat()
        while not self._stop_event.wait(timeout=self._interval):
            self._do_heartbeat()

    def _do_heartbeat(self) -> None:
        self._last_heartbeat_at = int(time.time())
        try:
            self._check_lease()
        except Exception as exc:
            _log.warning("Lease check error: %s", exc)
        try:
            if self._on_heartbeat:
                self._on_heartbeat()
        except Exception as exc:
            _log.warning("Heartbeat callback error: %s", exc)

    def _check_lease(self) -> None:
        """Read lease status from DB and fire transition callbacks as needed."""
        if self._conn is None or self._operator_id is None:
            return
        row = self._conn.execute(
            "SELECT lease_expires_at, revoked FROM operators WHERE id = ?",
            (self._operator_id,),
        ).fetchone()
        if row is None:
            return
        lease_expires_at, revoked = row
        now = int(time.time())
        expired = bool(revoked) or (lease_expires_at < now)
        if expired and not self._locked:
            self._locked = True
            _log.info(
                "Lease expired for operator %s (expires=%s revoked=%s) — triggering lock",
                self._operator_id, lease_expires_at, revoked,
            )
            if self._on_lease_expired:
                self._on_lease_expired()
        elif not expired and self._locked:
            self._locked = False
            _log.info("Lease renewed for operator %s — dismissing lock", self._operator_id)
            if self._on_lease_renewed:
                self._on_lease_renewed()

    # ------------------------------------------------------------------
    # Version-map helpers (used to build delta sync requests)
    # ------------------------------------------------------------------

    @staticmethod
    def build_version_map(conn: object) -> dict[str, dict[int, int]]:
        """
        Build a map of {table_name: {record_id: version}} from the local DB.
        Used to compute the delta to request from the server.
        """
        assert hasattr(conn, "execute"), "conn must be a DB connection"
        version_map: dict[str, dict[int, int]] = {}
        for table in SYNC_TABLES:
            try:
                rows = conn.execute(
                    f"SELECT id, version FROM {_validated_table(table)}"  # noqa: S608
                ).fetchall()
                version_map[table] = {row[0]: row[1] for row in rows}
            except Exception:
                version_map[table] = {}
        return version_map

    # ------------------------------------------------------------------
    # Record application (server → client upsert)
    # ------------------------------------------------------------------

    @staticmethod
    def apply_server_record(
        conn: object,
        table: str,
        record: dict,
        local_version: typing.Optional[int],
    ) -> bool:
        """
        Apply a record received from the server.

        Server version always wins. If the local record has diverged, a warning
        is logged (conflict). The local overwrite is not saved separately because
        there is no amendments table in the current schema; add migration 0007 if
        a full conflict audit trail is required.

        Returns True if the record was applied, False if skipped (already current).
        """
        server_version = record.get("version", 1)
        if local_version is not None and local_version >= server_version:
            return False  # already up to date

        _log.debug(
            "Applying server record: table=%s id=%s v=%s",
            table, record.get("id"), server_version,
        )

        if conn is None:
            # No DB connection — used in tests to check version logic only.
            return True

        _validated_table(table)

        if local_version is not None and local_version > 0:
            _log.warning(
                "Sync conflict: table=%s id=%s local_v=%s server_v=%s — server wins",
                table, record.get("id"), local_version, server_version,
            )

        SyncEngine._upsert_record(conn, table, record)
        return True

    def set_operator_id(self, operator_id: typing.Optional[int]) -> None:
        """Update the operator monitored by the lease heartbeat."""
        self._operator_id = operator_id
        self._locked = False
        self._check_lease()

    def status(self) -> dict[str, typing.Any]:
        """Return a UI-safe heartbeat/lease status snapshot."""
        return {
            "started": self._thread is not None and self._thread.is_alive(),
            "interval_s": self._interval,
            "last_heartbeat_at": self._last_heartbeat_at,
            "locked": self._locked,
            "operator_id": self._operator_id,
        }

    @staticmethod
    def _upsert_record(conn: object, table: str, record: dict) -> None:
        """
        Insert a new record or update an existing row in place.

        Column names in *record* are validated against the live schema via
        PRAGMA table_info so injected keys from untrusted sync packets cannot
        reach the SQL statement.
        """
        _validated_table(table)
        # Gate columns against the actual schema — guards against injected keys
        # in records received from the network.
        valid_cols: set[str] = {
            row[1]
            for row in conn.execute(
                f"PRAGMA table_info({_validated_table(table)})"  # noqa: S608
            ).fetchall()
        }
        cols = [c for c in record if c in valid_cols]
        if not cols:
            raise ValueError(
                f"Record has no valid columns for table {table!r}: {list(record)}"
            )
        placeholders = ", ".join("?" for _ in cols)
        col_list = ", ".join(cols)
        values = [record[c] for c in cols]
        table_name = _validated_table(table)
        if "id" in cols:
            update_cols = [c for c in cols if c != "id"]
            if update_cols:
                assignments = ", ".join(f"{c} = excluded.{c}" for c in update_cols)
                conn.execute(
                    f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders}) "  # noqa: S608
                    f"ON CONFLICT(id) DO UPDATE SET {assignments}",
                    values,
                )
            else:
                conn.execute(
                    f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders}) "  # noqa: S608
                    "ON CONFLICT(id) DO NOTHING",
                    values,
                )
        else:
            conn.execute(
                f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})",  # noqa: S608
                values,
            )
        conn.commit()

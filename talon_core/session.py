"""Initial UI-independent core session facade.

This module starts the Phase 1 extraction without moving the existing backend
modules yet.  It gives new desktop/mobile clients a stable boundary while the
Kivy app can continue using the legacy imports during migration.
"""
from __future__ import annotations

import dataclasses
import pathlib
import typing

from talon_core.config import (
    get_data_dir,
    get_db_path,
    get_document_storage_path,
    get_mode,
    get_rns_config_dir,
    get_salt_path,
    load_config,
)
from talon_core.crypto.keystore import derive_key, load_or_create_salt
from talon_core.db.connection import close_db, open_db
from talon_core.db.migrations import apply_migrations
from talon_core.operators import (
    list_operators,
    require_local_operator_id,
    resolve_local_operator_id,
)
from talon_core.services.events import DomainEvent

Mode = typing.Literal["server", "client"]
EventHandler = typing.Callable[[DomainEvent], None]


class CoreSessionError(RuntimeError):
    """Raised when the core session is used in an invalid state."""


@dataclasses.dataclass(frozen=True)
class CorePaths:
    data_dir: pathlib.Path
    db_path: pathlib.Path
    salt_path: pathlib.Path
    rns_config_dir: pathlib.Path
    document_storage_path: pathlib.Path


@dataclasses.dataclass(frozen=True)
class CoreUnlockResult:
    mode: Mode
    operator_id: typing.Optional[int]
    db_path: pathlib.Path
    data_dir: pathlib.Path


@dataclasses.dataclass(frozen=True)
class DocumentListItem:
    document: object
    uploader_callsign: str


@dataclasses.dataclass(frozen=True)
class DocumentCommandResult:
    document_id: int
    document: typing.Optional[object]
    events: tuple[DomainEvent, ...]


@dataclasses.dataclass(frozen=True)
class DocumentDownloadResult:
    document: object
    plaintext: bytes


@dataclasses.dataclass(frozen=True)
class RecordCommandResult:
    table: str
    record_id: int
    events: tuple[DomainEvent, ...]


@dataclasses.dataclass(frozen=True)
class ChatCommandResult:
    table: str
    record_id: int
    channel: typing.Optional[object] = None
    message: typing.Optional[object] = None
    events: tuple[DomainEvent, ...] = ()


@dataclasses.dataclass(frozen=True)
class EnrollmentTokenResult:
    token: str
    server_hash: str
    combined: str
    events: tuple[DomainEvent, ...] = ()


@dataclasses.dataclass(frozen=True)
class SyncStatus:
    mode: Mode
    reticulum_started: bool
    sync_started: bool
    lease_monitor_started: bool
    connection_state: str
    connected: bool
    heartbeat_interval_s: typing.Optional[int]
    last_heartbeat_at: typing.Optional[int]
    lease_locked: typing.Optional[bool]
    monitored_operator_id: typing.Optional[int]
    pending_outbox_count: int
    pending_outbox_by_table: dict[str, int]
    last_sync_at: typing.Optional[int]
    active_client_count: int


@dataclasses.dataclass(frozen=True)
class DashboardSummary:
    mode: Mode
    unlocked: bool
    operator_id: typing.Optional[int]
    generated_at: int
    counts: dict[str, int]
    sync: SyncStatus
    paths: CorePaths


class TalonCoreSession:
    """UI-independent facade over TALON backend runtime state."""

    def __init__(
        self,
        *,
        config_path: typing.Optional[typing.Union[str, pathlib.Path]] = None,
        cfg=None,
        mode: typing.Optional[Mode] = None,
        on_lease_expired: typing.Optional[typing.Callable[[], None]] = None,
        on_lease_renewed: typing.Optional[typing.Callable[[], None]] = None,
        on_data_pushed: typing.Optional[typing.Callable[..., None]] = None,
        on_client_lock_check: typing.Optional[typing.Callable[[int], None]] = None,
    ) -> None:
        self._config_path = pathlib.Path(config_path) if config_path is not None else None
        self._cfg = cfg
        self._mode_override = mode
        self._mode: typing.Optional[Mode] = None
        self._paths: typing.Optional[CorePaths] = None
        self._conn = None
        self._db_key: typing.Optional[bytes] = None
        self._audit_key: typing.Optional[bytes] = None
        self._operator_id: typing.Optional[int] = None
        self._sync_engine = None
        self._net_handler = None
        self._client_sync = None
        self._reticulum_started = False
        self._event_handlers: list[EventHandler] = []
        self._on_lease_expired = on_lease_expired
        self._on_lease_renewed = on_lease_renewed
        self._on_data_pushed = on_data_pushed
        self._on_client_lock_check = on_client_lock_check

    @property
    def cfg(self):
        self._require_started()
        return self._cfg

    @property
    def mode(self) -> Mode:
        self._require_started()
        assert self._mode is not None
        return self._mode

    @property
    def paths(self) -> CorePaths:
        self._require_started()
        assert self._paths is not None
        return self._paths

    @property
    def conn(self):
        return self._conn

    @property
    def db_key(self) -> typing.Optional[bytes]:
        return self._db_key

    @property
    def operator_id(self) -> typing.Optional[int]:
        return self._operator_id

    @property
    def sync_engine(self):
        return self._sync_engine

    @property
    def net_handler(self):
        return self._net_handler

    @property
    def client_sync(self):
        return self._client_sync

    @property
    def is_unlocked(self) -> bool:
        return self._conn is not None

    def start(self) -> "TalonCoreSession":
        """Load config, resolve mode, and calculate runtime paths."""
        if self._cfg is None:
            self._cfg = load_config(self._config_path)

        self._mode = self._resolve_mode()
        self._paths = CorePaths(
            data_dir=get_data_dir(self._cfg),
            db_path=get_db_path(self._cfg),
            salt_path=get_salt_path(self._cfg),
            rns_config_dir=get_rns_config_dir(self._cfg),
            document_storage_path=get_document_storage_path(self._cfg),
        )
        return self

    def unlock(
        self,
        passphrase: str,
        *,
        start_lease_monitor: bool = False,
        install_audit: bool = True,
    ) -> CoreUnlockResult:
        """Derive the DB key, open SQLCipher, and apply migrations."""
        self._require_started()
        if self._conn is not None:
            raise CoreSessionError("Core session is already unlocked.")

        paths = self.paths
        salt = load_or_create_salt(paths.salt_path)
        key = derive_key(passphrase, salt)
        audit_key: typing.Optional[bytes] = None
        if self.mode == "server" and install_audit:
            audit_key = derive_key(passphrase + ":audit", salt)

        passphrase = "\x00" * len(passphrase)
        del passphrase

        if key is None:
            raise CoreSessionError("DB key derivation returned None.")

        return self.unlock_with_key(
            key,
            audit_key=audit_key,
            start_lease_monitor=start_lease_monitor,
            install_audit=install_audit,
        )

    def unlock_with_key(
        self,
        key: bytes,
        *,
        audit_key: typing.Optional[bytes] = None,
        start_lease_monitor: bool = False,
        install_audit: bool = False,
    ) -> CoreUnlockResult:
        """Open the database using an already-derived key.

        This is useful for tests and future platform integrations that may
        source the key from a platform-specific secret flow.
        """
        self._require_started()
        if self._conn is not None:
            raise CoreSessionError("Core session is already unlocked.")

        conn = None
        try:
            conn = open_db(self.paths.db_path, key)
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            apply_migrations(conn)

            if self.mode == "server" and install_audit:
                if audit_key is None:
                    raise CoreSessionError("Server audit hook requires an audit key.")
                from talon_core.server.audit import install_hook

                install_hook(conn, audit_key)
                self._audit_key = audit_key

            self._conn = conn
            self._db_key = key
            self._operator_id = resolve_local_operator_id(
                conn,
                mode=self.mode,
                allow_server_sentinel=(self.mode == "server"),
            )
            conn = None

            if start_lease_monitor:
                self.start_lease_monitor()

            return CoreUnlockResult(
                mode=self.mode,
                operator_id=self._operator_id,
                db_path=self.paths.db_path,
                data_dir=self.paths.data_dir,
            )
        finally:
            if conn is not None:
                close_db(conn)

    def start_reticulum(self) -> None:
        """Initialize Reticulum through the existing core-owned network module."""
        self._require_started()
        if self._reticulum_started:
            return
        from talon_core.network.node import init_reticulum

        init_reticulum(self.paths.rns_config_dir, mode=self.mode)
        self._reticulum_started = True

    def start_lease_monitor(self) -> None:
        """Start the lease heartbeat monitor without starting RNS sync."""
        self._require_unlocked()
        if self._sync_engine is not None:
            return
        from talon_core.network.sync import SyncEngine

        self._sync_engine = SyncEngine(
            is_lora=self.cfg.getboolean("network", "lora_mode", fallback=False),
            conn=self._conn,
            operator_id=self._operator_id,
            on_lease_expired=self._on_lease_expired,
            on_lease_renewed=self._on_lease_renewed,
        )
        self._sync_engine.start()

    def start_sync(self, *, init_reticulum: bool = True) -> None:
        """Start the server or client network sync lifecycle."""
        self._require_unlocked()
        if init_reticulum:
            self.start_reticulum()

        if self.mode == "server":
            if self._net_handler is not None:
                return
            from talon_core.server.net_handler import ServerNetHandler

            self._net_handler = ServerNetHandler(
                self._conn,
                self.cfg,
                self._require_db_key(),
                notify_ui=self._notify_server_ui,
            )
            self._net_handler.start()
            return

        if self._client_sync is not None:
            return
        from talon_core.network.client_sync import ClientSyncManager

        self._client_sync = ClientSyncManager(
            self._conn,
            self.cfg,
            self._require_db_key(),
            notify_ui=self._notify_client_ui,
            trigger_lock_check=self._trigger_client_lock_check,
        )
        self._client_sync.start()

    def stop_sync(self) -> None:
        """Stop active network sync managers."""
        if self._net_handler is not None:
            self._net_handler.stop()
            self._net_handler = None
        if self._client_sync is not None:
            self._client_sync.stop()
            self._client_sync = None

    def stop_lease_monitor(self) -> None:
        if self._sync_engine is not None:
            self._sync_engine.stop()
            self._sync_engine = None

    def enroll_client(self, combined: str, callsign: str, *, timeout_s: float = 30.0) -> int:
        """Enroll a client and return the assigned operator id."""
        self._require_unlocked()
        if self.mode != "client":
            raise CoreSessionError("Client enrollment is only valid in client mode.")
        if self._client_sync is None:
            self.start_sync(init_reticulum=False)

        import threading

        done = threading.Event()
        result: dict[str, typing.Any] = {}

        def _ok(operator_id: int) -> None:
            result["operator_id"] = operator_id
            done.set()

        def _err(message: str) -> None:
            result["error"] = message
            done.set()

        self._client_sync.enroll(combined, callsign, _ok, _err)
        if not done.wait(timeout=timeout_s):
            raise CoreSessionError("Timed out waiting for client enrollment.")
        if "error" in result:
            raise CoreSessionError(str(result["error"]))

        self._operator_id = int(result["operator_id"])
        if self._sync_engine is not None:
            self._sync_engine.set_operator_id(self._operator_id)
        if self._client_sync is not None:
            self._client_sync.start_after_enroll()
        return self._operator_id

    def subscribe(self, handler: EventHandler) -> typing.Callable[[], None]:
        """Subscribe to core domain events and return an unsubscribe callback."""
        self._event_handlers.append(handler)

        def _unsubscribe() -> None:
            try:
                self._event_handlers.remove(handler)
            except ValueError:
                pass

        return _unsubscribe

    def publish_events(self, events: typing.Iterable[DomainEvent]) -> None:
        """Deliver domain events to UI adapters."""
        event_tuple = tuple(events)
        for event in event_tuple:
            for handler in tuple(self._event_handlers):
                handler(event)

    def _notify_server_ui(self, table: str) -> None:
        if self._on_data_pushed is not None:
            self._on_data_pushed(table)

    def _notify_client_ui(self, table: str, *, badge: bool = True) -> None:
        if self._on_data_pushed is not None:
            self._on_data_pushed(table, badge=badge)

    def _trigger_client_lock_check(self, operator_id: int) -> None:
        if self._on_client_lock_check is not None:
            self._on_client_lock_check(operator_id)

    def command(
        self,
        command_name: str,
        payload: typing.Optional[dict] = None,
        **kwargs,
    ):
        """Run a core service command and publish returned domain events."""
        self._require_unlocked()
        data = dict(payload or {})
        data.update(kwargs)
        result = self._execute_command(command_name, data)
        events = tuple(getattr(result, "events", ()) or ())
        if events:
            self.publish_events(events)
        return result

    def read_model(
        self,
        name: str,
        filters: typing.Optional[dict[str, typing.Any]] = None,
    ):
        """Return a small UI-ready read model from the initial core boundary."""
        filters = filters or {}
        if name == "session":
            return {
                "mode": self.mode,
                "unlocked": self.is_unlocked,
                "operator_id": self._operator_id,
                "paths": self.paths,
                "sync_started": self._net_handler is not None or self._client_sync is not None,
                "lease_monitor_started": self._sync_engine is not None,
            }
        if name == "dashboard.summary":
            return self._dashboard_summary()
        if name == "sync.status":
            return self._sync_status()
        if name == "operators":
            self._require_unlocked()
            return list_operators(
                self._conn,
                include_sentinel=bool(filters.get("include_sentinel", False)),
            )
        if name == "operators.list":
            self._require_unlocked()
            return list_operators(
                self._conn,
                include_sentinel=bool(filters.get("include_sentinel", False)),
            )
        if name == "operators.detail":
            self._require_unlocked()
            from talon_core.operators import get_operator

            return get_operator(self._conn, int(filters["operator_id"]))
        if name == "assets.list":
            self._require_unlocked()
            from talon_core.assets import load_assets

            return load_assets(
                self._conn,
                category=filters.get("category"),
                available_only=bool(filters.get("available_only", False)),
                limit=int(filters.get("limit", 500)),
            )
        if name == "assets.detail":
            self._require_unlocked()
            from talon_core.assets import get_asset

            return get_asset(self._conn, int(filters["asset_id"]))
        if name == "sitreps.list":
            self._require_unlocked()
            from talon_core.sitrep import load_sitreps

            return load_sitreps(
                self._conn,
                self._require_db_key(),
                limit=int(filters.get("limit", 200)),
                mission_id=filters.get("mission_id"),
                asset_id=filters.get("asset_id"),
            )
        if name == "missions.list":
            self._require_unlocked()
            from talon_core.missions import load_missions

            return load_missions(
                self._conn,
                status_filter=filters.get("status_filter"),
                limit=int(filters.get("limit", 200)),
            )
        if name == "missions.detail":
            self._require_unlocked()
            return self._mission_detail(int(filters["mission_id"]))
        if name == "missions.approval_context":
            self._require_unlocked()
            return self._mission_approval_context(int(filters["mission_id"]))
        if name == "chat.channels":
            self._require_unlocked()
            from talon_core.chat import load_channels

            return load_channels(self._conn)
        if name == "chat.messages":
            self._require_unlocked()
            from talon_core.chat import load_messages

            return load_messages(
                self._conn,
                int(filters["channel_id"]),
                limit=int(filters.get("limit", 100)),
            )
        if name == "chat.operators":
            self._require_unlocked()
            return self._chat_operators(set(filters.get("online_peers") or set()))
        if name == "chat.alerts":
            self._require_unlocked()
            return self._chat_alerts(limit=int(filters.get("limit", 10)))
        if name == "chat.current_operator":
            self._require_unlocked()
            return self._current_operator_summary()
        if name == "map.context":
            self._require_unlocked()
            from talon_core.map import load_map_context

            return load_map_context(
                self._conn,
                mission_id=filters.get("mission_id"),
                limit=int(filters.get("limit", 500)),
            )
        if name == "enrollment.pending_tokens":
            self._require_unlocked()
            self._require_server_mode("Pending enrollment tokens")
            from talon_core.server.enrollment import list_pending_tokens

            return list_pending_tokens(self._conn)
        if name == "enrollment.server_hash":
            self._require_unlocked()
            self._require_server_mode("Server RNS hash")
            return self._server_rns_hash()
        if name == "audit.list":
            self._require_unlocked()
            self._require_server_mode("Audit log")
            from talon_core.server.audit import query_entries

            return query_entries(
                self._conn,
                self._audit_key or self._require_db_key(),
                since=filters.get("since"),
                until=filters.get("until"),
                event_filter=filters.get("event_filter"),
                limit=int(filters.get("limit", 500)),
            )
        if name == "settings.meta":
            self._require_unlocked()
            return self._meta_value(
                str(filters["key"]),
                filters.get("default"),
            )
        if name == "settings.audio_enabled":
            self._require_unlocked()
            from talon_core.audio_alerts import is_audio_enabled

            return is_audio_enabled(self._conn)
        if name == "settings.font_scale":
            self._require_unlocked()
            value = self._meta_value("global_font_scale", "1.0")
            try:
                return float(value)
            except (TypeError, ValueError):
                return 1.0
        if name == "documents.list":
            self._require_unlocked()
            return self._documents_list(limit=int(filters.get("limit", 200)))
        if name == "documents.detail":
            self._require_unlocked()
            return self._documents_detail(int(filters["document_id"]))
        raise KeyError(f"Unknown read model: {name}")

    def close(self) -> None:
        """Stop runtime managers and close the database."""
        self.stop_sync()
        self.stop_lease_monitor()
        if self._mode == "server":
            try:
                from talon_core.server.propagation import stop_propagation_node

                stop_propagation_node()
            except Exception:
                pass
        if self._reticulum_started:
            try:
                from talon_core.network.node import shutdown_reticulum

                shutdown_reticulum()
            finally:
                self._reticulum_started = False
        if self._conn is not None:
            close_db(self._conn)
            self._conn = None
        self._db_key = None
        self._audit_key = None
        self._operator_id = None

    def _dashboard_summary(self) -> DashboardSummary:
        self._require_started()
        counts: dict[str, int] = {}
        if self.is_unlocked:
            now = self._now()
            counts = {
                "operators": self._count_rows("operators"),
                "active_operators": self._count_rows("operators", "revoked = 0"),
                "revoked_operators": self._count_rows("operators", "revoked != 0"),
                "assets": self._count_rows("assets"),
                "verified_assets": self._count_rows("assets", "verified = 1"),
                "asset_deletion_requests": self._count_rows(
                    "assets",
                    "deletion_requested = 1",
                ),
                "sitreps": self._count_rows("sitreps"),
                "flash_sitreps": self._count_rows(
                    "sitreps",
                    "level IN ('FLASH', 'FLASH_OVERRIDE')",
                ),
                "missions": self._count_rows("missions"),
                "active_missions": self._count_rows("missions", "status = 'active'"),
                "pending_missions": self._count_rows(
                    "missions",
                    "status = 'pending_approval'",
                ),
                "channels": self._count_rows("channels"),
                "messages": self._count_rows("messages"),
                "urgent_messages": self._count_rows("messages", "is_urgent = 1"),
                "documents": self._count_rows("documents"),
                "unreviewed_amendments": self._count_rows(
                    "amendments",
                    "reviewed = 0",
                ),
            }
            if self.mode == "server":
                counts["pending_enrollment_tokens"] = self._count_rows(
                    "enrollment_tokens",
                    "used_at IS NULL AND expires_at > ?",
                    (now,),
                )

        return DashboardSummary(
            mode=self.mode,
            unlocked=self.is_unlocked,
            operator_id=self._operator_id,
            generated_at=self._now(),
            counts=counts,
            sync=self._sync_status(),
            paths=self.paths,
        )

    def _sync_status(self) -> SyncStatus:
        self._require_started()
        lease_status = self._lease_monitor_status()
        client_status = self._client_sync_status()
        server_status = self._server_net_status()
        pending_by_table = self._pending_outbox_counts() if self.is_unlocked else {}
        pending_total = sum(pending_by_table.values())

        sync_started = bool(client_status.get("started") or server_status.get("started"))
        connected = bool(
            client_status.get("connected")
            or int(server_status.get("active_client_count", 0) or 0) > 0
        )
        if self.mode == "server":
            if server_status.get("started"):
                connection_state = (
                    "server-active-clients" if connected else "server-listening"
                )
            else:
                connection_state = "server-stopped"
        else:
            if client_status.get("connected"):
                connection_state = "client-connected"
            elif client_status.get("started"):
                connection_state = (
                    "client-enrolled"
                    if client_status.get("enrolled")
                    else "client-not-enrolled"
                )
            else:
                connection_state = "client-stopped"

        return SyncStatus(
            mode=self.mode,
            reticulum_started=self._reticulum_started,
            sync_started=sync_started,
            lease_monitor_started=bool(lease_status.get("started")),
            connection_state=connection_state,
            connected=connected,
            heartbeat_interval_s=typing.cast(
                typing.Optional[int],
                lease_status.get("interval_s"),
            ),
            last_heartbeat_at=typing.cast(
                typing.Optional[int],
                lease_status.get("last_heartbeat_at"),
            ),
            lease_locked=typing.cast(
                typing.Optional[bool],
                lease_status.get("locked"),
            ),
            monitored_operator_id=typing.cast(
                typing.Optional[int],
                lease_status.get("operator_id"),
            ),
            pending_outbox_count=pending_total,
            pending_outbox_by_table=pending_by_table,
            last_sync_at=typing.cast(
                typing.Optional[int],
                client_status.get("last_sync_at"),
            ),
            active_client_count=int(server_status.get("active_client_count", 0) or 0),
        )

    def _lease_monitor_status(self) -> dict[str, typing.Any]:
        if self._sync_engine is None:
            return {
                "started": False,
                "interval_s": None,
                "last_heartbeat_at": None,
                "locked": None,
                "operator_id": self._operator_id,
            }
        if hasattr(self._sync_engine, "status"):
            return dict(self._sync_engine.status())
        return {"started": True, "operator_id": self._operator_id}

    def _client_sync_status(self) -> dict[str, typing.Any]:
        if self._client_sync is None:
            return {
                "started": False,
                "connected": False,
                "enrolled": self._operator_id is not None,
                "operator_id": self._operator_id,
                "last_sync_at": None,
            }
        if hasattr(self._client_sync, "status"):
            return dict(self._client_sync.status())
        return {
            "started": True,
            "connected": bool(getattr(self._client_sync, "is_connected", lambda: False)()),
            "operator_id": self._operator_id,
            "last_sync_at": getattr(self._client_sync, "_last_sync_at", None),
        }

    def _server_net_status(self) -> dict[str, typing.Any]:
        if self._net_handler is None:
            return {"started": False, "active_client_count": 0}
        if hasattr(self._net_handler, "status"):
            return dict(self._net_handler.status())
        active_links = getattr(self._net_handler, "_active_links", {})
        return {"started": True, "active_client_count": len(active_links)}

    def _pending_outbox_counts(self) -> dict[str, int]:
        from talon_core.network.registry import OFFLINE_TABLES, validated_sync_table

        counts: dict[str, int] = {}
        for table in OFFLINE_TABLES:
            table_name = validated_sync_table(table)
            try:
                row = self._conn.execute(
                    f"SELECT count(*) FROM {table_name} WHERE sync_status = 'pending'"  # noqa: S608
                ).fetchone()
            except Exception:
                count = 0
            else:
                count = int(row[0] if row is not None else 0)
            counts[table] = count
        return counts

    def _count_rows(
        self,
        table: str,
        where: str = "",
        params: tuple[typing.Any, ...] = (),
    ) -> int:
        safe_tables = {
            "amendments",
            "assets",
            "channels",
            "documents",
            "enrollment_tokens",
            "messages",
            "missions",
            "operators",
            "sitreps",
        }
        if table not in safe_tables:
            raise ValueError(f"Unsupported count table: {table!r}")
        sql = f"SELECT count(*) FROM {table}"  # noqa: S608
        if where:
            sql += f" WHERE {where}"
        row = self._conn.execute(sql, params).fetchone()
        return int(row[0] if row is not None else 0)

    @staticmethod
    def _now() -> int:
        import time

        return int(time.time())

    def _execute_command(self, name: str, payload: dict):
        if name == "operators.update":
            from talon_core.services.operators import update_operator_command

            return update_operator_command(self._conn, **payload)
        if name == "operators.renew_lease":
            from talon_core.services.operators import renew_operator_lease_command
            from talon_core.constants import LEASE_DURATION_S

            payload.setdefault("duration_s", LEASE_DURATION_S)
            return renew_operator_lease_command(self._conn, **payload)
        if name == "operators.revoke":
            from talon_core.services.operators import revoke_operator_command

            return revoke_operator_command(self._conn, **payload)

        if name == "assets.create":
            from talon_core.services.assets import create_asset_command

            payload.setdefault("author_id", self.require_local_operator_id())
            return create_asset_command(self._conn, **payload)
        if name == "assets.update":
            from talon_core.services.assets import update_asset_command

            return update_asset_command(self._conn, **payload)
        if name == "assets.verify":
            from talon_core.services.assets import verify_asset_command

            if payload.get("verified") and payload.get("confirmer_id") is None:
                payload["confirmer_id"] = self.require_local_operator_id()
            else:
                payload.setdefault("confirmer_id", None)
            self._ensure_asset_verification_allowed(
                int(payload["asset_id"]),
                bool(payload["verified"]),
                typing.cast(int, payload.get("confirmer_id")),
            )
            return verify_asset_command(self._conn, **payload)
        if name == "assets.request_delete":
            from talon_core.services.assets import request_asset_deletion_command

            return request_asset_deletion_command(self._conn, **payload)
        if name == "assets.hard_delete":
            from talon_core.services.assets import hard_delete_asset_command

            self._require_server_mode("Asset hard delete")
            return hard_delete_asset_command(self._conn, **payload)

        if name == "sitreps.create":
            return self._sitreps_create(**payload)
        if name == "sitreps.delete":
            return self._sitreps_delete(**payload)

        if name == "missions.create":
            from talon_core.services.missions import create_mission_command

            payload.setdefault("created_by", self.require_local_operator_id())
            return create_mission_command(self._conn, **payload)
        if name == "missions.approve":
            self._require_server_mode("Mission approval")
            from talon_core.services.missions import approve_mission_command

            return approve_mission_command(self._conn, **payload)
        if name == "missions.reject":
            self._require_server_mode("Mission rejection")
            from talon_core.services.missions import reject_mission_command

            return reject_mission_command(self._conn, **payload)
        if name == "missions.complete":
            self._require_server_mode("Mission completion")
            from talon_core.services.missions import complete_mission_command

            return complete_mission_command(self._conn, **payload)
        if name == "missions.abort":
            self._require_server_mode("Mission abort")
            from talon_core.services.missions import abort_mission_command

            return abort_mission_command(self._conn, **payload)
        if name == "missions.delete":
            self._require_server_mode("Mission delete")
            from talon_core.services.missions import delete_mission_command

            return delete_mission_command(self._conn, **payload)

        if name == "chat.ensure_defaults":
            from talon_core.chat import ensure_default_channels

            ensure_default_channels(self._conn)
            return RecordCommandResult("channels", 0, ())
        if name == "chat.create_channel":
            return self._chat_create_channel(**payload)
        if name == "chat.delete_channel":
            return self._chat_delete_channel(**payload)
        if name == "chat.get_or_create_dm":
            return self._chat_get_or_create_dm(**payload)
        if name == "chat.send_message":
            return self._chat_send_message(**payload)
        if name == "chat.delete_message":
            return self._chat_delete_message(**payload)

        if name == "settings.set_meta":
            return self._settings_set_meta(**payload)
        if name == "settings.set_audio_enabled":
            from talon_core.audio_alerts import set_audio_enabled

            enabled = bool(payload["enabled"])
            set_audio_enabled(self._conn, enabled)
            return RecordCommandResult("meta", 0, ())

        if name == "documents.upload":
            return self._documents_upload(**payload)
        if name == "documents.download":
            return self._documents_download(**payload)
        if name == "documents.delete":
            return self._documents_delete(**payload)

        if name == "enrollment.generate_token":
            return self._generate_enrollment_token()

        raise KeyError(f"Unknown command: {name}")

    def _sitreps_create(
        self,
        *,
        level: str,
        body: str,
        template: str = "",
        mission_id: typing.Optional[int] = None,
        asset_id: typing.Optional[int] = None,
        author_id: typing.Optional[int] = None,
        sync_status: str = "synced",
    ) -> RecordCommandResult:
        from talon_core.services.events import record_changed
        from talon_core.sitrep import create_sitrep

        if author_id is None:
            author_id = self.require_local_operator_id()
        sitrep_id = create_sitrep(
            self._conn,
            self._require_db_key(),
            author_id=author_id,
            level=level,
            template=template,
            body=body,
            mission_id=mission_id,
            asset_id=asset_id,
            sync_status=sync_status,
        )
        return RecordCommandResult("sitreps", sitrep_id, (record_changed("sitreps", sitrep_id),))

    def _sitreps_delete(self, *, sitrep_id: int) -> RecordCommandResult:
        self._require_server_mode("SITREP delete")
        from talon_core.services.events import record_deleted
        from talon_core.sitrep import delete_sitrep

        doc_id = int(sitrep_id)
        delete_sitrep(self._conn, doc_id)
        return RecordCommandResult("sitreps", doc_id, (record_deleted("sitreps", doc_id),))

    def _documents_list(self, *, limit: int = 200) -> list[DocumentListItem]:
        from talon_core.documents import list_documents

        callsigns = self._document_callsigns()
        return [
            DocumentListItem(
                document=doc,
                uploader_callsign=callsigns.get(doc.uploaded_by, f"id={doc.uploaded_by}"),
            )
            for doc in list_documents(self._conn, limit=limit)
        ]

    def _documents_detail(self, document_id: int) -> DocumentListItem:
        from talon_core.documents import get_document

        doc = get_document(self._conn, document_id)
        callsigns = self._document_callsigns()
        return DocumentListItem(
            document=doc,
            uploader_callsign=callsigns.get(doc.uploaded_by, f"id={doc.uploaded_by}"),
        )

    def _documents_upload(
        self,
        *,
        raw_filename: str,
        file_data: bytes,
        uploaded_by: typing.Optional[int] = None,
        description: str = "",
        storage_root: typing.Optional[pathlib.Path] = None,
    ) -> DocumentCommandResult:
        from talon_core.documents import upload_document
        from talon_core.services.events import record_changed

        if uploaded_by is None:
            uploaded_by = self.require_local_operator_id()
        doc = upload_document(
            self._conn,
            self._require_db_key(),
            pathlib.Path(storage_root) if storage_root is not None else self.paths.document_storage_path,
            raw_filename=raw_filename,
            file_data=file_data,
            uploaded_by=uploaded_by,
            description=description,
        )
        return DocumentCommandResult(
            document_id=doc.id,
            document=doc,
            events=(record_changed("documents", doc.id),),
        )

    def _documents_download(
        self,
        *,
        document_id: int,
        downloader_id: typing.Optional[int] = None,
        timeout_s: float = 60.0,
        storage_root: typing.Optional[pathlib.Path] = None,
    ) -> DocumentDownloadResult:
        from talon_core.documents import DocumentError, download_document, get_document

        doc_id = int(document_id)
        if self.mode == "client":
            if self._client_sync is None:
                raise DocumentError(
                    "Document download requires an active client sync session."
                )
            plaintext = self._client_sync.fetch_document(doc_id, timeout_s=timeout_s)
            return DocumentDownloadResult(get_document(self._conn, doc_id), plaintext)

        if downloader_id is None:
            downloader_id = self.require_local_operator_id()
        doc, plaintext = download_document(
            self._conn,
            self._require_db_key(),
            pathlib.Path(storage_root) if storage_root is not None else self.paths.document_storage_path,
            doc_id,
            downloader_id=downloader_id,
        )
        return DocumentDownloadResult(doc, plaintext)

    def _documents_delete(
        self,
        *,
        document_id: int,
        storage_root: typing.Optional[pathlib.Path] = None,
    ) -> DocumentCommandResult:
        if self.mode != "server":
            raise CoreSessionError("Document deletion is only valid in server mode.")
        from talon_core.documents import get_document, delete_document
        from talon_core.services.events import record_deleted

        doc_id = int(document_id)
        doc = get_document(self._conn, doc_id)
        delete_document(
            self._conn,
            pathlib.Path(storage_root) if storage_root is not None else self.paths.document_storage_path,
            doc_id,
        )
        return DocumentCommandResult(
            document_id=doc_id,
            document=doc,
            events=(record_deleted("documents", doc_id),),
        )

    def _document_callsigns(self) -> dict[int, str]:
        rows = self._conn.execute("SELECT id, callsign FROM operators").fetchall()
        return {int(row[0]): str(row[1]) for row in rows}

    def _mission_detail(self, mission_id: int) -> dict[str, typing.Any]:
        from talon_core.missions import get_channel_for_mission, get_mission, get_mission_assets
        from talon_core.sitrep import load_sitreps
        from talon_core.waypoints import load_waypoints
        from talon_core.zones import load_zones

        mission = get_mission(self._conn, mission_id)
        if mission is None:
            raise ValueError(f"Mission {mission_id} not found.")
        zones = load_zones(self._conn, mission_id=mission_id)
        return {
            "mission": mission,
            "creator_callsign": self._operator_callsign(mission.created_by),
            "assets": get_mission_assets(self._conn, mission_id),
            "channel_name": get_channel_for_mission(self._conn, mission_id) or "",
            "zones": zones,
            "ao_zones": [zone for zone in zones if zone.zone_type == "AO"],
            "waypoints": load_waypoints(self._conn, mission_id),
            "sitreps": load_sitreps(
                self._conn,
                self._require_db_key(),
                mission_id=mission_id,
            ),
        }

    def _mission_approval_context(self, mission_id: int) -> dict[str, typing.Any]:
        from talon_core.assets import load_assets
        from talon_core.missions import get_mission, get_mission_assets

        mission = get_mission(self._conn, mission_id)
        if mission is None:
            raise ValueError(f"Mission {mission_id} not found.")
        requested_assets = get_mission_assets(self._conn, mission_id)
        return {
            "mission": mission,
            "requested_assets": requested_assets,
            "requested_ids": {asset.id for asset in requested_assets},
            "all_assets": load_assets(self._conn),
            "creator_callsign": self._operator_callsign(mission.created_by),
        }

    def _operator_callsign(self, operator_id: int) -> str:
        row = self._conn.execute(
            "SELECT callsign FROM operators WHERE id = ?",
            (operator_id,),
        ).fetchone()
        return str(row[0]) if row else f"#{operator_id}"

    def _chat_create_channel(self, *, name: str) -> ChatCommandResult:
        from talon_core.chat import create_channel
        from talon_core.services.events import record_changed

        channel = create_channel(self._conn, name)
        return ChatCommandResult(
            "channels",
            channel.id,
            channel=channel,
            events=(record_changed("channels", channel.id),),
        )

    def _chat_delete_channel(self, *, channel_id: int) -> ChatCommandResult:
        self._require_server_mode("Channel delete")
        from talon_core.chat import delete_channel
        from talon_core.services.events import record_deleted

        cid = int(channel_id)
        delete_channel(self._conn, cid)
        return ChatCommandResult(
            "channels",
            cid,
            events=(record_deleted("channels", cid),),
        )

    def _chat_get_or_create_dm(
        self,
        *,
        operator_a_id: int,
        operator_b_id: int,
    ) -> ChatCommandResult:
        from talon_core.chat import get_or_create_dm_channel
        from talon_core.services.events import record_changed

        channel = get_or_create_dm_channel(self._conn, operator_a_id, operator_b_id)
        return ChatCommandResult(
            "channels",
            channel.id,
            channel=channel,
            events=(record_changed("channels", channel.id),),
        )

    def _chat_send_message(
        self,
        *,
        channel_id: int,
        body: str,
        sender_id: typing.Optional[int] = None,
        is_urgent: bool = False,
        grid_ref: typing.Optional[str] = None,
        sync_status: str = "synced",
    ) -> ChatCommandResult:
        from talon_core.chat import send_message
        from talon_core.services.events import record_changed

        if sender_id is None:
            sender_id = self.require_local_operator_id()
        message = send_message(
            self._conn,
            int(channel_id),
            int(sender_id),
            body,
            is_urgent=is_urgent,
            grid_ref=grid_ref,
            sync_status=sync_status,
        )
        return ChatCommandResult(
            "messages",
            message.id,
            message=message,
            events=(record_changed("messages", message.id),),
        )

    def _chat_delete_message(self, *, message_id: int) -> ChatCommandResult:
        self._require_server_mode("Message delete")
        from talon_core.chat import delete_message
        from talon_core.services.events import record_deleted

        mid = int(message_id)
        delete_message(self._conn, mid)
        return ChatCommandResult(
            "messages",
            mid,
            events=(record_deleted("messages", mid),),
        )

    def _chat_operators(self, online_peers: set[str]) -> list[dict[str, typing.Any]]:
        operators = []
        for operator in list_operators(self._conn, include_sentinel=True):
            if operator.revoked:
                continue
            role = operator.profile.get("role", "") if isinstance(operator.profile, dict) else ""
            online = self.mode == "server" or operator.callsign in online_peers
            operators.append(
                {
                    "id": operator.id,
                    "callsign": operator.callsign,
                    "role": role,
                    "online": online,
                }
            )
        operators.sort(key=lambda item: str(item["callsign"]))
        return operators

    def _chat_alerts(self, *, limit: int) -> list[dict[str, typing.Any]]:
        rows = self._conn.execute(
            "SELECT m.body, m.sent_at, m.grid_ref, COALESCE(o.callsign,'UNKNOWN'), m.channel_id "
            "FROM messages m "
            "LEFT JOIN operators o ON m.sender_id = o.id "
            "WHERE m.is_urgent = 1 "
            "ORDER BY m.sent_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        alerts = []
        for body, sent_at, grid_ref, callsign, channel_id in rows:
            body_text = bytes(body).decode("utf-8", errors="replace") if body else ""
            alerts.append(
                {
                    "type": "contact",
                    "label": "URGENT",
                    "sent_at": sent_at,
                    "grid_ref": grid_ref,
                    "callsign": callsign,
                    "channel_id": channel_id,
                    "text": f"{callsign}: {body_text}",
                }
            )
        return alerts

    def _current_operator_summary(self) -> dict[str, typing.Any]:
        operator_id = self.require_local_operator_id()
        operator = next(
            (op for op in list_operators(self._conn, include_sentinel=True) if op.id == operator_id),
            None,
        )
        if operator is None:
            return {"id": operator_id, "callsign": "UNKNOWN", "role": ""}
        role = operator.profile.get("role", "") if isinstance(operator.profile, dict) else ""
        return {"id": operator.id, "callsign": operator.callsign, "role": role}

    def _generate_enrollment_token(self) -> EnrollmentTokenResult:
        self._require_server_mode("Enrollment token generation")
        from talon_core.server.enrollment import generate_enrollment_token

        token = generate_enrollment_token(self._conn)
        server_hash = self._server_rns_hash()
        return EnrollmentTokenResult(
            token=token,
            server_hash=server_hash,
            combined=f"{token}:{server_hash}" if server_hash else token,
        )

    def _server_rns_hash(self) -> str:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'server_rns_hash'"
        ).fetchone()
        return str(row[0]).strip() if row and row[0] else ""

    def _meta_value(
        self,
        key: str,
        default: typing.Optional[typing.Any] = None,
    ) -> typing.Optional[typing.Any]:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (key,),
        ).fetchone()
        return row[0] if row else default

    def _settings_set_meta(
        self,
        *,
        key: str,
        value: typing.Any,
    ) -> RecordCommandResult:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
        self._conn.commit()
        return RecordCommandResult("meta", 0, ())

    def _ensure_asset_verification_allowed(
        self,
        asset_id: int,
        verified: bool,
        confirmer_id: typing.Optional[int],
    ) -> None:
        if not verified or self.mode == "server" or confirmer_id is None:
            return
        from talon_core.assets import get_asset

        asset = get_asset(self._conn, asset_id)
        if asset is not None and asset.created_by == confirmer_id:
            raise ValueError("Operators cannot verify their own assets.")

    def require_local_operator_id(
        self,
        *,
        allow_server_sentinel: typing.Optional[bool] = None,
    ) -> int:
        self._require_unlocked()
        if allow_server_sentinel is None:
            allow_server_sentinel = self.mode == "server"
        operator_id = require_local_operator_id(
            self._conn,
            mode=self.mode,
            current_operator_id=self._operator_id,
            allow_server_sentinel=allow_server_sentinel,
        )
        self._operator_id = operator_id
        return operator_id

    def _resolve_mode(self) -> Mode:
        if self._mode_override is not None:
            if self._mode_override not in ("server", "client"):
                raise ValueError(
                    f"Invalid TALON mode: {self._mode_override!r}; must be 'server' or 'client'"
                )
            return self._mode_override
        return get_mode(self._cfg)

    def _require_started(self) -> None:
        if self._cfg is None or self._mode is None or self._paths is None:
            raise CoreSessionError("Core session has not been started.")

    def _require_unlocked(self) -> None:
        self._require_started()
        if self._conn is None:
            raise CoreSessionError("Core session is not unlocked.")

    def _require_db_key(self) -> bytes:
        if self._db_key is None:
            raise CoreSessionError("Core session has no DB key.")
        return self._db_key

    def _require_server_mode(self, action: str) -> None:
        if self.mode != "server":
            raise CoreSessionError(f"{action} is only valid in server mode.")

    def __enter__(self) -> "TalonCoreSession":
        if self._mode is None:
            self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

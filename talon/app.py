"""
TalonApp — main application class.

Screen registration is split into shared screens (always loaded) and
server-exclusive screens (deferred import + registration only when
mode == "server").  This keeps talon.server.* out of client memory
and allows Buildozer to exclude the package from field APKs.
"""
import configparser
import pathlib
import typing

from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import ScreenManager
from kivymd.app import MDApp

from talon.network.registry import (
    CLIENT_PUSH_TABLES,
    UI_REFRESH_TARGETS,
    is_client_pushable,
    ui_refresh_targets,
)
from talon.services.events import (
    DomainEvent,
    RecordMutation,
    expand_record_mutations,
    record_changed,
    record_deleted,
)
from talon.ui.theme import (
    apply_theme,
    get_ui_theme_key,
    load_ui_theme_from_db,
    save_ui_theme_to_db,
    set_ui_theme,
)
from talon.utils.logging import get_logger

_log = get_logger("app")

_CLIENT_PUSH_TABLES = CLIENT_PUSH_TABLES
_TABLE_SCREENS = UI_REFRESH_TARGETS

_KV_DIR = pathlib.Path(__file__).parent / "ui" / "kv"


class TalonApp(MDApp):
    def __init__(
        self,
        mode: typing.Literal["server", "client"] = "client",
        cfg: typing.Optional[configparser.ConfigParser] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.mode = mode
        self.title = f"T.A.L.O.N.  [{mode.upper()}]"
        # Config — fall back to empty config if not supplied
        self.cfg: configparser.ConfigParser = cfg or configparser.ConfigParser()
        # Post-login state — set by LoginScreen after successful auth
        self.conn = None       # open sqlcipher Connection
        self.db_key: typing.Optional[bytes] = None  # 32-byte derived key
        self.operator_id: typing.Optional[int] = None  # logged-in operator's DB id
        self.sync_engine = None  # SyncEngine — started by LoginScreen, stopped on exit
        # Network handlers — mutually exclusive: server uses net_handler, client uses client_sync.
        self.net_handler = None    # ServerNetHandler (server mode only)
        self.client_sync = None    # ClientSyncManager (client mode only)
        # Badge counters for screens that aren't currently visible when data arrives.
        # screen_name → unseen update count.  Cleared when the user navigates to that screen.
        self._unread_badges: dict = {}
        self.ui_theme_key = get_ui_theme_key()

    # ------------------------------------------------------------------
    # Push notification helpers — called by server screens after DB writes
    # ------------------------------------------------------------------

    def on_data_pushed(self, table: str, *, badge: bool = True) -> None:
        """
        Called on the **main thread** (via Clock.schedule_once) when a
        push-applied record modifies the local DB.

        If the affected screen is currently visible: refresh it immediately.
        If not visible: increment its badge counter so the operator knows new
        data is waiting when they navigate to that screen.  Startup hydration
        can pass ``badge=False`` so records from a previous app session refresh
        quietly without showing as new alerts at login.
        """
        self._consume_ui_batches((ui_refresh_targets(table),), badge=badge)

    def clear_badge(self, screen_name: str) -> None:
        """Clear the badge for *screen_name*.  Call from each screen's on_pre_enter."""
        if self._unread_badges.pop(screen_name, None) is not None:
            self._refresh_badge_display()

    def _refresh_badge_display(self) -> None:
        """Propagate current badge counts to the persistent nav rail."""
        nav_rail = getattr(self, '_nav_rail', None)
        if nav_rail is not None:
            try:
                nav_rail.set_badges(dict(self._unread_badges))
            except Exception as exc:
                _log.debug("_refresh_badge_display: %s", exc)

    def net_notify_change(self, table: str, record_id: int) -> None:
        """Push a record change.

        Server mode: pushes the record to all connected clients via net_handler.
        Client mode: marks the record as pending and pushes it to the server via
        client_sync (for tables in _CLIENT_PUSH_TABLES).  Non-pushable tables
        (channels, documents) are silently skipped in client mode — those flows
        are server-authoritative and do not originate from clients.
        """
        self.dispatch_domain_events((record_changed(table, record_id),))

    def net_notify_delete(self, table: str, record_id: int) -> None:
        """Record a tombstone and push a delete to all connected clients (server mode only).
        Call after the local delete commits so clients never receive false deletes."""
        self.dispatch_domain_events((record_deleted(table, record_id),))

    def dispatch_domain_events(self, events: typing.Iterable[DomainEvent]) -> None:
        """Route service-command domain events to network and UI consumers."""
        event_list = tuple(events)
        for change in expand_record_mutations(event_list):
            self._dispatch_record_mutation(change)

        ui_batches: list[frozenset[str]] = []
        for event in event_list:
            for change in event.iter_records():
                targets = ui_refresh_targets(change.table)
                if targets:
                    ui_batches.append(targets)
            if event.ui_targets:
                ui_batches.append(event.ui_targets)
        self._consume_ui_batches(ui_batches)

    def _dispatch_record_mutation(self, change: RecordMutation) -> None:
        if change.action == "changed":
            if self.net_handler is not None:
                try:
                    self.net_handler.notify_change(change.table, change.record_id)
                except Exception as exc:
                    _log.warning("net_notify_change failed: %s", exc)
            elif self.client_sync is not None and is_client_pushable(change.table):
                try:
                    self.client_sync.push_pending_to_server(change.table, change.record_id)
                except Exception as exc:
                    _log.warning(
                        "client push failed table=%s id=%s: %s",
                        change.table,
                        change.record_id,
                        exc,
                    )
        elif change.action == "deleted" and self.net_handler is not None:
            try:
                self.net_handler.notify_delete(change.table, change.record_id)
            except Exception as exc:
                _log.warning("net_notify_delete failed: %s", exc)

    def _consume_ui_batches(
        self,
        batches: typing.Iterable[typing.Iterable[str]],
        *,
        badge: bool = True,
    ) -> None:
        sm = getattr(self, "_sm", None)
        if sm is None:
            return

        refresh_current = False
        badge_changed = False
        for raw_targets in batches:
            targets = self._existing_screens(raw_targets)
            if not targets:
                continue
            if sm.current in targets:
                refresh_current = True
                continue
            if not badge:
                continue
            for screen_name in targets:
                self._unread_badges[screen_name] = (
                    self._unread_badges.get(screen_name, 0) + 1
                )
                badge_changed = True

        if refresh_current:
            screen = sm.current_screen
            if screen is not None and hasattr(screen, "on_pre_enter"):
                screen.on_pre_enter()
        if badge_changed:
            self._refresh_badge_display()

    def _existing_screens(self, screen_names: typing.Iterable[str]) -> frozenset[str]:
        sm = getattr(self, "_sm", None)
        if sm is None:
            return frozenset()
        targets = [
            screen_name
            for screen_name in screen_names
            if screen_name and sm.has_screen(screen_name)
        ]
        return frozenset(targets)

    def resolve_local_operator_id(
        self,
        *,
        allow_server_sentinel: bool = False,
    ) -> typing.Optional[int]:
        """Return the current local operator id, or None if it cannot be resolved."""
        if self.conn is None:
            return None
        from talon.operators import resolve_local_operator_id

        return resolve_local_operator_id(
            self.conn,
            mode=self.mode,
            current_operator_id=self.operator_id,
            allow_server_sentinel=allow_server_sentinel,
        )

    def require_local_operator_id(
        self,
        *,
        allow_server_sentinel: bool = False,
    ) -> int:
        """Return the current local operator id or raise if unavailable."""
        if self.conn is None:
            raise RuntimeError("No database connection.")
        from talon.operators import require_local_operator_id

        return require_local_operator_id(
            self.conn,
            mode=self.mode,
            current_operator_id=self.operator_id,
            allow_server_sentinel=allow_server_sentinel,
        )

    # ------------------------------------------------------------------
    # Kivy lifecycle
    # ------------------------------------------------------------------

    def build(self) -> BoxLayout:
        apply_theme(self)
        self.ui_theme_key = get_ui_theme_key()
        self._load_kv_files()

        from talon.ui.widgets.nav_rail import TalonNavRail

        self._sm = ScreenManager()
        self._register_screens(self._sm)

        self._nav_rail = TalonNavRail(mode=self.mode)
        self._nav_rail.hide()  # hidden until user passes login/lock

        self._sm.bind(current=self._on_screen_change)

        root = BoxLayout(orientation='horizontal')
        root.add_widget(self._nav_rail)
        root.add_widget(self._sm)

        _log.info("TalonApp started (mode=%s)", self.mode)
        return root

    def apply_stored_theme(self) -> str:
        """Load the operator-selected UI theme from DB and apply it to KivyMD."""
        previous = self.ui_theme_key
        self.ui_theme_key = load_ui_theme_from_db(self.conn)
        apply_theme(self)
        if self.ui_theme_key != previous:
            self._notify_theme_changed()
        return self.ui_theme_key

    def set_global_theme(self, theme_key: str) -> str:
        """Persist a global UI theme and notify already-built screens."""
        self.ui_theme_key = (
            save_ui_theme_to_db(self.conn, theme_key)
            if self.conn is not None
            else set_ui_theme(theme_key)
        )
        apply_theme(self)
        self._notify_theme_changed()
        return self.ui_theme_key

    def _notify_theme_changed(self) -> None:
        nav_rail = getattr(self, "_nav_rail", None)
        if nav_rail is not None and hasattr(nav_rail, "on_ui_theme_changed"):
            try:
                nav_rail.on_ui_theme_changed()
            except Exception as exc:
                _log.debug("nav theme refresh failed: %s", exc)

        sm = getattr(self, "_sm", None)
        if sm is None:
            return
        for screen in sm.screens:
            if hasattr(screen, "on_ui_theme_changed"):
                try:
                    screen.on_ui_theme_changed()
                except Exception as exc:
                    _log.debug("screen theme refresh failed (%s): %s", screen.name, exc)

    def _on_screen_change(self, _sm, screen_name: str) -> None:
        _HIDDEN = {'login', 'lock'}
        if screen_name in _HIDDEN:
            self._nav_rail.hide()
        else:
            self._nav_rail.show()
            self._nav_rail.set_active(screen_name)

    def on_stop(self) -> None:
        if self.sync_engine is not None:
            self.sync_engine.stop()
            self.sync_engine = None
        if self.net_handler is not None:
            try:
                self.net_handler.stop()
            except Exception as exc:
                _log.warning("Error stopping net_handler: %s", exc)
            self.net_handler = None
        if self.client_sync is not None:
            try:
                self.client_sync.stop()
            except Exception as exc:
                _log.warning("Error stopping client_sync: %s", exc)
            self.client_sync = None
        # Stop the propagation node first (server mode), then the transport stack.
        # Both helpers are no-ops if the respective component was never started.
        try:
            from talon.server.propagation import stop_propagation_node
            stop_propagation_node()
        except Exception as exc:
            _log.warning("Error stopping propagation node: %s", exc)
        try:
            from talon.network.node import shutdown_reticulum
            shutdown_reticulum()
        except Exception as exc:
            _log.warning("Error stopping Reticulum: %s", exc)
        if self.conn is not None:
            from talon.db.connection import close_db
            close_db(self.conn)
            self.conn = None
            _log.info("Database closed.")
        _log.info("TalonApp stopping.")

    # ------------------------------------------------------------------
    # KV loading
    # ------------------------------------------------------------------

    def _load_kv_files(self) -> None:
        """Load all KV layout files before screens are instantiated."""
        for kv_file in sorted(_KV_DIR.glob("*.kv")):
            Builder.load_file(str(kv_file))
        if self.mode == "server":
            server_kv_dir = _KV_DIR / "server"
            if server_kv_dir.is_dir():
                for kv_file in sorted(server_kv_dir.glob("*.kv")):
                    Builder.load_file(str(kv_file))

    # ------------------------------------------------------------------
    # Screen registration
    # ------------------------------------------------------------------

    def _register_screens(self, sm: ScreenManager) -> None:
        """Add all screens to the ScreenManager."""
        self._register_shared_screens(sm)
        if self.mode == "server":
            self._register_server_screens(sm)

    def _register_shared_screens(self, sm: ScreenManager) -> None:
        from talon.ui.screens.login_screen import LoginScreen
        from talon.ui.screens.lock_screen import LockScreen
        from talon.ui.screens.main_screen import MainScreen
        from talon.ui.screens.asset_screen import AssetScreen
        from talon.ui.screens.sitrep_screen import SitrepScreen
        from talon.ui.screens.mission_screen import MissionScreen
        from talon.ui.screens.mission_create_screen import MissionCreateScreen
        from talon.ui.screens.chat_screen import ChatScreen
        from talon.ui.screens.document_screen import DocumentScreen

        sm.add_widget(LoginScreen(name="login"))
        sm.add_widget(LockScreen(name="lock"))
        sm.add_widget(MainScreen(name="main"))
        sm.add_widget(AssetScreen(name="assets"))
        sm.add_widget(SitrepScreen(name="sitrep"))
        sm.add_widget(MissionScreen(name="mission"))
        sm.add_widget(MissionCreateScreen(name="mission_create"))
        sm.add_widget(ChatScreen(name="chat"))
        sm.add_widget(DocumentScreen(name="documents"))

    def _register_server_screens(self, sm: ScreenManager) -> None:
        # Deferred imports — never executed on clients.
        from talon.ui.screens.server.clients_screen import ClientsScreen
        from talon.ui.screens.server.audit_screen import AuditScreen
        from talon.ui.screens.server.enroll_screen import EnrollScreen
        from talon.ui.screens.server.keys_screen import KeysScreen

        sm.add_widget(ClientsScreen(name="clients"))
        sm.add_widget(AuditScreen(name="audit"))
        sm.add_widget(EnrollScreen(name="enroll"))
        sm.add_widget(KeysScreen(name="keys"))

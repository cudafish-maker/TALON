"""Tests for TalonApp domain-event dispatch routing."""

from talon.app import TalonApp
from talon.services.events import (
    lease_renewed,
    linked_records_changed,
    operator_revoked,
    record_changed,
    record_deleted,
)


class _FakeScreen:
    def __init__(self) -> None:
        self.refresh_count = 0

    def on_pre_enter(self) -> None:
        self.refresh_count += 1


class _FakeScreenManager:
    def __init__(self, current: str, screens: dict[str, _FakeScreen]) -> None:
        self.current = current
        self.current_screen = screens[current]
        self._screens = screens

    def has_screen(self, name: str) -> bool:
        return name in self._screens


class _FakeNavRail:
    def __init__(self) -> None:
        self.badges: dict[str, int] = {}

    def set_badges(self, badges: dict[str, int]) -> None:
        self.badges = dict(badges)


class _FakeNetHandler:
    def __init__(self) -> None:
        self.changed: list[tuple[str, int]] = []
        self.deleted: list[tuple[str, int]] = []

    def notify_change(self, table: str, record_id: int) -> None:
        self.changed.append((table, record_id))

    def notify_delete(self, table: str, record_id: int) -> None:
        self.deleted.append((table, record_id))


def _make_app(current: str, *screen_names: str) -> tuple[TalonApp, dict[str, _FakeScreen], _FakeNetHandler, _FakeNavRail]:
    app = TalonApp.__new__(TalonApp)
    screens = {name: _FakeScreen() for name in screen_names}
    nav_rail = _FakeNavRail()
    net_handler = _FakeNetHandler()
    app._sm = _FakeScreenManager(current, screens)
    app._nav_rail = nav_rail
    app._unread_badges = {}
    app.net_handler = net_handler
    app.client_sync = None
    return app, screens, net_handler, nav_rail


class _FakeCoreSession:
    conn = object()
    db_key = b"core-key"
    operator_id = 12
    sync_engine = object()
    net_handler = object()
    client_sync = object()


def test_app_mirrors_core_runtime_refs_for_legacy_screens() -> None:
    app = TalonApp.__new__(TalonApp)
    app.core_session = _FakeCoreSession()

    app._sync_core_runtime_refs()

    assert app.conn is app.core_session.conn
    assert app.db_key == b"core-key"
    assert app.operator_id == 12
    assert app.sync_engine is app.core_session.sync_engine
    assert app.net_handler is app.core_session.net_handler
    assert app.client_sync is app.core_session.client_sync


def test_dispatch_domain_events_expands_linked_record_notifications() -> None:
    app, screens, net_handler, nav_rail = _make_app(
        "audit",
        "audit",
        "chat",
        "mission",
        "main",
        "sitrep",
    )

    app.dispatch_domain_events((
        linked_records_changed(
            record_deleted("messages", 10),
            record_deleted("channels", 11),
            record_changed("missions", 12),
            record_changed("sitreps", 13),
        ),
    ))

    assert net_handler.deleted == [("messages", 10), ("channels", 11)]
    assert net_handler.changed == [("missions", 12), ("sitreps", 13)]
    assert screens["audit"].refresh_count == 0
    assert app._unread_badges == {
        "chat": 2,
        "mission": 1,
        "main": 2,
        "sitrep": 1,
    }
    assert nav_rail.badges == app._unread_badges


def test_dispatch_domain_events_routes_operator_events_to_server_screens() -> None:
    app, screens, net_handler, nav_rail = _make_app(
        "main",
        "main",
        "clients",
        "keys",
    )

    app.dispatch_domain_events((
        lease_renewed(7, 9999, ui_targets=("clients",)),
        operator_revoked(8, ui_targets=("clients", "keys")),
    ))

    assert net_handler.changed == [("operators", 7), ("operators", 8)]
    assert net_handler.deleted == []
    assert screens["main"].refresh_count == 0
    assert app._unread_badges == {"clients": 2, "keys": 1}
    assert nav_rail.badges == app._unread_badges


def test_dispatch_domain_events_refreshes_current_screen_once_per_batch() -> None:
    app, screens, net_handler, _nav_rail = _make_app(
        "mission",
        "mission",
        "main",
    )

    app.dispatch_domain_events((
        linked_records_changed(
            record_changed("missions", 20),
            record_changed("waypoints", 21),
        ),
    ))

    assert net_handler.changed == [("missions", 20), ("waypoints", 21)]
    assert screens["mission"].refresh_count == 1
    assert app._unread_badges == {}


def test_on_data_pushed_can_refresh_without_badging() -> None:
    app, screens, _net_handler, nav_rail = _make_app(
        "login",
        "login",
        "main",
        "sitrep",
    )

    app.on_data_pushed("sitreps", badge=False)

    assert screens["login"].refresh_count == 0
    assert app._unread_badges == {}
    assert nav_rail.badges == {}

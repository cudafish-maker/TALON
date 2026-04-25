"""Regression tests for screen flows that must resolve the local operator."""

from types import SimpleNamespace

import talon.sitrep as sitrep_module
from talon.ui.screens import asset_screen, mission_create_screen, sitrep_screen


class _FakeApp:
    def __init__(self) -> None:
        self.conn = object()
        self.db_key = bytes(range(32))
        self.mode = "client"
        self.require_calls: list[bool] = []
        self.dispatched: list[tuple] = []
        self.net_notifications: list[tuple[str, int]] = []

    def require_local_operator_id(self, *, allow_server_sentinel: bool = False) -> int:
        self.require_calls.append(allow_server_sentinel)
        return 77

    def dispatch_domain_events(self, events) -> None:
        self.dispatched.append(tuple(events))

    def net_notify_change(self, table: str, record_id: int) -> None:
        self.net_notifications.append((table, record_id))


class _FakeModal:
    def __init__(self) -> None:
        self.dismissed = False

    def dismiss(self) -> None:
        self.dismissed = True


def test_asset_screen_create_uses_require_local_operator_id(monkeypatch):
    fake_app = _FakeApp()
    captured = {}
    screen = asset_screen.AssetScreen.__new__(asset_screen.AssetScreen)
    modal = _FakeModal()
    status_label = SimpleNamespace(text="")
    load_calls = []
    refresh_calls = []
    screen._load_assets = lambda: load_calls.append(True)
    screen._refresh_map = lambda: refresh_calls.append(True)

    monkeypatch.setattr(
        asset_screen,
        "App",
        type("FakeAssetApp", (), {"get_running_app": staticmethod(lambda: fake_app)}),
    )
    monkeypatch.setattr(
        asset_screen,
        "create_asset_command",
        lambda conn, *, author_id, category, label, description="", lat=None, lon=None: (
            captured.update(
                {
                    "conn": conn,
                    "author_id": author_id,
                    "category": category,
                    "label": label,
                }
            )
            or SimpleNamespace(events=("asset-created",))
        ),
    )

    screen._do_create(modal, status_label, "cache", "CACHE-77", "", "", "")

    assert captured["author_id"] == 77
    assert fake_app.require_calls == [False]
    assert fake_app.dispatched == [("asset-created",)]
    assert modal.dismissed is True
    assert load_calls == [True]
    assert refresh_calls == [True]


def test_mission_create_submit_uses_require_local_operator_id(monkeypatch):
    fake_app = _FakeApp()
    captured = {}
    screen = mission_create_screen.MissionCreateScreen.__new__(
        mission_create_screen.MissionCreateScreen
    )
    screen._data = {"title": "Mission 77", "description": "client-created"}
    screen._selected_asset_ids = {8, 9}
    screen._ao_polygon = None
    screen._route = None
    screen.manager = SimpleNamespace(current="mission_create")
    screen._collect_all_steps = lambda: None
    screen._show_error = lambda _message: None

    monkeypatch.setattr(
        mission_create_screen,
        "App",
        type("FakeMissionApp", (), {"get_running_app": staticmethod(lambda: fake_app)}),
    )
    monkeypatch.setattr(
        mission_create_screen,
        "create_mission_command",
        lambda conn, **kwargs: (
            captured.update({"conn": conn, **kwargs})
            or SimpleNamespace(events=("mission-created",))
        ),
    )

    screen._do_submit()

    assert captured["created_by"] == 77
    assert set(captured["asset_ids"]) == {8, 9}
    assert fake_app.require_calls == [False]
    assert fake_app.dispatched == [("mission-created",)]
    assert screen.manager.current == "mission"


def test_sitrep_submit_uses_require_local_operator_id(monkeypatch):
    fake_app = _FakeApp()
    captured = {}
    screen = sitrep_screen.SitrepScreen.__new__(sitrep_screen.SitrepScreen)
    screen._compose_level = "ROUTINE"
    screen._linked_asset_id = None
    screen._linked_asset_label = ""
    screen._linked_mission_id = None
    screen._linked_mission_title = ""
    screen._body_field = SimpleNamespace(text="existing")
    screen._update_link_status = lambda: None
    screen._load_feed = lambda: None
    screen._set_status = lambda _text, **_kwargs: None

    monkeypatch.setattr(
        sitrep_screen,
        "App",
        type("FakeSitrepApp", (), {"get_running_app": staticmethod(lambda: fake_app)}),
    )
    monkeypatch.setattr(
        sitrep_module,
        "create_sitrep",
        lambda conn, db_key, *, author_id, level, body, asset_id=None, mission_id=None: (
            captured.update(
                {
                    "conn": conn,
                    "db_key": db_key,
                    "author_id": author_id,
                    "level": level,
                    "body": body,
                }
            )
            or 91
        ),
    )

    screen.on_submit_pressed(" client-authored sitrep ")

    assert captured["author_id"] == 77
    assert captured["body"] == "client-authored sitrep"
    assert fake_app.require_calls == [False]
    assert fake_app.net_notifications == [("sitreps", 91)]

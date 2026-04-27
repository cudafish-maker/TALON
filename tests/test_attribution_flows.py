"""Regression tests for screen flows that delegate attribution to core."""

from types import SimpleNamespace

from talon.ui.screens import asset_screen, mission_create_screen, sitrep_screen


class _FakeCoreSession:
    is_unlocked = True

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict]] = []

    def command(self, command_name: str, payload=None, **kwargs):
        data = dict(payload or {})
        data.update(kwargs)
        self.commands.append((command_name, data))
        if command_name == "assets.create":
            return SimpleNamespace(asset_id=81, events=("asset-created",))
        if command_name == "missions.create":
            return SimpleNamespace(mission=SimpleNamespace(id=82), events=("mission-created",))
        if command_name == "sitreps.create":
            return SimpleNamespace(record_id=91, events=("sitrep-created",))
        return SimpleNamespace(events=())


class _FakeApp:
    def __init__(self) -> None:
        self.conn = object()
        self.db_key = bytes(range(32))
        self.mode = "client"
        self.core_session = _FakeCoreSession()
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


def test_asset_screen_create_delegates_to_core(monkeypatch):
    fake_app = _FakeApp()
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

    screen._do_create(modal, status_label, "cache", "CACHE-77", "", "", "")

    assert fake_app.core_session.commands == [
        (
            "assets.create",
            {
                "category": "cache",
                "label": "CACHE-77",
                "description": "",
                "lat": None,
                "lon": None,
            },
        )
    ]
    assert fake_app.require_calls == []
    assert fake_app.dispatched == []
    assert modal.dismissed is True
    assert load_calls == [True]
    assert refresh_calls == [True]


def test_mission_create_submit_delegates_to_core(monkeypatch):
    fake_app = _FakeApp()
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

    screen._do_submit()

    assert fake_app.core_session.commands[0][0] == "missions.create"
    assert set(fake_app.core_session.commands[0][1]["asset_ids"]) == {8, 9}
    assert "created_by" not in fake_app.core_session.commands[0][1]
    assert fake_app.require_calls == []
    assert fake_app.dispatched == []
    assert screen.manager.current == "mission"


def test_sitrep_submit_delegates_to_core(monkeypatch):
    fake_app = _FakeApp()
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

    screen.on_submit_pressed(" client-authored sitrep ")

    assert fake_app.core_session.commands == [
        (
            "sitreps.create",
            {
                "level": "ROUTINE",
                "body": "client-authored sitrep",
                "asset_id": None,
                "mission_id": None,
            },
        )
    ]
    assert fake_app.require_calls == []
    assert fake_app.net_notifications == []

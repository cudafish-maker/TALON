"""Tests for PySide6 desktop domain-event routing."""

import pytest

QtCore = pytest.importorskip("PySide6.QtCore")

from talon_core.services.events import (
    RecordMutation,
    lease_renewed,
    linked_records_changed,
    operator_revoked,
    record_changed,
    record_deleted,
)
from talon_desktop.qt_events import CoreEventBridge


def _bridge() -> CoreEventBridge:
    QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    return CoreEventBridge()


def test_core_event_bridge_expands_linked_record_notifications() -> None:
    bridge = _bridge()
    received_events = []
    mutations: list[tuple[str, str, int]] = []
    refreshes: list[str] = []
    locks: list[str] = []

    bridge.eventReceived.connect(received_events.append)
    bridge.recordMutated.connect(
        lambda action, table, record_id: mutations.append((action, table, record_id))
    )
    bridge.refreshRequested.connect(refreshes.append)
    bridge.lockRequested.connect(locks.append)

    event = linked_records_changed(
        record_deleted("messages", 10),
        record_deleted("channels", 11),
        record_changed("missions", 12),
        record_changed("sitreps", 13),
    )
    bridge.handle_core_event(event)

    assert received_events == [event]
    assert mutations == [
        ("deleted", "messages", 10),
        ("deleted", "channels", 11),
        ("changed", "missions", 12),
        ("changed", "sitreps", 13),
    ]
    assert set(refreshes) == {
        "assignments",
        "chat",
        "dashboard",
        "map",
        "missions",
        "sitreps",
    }
    assert locks == []


def test_core_event_bridge_routes_operator_events_to_server_sections() -> None:
    bridge = _bridge()
    mutations: list[tuple[str, str, int]] = []
    refreshes: list[str] = []
    locks: list[str] = []

    bridge.recordMutated.connect(
        lambda action, table, record_id: mutations.append((action, table, record_id))
    )
    bridge.refreshRequested.connect(refreshes.append)
    bridge.lockRequested.connect(locks.append)

    bridge.handle_core_event(lease_renewed(7, 9999, ui_targets=("operators",)))
    bridge.handle_core_event(operator_revoked(8, ui_targets=("operators", "keys")))

    assert mutations == [
        ("changed", "operators", 7),
        ("changed", "operators", 8),
    ]
    assert set(refreshes) == {"dashboard", "keys", "operators"}
    assert locks == ["revoked"]


def test_core_event_bridge_refreshes_current_record_surfaces_once() -> None:
    bridge = _bridge()
    mutations: list[tuple[str, str, int]] = []
    refreshes: list[str] = []

    bridge.recordMutated.connect(
        lambda action, table, record_id: mutations.append((action, table, record_id))
    )
    bridge.refreshRequested.connect(refreshes.append)

    bridge.handle_core_event(
        linked_records_changed(
            RecordMutation("changed", "missions", 20),
            RecordMutation("changed", "waypoints", 21),
        )
    )

    assert mutations == [
        ("changed", "missions", 20),
        ("changed", "waypoints", 21),
    ]
    assert set(refreshes) == {"assignments", "dashboard", "map", "missions"}

"""Qt signal adapter for TALON core domain events."""
from __future__ import annotations

from PySide6 import QtCore

from talon_core.services.events import DomainEvent
from talon_desktop.events import desktop_update_from_event


class CoreEventBridge(QtCore.QObject):
    """Adapt core events into UI-thread friendly Qt signals."""

    eventReceived = QtCore.Signal(object)
    refreshRequested = QtCore.Signal(str)
    recordMutated = QtCore.Signal(str, str, int)
    lockRequested = QtCore.Signal(str)

    @QtCore.Slot(object)
    def handle_core_event(self, event: DomainEvent) -> None:
        update = desktop_update_from_event(event)
        self.eventReceived.emit(event)
        for mutation in update.mutations:
            self.recordMutated.emit(
                mutation.action,
                mutation.table,
                int(mutation.record_id),
            )
        for section in sorted(update.refresh_sections):
            self.refreshRequested.emit(section)
        if update.lock_reason:
            self.lockRequested.emit(update.lock_reason)

"""Core-to-desktop event mapping."""
from __future__ import annotations

import dataclasses
import typing

from talon_core.network.registry import ui_refresh_targets
from talon_core.services.events import DomainEvent, RecordMutation

from talon_desktop.navigation import desktop_sections_for_legacy_targets


@dataclasses.dataclass(frozen=True)
class DesktopEventUpdate:
    """UI work requested by one core domain event."""

    kind: str
    mutations: tuple[RecordMutation, ...]
    refresh_sections: frozenset[str]
    lock_reason: str | None = None


def desktop_update_from_event(event: DomainEvent) -> DesktopEventUpdate:
    """Convert a core event into section refresh and lock requests."""
    mutations = event.iter_records()
    legacy_targets: set[str] = set(event.ui_targets)
    for mutation in mutations:
        legacy_targets.update(ui_refresh_targets(mutation.table))

    refresh_sections = set(desktop_sections_for_legacy_targets(legacy_targets))
    lock_reason: str | None = None
    if event.kind == "lease_renewed":
        refresh_sections.add("dashboard")
        refresh_sections.add("operators")
    elif event.kind == "operator_revoked":
        refresh_sections.add("dashboard")
        refresh_sections.add("operators")
        lock_reason = "revoked"

    return DesktopEventUpdate(
        kind=event.kind,
        mutations=tuple(mutations),
        refresh_sections=frozenset(refresh_sections),
        lock_reason=lock_reason,
    )


def refresh_sections_for_events(
    events: typing.Iterable[DomainEvent],
) -> frozenset[str]:
    sections: set[str] = set()
    for event in events:
        sections.update(desktop_update_from_event(event).refresh_sections)
    return frozenset(sections)

"""Desktop navigation model shared by Qt shell and tests."""
from __future__ import annotations

import dataclasses
import typing

Mode = typing.Literal["server", "client"]


@dataclasses.dataclass(frozen=True)
class DesktopNavItem:
    key: str
    label: str
    read_model: str | None = None
    legacy_targets: frozenset[str] = dataclasses.field(default_factory=frozenset)
    server_only: bool = False


_COMMON_NAV: tuple[DesktopNavItem, ...] = (
    DesktopNavItem("dashboard", "Dashboard", "session", frozenset({"main"})),
    DesktopNavItem("map", "Map", "map.context", frozenset({"main"})),
    DesktopNavItem("sitreps", "SITREPs", "sitreps.list", frozenset({"sitrep"})),
    DesktopNavItem("assets", "Assets", "assets.list", frozenset({"assets"})),
    DesktopNavItem("missions", "Missions", "missions.list", frozenset({"mission"})),
    DesktopNavItem("assignments", "Assignments", "assignments.board", frozenset({"assignments"})),
    DesktopNavItem("incidents", "Incidents", "incidents.list", frozenset({"incidents"})),
    DesktopNavItem("chat", "Chat", "chat.channels", frozenset({"chat"})),
    DesktopNavItem("documents", "Documents", "documents.list", frozenset({"documents"})),
    DesktopNavItem("operators", "Operators", "operators.list", frozenset({"operators"})),
)

_SERVER_NAV: tuple[DesktopNavItem, ...] = (
    DesktopNavItem(
        "enrollment",
        "Enrollment",
        "enrollment.pending_tokens",
        frozenset({"enroll"}),
        server_only=True,
    ),
    DesktopNavItem(
        "clients",
        "Clients",
        "operators.list",
        frozenset({"clients"}),
        server_only=True,
    ),
    DesktopNavItem(
        "audit",
        "Audit",
        "audit.list",
        frozenset({"audit"}),
        server_only=True,
    ),
    DesktopNavItem(
        "keys",
        "Keys",
        "enrollment.server_hash",
        frozenset({"keys"}),
        server_only=True,
    ),
)


def navigation_items(mode: Mode) -> tuple[DesktopNavItem, ...]:
    """Return the desktop sections visible for *mode*."""
    if mode == "server":
        return _COMMON_NAV + _SERVER_NAV
    if mode == "client":
        return _COMMON_NAV
    raise ValueError(f"Invalid TALON mode: {mode!r}")


def all_navigation_items() -> tuple[DesktopNavItem, ...]:
    """Return every declared section, including server-only sections."""
    return _COMMON_NAV + _SERVER_NAV


def section_for_key(key: str) -> DesktopNavItem:
    for item in all_navigation_items():
        if item.key == key:
            return item
    raise KeyError(f"Unknown desktop section: {key}")


def desktop_sections_for_legacy_targets(
    targets: typing.Iterable[str],
) -> frozenset[str]:
    """Map core/Kivy-era UI refresh targets onto desktop section keys."""
    target_set = frozenset(targets)
    if not target_set:
        return frozenset()
    sections: set[str] = set()
    for item in all_navigation_items():
        if item.legacy_targets & target_set:
            sections.add(item.key)
    return frozenset(sections)

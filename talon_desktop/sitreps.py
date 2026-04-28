"""SITREP helpers for the PySide6 desktop client.

This module stays free of Qt imports so behavior and safety policy can be
tested without PySide6 installed.
"""
from __future__ import annotations

import dataclasses
import datetime
import typing

from talon_core.constants import SITREP_LEVELS

FLASH_LEVELS = frozenset({"FLASH", "FLASH_OVERRIDE"})
ATTENTION_LEVELS = frozenset(SITREP_LEVELS)


@dataclasses.dataclass(frozen=True)
class SitrepFeedItem:
    id: int
    level: str
    body: str
    callsign: str
    asset_label: str | None
    mission_id: int | None
    asset_id: int | None
    created_at: int

    @property
    def is_flash(self) -> bool:
        return self.level in FLASH_LEVELS

    @property
    def needs_attention(self) -> bool:
        return self.level in ATTENTION_LEVELS


@dataclasses.dataclass(frozen=True)
class SitrepTemplate:
    key: str
    label: str
    level: str
    body: str


DEFAULT_TEMPLATE_KEY = "free_text"
SITREP_TEMPLATES = (
    SitrepTemplate(
        key=DEFAULT_TEMPLATE_KEY,
        label="Free text",
        level="ROUTINE",
        body="",
    ),
    SitrepTemplate(
        key="contact",
        label="Contact",
        level="IMMEDIATE",
        body=(
            "Location:\n"
            "Contact type:\n"
            "Direction/range:\n"
            "Activity:\n"
            "Action taken:\n"
            "Support needed:"
        ),
    ),
    SitrepTemplate(
        key="medical",
        label="Medical",
        level="PRIORITY",
        body=(
            "Location:\n"
            "Patient count:\n"
            "Condition:\n"
            "Care given:\n"
            "Evacuation need:\n"
            "Requested support:"
        ),
    ),
    SitrepTemplate(
        key="logistics",
        label="Logistics",
        level="ROUTINE",
        body=(
            "Location:\n"
            "Supply status:\n"
            "Shortfalls:\n"
            "Transport status:\n"
            "ETA/request:"
        ),
    ),
    SitrepTemplate(
        key="infrastructure",
        label="Infrastructure",
        level="PRIORITY",
        body=(
            "Location:\n"
            "System affected:\n"
            "Observed damage:\n"
            "Operational impact:\n"
            "Immediate hazard:\n"
            "Requested action:"
        ),
    ),
    SitrepTemplate(
        key="weather",
        label="Weather",
        level="ROUTINE",
        body=(
            "Location:\n"
            "Conditions:\n"
            "Visibility:\n"
            "Wind/precipitation:\n"
            "Impact on operations:"
        ),
    ),
)


def sitrep_template_for_key(key: str) -> SitrepTemplate:
    for template in SITREP_TEMPLATES:
        if template.key == key:
            return template
    raise KeyError(f"Unknown SITREP template: {key!r}")


def feed_item_from_entry(entry: object) -> SitrepFeedItem:
    """Normalize a core ``sitreps.list`` row for desktop display."""
    if isinstance(entry, tuple):
        sitrep = entry[0]
        callsign = str(entry[1]) if len(entry) > 1 else "UNKNOWN"
        asset_label = typing.cast(str | None, entry[2] if len(entry) > 2 else None)
    else:
        sitrep = entry
        callsign = str(_field(sitrep, "callsign", default="UNKNOWN"))
        asset_label = typing.cast(str | None, _field(sitrep, "asset_label", default=None))

    return SitrepFeedItem(
        id=int(_field(sitrep, "id")),
        level=str(_field(sitrep, "level")),
        body=body_text(_field(sitrep, "body")),
        callsign=callsign,
        asset_label=asset_label,
        mission_id=_optional_int(_field(sitrep, "mission_id", default=None)),
        asset_id=_optional_int(_field(sitrep, "asset_id", default=None)),
        created_at=int(_field(sitrep, "created_at", default=0) or 0),
    )


def feed_items_from_entries(entries: typing.Iterable[object]) -> list[SitrepFeedItem]:
    return [feed_item_from_entry(entry) for entry in entries]


def body_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)


def build_create_payload(
    *,
    level: str,
    body: str,
    template: str = "",
    asset_id: int | None = None,
    mission_id: int | None = None,
) -> dict[str, object]:
    """Validate desktop composer state and build a core command payload."""
    if level not in SITREP_LEVELS:
        raise ValueError(f"Unknown SITREP level: {level!r}")
    stripped = body.strip()
    if not stripped:
        raise ValueError("SITREP body is required.")
    payload: dict[str, object] = {
        "level": level,
        "body": stripped,
        "asset_id": asset_id,
        "mission_id": mission_id,
    }
    if template:
        payload["template"] = template
    return payload


def severity_counts(items: typing.Iterable[SitrepFeedItem]) -> dict[str, int]:
    counts = {level: 0 for level in SITREP_LEVELS}
    for item in items:
        counts[item.level] = counts.get(item.level, 0) + 1
    return counts


def should_play_audio(level: str, audio_enabled: bool) -> bool:
    """Return True only for opt-in FLASH audio eligibility."""
    return bool(audio_enabled and level in FLASH_LEVELS)


def format_created_at(timestamp: int) -> str:
    if timestamp <= 0:
        return "--:--"
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def _field(obj: object, name: str, *, default: object = "") -> object:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)

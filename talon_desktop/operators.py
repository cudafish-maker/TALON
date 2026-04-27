"""Desktop operator, enrollment, audit, and key-status helpers."""
from __future__ import annotations

import dataclasses
import datetime
import math
import time
import typing

from talon_core.constants import PREDEFINED_SKILLS
from talon_core.operators import SERVER_OPERATOR_ID


@dataclasses.dataclass(frozen=True)
class DesktopOperatorItem:
    id: int
    callsign: str
    rns_hash: str
    rns_preview: str
    skills: tuple[str, ...]
    skills_label: str
    profile: dict[str, typing.Any]
    display_name: str
    role: str
    notes: str
    enrolled_at: int
    enrolled_label: str
    lease_expires_at: int
    lease_label: str
    status: str
    status_label: str
    revoked: bool
    is_sentinel: bool


@dataclasses.dataclass(frozen=True)
class DesktopEnrollmentTokenItem:
    token: str
    token_preview: str
    created_at: int
    created_label: str
    expires_at: int
    expires_label: str
    remaining_label: str


@dataclasses.dataclass(frozen=True)
class DesktopAuditEntryItem:
    id: int
    event: str
    payload: dict[str, typing.Any]
    payload_label: str
    occurred_at: int
    occurred_label: str
    severity: str


def item_from_operator(operator: object, *, now: int | None = None) -> DesktopOperatorItem:
    current_time = int(time.time()) if now is None else int(now)
    profile = getattr(operator, "profile", {}) or {}
    if not isinstance(profile, dict):
        profile = {}
    skills = tuple(str(skill).strip().lower() for skill in getattr(operator, "skills", []) if str(skill).strip())
    lease_expires_at = int(getattr(operator, "lease_expires_at", 0) or 0)
    revoked = bool(getattr(operator, "revoked", False))
    status, status_label = _lease_status(
        revoked=revoked,
        lease_expires_at=lease_expires_at,
        now=current_time,
    )
    return DesktopOperatorItem(
        id=int(getattr(operator, "id")),
        callsign=str(getattr(operator, "callsign", "")),
        rns_hash=str(getattr(operator, "rns_hash", "")),
        rns_preview=preview_hash(str(getattr(operator, "rns_hash", ""))),
        skills=skills,
        skills_label=", ".join(skills) if skills else "None",
        profile=dict(profile),
        display_name=str(profile.get("display_name", "") or ""),
        role=str(profile.get("role", "") or ""),
        notes=str(profile.get("notes", "") or ""),
        enrolled_at=int(getattr(operator, "enrolled_at", 0) or 0),
        enrolled_label=format_timestamp(int(getattr(operator, "enrolled_at", 0) or 0)),
        lease_expires_at=lease_expires_at,
        lease_label=format_timestamp(lease_expires_at),
        status=status,
        status_label=status_label,
        revoked=revoked,
        is_sentinel=int(getattr(operator, "id")) == SERVER_OPERATOR_ID,
    )


def items_from_operators(
    operators: typing.Iterable[object],
    *,
    now: int | None = None,
) -> list[DesktopOperatorItem]:
    return [item_from_operator(operator, now=now) for operator in operators]


def build_operator_update_payload(
    *,
    operator_id: int,
    display_name: str = "",
    role: str = "",
    notes: str = "",
    selected_skills: typing.Iterable[str] = (),
    custom_skills_text: str = "",
) -> dict[str, object]:
    oid = int(operator_id)
    if oid <= 0:
        raise ValueError("A valid operator is required.")
    profile = {
        "display_name": display_name.strip(),
        "role": role.strip(),
        "notes": notes.strip(),
    }
    return {
        "operator_id": oid,
        "skills": parse_skills(
            custom_skills_text,
            selected_skills=selected_skills,
        ),
        "profile": profile,
    }


def parse_skills(
    custom_skills_text: str,
    *,
    selected_skills: typing.Iterable[str] = (),
) -> list[str]:
    values: list[str] = []
    for skill in tuple(selected_skills) + tuple(custom_skills_text.replace("\n", ",").split(",")):
        value = str(skill).strip().lower()
        if not value or value in values:
            continue
        values.append(value)
    return values


def can_edit_operator(
    *,
    mode: str,
    current_operator_id: int | None,
    item: DesktopOperatorItem | None,
) -> bool:
    if item is None or item.is_sentinel:
        return False
    if mode == "server":
        return True
    return current_operator_id is not None and item.id == current_operator_id


def can_renew_operator(mode: str, item: DesktopOperatorItem | None) -> bool:
    return mode == "server" and item is not None and not item.revoked and not item.is_sentinel


def can_revoke_operator(mode: str, item: DesktopOperatorItem | None) -> bool:
    return mode == "server" and item is not None and not item.revoked and not item.is_sentinel


def item_from_enrollment_token(
    token: object,
    *,
    now: int | None = None,
) -> DesktopEnrollmentTokenItem:
    current_time = int(time.time()) if now is None else int(now)
    raw_token = str(getattr(token, "token", ""))
    created_at = int(getattr(token, "created_at", 0) or 0)
    expires_at = int(getattr(token, "expires_at", 0) or 0)
    remaining_s = max(0, expires_at - current_time)
    return DesktopEnrollmentTokenItem(
        token=raw_token,
        token_preview=preview_token(raw_token),
        created_at=created_at,
        created_label=format_timestamp(created_at),
        expires_at=expires_at,
        expires_label=format_timestamp(expires_at),
        remaining_label=f"{remaining_s // 60} min",
    )


def items_from_enrollment_tokens(
    tokens: typing.Iterable[object],
    *,
    now: int | None = None,
) -> list[DesktopEnrollmentTokenItem]:
    return [item_from_enrollment_token(token, now=now) for token in tokens]


def item_from_audit_entry(entry: object) -> DesktopAuditEntryItem:
    payload = getattr(entry, "payload", {}) or {}
    if not isinstance(payload, dict):
        payload = {}
    event = str(getattr(entry, "event", ""))
    occurred_at = int(getattr(entry, "occurred_at", 0) or 0)
    return DesktopAuditEntryItem(
        id=int(getattr(entry, "id")),
        event=event,
        payload=dict(payload),
        payload_label=format_payload(payload),
        occurred_at=occurred_at,
        occurred_label=format_timestamp(occurred_at),
        severity=audit_severity(event),
    )


def items_from_audit_entries(entries: typing.Iterable[object]) -> list[DesktopAuditEntryItem]:
    return [item_from_audit_entry(entry) for entry in entries]


def format_payload(payload: typing.Mapping[str, typing.Any]) -> str:
    if not payload:
        return ""
    parts = [f"{key}={value}" for key, value in sorted(payload.items())]
    text = "  ".join(parts)
    return text if len(text) <= 120 else f"{text[:117]}..."


def audit_severity(event: str) -> str:
    lowered = event.lower()
    if any(token in lowered for token in ("revok", "shred", "burn", "delet")):
        return "danger"
    if any(token in lowered for token in ("lock", "expir", "rotat", "abort")):
        return "warning"
    if any(token in lowered for token in ("enroll", "renew", "approv", "creat", "complet")):
        return "positive"
    return "neutral"


def preview_hash(value: str) -> str:
    if not value:
        return ""
    return value if len(value) <= 16 else f"{value[:16]}..."


def preview_token(value: str) -> str:
    if not value:
        return ""
    return value if len(value) <= 32 else f"{value[:32]}..."


def format_timestamp(value: int) -> str:
    if value <= 0:
        return "Unknown"
    return datetime.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")


def predefined_skill_set() -> tuple[str, ...]:
    return tuple(PREDEFINED_SKILLS)


def _lease_status(
    *,
    revoked: bool,
    lease_expires_at: int,
    now: int,
) -> tuple[str, str]:
    if revoked:
        return "revoked", "REVOKED"
    if lease_expires_at < now:
        return "locked", "LOCKED"
    remaining_hours = max(1, math.ceil((lease_expires_at - now) / 3600))
    return "active", f"OK ({remaining_hours}h)"

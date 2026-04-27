"""Operator workflow commands that return notification-ready domain events."""
from __future__ import annotations

import dataclasses
import json
import pathlib
import typing

from talon_core.constants import LEASE_DURATION_S
from talon_core.db.connection import Connection
from talon_core.services.events import (
    DomainEvent,
    lease_renewed,
    operator_revoked,
    record_changed,
)
from talon_core.utils.logging import get_logger

_log = get_logger("services.operators")


@dataclasses.dataclass(frozen=True)
class OperatorCommandResult:
    operator_id: int
    events: tuple[DomainEvent, ...]
    lease_expires_at: typing.Optional[int] = None


def update_operator_command(
    conn: Connection,
    operator_id: int,
    *,
    skills: typing.Optional[list[str]] = None,
    profile: typing.Optional[dict] = None,
) -> OperatorCommandResult:
    updates: list[str] = []
    params: list[typing.Any] = []

    if skills is not None:
        normalised = [s.strip().lower() for s in skills if s.strip()]
        updates.append("skills = ?")
        params.append(json.dumps(normalised))
    if profile is not None:
        updates.append("profile = ?")
        params.append(json.dumps(profile))

    if not updates:
        raise ValueError("No operator updates were provided.")

    updates.append("version = version + 1")
    sql = f"UPDATE operators SET {', '.join(updates)} WHERE id = ?"
    cursor = conn.execute(sql, (*params, operator_id))
    if cursor.rowcount == 0:
        conn.rollback()
        raise ValueError(f"Operator {operator_id} not found.")
    conn.commit()
    _log.info(
        "Operator updated: operator_id=%s skills=%s profile=%s",
        operator_id,
        skills is not None,
        profile is not None,
    )
    return OperatorCommandResult(
        operator_id,
        events=(record_changed("operators", operator_id, ui_targets=("clients",)),),
    )


def renew_operator_lease_command(
    conn: Connection,
    operator_id: int,
    duration_s: int = LEASE_DURATION_S,
) -> OperatorCommandResult:
    from talon_core.server.enrollment import renew_lease

    new_expiry = renew_lease(conn, operator_id, duration_s)
    return OperatorCommandResult(
        operator_id,
        events=(lease_renewed(operator_id, new_expiry, ui_targets=("clients",)),),
        lease_expires_at=new_expiry,
    )


def revoke_operator_command(
    conn: Connection,
    operator_id: int,
    *,
    identity_path: typing.Optional[pathlib.Path] = None,
    group_key_rotator: typing.Optional[typing.Callable[[], None]] = None,
) -> OperatorCommandResult:
    from talon_core.server.revocation import revoke_operator

    revoke_operator(
        conn,
        operator_id,
        identity_path=identity_path,
        group_key_rotator=group_key_rotator,
    )
    return OperatorCommandResult(
        operator_id,
        events=(operator_revoked(operator_id, ui_targets=("clients", "keys")),),
    )

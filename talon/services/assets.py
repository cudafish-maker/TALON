"""Asset workflow commands that return notification-ready domain events."""
from __future__ import annotations

import dataclasses
import typing

from talon.assets import (
    _CLEAR,
    create_asset,
    delete_asset,
    request_asset_deletion,
    update_asset,
)
from talon.db.connection import Connection
from talon.services.events import (
    DomainEvent,
    linked_records_changed,
    record_changed,
    record_deleted,
)


@dataclasses.dataclass(frozen=True)
class AssetCommandResult:
    asset_id: int
    events: tuple[DomainEvent, ...]


def create_asset_command(
    conn: Connection,
    *,
    author_id: int,
    category: str,
    label: str,
    description: str = "",
    lat: typing.Optional[float] = None,
    lon: typing.Optional[float] = None,
    sync_status: str = "synced",
) -> AssetCommandResult:
    asset_id = create_asset(
        conn,
        author_id=author_id,
        category=category,
        label=label,
        description=description,
        lat=lat,
        lon=lon,
        sync_status=sync_status,
    )
    return AssetCommandResult(asset_id, (record_changed("assets", asset_id),))


def update_asset_command(
    conn: Connection,
    asset_id: int,
    *,
    label: typing.Optional[str] = None,
    description: typing.Optional[str] = None,
    lat: typing.Optional[float] = None,
    lon: typing.Optional[float] = None,
) -> AssetCommandResult:
    update_asset(
        conn,
        asset_id,
        label=label,
        description=description,
        lat=lat,
        lon=lon,
    )
    return AssetCommandResult(asset_id, (record_changed("assets", asset_id),))


def verify_asset_command(
    conn: Connection,
    asset_id: int,
    *,
    verified: bool,
    confirmer_id: typing.Optional[int],
) -> AssetCommandResult:
    confirmed_by = confirmer_id if verified else _CLEAR
    update_asset(conn, asset_id, verified=verified, confirmed_by=confirmed_by)
    return AssetCommandResult(asset_id, (record_changed("assets", asset_id),))


def request_asset_deletion_command(
    conn: Connection,
    asset_id: int,
) -> AssetCommandResult:
    request_asset_deletion(conn, asset_id)
    return AssetCommandResult(asset_id, (record_changed("assets", asset_id),))


def hard_delete_asset_command(
    conn: Connection,
    asset_id: int,
) -> AssetCommandResult:
    sitrep_ids = _sitrep_ids_for_asset(conn, asset_id)
    delete_asset(conn, asset_id)
    event = linked_records_changed(
        record_deleted("assets", asset_id),
        *(record_changed("sitreps", sid) for sid in sitrep_ids),
    )
    return AssetCommandResult(asset_id, (event,))


def _sitrep_ids_for_asset(conn: Connection, asset_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM sitreps WHERE asset_id = ? ORDER BY id ASC",
        (asset_id,),
    ).fetchall()
    return [r[0] for r in rows]

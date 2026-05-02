"""Small domain-event primitives returned by service commands."""
from __future__ import annotations

import dataclasses
import typing

RecordAction = typing.Literal["changed", "deleted"]
DomainEventKind = typing.Literal[
    "record_changed",
    "record_deleted",
    "linked_records_changed",
    "ui_refresh_requested",
    "lease_renewed",
    "operator_revoked",
]


@dataclasses.dataclass(frozen=True)
class RecordMutation:
    action: RecordAction
    table: str
    record_id: int


@dataclasses.dataclass(frozen=True)
class DomainEvent:
    kind: DomainEventKind
    records: tuple[RecordMutation, ...] = ()
    operator_id: typing.Optional[int] = None
    origin_operator_id: typing.Optional[int] = None
    lease_expires_at: typing.Optional[int] = None
    ui_targets: frozenset[str] = dataclasses.field(default_factory=frozenset)

    @property
    def action(self) -> typing.Optional[RecordAction]:
        records = self.iter_records()
        if len(records) != 1:
            return None
        return records[0].action

    @property
    def table(self) -> typing.Optional[str]:
        records = self.iter_records()
        if len(records) != 1:
            return None
        return records[0].table

    @property
    def record_id(self) -> typing.Optional[int]:
        records = self.iter_records()
        if len(records) != 1:
            return None
        return records[0].record_id

    def iter_records(self) -> tuple[RecordMutation, ...]:
        if self.records:
            return self.records
        if self.kind in {"lease_renewed", "operator_revoked"} and self.operator_id is not None:
            return (RecordMutation("changed", "operators", self.operator_id),)
        return ()


def record_changed(
    table: str,
    record_id: int,
    *,
    ui_targets: typing.Iterable[str] = (),
) -> DomainEvent:
    return DomainEvent(
        "record_changed",
        records=(RecordMutation("changed", table, record_id),),
        ui_targets=frozenset(ui_targets),
    )


def record_deleted(
    table: str,
    record_id: int,
    *,
    ui_targets: typing.Iterable[str] = (),
) -> DomainEvent:
    return DomainEvent(
        "record_deleted",
        records=(RecordMutation("deleted", table, record_id),),
        ui_targets=frozenset(ui_targets),
    )


def linked_records_changed(
    *records: typing.Union[DomainEvent, RecordMutation],
    ui_targets: typing.Iterable[str] = (),
) -> DomainEvent:
    changes: list[RecordMutation] = []
    for record in records:
        if isinstance(record, DomainEvent):
            changes.extend(record.iter_records())
        elif isinstance(record, RecordMutation):
            changes.append(record)
        else:
            raise TypeError(f"Unsupported linked record event: {record!r}")
    return DomainEvent(
        "linked_records_changed",
        records=tuple(changes),
        ui_targets=frozenset(ui_targets),
    )


def ui_refresh_requested(
    *,
    ui_targets: typing.Iterable[str] = (),
) -> DomainEvent:
    return DomainEvent(
        "ui_refresh_requested",
        ui_targets=frozenset(ui_targets),
    )


def lease_renewed(
    operator_id: int,
    lease_expires_at: int,
    *,
    ui_targets: typing.Iterable[str] = (),
) -> DomainEvent:
    return DomainEvent(
        "lease_renewed",
        operator_id=operator_id,
        lease_expires_at=lease_expires_at,
        ui_targets=frozenset(ui_targets),
    )


def operator_revoked(
    operator_id: int,
    *,
    ui_targets: typing.Iterable[str] = (),
) -> DomainEvent:
    return DomainEvent(
        "operator_revoked",
        operator_id=operator_id,
        ui_targets=frozenset(ui_targets),
    )


def expand_record_mutations(events: typing.Iterable[DomainEvent]) -> tuple[RecordMutation, ...]:
    changes: list[RecordMutation] = []
    for event in events:
        changes.extend(event.iter_records())
    return tuple(changes)

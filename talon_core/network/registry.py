"""Shared registry for synced table behavior."""
import dataclasses
import typing

from talon_core.crypto.fields import decrypt_field, encrypt_field


@dataclasses.dataclass(frozen=True)
class SyncedTable:
    name: str
    syncable: bool = True
    sync_order: int = 999
    client_pushable: bool = False
    offline_creatable: bool = False
    tombstone_order: int = 999
    redacted_fields: frozenset[str] = dataclasses.field(default_factory=frozenset)
    encrypted_fields: frozenset[str] = dataclasses.field(default_factory=frozenset)
    binary_text_fields: frozenset[str] = dataclasses.field(default_factory=frozenset)
    ownership_fields: tuple[str, ...] = ()
    client_push_forced_fields: dict[str, typing.Any] = dataclasses.field(default_factory=dict)
    ui_refresh_targets: frozenset[str] = dataclasses.field(default_factory=frozenset)
    predelete_sql: tuple[str, ...] = ()


def _fields(*names: str) -> frozenset[str]:
    return frozenset(names)


TABLES: dict[str, SyncedTable] = {
    "operators": SyncedTable(
        name="operators",
        sync_order=0,
        tombstone_order=8,
        ui_refresh_targets=_fields("operators", "clients"),
    ),
    "assets": SyncedTable(
        name="assets",
        sync_order=1,
        client_pushable=True,
        offline_creatable=True,
        tombstone_order=5,
        ownership_fields=("created_by",),
        client_push_forced_fields={"verified": 0, "confirmed_by": None},
        ui_refresh_targets=_fields("assets", "main"),
        predelete_sql=(
            "UPDATE sitreps SET asset_id = NULL WHERE asset_id = ?",
            "UPDATE assets SET mission_id = NULL WHERE id = ?",
        ),
    ),
    "sitreps": SyncedTable(
        name="sitreps",
        sync_order=2,
        client_pushable=True,
        offline_creatable=True,
        tombstone_order=4,
        encrypted_fields=_fields("body"),
        ownership_fields=("author_id",),
        ui_refresh_targets=_fields("sitrep", "main"),
    ),
    "missions": SyncedTable(
        name="missions",
        sync_order=3,
        client_pushable=True,
        offline_creatable=True,
        tombstone_order=7,
        ownership_fields=("created_by",),
        ui_refresh_targets=_fields("mission", "main"),
        predelete_sql=(
            "UPDATE sitreps SET mission_id = NULL WHERE mission_id = ?",
            "UPDATE zones SET mission_id = NULL WHERE mission_id = ?",
            "UPDATE channels SET mission_id = NULL WHERE mission_id = ?",
            "UPDATE assets SET mission_id = NULL WHERE mission_id = ?",
            "DELETE FROM waypoints WHERE mission_id = ?",
        ),
    ),
    "waypoints": SyncedTable(
        name="waypoints",
        sync_order=4,
        tombstone_order=2,
        ui_refresh_targets=_fields("mission", "main"),
    ),
    "zones": SyncedTable(
        name="zones",
        sync_order=5,
        client_pushable=True,
        offline_creatable=True,
        tombstone_order=3,
        ownership_fields=("created_by",),
        ui_refresh_targets=_fields("mission", "main"),
    ),
    "channels": SyncedTable(
        name="channels",
        sync_order=6,
        tombstone_order=1,
        ui_refresh_targets=_fields("chat"),
        predelete_sql=(
            "DELETE FROM messages WHERE channel_id = ?",
        ),
    ),
    "messages": SyncedTable(
        name="messages",
        sync_order=7,
        client_pushable=True,
        offline_creatable=True,
        tombstone_order=0,
        binary_text_fields=_fields("body"),
        ownership_fields=("sender_id",),
        ui_refresh_targets=_fields("chat"),
    ),
    "documents": SyncedTable(
        name="documents",
        sync_order=8,
        tombstone_order=6,
        redacted_fields=_fields("file_path"),
        ui_refresh_targets=_fields("documents"),
    ),
    "amendments": SyncedTable(
        name="amendments",
        syncable=False,
        ui_refresh_targets=_fields("sitrep"),
    ),
}

SYNC_TABLES: tuple[str, ...] = tuple(
    table.name
    for table in sorted(TABLES.values(), key=lambda item: item.sync_order)
    if table.syncable
)
SYNC_TABLE_ALLOWLIST: frozenset[str] = frozenset(SYNC_TABLES)
CLIENT_PUSH_TABLES: frozenset[str] = frozenset(
    table.name for table in TABLES.values() if table.client_pushable
)
OFFLINE_TABLES: tuple[str, ...] = tuple(
    table.name
    for table in sorted(TABLES.values(), key=lambda item: item.sync_order)
    if table.offline_creatable
)
TOMBSTONE_APPLY_ORDER: tuple[str, ...] = tuple(
    table.name
    for table in sorted(TABLES.values(), key=lambda item: item.tombstone_order)
    if table.syncable
)
TOMBSTONE_ORDER_MAP: dict[str, int] = {
    table: index for index, table in enumerate(TOMBSTONE_APPLY_ORDER)
}
DOCUMENTS_EXCLUDE: frozenset[str] = TABLES["documents"].redacted_fields
UI_REFRESH_TARGETS: dict[str, frozenset[str]] = {
    table.name: table.ui_refresh_targets
    for table in TABLES.values()
    if table.ui_refresh_targets
}


def get_table(name: str) -> typing.Optional[SyncedTable]:
    return TABLES.get(name)


def validated_sync_table(name: str) -> str:
    """Return *name* if it is syncable, else raise."""
    if name not in SYNC_TABLE_ALLOWLIST:
        raise ValueError(f"Table {name!r} is not in the sync allowlist - query refused.")
    return name


def is_syncable(name: str) -> bool:
    table = get_table(name)
    return bool(table and table.syncable)


def is_client_pushable(name: str) -> bool:
    table = get_table(name)
    return bool(table and table.client_pushable)


def is_offline_creatable(name: str) -> bool:
    table = get_table(name)
    return bool(table and table.offline_creatable)


def ui_refresh_targets(name: str) -> frozenset[str]:
    table = get_table(name)
    if table is None:
        return frozenset()
    return table.ui_refresh_targets


def predelete_sql(name: str) -> tuple[str, ...]:
    table = get_table(name)
    if table is None:
        return ()
    return table.predelete_sql


def serialise_record_for_wire(
    table_name: str,
    record: dict,
    db_key: bytes,
    *,
    logger=None,
) -> dict:
    """Return a JSON-safe copy of a DB record for network transport."""
    meta = _require_table(table_name)
    out = dict(record)
    for field in meta.redacted_fields:
        out.pop(field, None)
    for key, value in list(out.items()):
        if not isinstance(value, (bytes, bytearray)):
            continue
        if key in meta.encrypted_fields:
            try:
                out[key] = decrypt_field(bytes(value), db_key).decode(
                    "utf-8", errors="replace"
                )
            except Exception:
                if logger is not None:
                    logger.warning(
                        "Could not decrypt %s.%s (id=%s) - sending empty string",
                        table_name,
                        key,
                        out.get("id"),
                    )
                out[key] = ""
        else:
            out[key] = bytes(value).decode("utf-8", errors="replace")
    return out


def prepare_client_outbox_record(
    table_name: str,
    record: dict,
    db_key: bytes,
    *,
    logger=None,
) -> dict:
    """Return a client-created pending record in wire-safe form."""
    return serialise_record_for_wire(table_name, record, db_key, logger=logger)


def prepare_server_record_for_client_store(
    table_name: str,
    record: dict,
    db_key: bytes,
    *,
    logger=None,
) -> typing.Optional[dict]:
    """Convert a server wire record into the client's local DB representation."""
    meta = _require_table(table_name)
    out = dict(record)
    for field in meta.encrypted_fields:
        value = out.get(field)
        if isinstance(value, str):
            try:
                out[field] = encrypt_field(value.encode("utf-8"), db_key)
            except Exception as exc:
                if logger is not None:
                    logger.warning(
                        "Could not re-encrypt %s.%s id=%s: %s",
                        table_name,
                        field,
                        out.get("id"),
                        exc,
                    )
                return None
    for field in meta.binary_text_fields:
        value = out.get(field)
        if isinstance(value, str):
            out[field] = value.encode("utf-8")
    return out


def prepare_client_push_record_for_server_store(
    table_name: str,
    record: dict,
    *,
    uuid_value: str,
    operator_id: typing.Optional[int],
    db_key: bytes,
    logger=None,
) -> typing.Optional[dict]:
    """Normalize one client-pushed record before server insertion."""
    meta = _require_table(table_name)
    out = {
        key: value
        for key, value in record.items()
        if key not in {"id", "sync_status"}
    }
    out["uuid"] = uuid_value
    out["version"] = 1

    if operator_id is not None:
        for field in meta.ownership_fields:
            out[field] = operator_id

    for field, value in meta.client_push_forced_fields.items():
        out[field] = value

    for field in meta.encrypted_fields:
        value = out.get(field)
        if isinstance(value, str):
            try:
                out[field] = encrypt_field(value.encode("utf-8"), db_key)
            except Exception as exc:
                if logger is not None:
                    logger.warning(
                        "Client push: could not encrypt %s.%s uuid=%s: %s",
                        table_name,
                        field,
                        uuid_value,
                        exc,
                    )
                return None

    for field in meta.binary_text_fields:
        value = out.get(field)
        if isinstance(value, str):
            out[field] = value.encode("utf-8")

    return out


def _require_table(table_name: str) -> SyncedTable:
    table = get_table(table_name)
    if table is None or not table.syncable:
        raise ValueError(f"Table {table_name!r} is not in the sync registry.")
    return table

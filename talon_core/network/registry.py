"""Shared registry for synced table behavior."""
import dataclasses
import json
import time
import typing

from talon_core.constants import ASSET_CATEGORIES, SITREP_LEVELS
from talon_core.crypto.fields import decrypt_field, encrypt_field
from talon_core.zones import ZONE_TYPES


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
        sync_order=2,
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
        sync_order=7,
        client_pushable=True,
        offline_creatable=True,
        tombstone_order=4,
        encrypted_fields=_fields("body"),
        ownership_fields=("author_id",),
        ui_refresh_targets=_fields("sitrep", "main"),
    ),
    "missions": SyncedTable(
        name="missions",
        sync_order=1,
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
        sync_order=3,
        tombstone_order=2,
        ui_refresh_targets=_fields("mission", "main"),
    ),
    "zones": SyncedTable(
        name="zones",
        sync_order=4,
        client_pushable=True,
        offline_creatable=True,
        tombstone_order=3,
        ownership_fields=("created_by",),
        ui_refresh_targets=_fields("mission", "main"),
    ),
    "channels": SyncedTable(
        name="channels",
        sync_order=5,
        tombstone_order=1,
        ui_refresh_targets=_fields("chat"),
        predelete_sql=(
            "DELETE FROM messages WHERE channel_id = ?",
        ),
    ),
    "messages": SyncedTable(
        name="messages",
        sync_order=6,
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
    conn=None,
    logger=None,
) -> typing.Optional[dict]:
    """Normalize one client-pushed record before server insertion."""
    meta = _require_table(table_name)
    try:
        out = _client_push_dto(table_name, record, uuid_value, operator_id, conn)
    except ValueError as exc:
        if logger is not None:
            logger.warning(
                "Client push rejected table=%s uuid=%s: %s",
                table_name,
                uuid_value,
                exc,
            )
        return None

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


def _client_push_dto(
    table_name: str,
    record: dict,
    uuid_value: str,
    operator_id: typing.Optional[int],
    conn,
) -> dict:
    if operator_id is None:
        raise ValueError("authenticated operator context is required")
    now = int(time.time())

    if table_name == "assets":
        category = _str_field(record, "category")
        if category not in {*ASSET_CATEGORIES, "custom"}:
            raise ValueError(f"unknown asset category: {category!r}")
        label = _str_field(record, "label").strip()
        if not label:
            raise ValueError("asset label is required")
        lat = _optional_float(record.get("lat"), "lat", -90.0, 90.0)
        lon = _optional_float(record.get("lon"), "lon", -180.0, 180.0)
        return {
            "category": category,
            "label": label,
            "description": str(record.get("description") or "").strip(),
            "lat": lat,
            "lon": lon,
            "created_at": now,
            "deletion_requested": 0,
        }

    if table_name == "sitreps":
        level = _str_field(record, "level")
        if level not in SITREP_LEVELS:
            raise ValueError(f"unknown SITREP level: {level!r}")
        body = _str_field(record, "body")
        mission_id = _optional_int(record.get("mission_id"), "mission_id")
        asset_id = _optional_int(record.get("asset_id"), "asset_id")
        _require_fk(conn, "missions", mission_id)
        _require_fk(conn, "assets", asset_id)
        return {
            "level": level,
            "template": str(record.get("template") or ""),
            "body": body,
            "mission_id": mission_id,
            "asset_id": asset_id,
            "created_at": now,
        }

    if table_name == "missions":
        title = _str_field(record, "title").strip()
        if not title:
            raise ValueError("mission title is required")
        return {
            "title": title,
            "description": str(record.get("description") or "").strip(),
            "status": "pending_approval",
            "created_at": now,
            "mission_type": str(record.get("mission_type") or ""),
            "priority": str(record.get("priority") or "ROUTINE"),
            "lead_coordinator": str(record.get("lead_coordinator") or ""),
            "organization": str(record.get("organization") or ""),
            "activation_time": str(record.get("activation_time") or ""),
            "operation_window": str(record.get("operation_window") or ""),
            "max_duration": str(record.get("max_duration") or ""),
            "staging_area": str(record.get("staging_area") or ""),
            "demob_point": str(record.get("demob_point") or ""),
            "standdown_criteria": str(record.get("standdown_criteria") or ""),
            "phases": _json_text(record.get("phases"), list, "phases"),
            "constraints": _json_text(record.get("constraints"), list, "constraints"),
            "support_medical": str(record.get("support_medical") or ""),
            "support_logistics": str(record.get("support_logistics") or ""),
            "support_comms": str(record.get("support_comms") or ""),
            "support_equipment": str(record.get("support_equipment") or ""),
            "custom_resources": _json_text(
                record.get("custom_resources"),
                list,
                "custom_resources",
            ),
            "objectives": _json_text(record.get("objectives"), list, "objectives"),
            "key_locations": _json_text(
                record.get("key_locations"),
                dict,
                "key_locations",
            ),
        }

    if table_name == "zones":
        zone_type = _str_field(record, "zone_type")
        if zone_type not in (*ZONE_TYPES, "custom"):
            raise ValueError(f"unknown zone type: {zone_type!r}")
        label = _str_field(record, "label").strip()
        if not label:
            raise ValueError("zone label is required")
        polygon_text = _polygon_text(record.get("polygon"))
        mission_id = _optional_int(record.get("mission_id"), "mission_id")
        _require_fk(conn, "missions", mission_id)
        return {
            "label": label,
            "zone_type": zone_type,
            "polygon": polygon_text,
            "mission_id": mission_id,
            "created_at": now,
        }

    if table_name == "messages":
        channel_id = _required_int(record.get("channel_id"), "channel_id")
        _require_fk(conn, "channels", channel_id)
        body = _str_field(record, "body").strip()
        if not body:
            raise ValueError("message body is required")
        grid_ref = record.get("grid_ref")
        if grid_ref is not None:
            grid_ref = str(grid_ref).strip() or None
        return {
            "channel_id": channel_id,
            "body": body,
            "sent_at": now,
            "is_urgent": 1 if bool(record.get("is_urgent")) else 0,
            "grid_ref": grid_ref,
        }

    raise ValueError(f"unsupported client-push table: {table_name}")


def _str_field(record: dict, field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _required_int(value: typing.Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc


def _optional_int(value: typing.Any, field: str) -> typing.Optional[int]:
    if value is None or value == "":
        return None
    return _required_int(value, field)


def _optional_float(
    value: typing.Any,
    field: str,
    minimum: float,
    maximum: float,
) -> typing.Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{field} out of range")
    return number


def _required_float(
    value: typing.Any,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    number = _optional_float(value, field, minimum, maximum)
    if number is None:
        raise ValueError(f"{field} must be a number")
    return number


def _json_text(
    value: typing.Any,
    expected_type: type,
    field: str,
) -> str:
    if value in (None, ""):
        value = {} if expected_type is dict else []
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field} must be valid JSON") from exc
    else:
        loaded = value
    if not isinstance(loaded, expected_type):
        raise ValueError(f"{field} must be {expected_type.__name__} JSON")
    return json.dumps(loaded)


def _polygon_text(value: typing.Any) -> str:
    if isinstance(value, str):
        try:
            polygon = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("polygon must be valid JSON") from exc
    else:
        polygon = value
    if not isinstance(polygon, list) or len(polygon) < 3:
        raise ValueError("polygon requires at least three vertices")
    cleaned = []
    for index, point in enumerate(polygon):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"polygon vertex {index} must be [lat, lon]")
        lat = _required_float(point[0], f"polygon[{index}].lat", -90.0, 90.0)
        lon = _required_float(point[1], f"polygon[{index}].lon", -180.0, 180.0)
        cleaned.append([lat, lon])
    return json.dumps(cleaned)


def _require_fk(conn, table: str, record_id: typing.Optional[int]) -> None:
    if conn is None or record_id is None:
        return
    row = conn.execute(
        f"SELECT 1 FROM {validated_sync_table(table)} WHERE id = ?",
        (record_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"{table} id={record_id} does not exist")


def _require_table(table_name: str) -> SyncedTable:
    table = get_table(table_name)
    if table is None or not table.syncable:
        raise ValueError(f"Table {table_name!r} is not in the sync registry.")
    return table

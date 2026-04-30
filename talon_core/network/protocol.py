"""
TALON wire protocol — message encoding for RNS Link exchanges.

All messages are UTF-8 JSON objects with a protocol version field.  Small
messages fit in one RNS packet; larger messages are split into MSG_CHUNK
fragments by talon.network.framing and reassembled before handler dispatch.

Message flow summary
--------------------
Enrollment (client → server, one-shot link):
    client  →  enroll_request
    server  →  enroll_response   (link torn down after)

Persistent sync session (broadband — one long-lived link per client):
    client  →  sync_request      (on connect; includes last_sync_at timestamp)
    server  →  sync_response     (0..N, one record per message)
    server  →  sync_done         (includes tombstones since last_sync_at)
    --- link stays open ---
    client  →  heartbeat         (every 60 s on the same link)
    server  →  heartbeat_ack     (on same link; no teardown)
    client  →  document_request  (on-demand document fetch over the same link)
    server  →  document_response (error reply, inline base64 payload for
                                  medium files, or RNS Resource metadata for
                                  larger files)
    server  →  push_update       (any time a record is created/changed)
    server  →  push_delete       (any time a record is deleted)
    server  →  operator_revoked  (operator identity has been revoked)

LoRa fallback (polling — new link each cycle, 120 s interval):
    client  →  sync_request
    server  →  sync_response (0..N) + sync_done   (link torn down after)
    client  →  heartbeat
    server  →  heartbeat_ack                        (link torn down after)

Error (either direction, any time):
    either  →  error
"""
import json
import typing

# ---------------------------------------------------------------------------
# Message type constants
# ---------------------------------------------------------------------------

MSG_ENROLL_REQUEST  = "enroll_request"
MSG_ENROLL_RESPONSE = "enroll_response"
MSG_SYNC_REQUEST    = "sync_request"
MSG_SYNC_RESPONSE   = "sync_response"
MSG_SYNC_DONE       = "sync_done"
MSG_HEARTBEAT       = "heartbeat"
MSG_HEARTBEAT_ACK   = "heartbeat_ack"
MSG_DOCUMENT_REQUEST = "document_request"
MSG_DOCUMENT_RESPONSE = "document_response"
MSG_PUSH_UPDATE     = "push_update"   # server → client: one record changed/created
MSG_PUSH_DELETE     = "push_delete"   # server → client: one record deleted
MSG_OPERATOR_REVOKED = "operator_revoked"  # server → client: operator must lock
MSG_ERROR           = "error"
MSG_CHUNK           = "chunk"         # either direction: fragment of a large message
# Bidirectional client-push (client → server: offline records; server → client: ack)
MSG_CLIENT_PUSH_RECORDS = "client_push_records"
MSG_PUSH_ACK            = "push_ack"

PROTOCOL_VERSION = 1
ERROR_OPERATOR_INACTIVE = "operator_inactive"
ERROR_LEASE_EXPIRED = "lease_expired"

CLIENT_MESSAGE_TYPES = frozenset({
    MSG_ENROLL_REQUEST,
    MSG_SYNC_REQUEST,
    MSG_HEARTBEAT,
    MSG_DOCUMENT_REQUEST,
    MSG_CLIENT_PUSH_RECORDS,
    MSG_CHUNK,
})

SERVER_MESSAGE_TYPES = frozenset({
    MSG_ENROLL_RESPONSE,
    MSG_SYNC_RESPONSE,
    MSG_SYNC_DONE,
    MSG_HEARTBEAT_ACK,
    MSG_DOCUMENT_RESPONSE,
    MSG_PUSH_UPDATE,
    MSG_PUSH_DELETE,
    MSG_OPERATOR_REVOKED,
    MSG_PUSH_ACK,
    MSG_ERROR,
    MSG_CHUNK,
})

# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------

class ProtocolValidationError(ValueError):
    """Raised when a decoded message has an invalid wire shape."""


def encode(msg: dict) -> bytes:
    """Serialise a message dict to UTF-8 JSON bytes.

    ``version`` is injected for current wire messages when callers omit it.
    """
    if not isinstance(msg, dict):
        raise TypeError(f"Expected dict, got {type(msg).__name__}")
    wire = dict(msg)
    wire.setdefault("version", PROTOCOL_VERSION)
    return json.dumps(wire, separators=(",", ":")).encode("utf-8")


def decode(data: bytes) -> dict:
    """Deserialise UTF-8 JSON bytes to a message dict.

    Raises ValueError if *data* is not valid UTF-8 JSON or not a dict.
    """
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Protocol decode error: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object, got {type(obj).__name__}")
    return obj


def validate_client_message(msg: dict) -> dict:
    """Validate a client -> server message after ``decode()``."""
    return validate_message(msg, CLIENT_MESSAGE_TYPES, direction="client")


def validate_server_message(msg: dict) -> dict:
    """Validate a server -> client message after ``decode()``."""
    return validate_message(msg, SERVER_MESSAGE_TYPES, direction="server")


def validate_message(
    msg: dict,
    allowed_types: typing.Iterable[str],
    *,
    direction: str = "wire",
) -> dict:
    """Validate decoded message shape before handler dispatch."""
    if not isinstance(msg, dict):
        raise ProtocolValidationError(f"Expected dict, got {type(msg).__name__}")

    version = msg.get("version")
    if not _is_int(version):
        raise ProtocolValidationError("Missing or invalid protocol version")
    if version != PROTOCOL_VERSION:
        raise ProtocolValidationError(
            f"Unsupported protocol version: {version!r}"
        )

    msg_type = msg.get("type")
    if not isinstance(msg_type, str) or not msg_type:
        raise ProtocolValidationError("Missing or invalid message type")

    allowed = frozenset(allowed_types)
    if msg_type not in allowed:
        raise ProtocolValidationError(
            f"Unexpected {direction} message type: {msg_type!r}"
        )

    validator = _MESSAGE_VALIDATORS.get(msg_type)
    if validator is not None:
        validator(msg)
    return msg


def _is_int(value: typing.Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require(
    msg: dict,
    field: str,
    expected: typing.Callable[[typing.Any], bool],
    description: str,
    *,
    allow_none: bool = False,
) -> typing.Any:
    if field not in msg:
        raise ProtocolValidationError(f"{msg.get('type')}: missing {field}")
    value = msg[field]
    if allow_none and value is None:
        return value
    if not expected(value):
        raise ProtocolValidationError(
            f"{msg.get('type')}: {field} must be {description}"
        )
    return value


def _is_str(value: typing.Any) -> bool:
    return isinstance(value, str)


def _is_bool(value: typing.Any) -> bool:
    return isinstance(value, bool)


def _is_dict(value: typing.Any) -> bool:
    return isinstance(value, dict)


def _is_list(value: typing.Any) -> bool:
    return isinstance(value, list)


def _validate_enroll_request(msg: dict) -> None:
    _require(msg, "token", _is_str, "a string")
    _require(msg, "callsign", _is_str, "a string")
    if "rns_hash" in msg and not _is_str(msg.get("rns_hash")):
        raise ProtocolValidationError("enroll_request: rns_hash must be a string")


def _validate_enroll_response(msg: dict) -> None:
    _require(msg, "ok", _is_bool, "a boolean")
    _require(msg, "operator_id", _is_int, "an integer", allow_none=True)
    _require(msg, "callsign", _is_str, "a string")
    _require(
        msg,
        "lease_expires_at",
        _is_int,
        "an integer",
        allow_none=True,
    )
    _require(msg, "error", _is_str, "a string", allow_none=True)


def _validate_sync_request(msg: dict) -> None:
    if "operator_rns_hash" in msg and not _is_str(msg.get("operator_rns_hash")):
        raise ProtocolValidationError(
            "sync_request: operator_rns_hash must be a string"
        )
    version_map = _require(msg, "version_map", _is_dict, "an object")
    for table, versions in version_map.items():
        if not isinstance(table, str):
            raise ProtocolValidationError(
                "sync_request: version_map table names must be strings"
            )
        if not isinstance(versions, dict):
            raise ProtocolValidationError(
                "sync_request: version_map values must be objects"
            )
        for record_id, version in versions.items():
            if not isinstance(record_id, str) or not _is_int(version):
                raise ProtocolValidationError(
                    "sync_request: version_map entries must be string ids and integer versions"
                )
    _require(msg, "last_sync_at", _is_int, "an integer")


def _validate_sync_response(msg: dict) -> None:
    _require(msg, "table", _is_str, "a string")
    _require(msg, "record", _is_dict, "an object")


def _validate_sync_done(msg: dict) -> None:
    tombstones = _require(msg, "tombstones", _is_list, "a list")
    for item in tombstones:
        if not isinstance(item, dict):
            raise ProtocolValidationError("sync_done: tombstones must be objects")
        _require(item, "table", _is_str, "a string")
        _require(item, "record_id", _is_int, "an integer")

    server_id_sets = _require(msg, "server_id_sets", _is_dict, "an object")
    for table, record_ids in server_id_sets.items():
        if not isinstance(table, str) or not isinstance(record_ids, list):
            raise ProtocolValidationError(
                "sync_done: server_id_sets must map string tables to id lists"
            )
        if any(not _is_int(record_id) for record_id in record_ids):
            raise ProtocolValidationError(
                "sync_done: server_id_sets ids must be integers"
            )


def _validate_heartbeat(msg: dict) -> None:
    if "operator_rns_hash" in msg and not _is_str(msg.get("operator_rns_hash")):
        raise ProtocolValidationError(
            "heartbeat: operator_rns_hash must be a string"
        )


def _validate_heartbeat_ack(msg: dict) -> None:
    _require(msg, "timestamp", _is_int, "an integer")
    _require(msg, "lease_expires_at", _is_int, "an integer")


def _validate_document_request(msg: dict) -> None:
    if "operator_rns_hash" in msg and not _is_str(msg.get("operator_rns_hash")):
        raise ProtocolValidationError(
            "document_request: operator_rns_hash must be a string"
        )
    _require(msg, "document_id", _is_int, "an integer")


def _validate_document_response(msg: dict) -> None:
    _require(msg, "ok", _is_bool, "a boolean")
    _require(msg, "document_id", _is_int, "an integer")
    if (
        "error" in msg
        and msg.get("error") is not None
        and not _is_str(msg.get("error"))
    ):
        raise ProtocolValidationError("document_response: error must be a string")


def _validate_client_push_records(msg: dict) -> None:
    if "operator_rns_hash" in msg and not _is_str(msg.get("operator_rns_hash")):
        raise ProtocolValidationError(
            "client_push_records: operator_rns_hash must be a string"
        )
    records_by_table = _require(msg, "records", _is_dict, "an object")
    for table, records in records_by_table.items():
        if not isinstance(table, str):
            raise ProtocolValidationError(
                "client_push_records: table names must be strings"
            )
        if not isinstance(records, list):
            raise ProtocolValidationError(
                "client_push_records: table records must be lists"
            )
        if any(not isinstance(record, dict) for record in records):
            raise ProtocolValidationError(
                "client_push_records: records must be objects"
            )


def _validate_push_update(msg: dict) -> None:
    _require(msg, "table", _is_str, "a string")
    _require(msg, "record", _is_dict, "an object")


def _validate_push_delete(msg: dict) -> None:
    _require(msg, "table", _is_str, "a string")
    _require(msg, "record_id", _is_int, "an integer")


def _validate_operator_revoked(msg: dict) -> None:
    _require(msg, "operator_id", _is_int, "an integer")
    _require(msg, "lease_expires_at", _is_int, "an integer")
    if "version" in msg and not _is_int(msg.get("version")):
        raise ProtocolValidationError("operator_revoked: version must be an integer")
    if (
        "reason" in msg
        and msg.get("reason") is not None
        and not _is_str(msg.get("reason"))
    ):
        raise ProtocolValidationError("operator_revoked: reason must be a string")


def _validate_push_ack(msg: dict) -> None:
    accepted = _require(msg, "accepted", _is_list, "a list")
    rejected = _require(msg, "rejected", _is_list, "a list")
    if any(not isinstance(uuid_value, str) for uuid_value in accepted):
        raise ProtocolValidationError("push_ack: accepted entries must be strings")
    if any(not isinstance(item, dict) for item in rejected):
        raise ProtocolValidationError("push_ack: rejected entries must be objects")


def _validate_error(msg: dict) -> None:
    _require(msg, "message", _is_str, "a string")
    if (
        "code" in msg
        and msg.get("code") is not None
        and not _is_str(msg.get("code"))
    ):
        raise ProtocolValidationError("error: code must be a string")


def _validate_chunk(msg: dict) -> None:
    _require(msg, "id", _is_str, "a string")
    _require(msg, "seq", _is_int, "an integer")
    _require(msg, "total", _is_int, "an integer")
    _require(msg, "data", _is_str, "a string")


_MESSAGE_VALIDATORS: dict[str, typing.Callable[[dict], None]] = {
    MSG_ENROLL_REQUEST: _validate_enroll_request,
    MSG_ENROLL_RESPONSE: _validate_enroll_response,
    MSG_SYNC_REQUEST: _validate_sync_request,
    MSG_SYNC_RESPONSE: _validate_sync_response,
    MSG_SYNC_DONE: _validate_sync_done,
    MSG_HEARTBEAT: _validate_heartbeat,
    MSG_HEARTBEAT_ACK: _validate_heartbeat_ack,
    MSG_DOCUMENT_REQUEST: _validate_document_request,
    MSG_DOCUMENT_RESPONSE: _validate_document_response,
    MSG_CLIENT_PUSH_RECORDS: _validate_client_push_records,
    MSG_PUSH_UPDATE: _validate_push_update,
    MSG_PUSH_DELETE: _validate_push_delete,
    MSG_OPERATOR_REVOKED: _validate_operator_revoked,
    MSG_PUSH_ACK: _validate_push_ack,
    MSG_ERROR: _validate_error,
    MSG_CHUNK: _validate_chunk,
}

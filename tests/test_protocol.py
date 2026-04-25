"""Tests for TALON wire protocol versioning and validation."""
import configparser
import threading

import pytest

from talon.network import protocol as proto
from talon.network.client_sync import ClientSyncManager
from talon.server import net_handler


def _base(msg_type):
    return {"version": proto.PROTOCOL_VERSION, "type": msg_type}


def test_encode_injects_protocol_version():
    msg = proto.decode(proto.encode({
        "type": proto.MSG_HEARTBEAT,
        "operator_rns_hash": "abc",
    }))

    assert msg["version"] == proto.PROTOCOL_VERSION


def test_decode_does_not_validate_message_shape():
    msg = proto.decode(b'{"type":"heartbeat"}')

    assert "version" not in msg
    with pytest.raises(proto.ProtocolValidationError):
        proto.validate_client_message(msg)


@pytest.mark.parametrize(
    "msg",
    [
        {**_base(proto.MSG_ENROLL_REQUEST), "token": 123, "callsign": "A", "rns_hash": "h"},
        {**_base(proto.MSG_ENROLL_REQUEST), "token": "t", "callsign": ["A"], "rns_hash": "h"},
        {**_base(proto.MSG_ENROLL_REQUEST), "token": "t", "callsign": "A", "rns_hash": None},
    ],
)
def test_rejects_malformed_enroll_request(msg):
    with pytest.raises(proto.ProtocolValidationError):
        proto.validate_client_message(msg)


@pytest.mark.parametrize(
    "msg",
    [
        {**_base(proto.MSG_SYNC_REQUEST), "operator_rns_hash": 1, "version_map": {}, "last_sync_at": 0},
        {**_base(proto.MSG_SYNC_REQUEST), "operator_rns_hash": "h", "version_map": [], "last_sync_at": 0},
        {
            **_base(proto.MSG_SYNC_REQUEST),
            "operator_rns_hash": "h",
            "version_map": {"assets": {"1": "2"}},
            "last_sync_at": 0,
        },
        {**_base(proto.MSG_SYNC_REQUEST), "operator_rns_hash": "h", "version_map": {}, "last_sync_at": "0"},
    ],
)
def test_rejects_malformed_sync_request(msg):
    with pytest.raises(proto.ProtocolValidationError):
        proto.validate_client_message(msg)


@pytest.mark.parametrize(
    "msg",
    [
        {**_base(proto.MSG_HEARTBEAT), "operator_rns_hash": 123},
        {**_base(proto.MSG_HEARTBEAT)},
    ],
)
def test_rejects_malformed_heartbeat(msg):
    with pytest.raises(proto.ProtocolValidationError):
        proto.validate_client_message(msg)


@pytest.mark.parametrize(
    "msg",
    [
        {**_base(proto.MSG_CLIENT_PUSH_RECORDS), "operator_rns_hash": "h", "records": []},
        {**_base(proto.MSG_CLIENT_PUSH_RECORDS), "operator_rns_hash": "h", "records": {1: []}},
        {**_base(proto.MSG_CLIENT_PUSH_RECORDS), "operator_rns_hash": "h", "records": {"assets": {}}},
        {**_base(proto.MSG_CLIENT_PUSH_RECORDS), "operator_rns_hash": "h", "records": {"assets": ["bad"]}},
    ],
)
def test_rejects_malformed_client_push_records(msg):
    with pytest.raises(proto.ProtocolValidationError):
        proto.validate_client_message(msg)


@pytest.mark.parametrize(
    "msg",
    [
        {**_base(proto.MSG_PUSH_UPDATE), "table": 1, "record": {}},
        {**_base(proto.MSG_PUSH_UPDATE), "table": "assets", "record": []},
        {**_base(proto.MSG_PUSH_UPDATE), "table": "assets"},
    ],
)
def test_rejects_malformed_push_update(msg):
    with pytest.raises(proto.ProtocolValidationError):
        proto.validate_server_message(msg)


@pytest.mark.parametrize(
    "msg",
    [
        {**_base(proto.MSG_PUSH_DELETE), "table": 1, "record_id": 1},
        {**_base(proto.MSG_PUSH_DELETE), "table": "assets", "record_id": "1"},
        {**_base(proto.MSG_PUSH_DELETE), "table": "assets"},
    ],
)
def test_rejects_malformed_push_delete(msg):
    with pytest.raises(proto.ProtocolValidationError):
        proto.validate_server_message(msg)


@pytest.mark.parametrize(
    "msg",
    [
        {**_base(proto.MSG_OPERATOR_REVOKED), "operator_id": "1", "lease_expires_at": 1},
        {**_base(proto.MSG_OPERATOR_REVOKED), "operator_id": 1, "lease_expires_at": "1"},
        {**_base(proto.MSG_OPERATOR_REVOKED), "operator_id": 1, "lease_expires_at": 1, "version": "2"},
    ],
)
def test_rejects_malformed_operator_revoked(msg):
    with pytest.raises(proto.ProtocolValidationError):
        proto.validate_server_message(msg)


def test_error_accepts_operator_inactive_code():
    msg = {
        **_base(proto.MSG_ERROR),
        "message": "Operator not found or revoked",
        "code": proto.ERROR_OPERATOR_INACTIVE,
    }

    assert proto.validate_server_message(msg) is msg


def test_server_rejects_invalid_payload_before_handler_dispatch(tmp_db, test_key, monkeypatch):
    conn, _ = tmp_db
    handler = net_handler.ServerNetHandler(conn, configparser.ConfigParser(), test_key)
    called = threading.Event()
    errors = []
    teardowns = []
    link = object()

    monkeypatch.setattr(handler, "_handle_enroll", lambda *_args: called.set())
    monkeypatch.setattr(net_handler, "_send_error", lambda _link, message: errors.append(message))
    monkeypatch.setattr(net_handler, "_teardown", lambda _link: teardowns.append(_link))

    handler._on_packet(
        link,
        proto.encode({
            "type": proto.MSG_ENROLL_REQUEST,
            "token": 123,
            "callsign": "BAD",
            "rns_hash": "a" * 64,
        }),
        None,
    )

    assert not called.is_set()
    assert errors
    assert teardowns == [link]


def test_client_rejects_invalid_payload_before_handler_dispatch(tmp_db, test_key, monkeypatch):
    conn, _ = tmp_db
    manager = ClientSyncManager(conn, configparser.ConfigParser(), test_key)
    called = threading.Event()

    monkeypatch.setattr(manager, "_apply_record", lambda *_args: called.set())

    manager._handle_incoming(
        {
            "version": proto.PROTOCOL_VERSION,
            "type": proto.MSG_PUSH_UPDATE,
            "table": "assets",
            "record": "not-a-record",
        },
        threading.Event(),
    )

    assert not called.is_set()

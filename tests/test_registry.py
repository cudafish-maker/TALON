"""Tests for synced table registry metadata."""
import configparser
import uuid

from talon.crypto.fields import decrypt_field, encrypt_field
from talon.network import protocol as proto
from talon.network import registry
from talon.server import net_handler


class _FakeIdentity:
    def __init__(self, hash_hex: str) -> None:
        self.hash = bytes.fromhex(hash_hex)


class _FakeLink:
    def __init__(self, hash_hex: str) -> None:
        self._identity = _FakeIdentity(hash_hex)

    def get_remote_identity(self):
        return self._identity

    def teardown(self) -> None:
        return None


def test_registry_exposes_current_sync_sets():
    assert registry.SYNC_TABLES == (
        "operators",
        "missions",
        "assignments",
        "assets",
        "waypoints",
        "zones",
        "channels",
        "messages",
        "documents",
        "sitreps",
        "sitrep_followups",
        "sitrep_documents",
        "checkins",
    )
    assert registry.CLIENT_PUSH_TABLES == {
        "assets",
        "sitreps",
        "missions",
        "messages",
        "zones",
        "assignments",
        "checkins",
        "sitrep_followups",
        "sitrep_documents",
    }
    assert registry.OFFLINE_TABLES == (
        "missions",
        "assignments",
        "assets",
        "zones",
        "messages",
        "sitreps",
        "sitrep_followups",
        "sitrep_documents",
        "checkins",
    )
    assert registry.TOMBSTONE_APPLY_ORDER == (
        "messages",
        "channels",
        "waypoints",
        "zones",
        "checkins",
        "sitrep_documents",
        "sitrep_followups",
        "sitreps",
        "assets",
        "documents",
        "assignments",
        "missions",
        "operators",
    )


def test_registry_captures_table_metadata():
    documents = registry.get_table("documents")
    sitreps = registry.get_table("sitreps")
    messages = registry.get_table("messages")
    assets = registry.get_table("assets")
    assignments = registry.get_table("assignments")
    checkins = registry.get_table("checkins")
    sitrep_followups = registry.get_table("sitrep_followups")
    sitrep_documents = registry.get_table("sitrep_documents")

    assert documents.redacted_fields == {"file_path"}
    assert sitreps.encrypted_fields == {"body"}
    assert messages.binary_text_fields == {"body"}
    assert messages.ownership_fields == ("sender_id",)
    assert assets.ownership_fields == ("created_by",)
    assert assignments.ownership_fields == ("created_by",)
    assert checkins.ownership_fields == ("operator_id",)
    assert sitrep_followups.ownership_fields == ("author_id",)
    assert sitrep_documents.ownership_fields == ("created_by",)
    assert assets.client_push_forced_fields == {"verified": 0, "confirmed_by": None}
    assert registry.ui_refresh_targets("sitreps") == {"sitrep", "map", "main"}
    assert registry.ui_refresh_targets("missions") == {"mission", "main"}
    assert registry.ui_refresh_targets("assignments") == {
        "assignments",
        "mission",
        "map",
        "main",
    }
    assert registry.ui_refresh_targets("sitrep_followups") == {"sitrep", "map", "main"}
    assert registry.ui_refresh_targets("sitrep_documents") == {
        "sitrep",
        "documents",
        "main",
    }
    assert registry.ui_refresh_targets("amendments") == {"sitrep"}


def test_registry_validated_sync_table_blocks_unsupported_table():
    assert registry.validated_sync_table("assets") == "assets"

    try:
        registry.validated_sync_table("audit_log")
    except ValueError as exc:
        assert "sync allowlist" in str(exc)
    else:
        raise AssertionError("audit_log should not be syncable")


def test_registry_wire_transforms_redact_and_encode_fields(test_key):
    document = registry.serialise_record_for_wire(
        "documents",
        {"id": 1, "filename": "ops.pdf", "file_path": "internal.bin"},
        test_key,
    )
    message = registry.serialise_record_for_wire(
        "messages",
        {"id": 2, "body": b"hello"},
        test_key,
    )

    assert "file_path" not in document
    assert message["body"] == "hello"


def test_registry_wire_transforms_round_trip_encrypted_sitrep_body(test_key):
    encrypted = encrypt_field(b"encrypted body", test_key)

    wire = registry.serialise_record_for_wire(
        "sitreps",
        {"id": 3, "body": encrypted},
        test_key,
    )
    stored = registry.prepare_server_record_for_client_store(
        "sitreps",
        wire,
        test_key,
    )

    assert wire["body"] == "encrypted body"
    assert decrypt_field(stored["body"], test_key) == b"encrypted body"


def test_registry_wire_transforms_encode_message_body_for_client_store(test_key):
    stored = registry.prepare_server_record_for_client_store(
        "messages",
        {"id": 4, "body": "plain text"},
        test_key,
    )

    assert stored["body"] == b"plain text"


def test_registry_wire_transforms_encode_message_body_for_server_store(test_key):
    stored = registry.prepare_client_push_record_for_server_store(
        "messages",
        {
            "id": 4,
            "uuid": "a" * 32,
            "channel_id": 10,
            "body": "plain text",
            "sender_id": 999,
        },
        uuid_value="a" * 32,
        operator_id=7,
        db_key=test_key,
    )

    assert stored["body"] == b"plain text"
    assert stored["sender_id"] == 7


def test_server_notifications_ignore_unsupported_tables(tmp_db, test_key):
    conn, _ = tmp_db
    handler = net_handler.ServerNetHandler(conn, configparser.ConfigParser(), test_key)

    handler.notify_change("audit_log", 1)
    handler.notify_delete("audit_log", 1)

    tombstone = conn.execute(
        "SELECT id FROM deleted_records WHERE table_name = 'audit_log'"
    ).fetchone()
    assert handler._push_buffer == {}
    assert tombstone is None


def test_server_client_push_rejects_syncable_but_not_client_pushable_table(
    tmp_db,
    test_key,
    monkeypatch,
):
    conn, _ = tmp_db
    operator_hash = "c" * 64
    conn.execute(
        "INSERT INTO operators (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
        "VALUES (7, 'CLIENT3', ?, '[]', '{}', 1000, 9999999999, 0)",
        (operator_hash,),
    )
    conn.commit()

    sent = []
    monkeypatch.setattr(
        net_handler,
        "_smart_send",
        lambda _link, data: sent.append(proto.decode(data)),
    )
    handler = net_handler.ServerNetHandler(conn, configparser.ConfigParser(), test_key)
    handler.notify_change = lambda _table, _record_id: None

    channel_uuid = uuid.uuid4().hex
    handler._handle_client_push(_FakeLink(operator_hash), {
        "records": {
            "channels": [{
                "uuid": channel_uuid,
                "name": "#not-allowed",
                "mission_id": None,
                "is_dm": 0,
                "version": 1,
            }],
        },
    })

    row = conn.execute("SELECT id FROM channels WHERE uuid = ?", (channel_uuid,)).fetchone()
    assert row is None
    assert sent[-1]["accepted"] == []

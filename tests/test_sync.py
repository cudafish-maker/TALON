"""Tests for talon.network.sync."""
import base64
import configparser
import hashlib
import threading
import time
import uuid

import pytest

from talon.db.connection import close_db, open_db
from talon.db.migrations import apply_migrations
from talon.documents import DocumentError, cache_document_download
from talon.network import protocol as proto
from talon.network import registry
from talon.network.client_sync import ClientSyncManager
from talon.network.sync import SyncEngine, _validated_table
from talon.server import net_components, net_handler
from talon.services.assets import request_asset_deletion_command, verify_asset_command
from talon.services.operators import revoke_operator_command
from talon_core.community_safety import create_assignment, list_assignments
from talon.constants import (
    HEARTBEAT_BROADBAND_S,
    HEARTBEAT_LORA_S,
    MAX_DOCUMENT_SIZE_BYTES,
)


class _NoOpTimer:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def start(self) -> None:
        return None


class _FakeIdentity:
    def __init__(self, hash_hex: str) -> None:
        self.hash = bytes.fromhex(hash_hex)


class _FakeLink:
    def __init__(self, hash_hex: str) -> None:
        self._identity = _FakeIdentity(hash_hex)
        self.torn_down = False

    def get_remote_identity(self):
        return self._identity

    def teardown(self) -> None:
        self.torn_down = True


class _FakeResource:
    def __init__(self, doc_id: int, size: int) -> None:
        self.metadata = {
            "type": proto.MSG_DOCUMENT_RESPONSE,
            "record": {"id": doc_id},
        }
        self._size = size

    def get_data_size(self) -> int:
        return self._size


def _open_test_db(tmp_path, name: str, key: bytes):
    conn = open_db(tmp_path / name, key)
    apply_migrations(conn)
    return conn


def _insert_operator(conn, operator_id: int, callsign: str, rns_hash: str) -> None:
    conn.execute(
        "INSERT INTO operators (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
        "VALUES (?, ?, ?, '[]', '{}', 1000, 9999999999, 0)",
        (operator_id, callsign, rns_hash),
    )


def _make_client_manager(conn, test_key: bytes, operator_id: int) -> ClientSyncManager:
    manager = ClientSyncManager(conn, configparser.ConfigParser(), test_key)
    manager._operator_id = operator_id
    return manager


def _insert_document_row(
    conn,
    *,
    doc_id: int,
    filename: str,
    plaintext: bytes,
    version: int = 1,
) -> str:
    sha256_hash = hashlib.sha256(plaintext).hexdigest()
    conn.execute(
        "INSERT INTO documents "
        "(id, filename, mime_type, size_bytes, sha256_hash, description, "
        "uploaded_by, uploaded_at, version) "
        "VALUES (?, ?, 'text/plain', ?, ?, '', 1, 1000, ?)",
        (doc_id, filename, len(plaintext), sha256_hash, version),
    )
    conn.commit()
    return sha256_hash


# ---------------------------------------------------------------------------
# Interval / start-stop
# ---------------------------------------------------------------------------

class TestSyncEngine:
    def test_broadband_interval(self):
        engine = SyncEngine(is_lora=False)
        assert engine._interval == HEARTBEAT_BROADBAND_S

    def test_lora_interval(self):
        engine = SyncEngine(is_lora=True)
        assert engine._interval == HEARTBEAT_LORA_S

    def test_heartbeat_fires(self):
        fired = threading.Event()
        engine = SyncEngine(is_lora=False, on_heartbeat=fired.set)
        engine._interval = 0  # fire immediately for test
        engine.start()
        assert fired.wait(timeout=2)
        engine.stop()

    def test_start_stop_idempotent(self):
        engine = SyncEngine()
        engine.start()
        engine.start()  # second start should not raise
        engine.stop()
        engine.stop()   # second stop should not raise


# ---------------------------------------------------------------------------
# apply_server_record — version comparison (no DB needed)
# ---------------------------------------------------------------------------

class TestApplyServerRecordVersionLogic:
    def test_skips_older_version(self):
        result = SyncEngine.apply_server_record(
            conn=None,
            table="assets",
            record={"id": 1, "version": 2},
            local_version=3,  # local is newer — skip
        )
        assert result is False

    def test_skips_same_version(self):
        result = SyncEngine.apply_server_record(
            conn=None,
            table="assets",
            record={"id": 1, "version": 3},
            local_version=3,
        )
        assert result is False

    def test_applies_newer(self):
        result = SyncEngine.apply_server_record(
            conn=None,
            table="assets",
            record={"id": 1, "version": 5},
            local_version=3,
        )
        assert result is True

    def test_applies_when_no_local(self):
        result = SyncEngine.apply_server_record(
            conn=None,
            table="assets",
            record={"id": 99, "version": 1},
            local_version=None,
        )
        assert result is True


# ---------------------------------------------------------------------------
# Table allowlist guard
# ---------------------------------------------------------------------------

class TestValidatedTable:
    def test_valid_table_passes(self):
        assert _validated_table("assets") == "assets"

    def test_invalid_table_raises(self):
        with pytest.raises(ValueError, match="sync allowlist"):
            _validated_table("audit_log")

    def test_sql_injection_attempt_raises(self):
        with pytest.raises(ValueError):
            _validated_table("assets; DROP TABLE operators")


# ---------------------------------------------------------------------------
# _upsert_record — real DB operations
# ---------------------------------------------------------------------------

class TestUpsertRecord:
    def test_inserts_new_asset(self, tmp_db):
        conn, _ = tmp_db
        record = {
            "id": 42,
            "category": "cache",
            "label": "Test Cache",
            "description": "Sync test",
            "lat": 51.5,
            "lon": -0.1,
            "verified": 0,
            "created_by": 1,
            "confirmed_by": None,
            "created_at": 1000,
            "version": 1,
        }
        SyncEngine._upsert_record(conn, "assets", record)
        row = conn.execute("SELECT label FROM assets WHERE id = 42").fetchone()
        assert row is not None
        assert row[0] == "Test Cache"

    def test_replaces_existing_asset(self, tmp_db):
        conn, _ = tmp_db
        # Insert initial row
        conn.execute(
            "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version) "
            "VALUES (10, 'vehicle', 'Old Label', '', 0, 1, 1000, 1)"
        )
        conn.commit()
        # Upsert with updated label + version
        SyncEngine._upsert_record(conn, "assets", {
            "id": 10, "category": "vehicle", "label": "New Label",
            "description": "", "verified": 0, "created_by": 1,
            "created_at": 1000, "version": 2,
        })
        row = conn.execute("SELECT label, version FROM assets WHERE id = 10").fetchone()
        assert row[0] == "New Label"
        assert row[1] == 2

    def test_updates_in_place_preserving_child_rows(self, tmp_db):
        conn, _ = tmp_db
        conn.execute(
            "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version) "
            "VALUES (10, 'vehicle', 'Old Label', '', 0, 1, 1000, 1)"
        )
        conn.execute(
            "INSERT INTO sitreps (id, level, template, body, author_id, asset_id, created_at, version) "
            "VALUES (20, 'ROUTINE', '', ?, 1, 10, 1001, 1)",
            (b"body",),
        )
        conn.commit()

        SyncEngine._upsert_record(conn, "assets", {
            "id": 10, "category": "vehicle", "label": "New Label",
            "description": "", "verified": 0, "created_by": 1,
            "created_at": 1000, "version": 2,
        })

        row = conn.execute("SELECT label, version FROM assets WHERE id = 10").fetchone()
        child = conn.execute("SELECT asset_id FROM sitreps WHERE id = 20").fetchone()
        assert row == ("New Label", 2)
        assert child[0] == 10

    def test_insert_without_id_allocates_new_row(self, tmp_db):
        conn, _ = tmp_db
        conn.execute(
            "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version) "
            "VALUES (1, 'cache', 'Server Asset', '', 0, 1, 1000, 1)"
        )
        conn.commit()

        pushed_uuid = uuid.uuid4().hex
        SyncEngine._upsert_record(conn, "assets", {
            "uuid": pushed_uuid,
            "category": "cache",
            "label": "Client Asset",
            "description": "",
            "verified": 0,
            "created_by": 1,
            "created_at": 1001,
            "version": 1,
        })

        original = conn.execute("SELECT label FROM assets WHERE id = 1").fetchone()
        inserted = conn.execute("SELECT id, label FROM assets WHERE uuid = ?", (pushed_uuid,)).fetchone()
        assert original[0] == "Server Asset"
        assert inserted[0] != 1
        assert inserted[1] == "Client Asset"

    def test_ignores_unknown_columns(self, tmp_db):
        conn, _ = tmp_db
        # Extra key "injected_col" is not a real column and must be silently dropped.
        record = {
            "id": 55,
            "category": "person",
            "label": "Agent Smith",
            "description": "",
            "verified": 0,
            "created_by": 1,
            "created_at": 1000,
            "version": 1,
            "injected_col": "evil",
        }
        SyncEngine._upsert_record(conn, "assets", record)
        row = conn.execute("SELECT label FROM assets WHERE id = 55").fetchone()
        assert row[0] == "Agent Smith"

    def test_raises_on_invalid_table(self, tmp_db):
        conn, _ = tmp_db
        with pytest.raises(ValueError, match="sync allowlist"):
            SyncEngine._upsert_record(conn, "audit_log", {"id": 1})

    def test_raises_when_no_valid_columns(self, tmp_db):
        conn, _ = tmp_db
        with pytest.raises(ValueError, match="no valid columns"):
            SyncEngine._upsert_record(conn, "assets", {"not_a_col": "x"})


class TestClientDocumentCacheSync:
    def test_apply_record_invalidates_stale_cached_document(
        self,
        tmp_db,
        test_key,
        tmp_path,
    ):
        conn, _ = tmp_db
        storage_root = tmp_path / "client-docs"
        old_plaintext = b"old cached content"
        old_hash = _insert_document_row(
            conn,
            doc_id=31,
            filename="brief.txt",
            plaintext=old_plaintext,
        )
        cached = cache_document_download(
            conn,
            test_key,
            storage_root,
            31,
            old_plaintext,
        )
        cached_path = storage_root / cached.file_path
        assert cached_path.exists()

        manager = _make_client_manager(conn, test_key, operator_id=1)
        manager._cfg.read_dict({"documents": {"storage_path": str(storage_root)}})

        new_plaintext = b"new server content"
        new_hash = hashlib.sha256(new_plaintext).hexdigest()
        assert new_hash != old_hash

        manager._apply_record(
            "documents",
            {
                "id": 31,
                "filename": "brief.txt",
                "mime_type": "text/plain",
                "size_bytes": len(new_plaintext),
                "sha256_hash": new_hash,
                "description": "",
                "uploaded_by": 1,
                "uploaded_at": 1000,
                "version": 2,
            },
            badge=False,
        )

        row = conn.execute(
            "SELECT file_path, sha256_hash, version FROM documents WHERE id = 31"
        ).fetchone()
        assert row == ("", new_hash, 2)
        assert not cached_path.exists()

    def test_apply_delete_removes_cached_document_file(
        self,
        tmp_db,
        test_key,
        tmp_path,
    ):
        conn, _ = tmp_db
        storage_root = tmp_path / "client-docs"
        plaintext = b"cached document"
        _insert_document_row(
            conn,
            doc_id=32,
            filename="cache.txt",
            plaintext=plaintext,
        )
        cached = cache_document_download(
            conn,
            test_key,
            storage_root,
            32,
            plaintext,
        )
        cached_path = storage_root / cached.file_path
        assert cached_path.exists()

        manager = _make_client_manager(conn, test_key, operator_id=1)
        manager._cfg.read_dict({"documents": {"storage_path": str(storage_root)}})

        manager._apply_delete("documents", 32, badge=False)

        assert conn.execute(
            "SELECT 1 FROM documents WHERE id = 32"
        ).fetchone() is None
        assert not cached_path.exists()

    def test_inline_document_response_caches_payload(
        self,
        tmp_db,
        test_key,
        tmp_path,
    ):
        conn, _ = tmp_db
        storage_root = tmp_path / "client-docs"
        manager = _make_client_manager(conn, test_key, operator_id=1)
        manager._cfg.read_dict({"documents": {"storage_path": str(storage_root)}})
        plaintext = b"x" * 254_000
        sha256_hash = hashlib.sha256(plaintext).hexdigest()
        state = {
            "event": threading.Event(),
            "payload": None,
            "error": None,
        }
        manager._pending_document_requests[33] = state

        manager._document_transfers.handle_response(
            {
                "type": proto.MSG_DOCUMENT_RESPONSE,
                "ok": True,
                "document_id": 33,
                "record": {
                    "id": 33,
                    "filename": "field-map.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": len(plaintext),
                    "sha256_hash": sha256_hash,
                    "folder_path": "Plans",
                    "description": "",
                    "uploaded_by": 1,
                    "uploaded_at": 1000,
                    "version": 1,
                },
                "encoding": "base64",
                "payload": base64.b64encode(plaintext).decode("ascii"),
            }
        )

        assert state["event"].is_set()
        assert state["payload"] == plaintext
        row = conn.execute(
            "SELECT filename, folder_path, file_path FROM documents WHERE id = 33"
        ).fetchone()
        assert row[0:2] == ("field-map.pdf", "Plans")
        assert (storage_root / row[2]).exists()


# ---------------------------------------------------------------------------
# apply_server_record — with real DB
# ---------------------------------------------------------------------------

class TestApplyServerRecordWithDB:
    def test_upserts_when_newer(self, tmp_db):
        conn, _ = tmp_db
        conn.execute(
            "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version) "
            "VALUES (77, 'rally_point', 'Old', '', 0, 1, 1000, 1)"
        )
        conn.commit()
        result = SyncEngine.apply_server_record(
            conn=conn,
            table="assets",
            record={
                "id": 77, "category": "rally_point", "label": "Updated",
                "description": "", "verified": 0, "created_by": 1,
                "created_at": 1000, "version": 3,
            },
            local_version=1,
        )
        assert result is True
        row = conn.execute("SELECT label, version FROM assets WHERE id = 77").fetchone()
        assert row[0] == "Updated"
        assert row[1] == 3

    def test_skips_when_current(self, tmp_db):
        conn, _ = tmp_db
        result = SyncEngine.apply_server_record(
            conn=conn,
            table="assets",
            record={"id": 1, "version": 2},
            local_version=2,
        )
        assert result is False


# ---------------------------------------------------------------------------
# Lease checking
# ---------------------------------------------------------------------------

class TestLeaseCheck:
    def _make_engine(self, conn, operator_id, on_expired=None, on_renewed=None):
        return SyncEngine(
            conn=conn,
            operator_id=operator_id,
            on_lease_expired=on_expired,
            on_lease_renewed=on_renewed,
        )

    def test_valid_lease_no_callback(self, tmp_db):
        conn, _ = tmp_db
        fired = threading.Event()
        engine = self._make_engine(conn, operator_id=1, on_expired=fired.set)
        # SERVER sentinel has lease_expires_at = 9999999999 — should not fire
        engine._check_lease()
        assert not fired.is_set()

    def test_expired_lease_fires_on_expired(self, tmp_db):
        conn, _ = tmp_db
        # Insert an operator with an already-expired lease
        conn.execute(
            "INSERT INTO operators (id, callsign, rns_hash, skills, profile, "
            "enrolled_at, lease_expires_at, revoked) "
            "VALUES (99, 'EXPIRED', 'hash-expired', '[]', '{}', 0, 1, 0)"
        )
        conn.commit()
        fired = threading.Event()
        engine = self._make_engine(conn, operator_id=99, on_expired=fired.set)
        engine._check_lease()
        assert fired.is_set()
        assert engine._locked is True

    def test_expired_lease_only_fires_once(self, tmp_db):
        conn, _ = tmp_db
        conn.execute(
            "INSERT INTO operators (id, callsign, rns_hash, skills, profile, "
            "enrolled_at, lease_expires_at, revoked) "
            "VALUES (98, 'EXP2', 'hash-exp2', '[]', '{}', 0, 1, 0)"
        )
        conn.commit()
        call_count = [0]
        def _counter():
            call_count[0] += 1
        engine = self._make_engine(conn, operator_id=98, on_expired=_counter)
        engine._check_lease()
        engine._check_lease()  # second call — already locked, should not fire again
        assert call_count[0] == 1

    def test_revoked_operator_fires_on_expired(self, tmp_db):
        conn, _ = tmp_db
        conn.execute(
            "INSERT INTO operators (id, callsign, rns_hash, skills, profile, "
            "enrolled_at, lease_expires_at, revoked) "
            "VALUES (97, 'REVOKED_OP', 'hash-rev', '[]', '{}', 0, 9999999999, 1)"
        )
        conn.commit()
        fired = threading.Event()
        engine = self._make_engine(conn, operator_id=97, on_expired=fired.set)
        engine._check_lease()
        assert fired.is_set()

    def test_renewal_fires_on_renewed(self, tmp_db):
        conn, _ = tmp_db
        # Start expired
        conn.execute(
            "INSERT INTO operators (id, callsign, rns_hash, skills, profile, "
            "enrolled_at, lease_expires_at, revoked) "
            "VALUES (96, 'RENEWED_OP', 'hash-ren', '[]', '{}', 0, 1, 0)"
        )
        conn.commit()
        renewed = threading.Event()
        engine = self._make_engine(conn, operator_id=96, on_renewed=renewed.set)
        engine._locked = True  # simulate we're already on the lock screen
        # Now update the lease to be valid
        conn.execute(
            "UPDATE operators SET lease_expires_at = 9999999999 WHERE id = 96"
        )
        conn.commit()
        engine._check_lease()
        assert renewed.is_set()
        assert engine._locked is False

    def test_no_conn_is_noop(self):
        fired = threading.Event()
        engine = SyncEngine(on_lease_expired=fired.set)
        engine._check_lease()  # should not raise or fire
        assert not fired.is_set()

    def test_set_operator_id_updates_monitored_operator(self, tmp_db):
        conn, _ = tmp_db
        conn.execute(
            "INSERT INTO operators (id, callsign, rns_hash, skills, profile, "
            "enrolled_at, lease_expires_at, revoked) "
            "VALUES (95, 'SET_OP', 'hash-set-op', '[]', '{}', 0, 1, 0)"
        )
        conn.commit()
        fired = threading.Event()
        engine = self._make_engine(conn, operator_id=None, on_expired=fired.set)
        engine.set_operator_id(95)
        assert engine._operator_id == 95
        assert fired.is_set()


# ---------------------------------------------------------------------------
# Chunk handling
# ---------------------------------------------------------------------------

class TestChunkHandling:
    def test_server_rejects_out_of_range_chunk_without_raising(self, tmp_db, test_key):
        conn, _ = tmp_db
        handler = net_handler.ServerNetHandler(conn, configparser.ConfigParser(), test_key)
        msg = {
            "id": "bad",
            "seq": 99,
            "total": 1,
            "data": base64.b64encode(b"x").decode(),
        }
        assert handler._handle_chunk_data(msg) is None
        assert handler._chunk_buffers == {}

    def test_client_rejects_out_of_range_chunk_without_raising(self, tmp_db, test_key):
        conn, _ = tmp_db
        mgr = ClientSyncManager(conn, configparser.ConfigParser(), test_key)
        msg = {
            "id": "bad",
            "seq": 99,
            "total": 1,
            "data": base64.b64encode(b"x").decode(),
        }
        assert mgr._handle_chunk_data(msg) is None
        assert mgr._chunk_buffers == {}

    def test_server_chunk_buffer_cap_drops_oldest(self, tmp_db, test_key):
        conn, _ = tmp_db
        handler = net_handler.ServerNetHandler(conn, configparser.ConfigParser(), test_key)
        for idx in range(net_handler._CHUNK_MAX_BUFFERS + 1):
            handler._handle_chunk_data({
                "id": f"chunk-{idx}",
                "seq": 0,
                "total": 2,
                "data": base64.b64encode(b"x").decode(),
            })
        assert len(handler._chunk_buffers) == net_handler._CHUNK_MAX_BUFFERS
        assert "chunk-0" not in handler._chunk_buffers


# ---------------------------------------------------------------------------
# Server client-push hardening
# ---------------------------------------------------------------------------

class TestServerClientPush:
    def test_expired_operator_heartbeat_is_rejected_without_auto_renew(
        self, tmp_db, test_key, monkeypatch
    ):
        conn, _ = tmp_db
        operator_hash = "9" * 64
        expired_at = int(time.time()) - 10
        conn.execute(
            "INSERT INTO operators (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
            "VALUES (70, 'EXPIRED', ?, '[]', '{}', 1000, ?, 0)",
            (operator_hash, expired_at),
        )
        conn.commit()

        sent = []
        handler = net_handler.ServerNetHandler(conn, configparser.ConfigParser(), test_key)
        handler._send_error = lambda _link, message, **extra: sent.append(
            {"message": message, **extra}
        )
        link = _FakeLink(operator_hash)

        handler._handle_heartbeat(link, {"type": proto.MSG_HEARTBEAT})

        row = conn.execute(
            "SELECT lease_expires_at, revoked FROM operators WHERE id = 70"
        ).fetchone()
        assert row == (expired_at, 0)
        assert sent[-1]["code"] == proto.ERROR_LEASE_EXPIRED
        assert sent[-1]["lease_expires_at"] == expired_at
        assert link.torn_down is True

    def test_valid_near_expiry_heartbeat_auto_renews(
        self, tmp_db, test_key, monkeypatch
    ):
        conn, _ = tmp_db
        operator_hash = "8" * 64
        near_expiry = int(time.time()) + 120
        conn.execute(
            "INSERT INTO operators (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
            "VALUES (71, 'RENEW', ?, '[]', '{}', 1000, ?, 0)",
            (operator_hash, near_expiry),
        )
        conn.commit()

        sent = []
        monkeypatch.setattr(
            net_handler,
            "_smart_send",
            lambda _link, data: sent.append(proto.decode(data)),
        )
        handler = net_handler.ServerNetHandler(conn, configparser.ConfigParser(), test_key)

        handler._handle_heartbeat(_FakeLink(operator_hash), {"type": proto.MSG_HEARTBEAT})

        row = conn.execute(
            "SELECT lease_expires_at FROM operators WHERE id = 71"
        ).fetchone()
        assert row[0] > near_expiry
        assert sent[-1]["type"] == proto.MSG_HEARTBEAT_ACK
        assert sent[-1]["lease_expires_at"] == row[0]

    def test_new_client_message_is_accepted_and_notifies_server_ui(
        self, tmp_db, test_key, monkeypatch
    ):
        conn, _ = tmp_db
        operator_hash = "d" * 64
        conn.execute(
            "INSERT INTO operators (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
            "VALUES (8, 'CHATTER', ?, '[]', '{}', 1000, 9999999999, 0)",
            (operator_hash,),
        )
        conn.execute(
            "INSERT INTO channels (id, name, mission_id, is_dm, version, group_type) "
            "VALUES (10, '#general', NULL, 0, 1, 'allhands')"
        )
        conn.execute(
            "INSERT INTO messages (id, channel_id, sender_id, body, sent_at, version, uuid) "
            "VALUES (1, 10, 1, ?, 1000, 1, ?)",
            (b"server already here", "e" * 32),
        )
        conn.commit()

        sent = []
        notified = []
        ui_notified = []
        monkeypatch.setattr(
            net_handler,
            "_smart_send",
            lambda _link, data: sent.append(proto.decode(data)),
        )
        monkeypatch.setattr(net_handler, "_notify_ui", lambda table: ui_notified.append(table))
        handler = net_handler.ServerNetHandler(conn, configparser.ConfigParser(), test_key)
        handler.notify_change = lambda table, record_id: notified.append((table, record_id))
        pushed_uuid = uuid.uuid4().hex

        handler._handle_client_push(_FakeLink(operator_hash), {
            "records": {
                "messages": [{
                    "id": 1,
                    "uuid": pushed_uuid,
                    "channel_id": 10,
                    "sender_id": 999,
                    "body": "client hello",
                    "sent_at": 1001,
                    "version": 99,
                    "is_urgent": 1,
                    "grid_ref": "AB1234",
                    "sync_status": "pending",
                }],
            },
        })

        inserted = conn.execute(
            "SELECT id, sender_id, body, version, sync_status FROM messages WHERE uuid = ?",
            (pushed_uuid,),
        ).fetchone()
        assert inserted is not None
        assert inserted[0] != 1
        assert inserted[1] == 8
        assert bytes(inserted[2]) == b"client hello"
        assert inserted[3:] == (1, "synced")
        assert sent[-1]["type"] == proto.MSG_PUSH_ACK
        assert pushed_uuid in sent[-1]["accepted"]
        assert notified == [("messages", inserted[0])]
        assert ui_notified == ["messages"]

    def test_new_client_record_strips_id_and_identity_fields(self, tmp_db, test_key, monkeypatch):
        conn, _ = tmp_db
        operator_hash = "a" * 64
        conn.execute(
            "INSERT INTO operators (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
            "VALUES (5, 'CLIENT', ?, '[]', '{}', 1000, 9999999999, 0)",
            (operator_hash,),
        )
        conn.execute(
            "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version) "
            "VALUES (1, 'cache', 'Server Asset', '', 0, 1, 1000, 1)"
        )
        conn.commit()

        sent = []
        notified = []
        monkeypatch.setattr(
            net_handler,
            "_smart_send",
            lambda _link, data: sent.append(proto.decode(data)),
        )
        handler = net_handler.ServerNetHandler(conn, configparser.ConfigParser(), test_key)
        handler.notify_change = lambda table, record_id: notified.append((table, record_id))
        pushed_uuid = uuid.uuid4().hex

        handler._handle_client_push(_FakeLink(operator_hash), {
            "operator_rns_hash": "f" * 64,
            "records": {
                "assets": [{
                    "id": 1,
                    "uuid": pushed_uuid,
                    "category": "cache",
                    "label": "Client Asset",
                    "description": "",
                    "lat": None,
                    "lon": None,
                    "verified": 1,
                    "created_by": 999,
                    "confirmed_by": 999,
                    "created_at": 1001,
                    "version": 99,
                    "sync_status": "pending",
                }],
            },
        })

        original = conn.execute("SELECT label FROM assets WHERE id = 1").fetchone()
        inserted = conn.execute(
            "SELECT id, created_by, verified, confirmed_by, version "
            "FROM assets WHERE uuid = ?",
            (pushed_uuid,),
        ).fetchone()
        assert original[0] == "Server Asset"
        assert inserted[0] != 1
        assert inserted[1:] == (5, 0, None, 1)
        assert sent[-1]["type"] == proto.MSG_PUSH_ACK
        assert pushed_uuid in sent[-1]["accepted"]
        assert notified == [("assets", inserted[0])]

    def test_client_push_rejects_malformed_uuid(self, tmp_db, test_key, monkeypatch):
        conn, _ = tmp_db
        operator_hash = "b" * 64
        conn.execute(
            "INSERT INTO operators (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
            "VALUES (6, 'CLIENT2', ?, '[]', '{}', 1000, 9999999999, 0)",
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

        handler._handle_client_push(_FakeLink(operator_hash), {
            "records": {
                "assets": [{
                    "uuid": "not-a-uuid",
                    "category": "cache",
                    "label": "Bad",
                    "description": "",
                    "verified": 0,
                    "created_by": 6,
                    "created_at": 1001,
                }],
            },
        })

        row = conn.execute("SELECT id FROM assets WHERE label = 'Bad'").fetchone()
        assert row is None
        assert sent[-1]["accepted"] == []


class TestClientServerPushIntegration:
    def test_sync_response_order_applies_mission_before_linked_asset(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_order.db", test_key)
        try:
            manager = _make_client_manager(client_conn, test_key, operator_id=1)
            records_by_table = {
                "missions": {
                    "id": 77,
                    "title": "Parent Mission",
                    "status": "active",
                    "created_by": 1,
                    "created_at": 1000,
                    "version": 1,
                    "description": "",
                },
                "assets": {
                    "id": 1,
                    "category": "cache",
                    "label": "Mission Cache",
                    "description": "",
                    "lat": None,
                    "lon": None,
                    "verified": 0,
                    "created_by": 1,
                    "confirmed_by": None,
                    "created_at": 1001,
                    "version": 1,
                    "mission_id": 77,
                },
            }
            sync_done_event = threading.Event()

            for table in registry.SYNC_TABLES:
                record = records_by_table.get(table)
                if record is None:
                    continue
                manager._handle_incoming(
                    {
                        "version": proto.PROTOCOL_VERSION,
                        "type": proto.MSG_SYNC_RESPONSE,
                        "table": table,
                        "record": record,
                    },
                    sync_done_event,
                )

            row = client_conn.execute(
                "SELECT mission_id FROM assets WHERE id = 1"
            ).fetchone()
            assert row == (77,)
        finally:
            close_db(client_conn)

    def test_mid_session_fk_failure_requests_followup_sync(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_fk_retry.db", test_key)
        try:
            manager = _make_client_manager(client_conn, test_key, operator_id=1)
            fake_link = object()
            manager._link = fake_link
            sync_requests = []

            manager._handle_incoming(
                {
                    "version": proto.PROTOCOL_VERSION,
                    "type": proto.MSG_PUSH_UPDATE,
                    "table": "assets",
                    "record": {
                        "id": 1,
                        "category": "cache",
                        "label": "Mission Cache",
                        "description": "",
                        "lat": None,
                        "lon": None,
                        "verified": 1,
                        "created_by": 1,
                        "confirmed_by": 1,
                        "created_at": 1001,
                        "version": 2,
                        "mission_id": 77,
                    },
                },
                threading.Event(),
                lambda link: sync_requests.append(link),
            )

            assert sync_requests == [fake_link]
            assert client_conn.execute(
                "SELECT 1 FROM assets WHERE id = 1"
            ).fetchone() is None
        finally:
            close_db(client_conn)

    def test_reconcile_preserves_server_operator_sentinel(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_sentinel_reconcile.db", test_key)
        try:
            manager = _make_client_manager(client_conn, test_key, operator_id=2)

            manager._reconcile_with_server({"operators": [2]}, badge=False)

            assert client_conn.execute(
                "SELECT callsign FROM operators WHERE id = 1"
            ).fetchone() == ("SERVER",)
        finally:
            close_db(client_conn)

    def test_operator_delete_ignores_server_operator_sentinel(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_sentinel_delete.db", test_key)
        try:
            manager = _make_client_manager(client_conn, test_key, operator_id=2)

            manager._apply_delete("operators", 1)

            assert client_conn.execute(
                "SELECT callsign FROM operators WHERE id = 1"
            ).fetchone() == ("SERVER",)
        finally:
            close_db(client_conn)

    def test_rejected_existing_pending_assignment_restores_server_copy(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_rejected_existing.db", test_key)
        try:
            _insert_operator(client_conn, 20, "ASTER", "a" * 64)
            assignment = create_assignment(
                client_conn,
                assignment_type="fixed_post",
                title="North Gate",
                status="needs_support",
                priority="ROUTINE",
                assigned_operator_ids=[20],
                team_lead="ASTER",
                created_by=20,
                sync_status="pending",
            )
            client_conn.execute(
                "UPDATE assignments SET version = 2 WHERE id = ?",
                (assignment.id,),
            )
            pending_uuid = client_conn.execute(
                "SELECT uuid FROM assignments WHERE id = ?",
                (assignment.id,),
            ).fetchone()[0]
            client_conn.commit()
            notifications = []
            manager = _make_client_manager(client_conn, test_key, operator_id=20)
            manager._ui_dispatcher._notify_ui = (
                lambda table, *, badge=True: notifications.append((table, badge))
            )
            cursor = client_conn.execute(
                "SELECT * FROM assignments WHERE id = ?",
                (assignment.id,),
            )
            cols = [desc[0] for desc in cursor.description]
            server_record = dict(zip(cols, cursor.fetchone()))
            server_record.update(
                {
                    "status": "active",
                    "version": 1,
                    "sync_status": "synced",
                }
            )

            manager._apply_push_ack(
                [],
                [
                    {
                        "uuid": pending_uuid,
                        "table": "assignments",
                        "client_record": {"uuid": pending_uuid},
                        "server_record": server_record,
                    }
                ],
            )

            row = client_conn.execute(
                "SELECT status, version, sync_status FROM assignments WHERE id = ?",
                (assignment.id,),
            ).fetchone()
            assert row == ("active", 1, "synced")
            assert client_conn.execute(
                "SELECT count(*) FROM amendments WHERE record_uuid = ?",
                (pending_uuid,),
            ).fetchone() == (1,)
            assert ("amendments", True) in notifications
            assert ("assignments", True) in notifications
            assert manager._collect_outbox() == {}
        finally:
            close_db(client_conn)

    def test_rejected_new_assignment_is_removed_from_board_outbox(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_rejected_new.db", test_key)
        try:
            _insert_operator(client_conn, 20, "ASTER", "a" * 64)
            assignment = create_assignment(
                client_conn,
                assignment_type="fixed_post",
                title="Old local assignment",
                status="active",
                priority="ROUTINE",
                assigned_operator_ids=[20],
                team_lead="ASTER",
                created_by=20,
                sync_status="pending",
            )
            pending_uuid = client_conn.execute(
                "SELECT uuid FROM assignments WHERE id = ?",
                (assignment.id,),
            ).fetchone()[0]
            manager = _make_client_manager(client_conn, test_key, operator_id=20)

            manager._apply_push_ack(
                [],
                [
                    {
                        "uuid": pending_uuid,
                        "table": "assignments",
                        "client_record": {"uuid": pending_uuid},
                        "server_record": None,
                    }
                ],
            )

            assert client_conn.execute(
                "SELECT sync_status FROM assignments WHERE id = ?",
                (assignment.id,),
            ).fetchone() == ("rejected",)
            assert list_assignments(client_conn) == []
            assert manager._collect_outbox() == {}
        finally:
            close_db(client_conn)

    def test_client_accepts_only_pending_document_resources(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_resource_budget.db", test_key)
        try:
            manager = _make_client_manager(client_conn, test_key, operator_id=2)

            assert manager._accept_resource(_FakeResource(5, 10)) is False

            manager._pending_document_requests[5] = {"event": threading.Event()}
            assert manager._accept_resource(_FakeResource(5, 10)) is True
            assert (
                manager._accept_resource(
                    _FakeResource(5, MAX_DOCUMENT_SIZE_BYTES + 1)
                )
                is False
            )
        finally:
            close_db(client_conn)

    def test_document_fetch_timeout_clears_pending_request(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_document_timeout.db", test_key)
        try:
            _insert_document_row(
                client_conn,
                doc_id=5,
                filename="field-report.txt",
                plaintext=b"field report",
            )
            manager = _make_client_manager(client_conn, test_key, operator_id=2)
            manager._cfg.read_dict(
                {"documents": {"storage_path": str(tmp_path / "documents")}}
            )
            manager._link = object()
            sent: list[bytes] = []
            manager._document_transfers._smart_send = (
                lambda _link, data: sent.append(data)
            )

            with pytest.raises(DocumentError, match="Timed out waiting"):
                manager.fetch_document(5, timeout_s=0.01)

            assert sent
            assert 5 not in manager._pending_document_requests
        finally:
            close_db(client_conn)

    def test_server_message_repairs_missing_server_operator_sentinel(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_sentinel_message.db", test_key)
        try:
            client_conn.execute("DELETE FROM operators WHERE id = 1")
            client_conn.execute(
                "INSERT INTO channels (id, name, mission_id, is_dm, version, group_type) "
                "VALUES (10, '#general', NULL, 0, 1, 'allhands')"
            )
            client_conn.commit()
            manager = _make_client_manager(client_conn, test_key, operator_id=2)

            applied = manager._apply_record(
                "messages",
                {
                    "id": 2,
                    "channel_id": 10,
                    "sender_id": 1,
                    "body": "server hello",
                    "sent_at": 1001,
                    "version": 1,
                    "uuid": "f" * 32,
                    "sync_status": "synced",
                },
                badge=False,
            )

            assert applied is True
            assert client_conn.execute(
                "SELECT callsign FROM operators WHERE id = 1"
            ).fetchone() == ("SERVER",)
            row = client_conn.execute(
                "SELECT sender_id, body FROM messages WHERE id = 2"
            ).fetchone()
            assert row[0] == 1
            assert bytes(row[1]) == b"server hello"
        finally:
            close_db(client_conn)

    def test_public_push_record_pending_delegates_to_outbox(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_public_push.db", test_key)
        try:
            manager = _make_client_manager(client_conn, test_key, operator_id=1)
            calls = []
            manager._outbox.push_record_pending = (
                lambda table, record_id: calls.append((table, record_id))
            )

            manager.push_record_pending("messages", 42)

            assert calls == [("messages", 42)]
        finally:
            close_db(client_conn)

    def test_startup_sync_refreshes_without_unread_badges(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_startup_badges.db", test_key)
        try:
            manager = _make_client_manager(client_conn, test_key, operator_id=1)
            notifications = []
            manager._ui_dispatcher._notify_ui = (
                lambda table, *, badge=True: notifications.append((table, badge))
            )

            sync_done_event = threading.Event()
            manager._handle_incoming(
                {
                    "version": proto.PROTOCOL_VERSION,
                    "type": proto.MSG_SYNC_RESPONSE,
                    "table": "assets",
                    "record": {
                        "id": 70,
                        "category": "cache",
                        "label": "Cached Asset",
                        "description": "",
                        "lat": None,
                        "lon": None,
                        "verified": 0,
                        "created_by": 1,
                        "confirmed_by": None,
                        "created_at": 1000,
                        "version": 1,
                    },
                },
                sync_done_event,
            )
            manager._handle_incoming(
                {
                    "version": proto.PROTOCOL_VERSION,
                    "type": proto.MSG_SYNC_DONE,
                    "tombstones": [],
                    "server_id_sets": {},
                },
                sync_done_event,
            )
            manager._handle_incoming(
                {
                    "version": proto.PROTOCOL_VERSION,
                    "type": proto.MSG_PUSH_UPDATE,
                    "table": "assets",
                    "record": {
                        "id": 70,
                        "category": "cache",
                        "label": "Live Asset Update",
                        "description": "",
                        "lat": None,
                        "lon": None,
                        "verified": 0,
                        "created_by": 1,
                        "confirmed_by": None,
                        "created_at": 1000,
                        "version": 2,
                    },
                },
                sync_done_event,
            )

            assert notifications == [("assets", False), ("assets", True)]
        finally:
            close_db(client_conn)

    def test_pending_client_asset_is_replaced_with_server_canonical_record(
        self, tmp_path, test_key, monkeypatch
    ):
        server_conn = _open_test_db(tmp_path, "server.db", test_key)
        client_conn = _open_test_db(tmp_path, "client.db", test_key)
        try:
            operator_hash = "9" * 64
            _insert_operator(server_conn, 20, "CLIENT", operator_hash)
            _insert_operator(client_conn, 20, "CLIENT", operator_hash)
            _insert_operator(client_conn, 21, "SPOOF", "8" * 64)
            server_conn.execute(
                "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version, uuid) "
                "VALUES (1, 'cache', 'Server Asset', '', 0, 1, 1000, 1, ?)",
                (uuid.uuid4().hex,),
            )
            client_conn.execute(
                "UPDATE meta SET value = '20' WHERE key = 'my_operator_id'"
            )
            server_conn.commit()
            client_conn.commit()

            local_id = client_conn.execute(
                "INSERT INTO assets (category, label, description, lat, lon, verified, created_by, confirmed_by, "
                "created_at, version, uuid, sync_status) "
                "VALUES ('cache', 'Client Asset', '', NULL, NULL, 1, 21, 21, 1001, 99, ?, 'pending')",
                (uuid.uuid4().hex,),
            ).lastrowid
            pending_uuid = client_conn.execute(
                "SELECT uuid FROM assets WHERE id = ?",
                (local_id,),
            ).fetchone()[0]
            client_conn.commit()

            sent = []
            fake_link = _FakeLink(operator_hash)
            monkeypatch.setattr(
                net_handler,
                "_smart_send",
                lambda _link, data: sent.append(proto.decode(data)),
            )
            monkeypatch.setattr(net_components.threading, "Timer", _NoOpTimer)
            handler = net_handler.ServerNetHandler(
                server_conn,
                configparser.ConfigParser(),
                test_key,
            )
            handler._active_links[operator_hash] = fake_link

            manager = _make_client_manager(client_conn, test_key, operator_id=20)
            outbox = manager._collect_outbox()
            handler._handle_client_push(
                fake_link,
                {
                    "records": outbox,
                },
            )
            handler._flush_push_buffer()

            ack = next(msg for msg in sent if msg["type"] == proto.MSG_PUSH_ACK)
            update = next(msg for msg in sent if msg["type"] == proto.MSG_PUSH_UPDATE)
            manager._handle_incoming(ack, threading.Event())
            manager._handle_incoming(update, threading.Event())

            row = client_conn.execute(
                "SELECT id, created_by, verified, confirmed_by, version, sync_status "
                "FROM assets WHERE uuid = ?",
                (pending_uuid,),
            ).fetchone()
            assert row[0] != local_id
            assert row[1:] == (20, 0, None, 1, "synced")
        finally:
            close_db(client_conn)
            close_db(server_conn)

    def test_existing_asset_verification_round_trips_to_server_and_back(
        self, tmp_path, test_key, monkeypatch
    ):
        server_conn = _open_test_db(tmp_path, "server_verify.db", test_key)
        client_conn = _open_test_db(tmp_path, "client_verify.db", test_key)
        try:
            operator_hash = "7" * 64
            asset_uuid = uuid.uuid4().hex
            _insert_operator(server_conn, 30, "VERIFY", operator_hash)
            _insert_operator(server_conn, 31, "CREATOR", "6" * 64)
            _insert_operator(client_conn, 30, "VERIFY", operator_hash)
            _insert_operator(client_conn, 31, "CREATOR", "6" * 64)
            server_conn.execute(
                "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version, uuid, sync_status) "
                "VALUES (5, 'cache', 'Shared Asset', '', 0, 31, 1000, 1, ?, 'synced')",
                (asset_uuid,),
            )
            client_conn.execute(
                "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version, uuid, sync_status) "
                "VALUES (5, 'cache', 'Shared Asset', '', 0, 31, 1000, 1, ?, 'synced')",
                (asset_uuid,),
            )
            client_conn.execute(
                "UPDATE meta SET value = '30' WHERE key = 'my_operator_id'"
            )
            server_conn.commit()
            client_conn.commit()

            verify_asset_command(client_conn, 5, verified=True, confirmer_id=30)

            sent = []
            fake_link = _FakeLink(operator_hash)
            monkeypatch.setattr(
                net_handler,
                "_smart_send",
                lambda _link, data: sent.append(proto.decode(data)),
            )
            monkeypatch.setattr(net_components.threading, "Timer", _NoOpTimer)
            handler = net_handler.ServerNetHandler(
                server_conn,
                configparser.ConfigParser(),
                test_key,
            )
            handler._active_links[operator_hash] = fake_link

            manager = _make_client_manager(client_conn, test_key, operator_id=30)
            manager._push_record_pending("assets", 5)
            outbox = manager._collect_outbox()
            handler._handle_client_push(
                fake_link,
                {
                    "records": outbox,
                },
            )
            handler._flush_push_buffer()

            ack = next(msg for msg in sent if msg["type"] == proto.MSG_PUSH_ACK)
            update = next(msg for msg in sent if msg["type"] == proto.MSG_PUSH_UPDATE)
            manager._handle_incoming(ack, threading.Event())
            manager._handle_incoming(update, threading.Event())

            server_row = server_conn.execute(
                "SELECT verified, confirmed_by, version FROM assets WHERE id = 5"
            ).fetchone()
            client_row = client_conn.execute(
                "SELECT verified, confirmed_by, version, sync_status FROM assets WHERE id = 5"
            ).fetchone()
            assert ack["accepted"] == [asset_uuid]
            assert server_row == (1, 30, 2)
            assert client_row == (1, 30, 2, "synced")
        finally:
            close_db(client_conn)
            close_db(server_conn)

    def test_client_operator_profile_update_round_trips_to_server(
        self, tmp_path, test_key, monkeypatch
    ):
        server_conn = _open_test_db(tmp_path, "server_operator_profile.db", test_key)
        client_conn = _open_test_db(tmp_path, "client_operator_profile.db", test_key)
        try:
            operator_hash = "8" * 64
            operator_uuid = uuid.uuid4().hex
            _insert_operator(server_conn, 40, "PROFILE", operator_hash)
            _insert_operator(client_conn, 40, "PROFILE", operator_hash)
            server_conn.execute(
                "UPDATE operators SET uuid = ? WHERE id = 40",
                (operator_uuid,),
            )
            client_conn.execute(
                "UPDATE operators SET uuid = ?, skills = ?, profile = ?, "
                "version = version + 1, sync_status = 'pending' WHERE id = 40",
                (operator_uuid, '["medic"]', '{"role": "field"}'),
            )
            server_conn.commit()
            client_conn.commit()

            sent = []
            fake_link = _FakeLink(operator_hash)
            monkeypatch.setattr(
                net_handler,
                "_smart_send",
                lambda _link, data: sent.append(proto.decode(data)),
            )
            handler = net_handler.ServerNetHandler(
                server_conn,
                configparser.ConfigParser(),
                test_key,
            )
            handler.notify_change = lambda _table, _record_id: None

            manager = _make_client_manager(client_conn, test_key, operator_id=40)
            outbox = manager._collect_outbox()
            assert list(outbox) == ["operators"]
            handler._handle_client_push(fake_link, {"records": outbox})

            ack = sent[-1]
            manager._handle_incoming(ack, threading.Event())
            server_row = server_conn.execute(
                "SELECT skills, profile, version FROM operators WHERE id = 40"
            ).fetchone()
            client_status = client_conn.execute(
                "SELECT sync_status FROM operators WHERE id = 40"
            ).fetchone()[0]
            assert ack["accepted"] == [operator_uuid]
            assert server_row == ('["medic"]', '{"role": "field"}', 2)
            assert client_status == "synced"
        finally:
            close_db(client_conn)
            close_db(server_conn)

    def test_client_operator_profile_update_falls_back_to_authenticated_operator_id(
        self, tmp_path, test_key, monkeypatch
    ):
        server_conn = _open_test_db(tmp_path, "server_operator_profile_uuid.db", test_key)
        client_conn = _open_test_db(tmp_path, "client_operator_profile_uuid.db", test_key)
        try:
            operator_hash = "6" * 64
            server_uuid = uuid.uuid4().hex
            client_uuid = uuid.uuid4().hex
            _insert_operator(server_conn, 42, "PROFILE", operator_hash)
            _insert_operator(client_conn, 99, "PROFILE", operator_hash)
            server_conn.execute(
                "UPDATE operators SET uuid = ? WHERE id = 42",
                (server_uuid,),
            )
            client_conn.execute(
                "UPDATE operators SET uuid = ?, skills = ?, profile = ?, "
                "version = version + 1, sync_status = 'pending' WHERE id = 99",
                (client_uuid, '["comms"]', '{"role": "relay"}'),
            )
            server_conn.commit()
            client_conn.commit()

            sent = []
            notified = []
            ui_notified = []
            monkeypatch.setattr(
                net_handler,
                "_smart_send",
                lambda _link, data: sent.append(proto.decode(data)),
            )
            handler = net_handler.ServerNetHandler(
                server_conn,
                configparser.ConfigParser(),
                test_key,
                notify_ui=lambda table: ui_notified.append(table),
            )
            handler.notify_change = lambda table, record_id: notified.append(
                (table, record_id)
            )

            manager = _make_client_manager(client_conn, test_key, operator_id=99)
            outbox = manager._collect_outbox()
            assert outbox["operators"][0]["uuid"] == client_uuid
            handler._on_packet(
                _FakeLink(operator_hash),
                proto.encode(
                    {
                        "type": proto.MSG_CLIENT_PUSH_RECORDS,
                        "records": outbox,
                    }
                ),
                None,
            )

            ack = sent[-1]
            manager._handle_incoming(ack, threading.Event())
            server_row = server_conn.execute(
                "SELECT uuid, skills, profile, version FROM operators WHERE id = 42"
            ).fetchone()
            client_status = client_conn.execute(
                "SELECT sync_status FROM operators WHERE id = 99"
            ).fetchone()[0]
            assert ack["accepted"] == [client_uuid]
            assert ack["rejected"] == []
            assert server_row == (server_uuid, '["comms"]', '{"role": "relay"}', 2)
            assert client_status == "synced"
            assert notified == [("operators", 42)]
            assert ui_notified == ["operators"]
        finally:
            close_db(client_conn)
            close_db(server_conn)

    def test_client_operator_profile_update_ignores_stale_server_owned_fields(
        self, tmp_path, test_key, monkeypatch
    ):
        server_conn = _open_test_db(tmp_path, "server_operator_stale_profile.db", test_key)
        try:
            operator_hash = "4" * 64
            operator_uuid = uuid.uuid4().hex
            _insert_operator(server_conn, 41, "PROFILE", operator_hash)
            server_conn.execute(
                "UPDATE operators SET uuid = ?, lease_expires_at = ? WHERE id = 41",
                (operator_uuid, 9999999999),
            )
            server_conn.commit()

            sent = []
            monkeypatch.setattr(
                net_handler,
                "_smart_send",
                lambda _link, data: sent.append(proto.decode(data)),
            )
            handler = net_handler.ServerNetHandler(
                server_conn,
                configparser.ConfigParser(),
                test_key,
            )
            handler.notify_change = lambda _table, _record_id: None

            handler._handle_client_push(
                _FakeLink(operator_hash),
                {
                    "records": {
                        "operators": [
                            {
                                "id": 41,
                                "uuid": operator_uuid,
                                "callsign": "CLIENT-STALE",
                                "rns_hash": "5" * 64,
                                "skills": '["medic"]',
                                "profile": '{"role": "field"}',
                                "enrolled_at": 1000,
                                "lease_expires_at": 1234,
                                "revoked": 1,
                                "version": 99,
                                "sync_status": "pending",
                            }
                        ],
                    },
                },
            )

            ack = sent[-1]
            server_row = server_conn.execute(
                "SELECT callsign, rns_hash, skills, profile, lease_expires_at, "
                "revoked, version FROM operators WHERE id = 41"
            ).fetchone()
            assert ack["accepted"] == [operator_uuid]
            assert ack["rejected"] == []
            assert server_row == (
                "PROFILE",
                operator_hash,
                '["medic"]',
                '{"role": "field"}',
                9999999999,
                0,
                2,
            )
        finally:
            close_db(server_conn)

    def test_client_pushed_checkin_updates_assignment_status(
        self,
        tmp_path,
        test_key,
        monkeypatch,
    ):
        server_conn = _open_test_db(tmp_path, "server_checkin.db", test_key)
        try:
            operator_hash = "f" * 64
            _insert_operator(server_conn, 20, "ASTER", operator_hash)
            assignment = create_assignment(
                server_conn,
                assignment_type="fixed_post",
                title="North Gate",
                status="active",
                priority="ROUTINE",
                assigned_operator_ids=[20],
                team_lead="ASTER",
                checkin_interval_min=1,
                overdue_threshold_min=1,
                created_by=1,
            )

            sent = []
            monkeypatch.setattr(
                net_handler,
                "_smart_send",
                lambda _link, data: sent.append(proto.decode(data)),
            )
            monkeypatch.setattr(net_components.threading, "Timer", _NoOpTimer)
            handler = net_handler.ServerNetHandler(
                server_conn,
                configparser.ConfigParser(),
                test_key,
            )
            fake_link = _FakeLink(operator_hash)
            handler._handle_client_push(
                fake_link,
                {
                    "records": {
                        "checkins": [
                            {
                                "uuid": uuid.uuid4().hex,
                                "assignment_id": assignment.id,
                                "state": "ok",
                                "note": "Checked in from client.",
                            }
                        ]
                    },
                },
            )

            ack = next(msg for msg in sent if msg["type"] == proto.MSG_PUSH_ACK)
            assert len(ack["accepted"]) == 1
            row = server_conn.execute(
                "SELECT status, last_checkin_state, last_checkin_operator_id "
                "FROM assignments WHERE id = ?",
                (assignment.id,),
            ).fetchone()
            assert row == ("active", "ok", 20)
        finally:
            close_db(server_conn)

    def test_existing_asset_deletion_request_round_trips_to_server_and_back(
        self, tmp_path, test_key, monkeypatch
    ):
        server_conn = _open_test_db(tmp_path, "server_delete.db", test_key)
        client_conn = _open_test_db(tmp_path, "client_delete.db", test_key)
        try:
            operator_hash = "5" * 64
            asset_uuid = uuid.uuid4().hex
            _insert_operator(server_conn, 40, "REQUEST", operator_hash)
            _insert_operator(client_conn, 40, "REQUEST", operator_hash)
            server_conn.execute(
                "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version, uuid, sync_status) "
                "VALUES (6, 'cache', 'Delete Me', '', 0, 1, 1000, 1, ?, 'synced')",
                (asset_uuid,),
            )
            client_conn.execute(
                "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version, uuid, sync_status) "
                "VALUES (6, 'cache', 'Delete Me', '', 0, 1, 1000, 1, ?, 'synced')",
                (asset_uuid,),
            )
            client_conn.execute(
                "UPDATE meta SET value = '40' WHERE key = 'my_operator_id'"
            )
            server_conn.commit()
            client_conn.commit()

            request_asset_deletion_command(client_conn, 6)

            sent = []
            fake_link = _FakeLink(operator_hash)
            monkeypatch.setattr(
                net_handler,
                "_smart_send",
                lambda _link, data: sent.append(proto.decode(data)),
            )
            monkeypatch.setattr(net_components.threading, "Timer", _NoOpTimer)
            handler = net_handler.ServerNetHandler(
                server_conn,
                configparser.ConfigParser(),
                test_key,
            )
            handler._active_links[operator_hash] = fake_link

            manager = _make_client_manager(client_conn, test_key, operator_id=40)
            manager._push_record_pending("assets", 6)
            outbox = manager._collect_outbox()
            handler._handle_client_push(
                fake_link,
                {
                    "records": outbox,
                },
            )
            handler._flush_push_buffer()

            ack = next(msg for msg in sent if msg["type"] == proto.MSG_PUSH_ACK)
            update = next(msg for msg in sent if msg["type"] == proto.MSG_PUSH_UPDATE)
            manager._handle_incoming(ack, threading.Event())
            manager._handle_incoming(update, threading.Event())

            server_row = server_conn.execute(
                "SELECT deletion_requested, version FROM assets WHERE id = 6"
            ).fetchone()
            client_row = client_conn.execute(
                "SELECT deletion_requested, version, sync_status FROM assets WHERE id = 6"
            ).fetchone()
            assert ack["accepted"] == [asset_uuid]
            assert server_row == (1, 2)
            assert client_row == (1, 2, "synced")
        finally:
            close_db(client_conn)
            close_db(server_conn)

    def test_operator_revocation_push_marks_client_revoked_and_triggers_lock(
        self, tmp_path, test_key, monkeypatch
    ):
        server_conn = _open_test_db(tmp_path, "server_revoke.db", test_key)
        client_conn = _open_test_db(tmp_path, "client_revoke.db", test_key)
        try:
            operator_hash = "4" * 64
            _insert_operator(server_conn, 50, "REVOKE", operator_hash)
            _insert_operator(client_conn, 50, "REVOKE", operator_hash)
            client_conn.execute(
                "UPDATE meta SET value = '50' WHERE key = 'my_operator_id'"
            )
            server_conn.commit()
            client_conn.commit()

            sent = []
            fake_link = _FakeLink(operator_hash)
            monkeypatch.setattr(
                net_handler,
                "_smart_send",
                lambda _link, data: sent.append(proto.decode(data)),
            )
            monkeypatch.setattr(net_components.threading, "Timer", _NoOpTimer)
            handler = net_handler.ServerNetHandler(
                server_conn,
                configparser.ConfigParser(),
                test_key,
            )
            handler._active_links[operator_hash] = fake_link

            result = revoke_operator_command(server_conn, 50)
            handler.notify_change("operators", result.operator_id)
            handler._flush_push_buffer()

            manager = _make_client_manager(client_conn, test_key, operator_id=50)
            lock_checks = []
            manager._trigger_local_lock_check = lambda: lock_checks.append(True)

            for msg in sent:
                if msg["type"] in {
                    proto.MSG_PUSH_UPDATE,
                    proto.MSG_OPERATOR_REVOKED,
                }:
                    manager._handle_incoming(msg, threading.Event())

            msg_types = [msg["type"] for msg in sent]
            assert proto.MSG_PUSH_UPDATE in msg_types
            assert proto.MSG_OPERATOR_REVOKED in msg_types

            row = client_conn.execute(
                "SELECT revoked, rns_hash, lease_expires_at FROM operators WHERE id = 50"
            ).fetchone()
            assert row[0] == 1
            assert row[1] == ""
            assert row[2] <= int(time.time())
            assert lock_checks == [True]

        finally:
            close_db(client_conn)
            close_db(server_conn)

    def test_operator_inactive_error_marks_local_operator_revoked(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_inactive.db", test_key)
        try:
            operator_hash = "3" * 64
            _insert_operator(client_conn, 60, "INACTIVE", operator_hash)
            client_conn.commit()

            manager = _make_client_manager(client_conn, test_key, operator_id=60)
            lock_checks = []
            manager._trigger_local_lock_check = lambda: lock_checks.append(True)

            manager._handle_incoming(
                {
                    "version": proto.PROTOCOL_VERSION,
                    "type": proto.MSG_ERROR,
                    "message": "Operator not found or revoked",
                    "code": proto.ERROR_OPERATOR_INACTIVE,
                },
                threading.Event(),
            )

            row = client_conn.execute(
                "SELECT revoked, rns_hash, lease_expires_at FROM operators WHERE id = 60"
            ).fetchone()
            assert row[0] == 1
            assert row[1] == ""
            assert row[2] <= int(time.time())
            assert lock_checks == [True]

        finally:
            close_db(client_conn)

    def test_lease_expired_error_soft_locks_without_identity_burn(
        self, tmp_path, test_key
    ):
        client_conn = _open_test_db(tmp_path, "client_lease_expired.db", test_key)
        try:
            operator_hash = "5" * 64
            _insert_operator(client_conn, 61, "SOFTLOCK", operator_hash)
            client_conn.commit()

            manager = _make_client_manager(client_conn, test_key, operator_id=61)
            lock_checks = []
            manager._trigger_local_lock_check = lambda: lock_checks.append(True)
            expired_at = int(time.time()) - 30

            manager._handle_incoming(
                {
                    "version": proto.PROTOCOL_VERSION,
                    "type": proto.MSG_ERROR,
                    "message": "Operator lease has expired",
                    "code": proto.ERROR_LEASE_EXPIRED,
                    "lease_expires_at": expired_at,
                },
                threading.Event(),
            )

            row = client_conn.execute(
                "SELECT revoked, rns_hash, lease_expires_at FROM operators WHERE id = 61"
            ).fetchone()
            assert row == (0, operator_hash, expired_at)
            assert lock_checks == [True]

        finally:
            close_db(client_conn)

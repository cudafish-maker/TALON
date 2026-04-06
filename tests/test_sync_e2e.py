# tests/test_sync_e2e.py
# End-to-end sync tests — two real SQLite databases simulating
# client ↔ server delta sync through the full protocol stack.
#
# No mocks (except transport). Both sides use real in-memory SQLite
# databases with the full T.A.L.O.N. schema.

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.client.cache import ClientCache
from talon.client.sync_client import SyncClient
from talon.db.database import initialize_tables
from talon.db.models import (
    new_id,
    now,
)
from talon.server.sync_engine import SyncEngine
from talon.sync.protocol import (
    apply_sync_response,
    build_client_changes,
    build_sync_request,
    build_sync_response,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_db():
    """Create an in-memory SQLite database with T.A.L.O.N. schema."""
    conn = sqlite3.connect(":memory:")
    initialize_tables(conn)
    return conn


def _insert_record(conn, table, record_dict):
    """Insert a dict record into a table."""
    columns = ", ".join(record_dict.keys())
    placeholders = ", ".join("?" for _ in record_dict)
    conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
        list(record_dict.values()),
    )
    conn.commit()


def _make_operator(callsign="WOLF-1", version=1, sync_state="synced"):
    return {
        "id": new_id(), "callsign": callsign,
        "reticulum_identity": new_id(),
        "role": "operator", "status": "active",
        "skills": "[]", "custom_skills": "[]", "bio": "",
        "enrolled_at": now(), "last_sync": now(),
        "version": version, "sync_state": sync_state,
    }


def _make_sitrep(created_by="WOLF-1", importance="ROUTINE", version=1,
                 sync_state="synced"):
    return {
        "id": new_id(), "type": "freeform", "template_name": None,
        "importance": importance, "created_by": created_by,
        "created_at": now(), "deleted": 0, "delete_reason": None,
        "version": version, "sync_state": sync_state,
    }


def _make_asset(name="Supply Cache", created_by="WOLF-1", version=1,
                sync_state="synced"):
    return {
        "id": new_id(), "name": name, "category": "SUPPLY",
        "custom_category": None, "latitude": 34.05, "longitude": -118.24,
        "status": "active", "verification": "unverified",
        "verified_by": None, "created_by": created_by,
        "created_at": now(), "updated_at": now(), "notes": "",
        "version": version, "sync_state": sync_state,
    }


def _make_message(channel_id, sender="WOLF-1", body="Test message",
                  version=1, sync_state="synced"):
    return {
        "id": new_id(), "channel_id": channel_id, "sender": sender,
        "type": "TEXT", "body": body, "created_at": now(),
        "edited": 0, "version": version, "sync_state": sync_state,
    }


def _make_channel(name="General", channel_type="GENERAL", version=1):
    return {
        "id": new_id(), "name": name, "type": channel_type,
        "created_by": None, "created_at": now(), "mission_id": None,
        "version": version, "sync_state": "synced",
    }


def _count_rows(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _make_client_cache():
    """Create a ClientCache backed by in-memory SQLite."""
    cache = ClientCache("/tmp/test-sync")
    cache.db = _make_db()
    return cache


# ==================================================================
# Protocol-level tests (build_sync_request / response / apply)
# ==================================================================

class TestProtocolRoundtrip:
    def test_empty_databases(self):
        """Two empty databases should produce no updates."""
        server_db = _make_db()
        client_db = _make_db()

        request = build_sync_request(client_db)
        response = build_sync_response(server_db, request.get("versions", {}))
        updates = response.get("updates", {})
        assert all(len(recs) == 0 for recs in updates.values()) or len(updates) == 0

    def test_server_has_data_client_empty(self):
        """Server data should flow to empty client."""
        server_db = _make_db()
        client_db = _make_db()

        # Add records to server
        op = _make_operator("WOLF-1")
        _insert_record(server_db, "operators", op)
        sitrep = _make_sitrep()
        _insert_record(server_db, "sitreps", sitrep)

        # Client requests sync
        request = build_sync_request(client_db)
        response = build_sync_response(server_db, request.get("versions", {}))

        # Apply to client
        conflicts = apply_sync_response(client_db, response)
        assert conflicts == []
        assert _count_rows(client_db, "operators") == 1
        assert _count_rows(client_db, "sitreps") == 1

    def test_client_already_up_to_date(self):
        """If client has same version, no updates should be sent."""
        server_db = _make_db()
        client_db = _make_db()

        op = _make_operator("WOLF-1", version=3)
        _insert_record(server_db, "operators", op)
        _insert_record(client_db, "operators", op.copy())

        request = build_sync_request(client_db)
        response = build_sync_response(server_db, request.get("versions", {}))
        updates = response.get("updates", {})
        op_updates = updates.get("operators", [])
        assert len(op_updates) == 0

    def test_server_has_newer_version(self):
        """Server's newer record should overwrite client's."""
        server_db = _make_db()
        client_db = _make_db()

        op_id = new_id()
        ident = new_id()

        old = {
            "id": op_id, "callsign": "WOLF-1",
            "reticulum_identity": ident,
            "role": "operator", "status": "active",
            "skills": "[]", "custom_skills": "[]", "bio": "",
            "enrolled_at": now(), "last_sync": now(),
            "version": 1, "sync_state": "synced",
        }
        new = old.copy()
        new["version"] = 5
        new["bio"] = "Updated bio"

        _insert_record(client_db, "operators", old)
        _insert_record(server_db, "operators", new)

        request = build_sync_request(client_db)
        response = build_sync_response(server_db, request.get("versions", {}))
        conflicts = apply_sync_response(client_db, response)

        assert conflicts == []
        row = client_db.execute(
            "SELECT bio, version FROM operators WHERE id = ?", (op_id,)
        ).fetchone()
        assert row[0] == "Updated bio"
        assert row[1] == 5

    def test_conflict_detected(self):
        """Client with same/higher version should trigger a conflict."""
        client_db = _make_db()

        op_id = new_id()
        ident = new_id()
        record = {
            "id": op_id, "callsign": "WOLF-1",
            "reticulum_identity": ident,
            "role": "operator", "status": "active",
            "skills": "[]", "custom_skills": "[]", "bio": "",
            "enrolled_at": now(), "last_sync": now(),
            "version": 5, "sync_state": "synced",
        }
        _insert_record(client_db, "operators", record)

        # Server tries to push version 3 (older)
        incoming = {"updates": {"operators": [{**record, "version": 3}]}}
        conflicts = apply_sync_response(client_db, incoming)
        assert len(conflicts) == 1
        assert "Conflict" in conflicts[0]

    def test_multiple_tables_sync(self):
        """Records across multiple tables should all sync."""
        server_db = _make_db()
        client_db = _make_db()

        op = _make_operator()
        _insert_record(server_db, "operators", op)
        sitrep = _make_sitrep()
        _insert_record(server_db, "sitreps", sitrep)
        asset = _make_asset()
        _insert_record(server_db, "assets", asset)

        request = build_sync_request(client_db)
        response = build_sync_response(server_db, request.get("versions", {}))
        apply_sync_response(client_db, response)

        assert _count_rows(client_db, "operators") == 1
        assert _count_rows(client_db, "sitreps") == 1
        assert _count_rows(client_db, "assets") == 1


class TestBuildClientChanges:
    def test_pending_records_collected(self):
        """Records with sync_state='pending' should be collected."""
        db = _make_db()
        op = _make_operator(sync_state="pending")
        _insert_record(db, "operators", op)
        sitrep = _make_sitrep(sync_state="pending")
        _insert_record(db, "sitreps", sitrep)

        result = build_client_changes(db)
        changes = result.get("changes", {})
        assert len(changes.get("operators", [])) == 1
        assert len(changes.get("sitreps", [])) == 1

    def test_synced_records_excluded(self):
        """Records with sync_state='synced' should not be included."""
        db = _make_db()
        op = _make_operator(sync_state="synced")
        _insert_record(db, "operators", op)

        result = build_client_changes(db)
        changes = result.get("changes", {})
        assert len(changes.get("operators", [])) == 0

    def test_empty_db(self):
        db = _make_db()
        result = build_client_changes(db)
        changes = result.get("changes", {})
        total = sum(len(recs) for recs in changes.values())
        assert total == 0


# ==================================================================
# SyncEngine tests (server-side orchestration)
# ==================================================================

class TestSyncEngine:
    def test_handle_sync_request_empty(self):
        """Empty server should return empty updates."""
        engine = SyncEngine(db=_make_db())
        result = engine.handle_sync_request("client1", {})
        assert result["type"] == "sync_response"
        updates = result.get("updates", {})
        total = sum(len(recs) for recs in updates.values())
        assert total == 0

    def test_handle_sync_request_with_data(self):
        """Server with data should return updates for empty client."""
        server_db = _make_db()
        op = _make_operator()
        _insert_record(server_db, "operators", op)

        engine = SyncEngine(db=server_db)
        # Client has version 0 for all tables
        versions = {"operators": 0}
        result = engine.handle_sync_request("client1", versions)
        assert len(result["updates"].get("operators", [])) == 1

    def test_handle_client_changes(self):
        """Server should accept and apply client changes."""
        server_db = _make_db()
        engine = SyncEngine(db=server_db)

        asset = _make_asset(name="New Cache", sync_state="pending")
        changes = {"assets": [asset]}
        result = engine.handle_client_changes("client1", changes)

        assert result["applied"] == 1
        assert result["conflicts"] == []
        assert _count_rows(server_db, "assets") == 1

    def test_handle_client_changes_conflict(self):
        """Server should report conflict when local version is higher."""
        server_db = _make_db()
        asset = _make_asset(version=5)
        _insert_record(server_db, "assets", asset)

        engine = SyncEngine(db=server_db)
        # Client tries to push version 2 (older)
        stale_asset = asset.copy()
        stale_asset["version"] = 2
        changes = {"assets": [stale_asset]}
        result = engine.handle_client_changes("client1", changes)
        assert len(result["conflicts"]) == 1

    def test_handle_message_sync_request(self):
        """handle_message should route sync_request correctly."""
        server_db = _make_db()
        op = _make_operator()
        _insert_record(server_db, "operators", op)

        engine = SyncEngine(db=server_db)
        msg = {"type": "sync_request", "versions": {"operators": 0}}
        result = engine.handle_message("client1", msg)
        assert result["type"] == "sync_response"
        assert len(result["updates"].get("operators", [])) == 1

    def test_handle_message_client_changes(self):
        """handle_message should route client_changes correctly."""
        server_db = _make_db()
        engine = SyncEngine(db=server_db)

        asset = _make_asset()
        msg = {"type": "client_changes", "changes": {"assets": [asset]}}
        result = engine.handle_message("client1", msg)
        assert result["applied"] == 1

    def test_handle_message_unknown_type(self):
        engine = SyncEngine(db=_make_db())
        result = engine.handle_message("client1", {"type": "bogus"})
        assert "error" in result

    def test_data_changed_callback(self):
        """on_data_changed should fire when client pushes new data."""
        server_db = _make_db()
        callback_log = []
        engine = SyncEngine(
            db=server_db,
            on_data_changed=lambda cid, changes: callback_log.append(cid),
        )
        asset = _make_asset()
        engine.handle_client_changes("client1", {"assets": [asset]})
        assert callback_log == ["client1"]

    def test_register_unregister_client(self):
        engine = SyncEngine(db=_make_db())
        engine.register_client("c1", "WOLF-1", "yggdrasil")
        assert "c1" in engine.get_connected_clients()
        engine.unregister_client("c1")
        assert "c1" not in engine.get_connected_clients()


# ==================================================================
# SyncClient tests (client-side orchestration)
# ==================================================================

class TestSyncClientBuildRequest:
    def test_build_request_has_versions(self):
        cache = _make_client_cache()
        sync = SyncClient(cache=cache)
        request = sync.build_request()
        assert request["type"] == "sync_request"
        assert "versions" in request
        assert "operators" in request["versions"]

    def test_build_request_reflects_local_data(self):
        cache = _make_client_cache()
        op = _make_operator(version=3)
        _insert_record(cache.db, "operators", op)

        sync = SyncClient(cache=cache)
        request = sync.build_request()
        assert request["versions"]["operators"] == 3


class TestSyncClientApplyResponse:
    def test_apply_response_inserts_records(self):
        cache = _make_client_cache()
        sync = SyncClient(cache=cache)

        op = _make_operator()
        response = {"type": "sync_response", "updates": {"operators": [op]}}
        count = sync.apply_response(response)
        assert count == 1
        assert _count_rows(cache.db, "operators") == 1

    def test_apply_response_empty(self):
        cache = _make_client_cache()
        sync = SyncClient(cache=cache)
        count = sync.apply_response({"type": "sync_response", "updates": {}})
        assert count == 0


class TestSyncClientGetPendingChanges:
    def test_pending_changes_from_db(self):
        cache = _make_client_cache()
        op = _make_operator(sync_state="pending")
        _insert_record(cache.db, "operators", op)

        sync = SyncClient(cache=cache)
        result = sync.get_pending_changes()
        changes = result.get("changes", {})
        assert len(changes.get("operators", [])) == 1


# ==================================================================
# Full end-to-end sync (client ↔ server via mock transport)
# ==================================================================

class TestFullSync:
    def _make_pair(self):
        """Create a server engine + client sync pair."""
        server_db = _make_db()
        cache = _make_client_cache()
        engine = SyncEngine(db=server_db)
        sync = SyncClient(cache=cache)
        return server_db, cache, engine, sync

    def _mock_transport(self, engine, client_id="test-client"):
        """Return a send_fn that routes messages through the engine."""
        def send_fn(message):
            return engine.handle_message(client_id, message)
        return send_fn

    def test_server_data_flows_to_client(self):
        """Records created on the server should appear on the client."""
        server_db, cache, engine, sync = self._make_pair()

        # Server has data
        op = _make_operator("WOLF-1")
        _insert_record(server_db, "operators", op)
        sitrep = _make_sitrep()
        _insert_record(server_db, "sitreps", sitrep)
        asset = _make_asset("Ammo Cache")
        _insert_record(server_db, "assets", asset)

        # Client syncs
        result = sync.full_sync(self._mock_transport(engine))

        assert result["received"] == 3
        assert result["sent"] == 0
        assert result["conflicts"] == []
        assert _count_rows(cache.db, "operators") == 1
        assert _count_rows(cache.db, "sitreps") == 1
        assert _count_rows(cache.db, "assets") == 1

    def test_client_data_flows_to_server(self):
        """Records created on the client should appear on the server."""
        server_db, cache, engine, sync = self._make_pair()

        # Client creates data locally (sync_state = pending)
        asset = _make_asset("Water Source", sync_state="pending")
        _insert_record(cache.db, "assets", asset)

        result = sync.full_sync(self._mock_transport(engine))

        assert result["sent"] == 1
        assert _count_rows(server_db, "assets") == 1

    def test_bidirectional_sync(self):
        """Both sides exchange data in a single sync cycle."""
        server_db, cache, engine, sync = self._make_pair()

        # Server has an operator
        op = _make_operator("EAGLE-1")
        _insert_record(server_db, "operators", op)

        # Client has a new SITREP
        sitrep = _make_sitrep(sync_state="pending")
        _insert_record(cache.db, "sitreps", sitrep)

        result = sync.full_sync(self._mock_transport(engine))

        # Client got the operator from server
        assert _count_rows(cache.db, "operators") == 1
        # Server got the SITREP from client
        assert _count_rows(server_db, "sitreps") == 1
        assert result["received"] == 1
        assert result["sent"] == 1

    def test_incremental_sync(self):
        """Second sync should only transfer new records."""
        server_db, cache, engine, sync = self._make_pair()
        transport = self._mock_transport(engine)

        # First sync: server has 1 operator
        op1 = _make_operator("WOLF-1")
        _insert_record(server_db, "operators", op1)
        sync.full_sync(transport)
        assert _count_rows(cache.db, "operators") == 1

        # Server gets a new operator (version must be > client's max)
        op2 = _make_operator("WOLF-2", version=2)
        _insert_record(server_db, "operators", op2)

        # Second sync: should only get the new one
        result = sync.full_sync(transport)
        assert _count_rows(cache.db, "operators") == 2
        assert result["received"] == 1  # Only the new operator

    def test_sync_sets_last_sync(self):
        server_db, cache, engine, sync = self._make_pair()
        assert sync.last_sync == 0
        sync.full_sync(self._mock_transport(engine))
        assert sync.last_sync > 0

    def test_sync_clears_is_syncing(self):
        server_db, cache, engine, sync = self._make_pair()
        sync.full_sync(self._mock_transport(engine))
        assert sync.is_syncing is False

    def test_sync_complete_callback(self):
        server_db, cache, engine, sync_client = self._make_pair()
        results = []
        sync_client.on_sync_complete = lambda r: results.append(r)
        sync_client.full_sync(self._mock_transport(engine))
        assert len(results) == 1

    def test_sync_while_already_syncing(self):
        server_db, cache, engine, sync = self._make_pair()
        sync.is_syncing = True
        result = sync.full_sync(self._mock_transport(engine))
        assert "error" in result

    def test_sync_no_response(self):
        cache = _make_client_cache()
        sync = SyncClient(cache=cache)
        result = sync.full_sync(lambda msg: None)
        assert "error" in result
        assert sync.is_syncing is False

    def test_sync_exception_handled(self):
        cache = _make_client_cache()
        sync = SyncClient(cache=cache)
        errors = []
        sync.on_sync_error = lambda e: errors.append(e)

        def bad_transport(msg):
            raise ConnectionError("Network down")

        result = sync.full_sync(bad_transport)
        assert "error" in result
        assert sync.is_syncing is False
        assert len(errors) == 1

    def test_chat_sync(self):
        """Channels and messages should sync end-to-end."""
        server_db, cache, engine, sync = self._make_pair()

        ch = _make_channel("Ops Channel")
        _insert_record(server_db, "channels", ch)
        msg = _make_message(ch["id"], body="All stations, check in")
        _insert_record(server_db, "messages", msg)

        sync.full_sync(self._mock_transport(engine))

        assert _count_rows(cache.db, "channels") == 1
        assert _count_rows(cache.db, "messages") == 1

    def test_multiple_sync_cycles(self):
        """Data should accumulate correctly over multiple syncs."""
        server_db, cache, engine, sync = self._make_pair()
        transport = self._mock_transport(engine)

        for i in range(5):
            op = _make_operator(f"WOLF-{i+1}", version=i + 1)
            _insert_record(server_db, "operators", op)
            sync.full_sync(transport)

        assert _count_rows(cache.db, "operators") == 5


class TestSyncEngineFiltering:
    def test_lora_filters_documents(self):
        """Documents should be excluded over LoRa."""
        server_db = _make_db()
        doc = {
            "id": new_id(), "title": "Field Manual", "category": "Manual",
            "file_type": "pdf", "file_path": "/docs/fm.pdf",
            "file_size": 1024, "tags": "[]", "access_level": "ALL",
            "uploaded_by": "WOLF-1", "uploaded_at": now(),
            "version": 1, "sync_state": "synced",
        }
        _insert_record(server_db, "documents", doc)

        engine = SyncEngine(db=server_db)
        result = engine.handle_sync_request("client1", {"documents": 0},
                                            is_broadband=False)
        assert len(result["updates"].get("documents", [])) == 0

    def test_broadband_includes_documents(self):
        """Documents should be included over broadband."""
        server_db = _make_db()
        doc = {
            "id": new_id(), "title": "Field Manual", "category": "Manual",
            "file_type": "pdf", "file_path": "/docs/fm.pdf",
            "file_size": 1024, "tags": "[]", "access_level": "ALL",
            "uploaded_by": "WOLF-1", "uploaded_at": now(),
            "version": 1, "sync_state": "synced",
        }
        _insert_record(server_db, "documents", doc)

        engine = SyncEngine(db=server_db)
        result = engine.handle_sync_request("client1", {"documents": 0},
                                            is_broadband=True)
        assert len(result["updates"].get("documents", [])) == 1

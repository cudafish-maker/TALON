# tests/test_client_cache.py
# Tests for ClientCache — the client-side data access layer.
#
# Uses a real in-memory SQLite database (via the sqlcipher3 mock that
# delegates to stdlib sqlite3) so we can test actual SQL round-trips
# without needing SQLCipher or a display server.

import sys
import os
import json
import sqlite3
import time
from unittest.mock import MagicMock, patch
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.db.models import (
    Asset, Channel, Document, Message, Mission, MissionNote,
    Objective, Operator, SITREP, SITREPEntry, new_id, now,
)
from talon.client.cache import ClientCache, _row_to_dataclass, _dataclass_to_row
from talon.sync.outbox import Outbox


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_cache():
    """Create a ClientCache with a real in-memory SQLite DB."""
    cache = ClientCache("/tmp/test-cache")
    cache.db = sqlite3.connect(":memory:")
    # Create the schema — import initialize_tables but use stdlib sqlite3
    from talon.db.database import initialize_tables
    initialize_tables(cache.db)
    return cache


def _insert_operator(cache, callsign="WOLF-1", role="operator"):
    """Insert an operator directly into the DB."""
    op = Operator(callsign=callsign, role=role,
                  reticulum_identity=new_id())
    columns, values = _dataclass_to_row(op)
    placeholders = ", ".join("?" for _ in values)
    col_names = ", ".join(columns)
    cache.db.execute(
        f"INSERT INTO operators ({col_names}) VALUES ({placeholders})", values
    )
    cache.db.commit()
    return op


# ==================================================================
# _row_to_dataclass / _dataclass_to_row helpers
# ==================================================================

class TestRowToDataclass:
    def test_basic_roundtrip(self):
        sitrep = SITREP(id="s1", type="freeform", importance="FLASH",
                        created_by="WOLF-1")
        columns, values = _dataclass_to_row(sitrep)
        restored = _row_to_dataclass(SITREP, columns, values)
        assert restored.id == "s1"
        assert restored.importance == "FLASH"
        assert restored.type == "freeform"
        assert restored.deleted is False

    def test_json_field_roundtrip(self):
        op = Operator(callsign="WOLF-1", skills=["medic", "comms"])
        columns, values = _dataclass_to_row(op)
        # skills should be JSON-serialized
        idx = columns.index("skills")
        assert isinstance(values[idx], str)
        assert json.loads(values[idx]) == ["medic", "comms"]
        # Restore
        restored = _row_to_dataclass(Operator, columns, values)
        assert restored.skills == ["medic", "comms"]

    def test_bool_fields_convert_to_int(self):
        sitrep = SITREP(deleted=True)
        columns, values = _dataclass_to_row(sitrep)
        idx = columns.index("deleted")
        assert values[idx] == 1  # int, not bool

    def test_bool_fields_restore_from_int(self):
        columns = ["id", "deleted"]
        row = ("s1", 1)
        restored = _row_to_dataclass(SITREP, columns, row)
        assert restored.deleted is True

    def test_extra_columns_ignored(self):
        columns = ["id", "callsign", "nonexistent_col"]
        row = ("op1", "WOLF-1", "ignored")
        restored = _row_to_dataclass(Operator, columns, row)
        assert restored.id == "op1"
        assert restored.callsign == "WOLF-1"


# ==================================================================
# get_all()
# ==================================================================

class TestGetAll:
    def test_empty_table(self):
        cache = _make_cache()
        result = cache.get_all("sitreps")
        assert result == []

    def test_returns_dataclass_instances(self):
        cache = _make_cache()
        cache.save_sitrep(SITREP(id="s1", type="freeform",
                                 importance="ROUTINE", created_by="WOLF-1"))
        result = cache.get_all("sitreps")
        assert len(result) == 1
        assert isinstance(result[0], SITREP)
        assert result[0].id == "s1"

    def test_multiple_records(self):
        cache = _make_cache()
        for i in range(5):
            cache.save_asset(Asset(id=f"a{i}", name=f"Asset {i}",
                                   created_by="WOLF-1"))
        result = cache.get_all("assets")
        assert len(result) == 5

    def test_unknown_table_returns_empty(self):
        cache = _make_cache()
        result = cache.get_all("nonexistent")
        assert result == []

    def test_no_db_returns_empty(self):
        cache = ClientCache("/tmp/test-cache")
        assert cache.get_all("sitreps") == []

    def test_operators_table(self):
        cache = _make_cache()
        _insert_operator(cache, "EAGLE-1", "operator")
        result = cache.get_all("operators")
        assert len(result) == 1
        assert result[0].callsign == "EAGLE-1"

    def test_missions_table(self):
        cache = _make_cache()
        cache.save_mission(Mission(id="m1", name="Op Shadow",
                                   created_by="WOLF-1"))
        result = cache.get_all("missions")
        assert len(result) == 1
        assert result[0].name == "Op Shadow"

    def test_channels_table(self):
        cache = _make_cache()
        cache.save_channel(Channel(id="ch1", name="General", type="GENERAL"))
        result = cache.get_all("channels")
        assert len(result) == 1
        assert result[0].name == "General"

    def test_documents_table(self):
        cache = _make_cache()
        cache.save_document(Document(id="d1", title="Field Manual",
                                     file_type="pdf", file_path="/docs/fm.pdf",
                                     uploaded_by="WOLF-1"))
        result = cache.get_all("documents")
        assert len(result) == 1
        assert result[0].title == "Field Manual"


# ==================================================================
# get_sitrep_entries()
# ==================================================================

class TestGetSitrepEntries:
    def test_empty(self):
        cache = _make_cache()
        assert cache.get_sitrep_entries("s1") == []

    def test_filters_by_sitrep_id(self):
        cache = _make_cache()
        cache.save_sitrep(SITREP(id="s1", type="freeform", created_by="W1"))
        cache.save_sitrep(SITREP(id="s2", type="freeform", created_by="W1"))
        cache.save_sitrep_entry(SITREPEntry(id="e1", sitrep_id="s1",
                                            author="W1", content="Entry 1"))
        cache.save_sitrep_entry(SITREPEntry(id="e2", sitrep_id="s1",
                                            author="W1", content="Entry 2"))
        cache.save_sitrep_entry(SITREPEntry(id="e3", sitrep_id="s2",
                                            author="W1", content="Other"))

        entries = cache.get_sitrep_entries("s1")
        assert len(entries) == 2
        assert all(e.sitrep_id == "s1" for e in entries)

    def test_ordered_by_created_at(self):
        cache = _make_cache()
        cache.save_sitrep(SITREP(id="s1", type="freeform", created_by="W1"))
        t = time.time()
        cache.save_sitrep_entry(SITREPEntry(id="e1", sitrep_id="s1",
                                            author="W1", content="First",
                                            created_at=t))
        cache.save_sitrep_entry(SITREPEntry(id="e2", sitrep_id="s1",
                                            author="W1", content="Second",
                                            created_at=t + 60))
        entries = cache.get_sitrep_entries("s1")
        assert entries[0].content == "First"
        assert entries[1].content == "Second"

    def test_no_db_returns_empty(self):
        cache = ClientCache("/tmp/test-cache")
        assert cache.get_sitrep_entries("s1") == []


# ==================================================================
# get_objectives()
# ==================================================================

class TestGetObjectives:
    def test_empty(self):
        cache = _make_cache()
        assert cache.get_objectives("m1") == []

    def test_filters_by_mission_id(self):
        cache = _make_cache()
        cache.save_mission(Mission(id="m1", name="Op A", created_by="W1"))
        cache.save_mission(Mission(id="m2", name="Op B", created_by="W1"))
        cache.save_objective(Objective(id="o1", mission_id="m1",
                                       description="Take hill"))
        cache.save_objective(Objective(id="o2", mission_id="m1",
                                       description="Hold hill"))
        cache.save_objective(Objective(id="o3", mission_id="m2",
                                       description="Other"))

        objs = cache.get_objectives("m1")
        assert len(objs) == 2
        assert all(o.mission_id == "m1" for o in objs)

    def test_no_db_returns_empty(self):
        cache = ClientCache("/tmp/test-cache")
        assert cache.get_objectives("m1") == []


# ==================================================================
# get_mission_notes()
# ==================================================================

class TestGetMissionNotes:
    def test_empty(self):
        cache = _make_cache()
        assert cache.get_mission_notes("m1") == []

    def test_filters_by_mission_id(self):
        cache = _make_cache()
        cache.save_mission(Mission(id="m1", name="Op A", created_by="W1"))
        cache._save_record("mission_notes",
                           MissionNote(id="n1", mission_id="m1",
                                       author="W1", content="Note 1"))
        cache._save_record("mission_notes",
                           MissionNote(id="n2", mission_id="m1",
                                       author="W1", content="Note 2"))
        notes = cache.get_mission_notes("m1")
        assert len(notes) == 2

    def test_ordered_by_created_at(self):
        cache = _make_cache()
        cache.save_mission(Mission(id="m1", name="Op A", created_by="W1"))
        t = time.time()
        cache._save_record("mission_notes",
                           MissionNote(id="n1", mission_id="m1", author="W1",
                                       content="First", created_at=t))
        cache._save_record("mission_notes",
                           MissionNote(id="n2", mission_id="m1", author="W1",
                                       content="Second", created_at=t + 60))
        notes = cache.get_mission_notes("m1")
        assert notes[0].content == "First"
        assert notes[1].content == "Second"


# ==================================================================
# get_messages()
# ==================================================================

class TestGetMessages:
    def test_empty(self):
        cache = _make_cache()
        assert cache.get_messages("ch1") == []

    def test_filters_by_channel_id(self):
        cache = _make_cache()
        cache.save_channel(Channel(id="ch1", name="General", type="GENERAL"))
        cache.save_channel(Channel(id="ch2", name="Ops", type="MISSION"))
        cache.save_message(Message(id="msg1", channel_id="ch1",
                                    sender="W1", body="Hello"))
        cache.save_message(Message(id="msg2", channel_id="ch1",
                                    sender="W2", body="Hi"))
        cache.save_message(Message(id="msg3", channel_id="ch2",
                                    sender="W1", body="Other"))

        msgs = cache.get_messages("ch1")
        assert len(msgs) == 2
        assert all(m.channel_id == "ch1" for m in msgs)

    def test_ordered_by_created_at(self):
        cache = _make_cache()
        cache.save_channel(Channel(id="ch1", name="General", type="GENERAL"))
        t = time.time()
        cache.save_message(Message(id="msg1", channel_id="ch1", sender="W1",
                                    body="First", created_at=t))
        cache.save_message(Message(id="msg2", channel_id="ch1", sender="W1",
                                    body="Second", created_at=t + 60))
        msgs = cache.get_messages("ch1")
        assert msgs[0].body == "First"
        assert msgs[1].body == "Second"

    def test_no_db_returns_empty(self):
        cache = ClientCache("/tmp/test-cache")
        assert cache.get_messages("ch1") == []


# ==================================================================
# get_channel_members()
# ==================================================================

class TestGetChannelMembers:
    def test_empty(self):
        cache = _make_cache()
        assert cache.get_channel_members("ch1") == []

    def test_returns_operator_ids(self):
        cache = _make_cache()
        cache.save_channel(Channel(id="ch1", name="General", type="GENERAL"))
        op1 = _insert_operator(cache, "WOLF-1")
        op2 = _insert_operator(cache, "WOLF-2")
        cache.db.execute(
            "INSERT INTO channel_members (channel_id, operator_id) VALUES (?, ?)",
            ("ch1", op1.id),
        )
        cache.db.execute(
            "INSERT INTO channel_members (channel_id, operator_id) VALUES (?, ?)",
            ("ch1", op2.id),
        )
        cache.db.commit()

        members = cache.get_channel_members("ch1")
        assert len(members) == 2
        assert op1.id in members
        assert op2.id in members

    def test_no_db_returns_empty(self):
        cache = ClientCache("/tmp/test-cache")
        assert cache.get_channel_members("ch1") == []


# ==================================================================
# get_my_callsign()
# ==================================================================

class TestGetMyCallsign:
    def test_no_db_returns_empty(self):
        cache = ClientCache("/tmp/test-cache")
        assert cache.get_my_callsign() == ""

    def test_no_operators_returns_empty(self):
        cache = _make_cache()
        assert cache.get_my_callsign() == ""

    def test_returns_operator_callsign(self):
        cache = _make_cache()
        _insert_operator(cache, "EAGLE-3", "operator")
        assert cache.get_my_callsign() == "EAGLE-3"

    def test_caches_result(self):
        cache = _make_cache()
        _insert_operator(cache, "WOLF-1", "operator")
        assert cache.get_my_callsign() == "WOLF-1"
        # Even if we wipe the DB, cached value persists
        cache.db.execute("DELETE FROM operators")
        cache.db.commit()
        assert cache.get_my_callsign() == "WOLF-1"

    def test_set_my_callsign_overrides(self):
        cache = _make_cache()
        cache.set_my_callsign("HAWK-7")
        assert cache.get_my_callsign() == "HAWK-7"

    def test_ignores_server_role(self):
        cache = _make_cache()
        _insert_operator(cache, "SERVER-1", "server")
        assert cache.get_my_callsign() == ""


# ==================================================================
# save methods — write + read round-trips
# ==================================================================

class TestSaveSitrep:
    def test_save_and_retrieve(self):
        cache = _make_cache()
        sitrep = SITREP(id="s1", type="freeform", importance="FLASH",
                        created_by="WOLF-1")
        cache.save_sitrep(sitrep)
        result = cache.get_all("sitreps")
        assert len(result) == 1
        assert result[0].id == "s1"
        assert result[0].importance == "FLASH"

    def test_sets_sync_state_pending(self):
        cache = _make_cache()
        sitrep = SITREP(id="s1", type="freeform", created_by="W1",
                        sync_state="synced")
        cache.save_sitrep(sitrep)
        result = cache.get_all("sitreps")
        assert result[0].sync_state == "pending"

    def test_update_existing(self):
        cache = _make_cache()
        cache.save_sitrep(SITREP(id="s1", type="freeform",
                                 importance="ROUTINE", created_by="W1"))
        cache.save_sitrep(SITREP(id="s1", type="freeform",
                                 importance="FLASH", created_by="W1"))
        result = cache.get_all("sitreps")
        assert len(result) == 1
        assert result[0].importance == "FLASH"


class TestSaveSitrepEntry:
    def test_save_and_retrieve(self):
        cache = _make_cache()
        cache.save_sitrep(SITREP(id="s1", type="freeform", created_by="W1"))
        entry = SITREPEntry(id="e1", sitrep_id="s1", author="W1",
                            content="Contact report")
        cache.save_sitrep_entry(entry)
        entries = cache.get_sitrep_entries("s1")
        assert len(entries) == 1
        assert entries[0].content == "Contact report"


class TestSaveAsset:
    def test_save_and_retrieve(self):
        cache = _make_cache()
        asset = Asset(id="a1", name="Supply Cache Alpha",
                      category="SUPPLY", created_by="WOLF-1")
        cache.save_asset(asset)
        result = cache.get_all("assets")
        assert len(result) == 1
        assert result[0].name == "Supply Cache Alpha"

    def test_updates_timestamp(self):
        cache = _make_cache()
        old_time = time.time() - 3600
        asset = Asset(id="a1", name="Cache", created_by="W1",
                      updated_at=old_time)
        cache.save_asset(asset)
        result = cache.get_all("assets")
        assert result[0].updated_at > old_time


class TestSaveMission:
    def test_save_and_retrieve(self):
        cache = _make_cache()
        mission = Mission(id="m1", name="Op Nightfall", status="ACTIVE",
                          created_by="WOLF-1")
        cache.save_mission(mission)
        result = cache.get_all("missions")
        assert len(result) == 1
        assert result[0].name == "Op Nightfall"
        assert result[0].status == "ACTIVE"

    def test_updates_timestamp(self):
        cache = _make_cache()
        old_time = time.time() - 3600
        mission = Mission(id="m1", name="Op A", created_by="W1",
                          updated_at=old_time)
        cache.save_mission(mission)
        result = cache.get_all("missions")
        assert result[0].updated_at > old_time


class TestSaveObjective:
    def test_save_and_retrieve(self):
        cache = _make_cache()
        cache.save_mission(Mission(id="m1", name="Op A", created_by="W1"))
        obj = Objective(id="o1", mission_id="m1", description="Secure bridge",
                        status="IN_PROGRESS")
        cache.save_objective(obj)
        objs = cache.get_objectives("m1")
        assert len(objs) == 1
        assert objs[0].description == "Secure bridge"
        assert objs[0].status == "IN_PROGRESS"


class TestSaveMessage:
    def test_save_and_retrieve(self):
        cache = _make_cache()
        cache.save_channel(Channel(id="ch1", name="General", type="GENERAL"))
        msg = Message(id="msg1", channel_id="ch1", sender="WOLF-1",
                      body="All stations, SITREP follows")
        cache.save_message(msg)
        msgs = cache.get_messages("ch1")
        assert len(msgs) == 1
        assert msgs[0].body == "All stations, SITREP follows"


class TestSaveChannel:
    def test_save_and_retrieve(self):
        cache = _make_cache()
        ch = Channel(id="ch1", name="Mission Ops", type="MISSION",
                     mission_id="m1")
        cache.save_channel(ch)
        result = cache.get_all("channels")
        assert len(result) == 1
        assert result[0].name == "Mission Ops"
        assert result[0].type == "MISSION"


class TestSaveDocument:
    def test_save_and_retrieve(self):
        cache = _make_cache()
        doc = Document(id="d1", title="Field Manual", file_type="pdf",
                       file_path="/docs/fm.pdf", file_size=1024,
                       tags=["reference", "tactics"],
                       uploaded_by="WOLF-1")
        cache.save_document(doc)
        result = cache.get_all("documents")
        assert len(result) == 1
        assert result[0].title == "Field Manual"
        assert result[0].tags == ["reference", "tactics"]
        assert result[0].file_size == 1024


class TestSaveNoDb:
    def test_save_with_no_db_is_noop(self):
        cache = ClientCache("/tmp/test-cache")
        cache.save_sitrep(SITREP(id="s1", type="freeform", created_by="W1"))
        # Should not raise


# ==================================================================
# queue_change() and outbox integration
# ==================================================================

class TestQueueChange:
    def test_queues_with_operation(self):
        cache = _make_cache()
        cache.queue_change("sitreps", "insert", {"id": "s1"})
        pending = cache.get_pending_changes()
        assert len(pending) == 1
        assert pending[0]["table"] == "sitreps"
        assert pending[0]["operation"] == "insert"
        assert pending[0]["record"] == {"id": "s1"}

    def test_multiple_changes(self):
        cache = _make_cache()
        cache.queue_change("sitreps", "insert", {"id": "s1"})
        cache.queue_change("assets", "update", {"id": "a1"})
        cache.queue_change("sitreps", "delete", {"id": "s2"})
        pending = cache.get_pending_changes()
        assert len(pending) == 3

    def test_clear_synced(self):
        cache = _make_cache()
        cache.queue_change("sitreps", "insert", {"id": "s1"})
        assert len(cache.get_pending_changes()) == 1
        cache.clear_synced()
        assert len(cache.get_pending_changes()) == 0


# ==================================================================
# SyncClient.queue_change() delegation
# ==================================================================

from talon.client.sync_client import SyncClient


class TestSyncClientQueueChange:
    def test_delegates_to_cache(self):
        mock_cache = MagicMock()
        sync = SyncClient(cache=mock_cache)
        sync.queue_change("assets", "insert", {"id": "a1", "name": "Cache"})
        mock_cache.queue_change.assert_called_once_with(
            "assets", "insert", {"id": "a1", "name": "Cache"}
        )

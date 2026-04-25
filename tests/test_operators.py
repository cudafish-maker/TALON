"""Tests for talon.operators — profile and skills management."""
import json

import pytest

from talon.chat import send_message
from talon.documents import upload_document
from talon.operators import (
    SERVER_OPERATOR_ID,
    LocalOperatorResolutionError,
    get_operator,
    list_operators,
    require_local_operator_id,
    resolve_local_operator_id,
    update_operator_profile,
    update_operator_skills,
)
from talon.services.assets import create_asset_command
from talon.services.missions import create_mission_command
from talon.sitrep import create_sitrep


# ---------------------------------------------------------------------------
# Fixtures — enroll a test operator
# ---------------------------------------------------------------------------

def _insert_operator(conn, *, op_id=10, callsign="ALPHA", skills=None, profile=None):
    skills_json = json.dumps(skills or [])
    profile_json = json.dumps(profile or {})
    conn.execute(
        "INSERT INTO operators "
        "(id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
        "VALUES (?, ?, ?, ?, ?, 1000, 9999999999, 0)",
        (op_id, callsign, f"hash-{callsign}", skills_json, profile_json),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# get_operator
# ---------------------------------------------------------------------------

class TestGetOperator:
    def test_returns_operator(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=20, callsign="BRAVO")
        op = get_operator(conn, 20)
        assert op is not None
        assert op.callsign == "BRAVO"
        assert op.id == 20

    def test_returns_none_for_missing(self, tmp_db):
        conn, _ = tmp_db
        assert get_operator(conn, 9999) is None

    def test_deserialises_skills(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=21, callsign="CHARLIE",
                         skills=["medic", "comms"])
        op = get_operator(conn, 21)
        assert op.skills == ["medic", "comms"]

    def test_deserialises_profile(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=22, callsign="DELTA",
                         profile={"display_name": "John", "notes": "EOD"})
        op = get_operator(conn, 22)
        assert op.profile["display_name"] == "John"
        assert op.profile["notes"] == "EOD"

    def test_empty_skills_returns_list(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=23, callsign="ECHO")
        op = get_operator(conn, 23)
        assert isinstance(op.skills, list)
        assert op.skills == []

    def test_empty_profile_returns_dict(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=24, callsign="FOXTROT")
        op = get_operator(conn, 24)
        assert isinstance(op.profile, dict)
        assert op.profile == {}


# ---------------------------------------------------------------------------
# list_operators
# ---------------------------------------------------------------------------

class TestListOperators:
    def test_excludes_sentinel_by_default(self, tmp_db):
        conn, _ = tmp_db
        ops = list_operators(conn)
        assert all(op.id != 1 for op in ops)

    def test_includes_sentinel_when_requested(self, tmp_db):
        conn, _ = tmp_db
        ops = list_operators(conn, include_sentinel=True)
        ids = [op.id for op in ops]
        assert 1 in ids

    def test_returns_enrolled_operators(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=30, callsign="GOLF")
        _insert_operator(conn, op_id=31, callsign="HOTEL")
        ops = list_operators(conn)
        callsigns = [op.callsign for op in ops]
        assert "GOLF" in callsigns
        assert "HOTEL" in callsigns

    def test_empty_when_no_enrolled(self, tmp_db):
        conn, _ = tmp_db
        # Only sentinel exists — list should be empty
        ops = list_operators(conn)
        assert ops == []


# ---------------------------------------------------------------------------
# local operator resolution
# ---------------------------------------------------------------------------

class TestResolveLocalOperatorId:
    def test_server_returns_sentinel_only_when_explicitly_allowed(self, tmp_db):
        conn, _ = tmp_db
        assert resolve_local_operator_id(conn, mode="server") is None
        assert resolve_local_operator_id(
            conn,
            mode="server",
            allow_server_sentinel=True,
        ) == SERVER_OPERATOR_ID

    def test_client_prefers_non_sentinel_current_operator_id(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=60, callsign="ROMEO")
        conn.execute(
            "UPDATE meta SET value = '61' WHERE key = 'my_operator_id'"
        )
        conn.commit()

        assert resolve_local_operator_id(
            conn,
            mode="client",
            current_operator_id=60,
        ) == 60

    def test_client_ignores_sentinel_current_operator_id_and_uses_meta(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=61, callsign="SIERRA")
        conn.execute(
            "UPDATE meta SET value = '61' WHERE key = 'my_operator_id'"
        )
        conn.commit()

        assert resolve_local_operator_id(
            conn,
            mode="client",
            current_operator_id=SERVER_OPERATOR_ID,
        ) == 61

    def test_client_prefers_meta_over_other_operator_rows(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=62, callsign="TANGO")
        _insert_operator(conn, op_id=63, callsign="UNIFORM")
        conn.execute(
            "UPDATE meta SET value = '63' WHERE key = 'my_operator_id'"
        )
        conn.commit()

        assert resolve_local_operator_id(conn, mode="client") == 63

    def test_client_infers_unique_operator_when_meta_missing(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=64, callsign="VICTOR")

        assert resolve_local_operator_id(conn, mode="client") == 64

    def test_client_returns_none_when_multiple_operator_rows_and_meta_missing(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=65, callsign="WHISKEY")
        _insert_operator(conn, op_id=66, callsign="XRAY")

        assert resolve_local_operator_id(conn, mode="client") is None

    def test_client_rejects_sentinel_meta_value(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=67, callsign="YANKEE")
        _insert_operator(conn, op_id=68, callsign="ZULU")
        conn.execute(
            "UPDATE meta SET value = '1' WHERE key = 'my_operator_id'"
        )
        conn.commit()

        assert resolve_local_operator_id(conn, mode="client") is None


class TestRequireLocalOperatorId:
    def test_raises_for_unresolved_client_operator(self, tmp_db):
        conn, _ = tmp_db
        with pytest.raises(LocalOperatorResolutionError, match="Re-enroll"):
            require_local_operator_id(conn, mode="client")


def test_client_attribution_uses_enrolled_operator_for_created_records(tmp_db, test_key, tmp_path):
    conn, _ = tmp_db
    _insert_operator(conn, op_id=70, callsign="ATLAS")
    conn.execute(
        "UPDATE meta SET value = '70' WHERE key = 'my_operator_id'"
    )
    conn.execute(
        "INSERT INTO channels (id, name, mission_id, is_dm, version, group_type) "
        "VALUES (20, '#general', NULL, 0, 1, 'allhands')"
    )
    conn.commit()

    operator_id = require_local_operator_id(conn, mode="client")

    asset_result = create_asset_command(
        conn,
        author_id=operator_id,
        category="cache",
        label="CACHE-70",
    )
    sitrep_id = create_sitrep(
        conn,
        test_key,
        author_id=operator_id,
        level="ROUTINE",
        body="client-authored sitrep",
    )
    mission_result = create_mission_command(
        conn,
        title="Mission 70",
        created_by=operator_id,
        asset_ids=[asset_result.asset_id],
    )
    doc = upload_document(
        conn,
        test_key,
        tmp_path / "docs",
        raw_filename="notes.txt",
        file_data=b"client-authored document",
        uploaded_by=operator_id,
    )
    msg = send_message(conn, 20, operator_id, "client-authored message")

    assert conn.execute(
        "SELECT created_by FROM assets WHERE id = ?",
        (asset_result.asset_id,),
    ).fetchone()[0] == 70
    assert conn.execute(
        "SELECT author_id FROM sitreps WHERE id = ?",
        (sitrep_id,),
    ).fetchone()[0] == 70
    assert conn.execute(
        "SELECT created_by FROM missions WHERE id = ?",
        (mission_result.mission.id,),
    ).fetchone()[0] == 70
    assert conn.execute(
        "SELECT uploaded_by FROM documents WHERE id = ?",
        (doc.id,),
    ).fetchone()[0] == 70
    assert conn.execute(
        "SELECT sender_id FROM messages WHERE id = ?",
        (msg.id,),
    ).fetchone()[0] == 70


# ---------------------------------------------------------------------------
# update_operator_skills
# ---------------------------------------------------------------------------

class TestUpdateOperatorSkills:
    def test_saves_skills(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=40, callsign="INDIA")
        update_operator_skills(conn, 40, ["medic", "recon"])
        op = get_operator(conn, 40)
        assert op.skills == ["medic", "recon"]

    def test_replaces_existing_skills(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=41, callsign="JULIET",
                         skills=["comms", "logistics"])
        update_operator_skills(conn, 41, ["security"])
        op = get_operator(conn, 41)
        assert op.skills == ["security"]

    def test_normalises_to_lowercase(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=42, callsign="KILO")
        update_operator_skills(conn, 42, ["MEDIC", "  Comms  "])
        op = get_operator(conn, 42)
        assert "medic" in op.skills
        assert "comms" in op.skills

    def test_strips_empty_strings(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=43, callsign="LIMA")
        update_operator_skills(conn, 43, ["medic", "", "  "])
        op = get_operator(conn, 43)
        assert op.skills == ["medic"]

    def test_raises_for_missing_operator(self, tmp_db):
        conn, _ = tmp_db
        with pytest.raises(ValueError, match="not found"):
            update_operator_skills(conn, 9999, ["medic"])

    def test_clears_skills(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=44, callsign="MIKE", skills=["comms"])
        update_operator_skills(conn, 44, [])
        op = get_operator(conn, 44)
        assert op.skills == []

    def test_bumps_version(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=45, callsign="NOVA")
        before = conn.execute("SELECT version FROM operators WHERE id = 45").fetchone()[0]
        update_operator_skills(conn, 45, ["medic"])
        after = conn.execute("SELECT version FROM operators WHERE id = 45").fetchone()[0]
        assert after == before + 1


# ---------------------------------------------------------------------------
# update_operator_profile
# ---------------------------------------------------------------------------

class TestUpdateOperatorProfile:
    def test_saves_profile(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=50, callsign="NOVEMBER")
        update_operator_profile(conn, 50, {"display_name": "Nav", "notes": "EOD"})
        op = get_operator(conn, 50)
        assert op.profile["display_name"] == "Nav"
        assert op.profile["notes"] == "EOD"

    def test_replaces_existing_profile(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=51, callsign="OSCAR",
                         profile={"display_name": "Old Name"})
        update_operator_profile(conn, 51, {"display_name": "New Name"})
        op = get_operator(conn, 51)
        assert op.profile["display_name"] == "New Name"
        assert "notes" not in op.profile

    def test_raises_for_missing_operator(self, tmp_db):
        conn, _ = tmp_db
        with pytest.raises(ValueError, match="not found"):
            update_operator_profile(conn, 9999, {"notes": "x"})

    def test_clears_profile(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=52, callsign="PAPA",
                         profile={"display_name": "Old"})
        update_operator_profile(conn, 52, {})
        op = get_operator(conn, 52)
        assert op.profile == {}

    def test_bumps_version(self, tmp_db):
        conn, _ = tmp_db
        _insert_operator(conn, op_id=53, callsign="QUEBEC")
        before = conn.execute("SELECT version FROM operators WHERE id = 53").fetchone()[0]
        update_operator_profile(conn, 53, {"notes": "updated"})
        after = conn.execute("SELECT version FROM operators WHERE id = 53").fetchone()[0]
        assert after == before + 1

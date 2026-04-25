"""Tests for service command domain-event orchestration."""

from talon.missions import approve_mission, create_mission
from talon.services.assets import (
    create_asset_command,
    hard_delete_asset_command,
    request_asset_deletion_command,
    update_asset_command,
    verify_asset_command,
)
from talon.services.events import DomainEvent, expand_record_mutations
from talon.services.missions import (
    abort_mission_command,
    approve_mission_command,
    complete_mission_command,
    create_mission_command,
    delete_mission_command,
    reject_mission_command,
)
from talon.services.operators import (
    renew_operator_lease_command,
    revoke_operator_command,
    update_operator_command,
)


def _events(events: tuple[DomainEvent, ...]) -> list[tuple[str, str, int]]:
    return [
        (change.action, change.table, change.record_id)
        for change in expand_record_mutations(events)
    ]


def _insert_asset(conn, asset_id: int, label: str) -> None:
    conn.execute(
        "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version) "
        "VALUES (?, 'cache', ?, '', 0, 1, 1000, 1)",
        (asset_id, label),
    )
    conn.commit()


def _insert_sitrep_for_asset(conn, sitrep_id: int, asset_id: int) -> None:
    conn.execute(
        "INSERT INTO sitreps (id, level, template, body, author_id, asset_id, created_at, version) "
        "VALUES (?, 'ROUTINE', '', ?, 1, ?, 1000, 1)",
        (sitrep_id, b"body", asset_id),
    )
    conn.commit()


def _insert_sitrep_for_mission(conn, sitrep_id: int, mission_id: int) -> None:
    conn.execute(
        "INSERT INTO sitreps (id, level, template, body, author_id, mission_id, created_at, version) "
        "VALUES (?, 'ROUTINE', '', ?, 1, ?, 1000, 1)",
        (sitrep_id, b"body", mission_id),
    )
    conn.commit()


def test_asset_commands_return_changed_events(tmp_db):
    conn, _ = tmp_db

    created = create_asset_command(
        conn,
        author_id=1,
        category="cache",
        label="Cache A",
        description="Supplies",
        lat=43.1,
        lon=-71.2,
    )
    updated = update_asset_command(conn, created.asset_id, label="Cache B")
    verified = verify_asset_command(
        conn,
        created.asset_id,
        verified=True,
        confirmer_id=1,
    )
    deletion_requested = request_asset_deletion_command(conn, created.asset_id)

    expected = [("changed", "assets", created.asset_id)]
    assert _events(created.events) == expected
    assert _events(updated.events) == expected
    assert _events(verified.events) == expected
    assert _events(deletion_requested.events) == expected


def test_hard_delete_asset_returns_asset_delete_and_sitrep_change_events(tmp_db):
    conn, _ = tmp_db
    _insert_asset(conn, 80, "CACHE-80")
    _insert_sitrep_for_asset(conn, 90, 80)

    result = hard_delete_asset_command(conn, 80)

    assert [event.kind for event in result.events] == ["linked_records_changed"]
    assert _events(result.events) == [
        ("deleted", "assets", 80),
        ("changed", "sitreps", 90),
    ]
    assert conn.execute("SELECT id FROM assets WHERE id = 80").fetchone() is None
    assert conn.execute("SELECT asset_id FROM sitreps WHERE id = 90").fetchone()[0] is None


def test_create_mission_command_returns_events_for_linked_records(tmp_db):
    conn, _ = tmp_db
    _insert_asset(conn, 81, "CACHE-81")

    result = create_mission_command(
        conn,
        title="Mission",
        created_by=1,
        asset_ids=[81],
        ao_polygon=[[43.0, -71.0], [43.1, -71.0], [43.1, -71.1]],
        route=[(43.0, -71.0), (43.1, -71.1)],
    )

    events = _events(result.events)
    assert events[:2] == [
        ("changed", "missions", result.mission.id),
        ("changed", "assets", 81),
    ]
    assert ("changed", "zones", 1) in events
    assert ("changed", "waypoints", 1) in events
    assert ("changed", "waypoints", 2) in events


def test_approve_mission_command_returns_mission_channel_and_asset_events(tmp_db):
    conn, _ = tmp_db
    _insert_asset(conn, 82, "OLD")
    _insert_asset(conn, 83, "NEW")
    mission = create_mission(conn, title="Mission", created_by=1, asset_ids=[82])

    result = approve_mission_command(conn, mission.id, asset_ids=[83])

    channel_id = conn.execute(
        "SELECT id FROM channels WHERE mission_id = ?",
        (mission.id,),
    ).fetchone()[0]
    assert _events(result.events) == [
        ("changed", "missions", mission.id),
        ("changed", "channels", channel_id),
        ("changed", "assets", 82),
        ("changed", "assets", 83),
    ]


def test_reject_abort_and_complete_mission_commands_return_release_events(tmp_db):
    conn, _ = tmp_db
    _insert_asset(conn, 84, "REJECT")
    rejected = create_mission(conn, title="Rejected", created_by=1, asset_ids=[84])

    reject_result = reject_mission_command(conn, rejected.id)

    _insert_asset(conn, 87, "ABORT")
    aborted = create_mission(conn, title="Aborted", created_by=1, asset_ids=[87])
    approve_mission(conn, aborted.id)

    abort_result = abort_mission_command(conn, aborted.id)

    _insert_asset(conn, 85, "COMPLETE")
    completed = create_mission(conn, title="Completed", created_by=1, asset_ids=[85])
    approve_mission(conn, completed.id)

    complete_result = complete_mission_command(conn, completed.id)

    assert _events(reject_result.events) == [
        ("changed", "missions", rejected.id),
        ("changed", "assets", 84),
    ]
    assert _events(abort_result.events) == [
        ("changed", "missions", aborted.id),
        ("changed", "assets", 87),
    ]
    assert _events(complete_result.events) == [
        ("changed", "missions", completed.id),
        ("changed", "assets", 85),
    ]


def test_delete_mission_command_returns_delete_and_unlink_events(tmp_db):
    conn, _ = tmp_db
    _insert_asset(conn, 86, "CACHE-86")
    mission = create_mission_command(
        conn,
        title="Delete Me",
        created_by=1,
        asset_ids=[86],
        ao_polygon=[[43.0, -71.0], [43.1, -71.0], [43.1, -71.1]],
        route=[(43.0, -71.0)],
    ).mission
    approve = approve_mission_command(conn, mission.id)
    channel_id = next(event.record_id for event in approve.events if event.table == "channels")
    conn.execute(
        "INSERT INTO messages (id, channel_id, sender_id, body, sent_at, version) "
        "VALUES (100, ?, 1, ?, 1000, 1)",
        (channel_id, b"body"),
    )
    _insert_sitrep_for_mission(conn, 91, mission.id)

    result = delete_mission_command(conn, mission.id)

    assert [event.kind for event in result.events] == ["linked_records_changed"]
    assert _events(result.events) == [
        ("deleted", "messages", 100),
        ("deleted", "channels", channel_id),
        ("deleted", "waypoints", 1),
        ("deleted", "zones", 1),
        ("deleted", "missions", mission.id),
        ("changed", "sitreps", 91),
        ("changed", "assets", 86),
    ]


def test_update_operator_command_updates_profile_and_skills_once(tmp_db):
    conn, _ = tmp_db
    conn.execute(
        "INSERT INTO operators (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
        "VALUES (200, 'OP-200', 'abcd', '[]', '{}', 1000, 9999999999, 0)"
    )
    conn.commit()

    before = conn.execute(
        "SELECT version FROM operators WHERE id = 200"
    ).fetchone()[0]

    result = update_operator_command(
        conn,
        200,
        skills=["Medic", "  comms  ", ""],
        profile={"display_name": "Scout", "notes": "Updated"},
    )

    row = conn.execute(
        "SELECT skills, profile, version FROM operators WHERE id = 200"
    ).fetchone()
    assert row[0] == '["medic", "comms"]'
    assert row[1] == '{"display_name": "Scout", "notes": "Updated"}'
    assert row[2] == before + 1
    assert _events(result.events) == [("changed", "operators", 200)]


def test_renew_operator_lease_command_returns_specialized_event(tmp_db):
    conn, _ = tmp_db
    conn.execute(
        "INSERT INTO operators (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
        "VALUES (201, 'OP-201', 'efgh', '[]', '{}', 1000, 1200, 0)"
    )
    conn.commit()

    result = renew_operator_lease_command(conn, 201, duration_s=3600)

    assert result.events[0].kind == "lease_renewed"
    assert result.events[0].operator_id == 201
    assert result.lease_expires_at is not None
    assert _events(result.events) == [("changed", "operators", 201)]
    row = conn.execute(
        "SELECT lease_expires_at FROM operators WHERE id = 201"
    ).fetchone()
    assert row[0] == result.lease_expires_at


def test_revoke_operator_command_returns_specialized_event(tmp_db):
    conn, _ = tmp_db
    conn.execute(
        "INSERT INTO operators (id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
        "VALUES (202, 'OP-202', ?, '[]', '{}', 1000, 9999999999, 0)",
        ("f" * 64,),
    )
    conn.commit()

    result = revoke_operator_command(conn, 202)

    assert result.events[0].kind == "operator_revoked"
    assert result.events[0].operator_id == 202
    assert _events(result.events) == [("changed", "operators", 202)]
    row = conn.execute(
        "SELECT revoked, rns_hash FROM operators WHERE id = 202"
    ).fetchone()
    assert row == (1, "")

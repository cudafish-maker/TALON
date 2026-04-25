"""Tests for mission relationship version bumps."""

from talon.missions import abort_mission, approve_mission, create_mission, delete_mission, get_mission
from talon.sitrep import link_sitreps_to_mission


def _insert_asset(conn, asset_id: int, label: str) -> None:
    conn.execute(
        "INSERT INTO assets (id, category, label, description, verified, created_by, created_at, version) "
        "VALUES (?, 'cache', ?, '', 0, 1, 1000, 1)",
        (asset_id, label),
    )
    conn.commit()


def test_create_mission_bumps_requested_asset_version(tmp_db):
    conn, _ = tmp_db
    _insert_asset(conn, 80, "CACHE-80")

    mission = create_mission(conn, title="Mission", created_by=1, asset_ids=[80])

    row = conn.execute("SELECT mission_id, version FROM assets WHERE id = 80").fetchone()
    assert row == (mission.id, 2)


def test_approve_mission_bumps_changed_asset_versions(tmp_db):
    conn, _ = tmp_db
    _insert_asset(conn, 81, "OLD")
    _insert_asset(conn, 82, "NEW")
    mission = create_mission(conn, title="Mission", created_by=1, asset_ids=[81])

    approve_mission(conn, mission.id, asset_ids=[82])

    old_row = conn.execute("SELECT mission_id, version FROM assets WHERE id = 81").fetchone()
    new_row = conn.execute("SELECT mission_id, version FROM assets WHERE id = 82").fetchone()
    assert old_row == (None, 3)
    assert new_row == (mission.id, 2)


def test_transition_release_bumps_asset_version(tmp_db):
    conn, _ = tmp_db
    _insert_asset(conn, 83, "CACHE-83")
    mission = create_mission(conn, title="Mission", created_by=1, asset_ids=[83])

    abort_mission(conn, mission.id)

    row = conn.execute("SELECT mission_id, version FROM assets WHERE id = 83").fetchone()
    assert row == (None, 3)


def test_link_sitreps_to_mission_bumps_sitrep_version(tmp_db):
    conn, _ = tmp_db
    mission = create_mission(conn, title="Mission", created_by=1)
    conn.execute(
        "INSERT INTO sitreps (id, level, template, body, author_id, created_at, version) "
        "VALUES (90, 'ROUTINE', '', ?, 1, 1000, 1)",
        (b"body",),
    )
    conn.commit()

    link_sitreps_to_mission(conn, mission.id, [90])

    row = conn.execute("SELECT mission_id, version FROM sitreps WHERE id = 90").fetchone()
    assert row == (mission.id, 2)


def test_create_mission_persists_custom_variants(tmp_db):
    conn, _ = tmp_db

    mission = create_mission(
        conn,
        title="Custom",
        created_by=1,
        mission_type="TREE CLEARANCE",
        constraints=["MEDIA BLACKOUT", "LOCAL CURFEW WINDOW"],
        custom_resources=[
            {"label": "Drone overwatch", "details": "One quadcopter team"},
        ],
        key_locations={
            "medical_station": "Clinic A",
            "Drone LZ": "43.10000, -71.20000",
        },
    )

    fetched = get_mission(conn, mission.id)

    assert fetched is not None
    assert fetched.mission_type == "TREE CLEARANCE"
    assert "LOCAL CURFEW WINDOW" in fetched.constraints
    assert fetched.custom_resources == [
        {"label": "Drone overwatch", "details": "One quadcopter team"},
    ]
    assert fetched.key_locations["Drone LZ"] == "43.10000, -71.20000"


def test_delete_mission_bumps_unlinked_child_versions_before_delete(tmp_db):
    conn, _ = tmp_db
    _insert_asset(conn, 84, "CACHE-84")
    mission = create_mission(conn, title="Mission", created_by=1, asset_ids=[84])
    conn.execute(
        "INSERT INTO sitreps (id, level, template, body, author_id, mission_id, created_at, version) "
        "VALUES (91, 'ROUTINE', '', ?, 1, ?, 1000, 1)",
        (b"body", mission.id),
    )
    conn.commit()

    delete_mission(conn, mission.id)

    asset_row = conn.execute("SELECT mission_id, version FROM assets WHERE id = 84").fetchone()
    sitrep_row = conn.execute("SELECT mission_id, version FROM sitreps WHERE id = 91").fetchone()
    assert asset_row == (None, 3)
    assert sitrep_row == (None, 2)

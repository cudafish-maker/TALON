"""Tests for shared operational map context loading."""

from talon.assets import create_asset
from talon.missions import create_mission
from talon.ui.widgets.map_data import load_map_context
from talon.waypoints import create_waypoints_for_mission
from talon.zones import create_zone


def test_load_map_context_includes_operational_records(tmp_db):
    conn, _ = tmp_db
    asset_id = create_asset(
        conn,
        author_id=1,
        category="cache",
        label="Water cache",
        lat=43.1,
        lon=-71.2,
    )
    mission = create_mission(conn, title="Route survey", created_by=1)
    create_zone(
        conn,
        zone_type="AO",
        label="Survey AO",
        polygon=[[43.0, -71.0], [43.2, -71.0], [43.2, -71.3]],
        mission_id=mission.id,
        created_by=1,
    )
    create_waypoints_for_mission(
        conn,
        mission.id,
        [(43.05, -71.05), (43.15, -71.18)],
    )

    context = load_map_context(conn)

    assert [asset.id for asset in context.assets] == [asset_id]
    assert [zone.label for zone in context.zones] == ["Survey AO"]
    assert [wp.sequence for wp in context.waypoints] == [1, 2]
    assert context.missions_by_id[mission.id].title == "Route survey"


def test_load_map_context_filters_mission_scoped_overlays(tmp_db):
    conn, _ = tmp_db
    create_asset(
        conn,
        author_id=1,
        category="rally_point",
        label="Global RP",
        lat=42.9,
        lon=-71.1,
    )
    mission_a_asset = create_asset(
        conn,
        author_id=1,
        category="vehicle",
        label="Mission A truck",
        lat=43.05,
        lon=-71.05,
    )
    mission_b_asset = create_asset(
        conn,
        author_id=1,
        category="vehicle",
        label="Mission B truck",
        lat=44.05,
        lon=-72.05,
    )
    mission_a = create_mission(conn, title="Mission A", created_by=1)
    mission_b = create_mission(conn, title="Mission B", created_by=1)
    conn.execute(
        "UPDATE assets SET mission_id = ? WHERE id = ?",
        (mission_a.id, mission_a_asset),
    )
    conn.execute(
        "UPDATE assets SET mission_id = ? WHERE id = ?",
        (mission_b.id, mission_b_asset),
    )
    conn.commit()
    create_zone(
        conn,
        zone_type="AO",
        label="A AO",
        polygon=[[43.0, -71.0], [43.1, -71.0], [43.1, -71.1]],
        mission_id=mission_a.id,
        created_by=1,
    )
    create_zone(
        conn,
        zone_type="AO",
        label="B AO",
        polygon=[[44.0, -72.0], [44.1, -72.0], [44.1, -72.1]],
        mission_id=mission_b.id,
        created_by=1,
    )
    create_waypoints_for_mission(conn, mission_a.id, [(43.0, -71.0)])
    create_waypoints_for_mission(conn, mission_b.id, [(44.0, -72.0)])

    context = load_map_context(conn, mission_id=mission_a.id)

    assert [asset.label for asset in context.assets] == ["Mission A truck"]
    assert [zone.label for zone in context.zones] == ["A AO"]
    assert [wp.mission_id for wp in context.waypoints] == [mission_a.id]


def test_selected_mission_overlays_hide_unselected_routes_and_areas(tmp_db):
    conn, _ = tmp_db
    create_asset(
        conn,
        author_id=1,
        category="cache",
        label="Shared cache",
        lat=42.8,
        lon=-71.0,
    )
    mission_a = create_mission(conn, title="Mission A", created_by=1)
    mission_b = create_mission(conn, title="Mission B", created_by=1)
    create_zone(
        conn,
        zone_type="DANGER",
        label="Standalone hazard",
        polygon=[[42.0, -71.0], [42.1, -71.0], [42.1, -71.1]],
        mission_id=None,
        created_by=1,
    )
    create_zone(
        conn,
        zone_type="AO",
        label="A AO",
        polygon=[[43.0, -71.0], [43.1, -71.0], [43.1, -71.1]],
        mission_id=mission_a.id,
        created_by=1,
    )
    create_zone(
        conn,
        zone_type="AO",
        label="B AO",
        polygon=[[44.0, -72.0], [44.1, -72.0], [44.1, -72.1]],
        mission_id=mission_b.id,
        created_by=1,
    )
    create_waypoints_for_mission(conn, mission_a.id, [(43.0, -71.0)])
    create_waypoints_for_mission(conn, mission_b.id, [(44.0, -72.0)])

    context = load_map_context(conn)
    unselected = context.with_selected_mission_overlays(None)
    selected_a = context.with_selected_mission_overlays(mission_a.id)

    assert [asset.label for asset in unselected.assets] == ["Shared cache"]
    assert [zone.label for zone in unselected.zones] == ["Standalone hazard"]
    assert unselected.waypoints == []
    assert {zone.label for zone in selected_a.zones} == {"Standalone hazard", "A AO"}
    assert [wp.mission_id for wp in selected_a.waypoints] == [mission_a.id]


def test_visible_assets_include_selected_mission_assets(tmp_db):
    conn, _ = tmp_db
    baseline_id = create_asset(
        conn,
        author_id=1,
        category="cache",
        label="Baseline cache",
        lat=42.8,
        lon=-71.0,
    )
    mission_asset_id = create_asset(
        conn,
        author_id=1,
        category="vehicle",
        label="Mission truck",
        lat=43.0,
        lon=-71.2,
    )
    hidden_id = create_asset(
        conn,
        author_id=1,
        category="person",
        label="Hidden observer",
        lat=44.0,
        lon=-72.0,
    )
    mission = create_mission(
        conn,
        title="Asset union mission",
        created_by=1,
        asset_ids=[mission_asset_id],
    )

    context = load_map_context(conn)
    visible = context.with_visible_assets(
        {baseline_id},
        selected_mission_id=mission.id,
    )

    assert {asset.id for asset in visible.assets} == {baseline_id, mission_asset_id}
    assert hidden_id not in {asset.id for asset in visible.assets}

# tests/test_models.py
# Tests for the business logic in talon/models/.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.db.models import Asset, Document, Objective, Zone
from talon.models.asset import can_verify, validate_asset
from talon.models.chat import (
    can_delete_message,
    can_send_message,
    create_channel,
    create_direct_channel,
)
from talon.models.document import (
    can_view_document,
    create_document,
    validate_document,
)
from talon.models.mission import (
    can_abort_mission,
    can_update_objective,
    create_mission,
)
from talon.models.operator import can_edit_profile, get_available_skills
from talon.models.route import (
    _haversine,
    calculate_route_distance,
    create_route,
    create_waypoint,
)
from talon.models.sitrep import (
    can_delete_sitrep,
    create_sitrep,
    get_available_templates,
    get_template,
)
from talon.models.zone import can_delete_zone, create_zone, validate_zone

# ---------- Operator ----------


def test_operator_can_edit_own_profile():
    assert can_edit_profile("Alpha", "Alpha", "operator") is True


def test_operator_cannot_edit_other_profile():
    assert can_edit_profile("Alpha", "Bravo", "operator") is False


def test_server_can_edit_any_profile():
    assert can_edit_profile("Server", "Alpha", "server") is True


def test_get_skills_includes_defaults():
    skills = get_available_skills()
    assert len(skills) > 0


def test_get_skills_with_custom():
    skills = get_available_skills(["Drone Pilot", "K9 Handler"])
    assert "Drone Pilot" in skills
    assert "K9 Handler" in skills


# ---------- Asset ----------


def test_cannot_verify_own_asset():
    asset = Asset(name="Cache Alpha", category="SUPPLY_CACHE", created_by="Alpha", verification="unverified")
    assert can_verify(asset, "Alpha", "operator") is False


def test_other_operator_can_verify():
    asset = Asset(name="Cache Alpha", category="SUPPLY_CACHE", created_by="Alpha", verification="unverified")
    assert can_verify(asset, "Bravo", "operator") is True


def test_server_can_verify():
    asset = Asset(name="Cache Alpha", category="SUPPLY_CACHE", created_by="Alpha", verification="unverified")
    assert can_verify(asset, "Server", "server") is True


def test_cannot_verify_already_verified():
    asset = Asset(name="Cache Alpha", category="SUPPLY_CACHE", created_by="Alpha", verification="verified")
    assert can_verify(asset, "Bravo", "operator") is False


def test_validate_asset_missing_name():
    asset = Asset(name="", category="VEHICLE", created_by="Alpha")
    errors = validate_asset(asset)
    assert "Asset name is required" in errors


# ---------- SITREP ----------


def test_create_sitrep():
    sitrep = create_sitrep("Alpha", importance="PRIORITY")
    assert sitrep.created_by == "Alpha"
    assert sitrep.importance == "PRIORITY"


def test_sitrep_templates_exist():
    templates = get_available_templates()
    assert "standard" in templates
    assert "contact" in templates
    assert "medevac" in templates


def test_get_template():
    template = get_template("medevac")
    assert template is not None
    assert "sections" in template
    assert "Location (Grid Reference)" in template["sections"]


def test_only_server_can_delete_sitrep():
    assert can_delete_sitrep("server") is True
    assert can_delete_sitrep("operator") is False


# ---------- Mission ----------


def test_create_mission():
    mission = create_mission("Operation Eagle", "Alpha")
    assert mission.name == "Operation Eagle"
    assert mission.created_by == "Alpha"


def test_assigned_operator_can_update_objective():
    obj = Objective(mission_id="m1", description="Secure LZ", assigned_to="Bravo")
    assert can_update_objective("Bravo", obj, "operator") is True


def test_unassigned_operator_cannot_update_objective():
    obj = Objective(mission_id="m1", description="Secure LZ", assigned_to="Bravo")
    assert can_update_objective("Charlie", obj, "operator") is False


def test_server_can_update_any_objective():
    obj = Objective(mission_id="m1", description="Secure LZ", assigned_to="Bravo")
    assert can_update_objective("Server", obj, "server") is True


def test_only_server_can_abort():
    assert can_abort_mission("server") is True
    assert can_abort_mission("operator") is False


# ---------- Route ----------


def test_haversine_same_point():
    """Distance from a point to itself should be 0."""
    assert _haversine(34.0, -118.0, 34.0, -118.0) == 0.0


def test_haversine_known_distance():
    """Rough check: LA to NYC is about 3,940 km."""
    distance = _haversine(34.05, -118.24, 40.71, -74.01)
    assert 3_900_000 < distance < 4_000_000  # metres


def test_create_route():
    route = create_route("MSR Tampa", "Alpha")
    assert route.name == "MSR Tampa"


def test_route_distance_empty():
    assert calculate_route_distance([]) == 0.0


def test_route_distance_single_point():
    wp = create_waypoint("A", 34.0, -118.0, "Alpha")
    assert calculate_route_distance([wp]) == 0.0


# ---------- Zone ----------


def test_create_zone():
    zone = create_zone("AO Eagle", "Alpha", zone_type="AO", boundary='[{"lat": 34.0, "lon": -118.0}]')
    assert zone.name == "AO Eagle"


def test_validate_zone_missing_name():
    zone = Zone(name="", created_by="Alpha", boundary=["point1"])
    errors = validate_zone(zone)
    assert "Zone name is required" in errors


def test_zone_delete_permissions():
    zone = Zone(name="AO", created_by="Alpha")
    assert can_delete_zone("Alpha", zone, "operator") is True
    assert can_delete_zone("Bravo", zone, "operator") is False
    assert can_delete_zone("Server", zone, "server") is True


# ---------- Chat ----------


def test_create_channel():
    channel = create_channel("General", "Alpha", channel_type="GROUP")
    assert channel.name == "General"


def test_direct_channel_name_consistent():
    """DM channel name should be the same regardless of who initiates."""
    ch1 = create_direct_channel("Alpha", "Bravo")
    ch2 = create_direct_channel("Bravo", "Alpha")
    assert ch1.name == ch2.name


def test_can_send_if_member():
    assert can_send_message("Alpha", ["Alpha", "Bravo"]) is True


def test_cannot_send_if_not_member():
    assert can_send_message("Charlie", ["Alpha", "Bravo"]) is False


def test_only_server_can_delete_messages():
    assert can_delete_message("server") is True
    assert can_delete_message("operator") is False


# ---------- Document ----------


def test_create_document():
    doc = create_document("Map Overlay", "Alpha", "overlays/ao.png", file_size=50000, mime_type="image/png")
    assert doc.title == "Map Overlay"
    assert doc.access_level == "ALL"


def test_validate_document_missing_name():
    doc = Document(title="", uploaded_by="Alpha", file_path="intel/report.pdf")
    errors = validate_document(doc)
    assert "Document name is required" in errors


def test_document_access_all():
    doc = Document(title="Map", uploaded_by="Alpha", file_path="map.png", access_level="ALL")
    assert can_view_document(doc, "Bravo", "operator") is True


def test_document_access_restricted():
    doc = Document(title="Notes", uploaded_by="Alpha", file_path="notes.txt", access_level="RESTRICTED")
    assert can_view_document(doc, "Alpha", "operator") is True
    assert can_view_document(doc, "Bravo", "operator") is False


def test_document_access_server_sees_all():
    doc = Document(title="Intel", uploaded_by="Alpha", file_path="intel.pdf", access_level="RESTRICTED")
    # Server can always view
    assert can_view_document(doc, "Server", "server") is True

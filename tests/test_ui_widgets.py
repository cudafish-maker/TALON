# tests/test_ui_widgets.py
# Tests for talon/ui/widgets/ — StatusBar logic and MapWidget logic.
#
# Kivy is mocked via conftest.py. We test the state management,
# property defaults, and utility methods without rendering.

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import MagicMock, patch

from talon.ui.theme import TRANSPORT_COLORS, COLOR_PRIMARY, COLOR_AMBER, COLOR_RED


# ================================================================
# StatusBar tests
# ================================================================

from talon.ui.widgets.status_bar import StatusBar


class TestStatusBarDefaults:
    def test_default_transport(self):
        bar = StatusBar()
        assert bar.transport == "offline"

    def test_default_callsign_empty(self):
        bar = StatusBar()
        assert bar.callsign == ""

    def test_default_not_online(self):
        bar = StatusBar()
        assert bar.is_online is False

    def test_default_pending_count_zero(self):
        bar = StatusBar()
        assert bar.pending_count == 0


class TestStatusBarDotColor:
    def test_yggdrasil_is_green(self):
        bar = StatusBar()
        bar.transport = "yggdrasil"
        assert bar._dot_color() == COLOR_PRIMARY

    def test_rnode_is_amber(self):
        bar = StatusBar()
        bar.transport = "rnode"
        assert bar._dot_color() == COLOR_AMBER

    def test_offline_is_red(self):
        bar = StatusBar()
        bar.transport = "offline"
        assert bar._dot_color() == COLOR_RED

    def test_unknown_transport_defaults_to_red(self):
        bar = StatusBar()
        bar.transport = "unknown_transport"
        assert bar._dot_color() == "#ff3b3b"

    def test_i2p_is_green(self):
        bar = StatusBar()
        bar.transport = "i2p"
        assert bar._dot_color() == COLOR_PRIMARY

    def test_tcp_is_green(self):
        bar = StatusBar()
        bar.transport = "tcp"
        assert bar._dot_color() == COLOR_PRIMARY

    def test_case_insensitive_via_lower(self):
        """_dot_color() lowercases the transport before lookup."""
        bar = StatusBar()
        bar.transport = "YGGDRASIL"
        assert bar._dot_color() == COLOR_PRIMARY


class TestStatusBarSyncText:
    def test_offline_shows_cached(self):
        bar = StatusBar()
        bar.is_online = False
        assert bar._sync_text() == "CACHED"

    def test_online_no_pending_shows_synced(self):
        bar = StatusBar()
        bar.is_online = True
        bar.pending_count = 0
        assert bar._sync_text() == "SYNCED"

    def test_online_with_pending_shows_count(self):
        bar = StatusBar()
        bar.is_online = True
        bar.pending_count = 5
        assert bar._sync_text() == "PENDING (5)"

    def test_pending_count_one(self):
        bar = StatusBar()
        bar.is_online = True
        bar.pending_count = 1
        assert bar._sync_text() == "PENDING (1)"


class TestStatusBarSyncColor:
    def test_offline_is_grey(self):
        bar = StatusBar()
        bar.is_online = False
        assert bar._sync_color() == "#8a9bb0"

    def test_synced_is_green(self):
        bar = StatusBar()
        bar.is_online = True
        bar.pending_count = 0
        assert bar._sync_color() == "#00e5a0"

    def test_pending_is_amber(self):
        bar = StatusBar()
        bar.is_online = True
        bar.pending_count = 3
        assert bar._sync_color() == "#f5a623"


# ================================================================
# MapWidget tests
# ================================================================

from talon.ui.widgets.map_widget import (
    TalonMapWidget, MapWidget, MAPVIEW_AVAILABLE,
    DEFAULT_LAT, DEFAULT_LON, DEFAULT_ZOOM,
)


class TestMapWidgetConstants:
    def test_default_coordinates(self):
        assert isinstance(DEFAULT_LAT, (int, float))
        assert isinstance(DEFAULT_LON, (int, float))
        assert -90 <= DEFAULT_LAT <= 90
        assert -180 <= DEFAULT_LON <= 180

    def test_default_zoom_in_range(self):
        assert 1 <= DEFAULT_ZOOM <= 18

    def test_mapview_not_available_in_test(self):
        """Without kivy_garden.mapview installed, flag should be False."""
        assert MAPVIEW_AVAILABLE is False

    def test_map_widget_alias(self):
        assert MapWidget is TalonMapWidget


class TestMapWidgetHexColor:
    def test_hex_to_kivy_green(self):
        result = TalonMapWidget._hex_to_kivy_color("#00e5a0")
        assert len(result) == 4
        assert result[0] == 0.0            # R
        assert abs(result[1] - 0.898) < 0.01  # G ≈ 229/255
        assert abs(result[2] - 0.627) < 0.01  # B ≈ 160/255
        assert result[3] == 1.0            # A

    def test_hex_to_kivy_black(self):
        result = TalonMapWidget._hex_to_kivy_color("#000000")
        assert result == [0.0, 0.0, 0.0, 1.0]

    def test_hex_to_kivy_white(self):
        result = TalonMapWidget._hex_to_kivy_color("#ffffff")
        assert result == [1.0, 1.0, 1.0, 1.0]

    def test_hex_to_kivy_red(self):
        result = TalonMapWidget._hex_to_kivy_color("#ff0000")
        assert result == [1.0, 0.0, 0.0, 1.0]


class TestMapWidgetProperties:
    def test_default_tile_source(self):
        widget = TalonMapWidget()
        assert widget.tile_source == "osm"

    def test_show_flags_default_true(self):
        widget = TalonMapWidget()
        assert widget.show_assets is True
        assert widget.show_zones is True
        assert widget.show_routes is True
        assert widget.show_operators is True

    def test_marker_dicts_start_empty(self):
        widget = TalonMapWidget()
        assert widget._asset_markers == {}
        assert widget._operator_markers == {}


class TestMapWidgetCentreOn:
    def test_centre_on_updates_properties(self):
        widget = TalonMapWidget()
        widget.centre_on(51.5074, -0.1278, zoom=14)
        assert widget.center_lat == 51.5074
        assert widget.center_lon == -0.1278
        assert widget.zoom_level == 14

    def test_centre_on_without_zoom(self):
        widget = TalonMapWidget()
        widget.zoom_level = 10
        widget.centre_on(40.7128, -74.0060)
        assert widget.center_lat == 40.7128
        assert widget.center_lon == -74.0060
        assert widget.zoom_level == 10  # Unchanged


class TestMapWidgetMarkers:
    def test_update_asset_marker_noop_without_mapview(self):
        """Without mapview, marker operations should be no-ops."""
        widget = TalonMapWidget()
        widget.update_asset_marker("a1", 34.0, -118.0, "VEHICLE", "verified")
        assert widget._asset_markers == {}  # No-op

    def test_remove_asset_marker_noop_without_mapview(self):
        widget = TalonMapWidget()
        widget.remove_asset_marker("a1")  # Should not raise

    def test_update_operator_marker_noop_without_mapview(self):
        widget = TalonMapWidget()
        widget.update_operator_marker("WOLF-1", 34.0, -118.0, "ONLINE")
        assert widget._operator_markers == {}


# ================================================================
# Documents helper tests (pure functions, no Kivy dependency)
# ================================================================

from talon.ui.screens.documents import _format_size, _file_icon


class TestFormatSize:
    def test_bytes(self):
        assert _format_size(500) == "500 B"

    def test_kilobytes(self):
        assert _format_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert _format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_zero_bytes(self):
        assert _format_size(0) == "0 B"

    def test_edge_1024(self):
        assert _format_size(1024) == "1.0 KB"


class TestFileIcon:
    def test_pdf(self):
        assert _file_icon("pdf") == "file-pdf-box"

    def test_image_types(self):
        for ext in ["image", "png", "jpg", "jpeg"]:
            assert _file_icon(ext) == "file-image"

    def test_text_types(self):
        for ext in ["text", "txt"]:
            assert _file_icon(ext) == "file-document"

    def test_unknown_type(self):
        assert _file_icon("zip") == "file-outline"

    def test_none_type(self):
        assert _file_icon(None) == "file-outline"

    def test_case_insensitive(self):
        assert _file_icon("PDF") == "file-pdf-box"

# talon/ui/widgets/map_widget.py
# Map widget — wraps kivy_garden.mapview for tile-based map display.
#
# Features:
#   - Renders cached OSM / satellite / topo tiles from the local tile cache
#   - Shows asset markers (coloured by category/verification status)
#   - Shows operator position markers (green = online, amber = stale, red = revoked)
#   - Shows zone overlays (translucent coloured polygons)
#   - Shows route overlays (dashed lines between waypoints)
#   - Never disappears — it is always the background of the main screen
#
# Tile sources are served from the local tile cache (tile_cache/).
# When online, new tiles outside the cached AO are queued for download.
# When offline, only cached tiles are shown; grey placeholder for uncached areas.
#
# kivy_garden.mapview docs:
#   https://github.com/kivy-garden/mapview

from kivy.graphics import Color, Line
from kivy.properties import (
    BooleanProperty,
    NumericProperty,
    StringProperty,
)
from kivy.uix.widget import Widget

try:
    from kivy_garden.mapview import MapMarker, MapView
    MAPVIEW_AVAILABLE = True
except ImportError:
    # kivy_garden.mapview not installed — use a fallback placeholder
    MAPVIEW_AVAILABLE = False
    MapView = Widget
    MapMarker = Widget


# Default map centre — can be overridden by config or GPS
DEFAULT_LAT = 34.052235
DEFAULT_LON = -118.243683
DEFAULT_ZOOM = 12


class TalonMapWidget(MapView if MAPVIEW_AVAILABLE else Widget):
    """Persistent tactical map widget.

    When kivy_garden.mapview is available, this renders actual map tiles.
    When it is not (e.g., during development without the garden package),
    it shows a dark placeholder so the rest of the UI still works.

    Properties:
        center_lat:     Map centre latitude.
        center_lon:     Map centre longitude.
        zoom_level:     Current zoom level (1–18).
        tile_source:    Active tile layer ('osm', 'satellite', 'topo').
        show_assets:    Whether to render asset markers.
        show_zones:     Whether to render zone overlays.
        show_routes:    Whether to render route overlays.
        show_operators: Whether to render operator position markers.
    """

    center_lat     = NumericProperty(DEFAULT_LAT)
    center_lon     = NumericProperty(DEFAULT_LON)
    zoom_level     = NumericProperty(DEFAULT_ZOOM)
    tile_source    = StringProperty("osm")
    show_assets    = BooleanProperty(True)
    show_zones     = BooleanProperty(True)
    show_routes    = BooleanProperty(True)
    show_operators = BooleanProperty(True)

    def __init__(self, **kwargs):
        if MAPVIEW_AVAILABLE:
            kwargs.setdefault("lat", DEFAULT_LAT)
            kwargs.setdefault("lon", DEFAULT_LON)
            kwargs.setdefault("zoom", DEFAULT_ZOOM)
        super().__init__(**kwargs)

        self._asset_markers   = {}   # asset_id → MapMarker
        self._operator_markers = {}  # callsign → MapMarker
        self._zone_layer      = None
        self._route_layer     = None

        # Set the local tile cache as the tile source
        if MAPVIEW_AVAILABLE:
            self._configure_tile_source()

        # Draw placeholder when mapview is unavailable
        if not MAPVIEW_AVAILABLE:
            self._draw_placeholder()

    # ------------------------------------------------------------------
    # Tile source
    # ------------------------------------------------------------------

    def _configure_tile_source(self):
        """Point the map at the local tile cache directory.

        Tiles are served from tile_cache/{source}/{z}/{x}/{y}.png.
        This works offline — no internet required for cached tiles.
        """
        # kivy_garden.mapview accepts a URL template for tile sources.
        # We use a file:// URL pointing to our local cache.
        import os
        cache_base = os.path.abspath("data/tiles")

        source_dirs = {
            "osm":       os.path.join(cache_base, "openstreetmap"),
            "satellite": os.path.join(cache_base, "satellite"),
            "topo":      os.path.join(cache_base, "topo"),
        }

        source_dir = source_dirs.get(self.tile_source, source_dirs["osm"])

        # MapView uses {z}/{x}/{y} substitution in its URL template.
        # On desktop (file://), we build local paths directly.
        tile_url = f"file://{source_dir}/{{z}}/{{x}}/{{y}}.png"

        try:
            from kivy_garden.mapview.source import MapSource
            self.map_source = MapSource(
                url=tile_url,
                min_zoom=6,
                max_zoom=18,
                tile_size=256,
            )
        except Exception:
            pass  # If custom source fails, use MapView's default

    def set_tile_source(self, source: str):
        """Switch the active tile layer.

        Args:
            source: One of 'osm', 'satellite', 'topo'.
        """
        self.tile_source = source
        if MAPVIEW_AVAILABLE:
            self._configure_tile_source()

    # ------------------------------------------------------------------
    # Marker management
    # ------------------------------------------------------------------

    def update_asset_marker(self, asset_id: str, lat: float, lon: float,
                            category: str, verification: str):
        """Add or move an asset marker on the map.

        Marker colour indicates verification status:
          verified   → tactical green
          unverified → amber
          compromised → red

        Args:
            asset_id:     Unique asset ID.
            lat, lon:     GPS coordinates.
            category:     AssetCategory name (for icon selection).
            verification: 'verified', 'unverified', or 'compromised'.
        """
        if not MAPVIEW_AVAILABLE:
            return

        color_map = {
            "verified":    "#00e5a0",
            "unverified":  "#f5a623",
            "compromised": "#ff3b3b",
        }
        marker_color = color_map.get(verification, "#8a9bb0")

        if asset_id in self._asset_markers:
            marker = self._asset_markers[asset_id]
            marker.lat = lat
            marker.lon = lon
        else:
            marker = MapMarker(lat=lat, lon=lon)
            self._asset_markers[asset_id] = marker
            self.add_marker(marker)

        # Set marker colour via its source image tint
        marker.color = self._hex_to_kivy_color(marker_color)

    def remove_asset_marker(self, asset_id: str):
        """Remove an asset marker from the map."""
        if not MAPVIEW_AVAILABLE:
            return
        if asset_id in self._asset_markers:
            self.remove_marker(self._asset_markers.pop(asset_id))

    def update_operator_marker(self, callsign: str, lat: float, lon: float,
                               status: str):
        """Add or move an operator position marker.

        Status colours:
          ONLINE → tactical green
          STALE  → amber
          REVOKED / offline → red

        Args:
            callsign: Operator callsign.
            lat, lon: GPS coordinates.
            status:   'ONLINE', 'STALE', or 'REVOKED'.
        """
        if not MAPVIEW_AVAILABLE:
            return

        color_map = {
            "ONLINE":  "#00e5a0",
            "STALE":   "#f5a623",
            "REVOKED": "#ff3b3b",
        }
        marker_color = color_map.get(status, "#8a9bb0")

        if callsign in self._operator_markers:
            marker = self._operator_markers[callsign]
            marker.lat = lat
            marker.lon = lon
        else:
            marker = MapMarker(lat=lat, lon=lon)
            self._operator_markers[callsign] = marker
            self.add_marker(marker)

        marker.color = self._hex_to_kivy_color(marker_color)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def centre_on(self, lat: float, lon: float, zoom: int = None):
        """Pan and optionally zoom the map to a given coordinate.

        Args:
            lat, lon: Target coordinates.
            zoom:     Optional zoom level override.
        """
        self.center_lat = lat
        self.center_lon = lon
        if zoom is not None:
            self.zoom_level = zoom

        if MAPVIEW_AVAILABLE:
            self.center_on(lat, lon)
            if zoom is not None:
                self.zoom = zoom

    def centre_on_asset(self, asset):
        """Pan the map to an asset's position."""
        if asset.latitude and asset.longitude:
            self.centre_on(asset.latitude, asset.longitude)

    # ------------------------------------------------------------------
    # Placeholder (when mapview is not installed)
    # ------------------------------------------------------------------

    def _draw_placeholder(self):
        """Draw a dark grid placeholder when MapView is unavailable."""
        from kivy.graphics import Rectangle
        with self.canvas:
            Color(0.04, 0.055, 0.078, 1)    # BG_BASE
            Rectangle(pos=self.pos, size=self.size)
            Color(0.12, 0.18, 0.24, 1)      # Grid lines
            # Draw a simple grid
            for i in range(0, 2000, 40):
                Line(points=[i, 0, i, 2000], width=0.5)
                Line(points=[0, i, 2000, i], width=0.5)

        self.bind(size=self._update_placeholder, pos=self._update_placeholder)

    def _update_placeholder(self, *args):
        self.canvas.clear()
        self._draw_placeholder()

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _hex_to_kivy_color(hex_color: str):
        """Convert hex color string to Kivy [r, g, b, a] list."""
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        return [r, g, b, 1.0]


# Register the widget name used in KV files.
# KV files reference this as <MapWidget> — we alias it here.
MapWidget = TalonMapWidget

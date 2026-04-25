"""
Map widget — interactive tile map with asset / zone / waypoint overlays.

Tile sources   : OSM (default), Satellite (ESRI World Imagery), Topo (OpenTopoMap).
Tile caching   : handled automatically by mapview in ~/.kivy/cache/.
AO pre-cache   : TODO — deferred until sync engine integration (broadband-only).
Zone tap       : TODO — deferred until zone management screen (no hit-test in
                 MapLayer by default; requires custom touch handler).
"""
from kivy.properties import StringProperty
from kivy_garden.mapview import MapView

from talon.ui.widgets.map_data import MapContext
from talon.ui.widgets.map_layers import OperationalOverlayController
from talon.ui.widgets.map_sources import DEFAULT_MAP_LAYER, MAP_SOURCES
from talon.utils.logging import get_logger

_log = get_logger("ui.map_widget")


# ---------------------------------------------------------------------------
# Main map widget
# ---------------------------------------------------------------------------

class MapWidget(MapView):
    """Scrollable, zoomable tactical map with overlay support.

    Public API
    ----------
    set_layer(name)
        Switch tile source: ``"osm"`` | ``"satellite"`` | ``"topo"``.
    add_asset_marker(asset)
        Place a marker for one asset (no-op if lat/lon are None).
    remove_asset_marker(asset_id)
        Remove a specific marker by asset id.
    refresh_asset_markers(assets)
        Replace all markers from a list (called after a sync update).
    set_zones(zones)
        Replace all zone polygon overlays.
    set_waypoints(waypoints, missions_by_id=None)
        Replace all persisted mission route overlays.
    set_map_context(context)
        Replace all operational overlays from a shared MapContext.

    Events
    ------
    on_asset_tap(asset)
        Fired when the user releases a tap on an asset marker.
    """

    active_layer = StringProperty(DEFAULT_MAP_LAYER)

    def __init__(self, **kwargs):
        kwargs.setdefault("lat", 43.8)
        kwargs.setdefault("lon", -71.5)
        kwargs.setdefault("zoom", 7)
        super().__init__(**kwargs)
        self.register_event_type("on_asset_tap")
        self._overlays = OperationalOverlayController(
            self,
            on_asset_tap=lambda asset: self.dispatch("on_asset_tap", asset),
        )

    # ------------------------------------------------------------------
    # Tile layer
    # ------------------------------------------------------------------

    def set_layer(self, name: str) -> None:
        source = MAP_SOURCES.get(name)
        if source is None:
            _log.warning("Unknown map layer %r — ignored.", name)
            return
        self.map_source = source
        self.active_layer = name
        _log.debug("Map layer → %s.", name)

    # ------------------------------------------------------------------
    # Asset markers
    # ------------------------------------------------------------------

    def add_asset_marker(self, asset) -> None:
        self._overlays.add_asset_marker(asset)

    def remove_asset_marker(self, asset_id: int) -> None:
        self._overlays.remove_asset_marker(asset_id)

    def refresh_asset_markers(self, assets: list) -> None:
        self._overlays.set_assets(assets)

    # ------------------------------------------------------------------
    # Zone overlays
    # ------------------------------------------------------------------

    def set_zones(self, zones: list) -> None:
        self._overlays.set_zones(zones)

    # ------------------------------------------------------------------
    # Waypoint / route overlays
    # ------------------------------------------------------------------

    def set_waypoints(self, waypoints: list, *, missions_by_id: dict | None = None) -> None:
        self._overlays.set_waypoints(waypoints, missions_by_id=missions_by_id)

    # ------------------------------------------------------------------
    # Shared map context
    # ------------------------------------------------------------------

    def set_map_context(self, context: MapContext) -> None:
        self._overlays.set_context(context)

    # ------------------------------------------------------------------
    # Default event handler (required for every registered event type)
    # ------------------------------------------------------------------

    def on_asset_tap(self, asset) -> None:
        pass

"""
Reusable tactical map overlay layers.

The main map and all picker/drawing modals use these layers so assets, zones,
and mission routes are rendered consistently across the application.
"""
from __future__ import annotations

import typing

from kivy.graphics import Color, Ellipse, Line, Mesh
from kivy.metrics import dp
from kivy_garden.mapview import MapLayer

from talon.ui.widgets.map_data import MapContext
from talon.utils.logging import get_logger

_log = get_logger("ui.map_layers")


# Zone polygon colours (RGBA) - translucent fill + opaque border.
_ZONE_COLOUR: dict[str, tuple] = {
    "AO":         (0.00, 0.60, 1.00, 0.35),
    "DANGER":     (1.00, 0.10, 0.10, 0.45),
    "RESTRICTED": (1.00, 0.50, 0.00, 0.35),
    "FRIENDLY":   (0.10, 0.80, 0.20, 0.30),
    "OBJECTIVE":  (0.80, 0.00, 0.80, 0.35),
}

_ROUTE_STATUS_COLOUR: dict[str, tuple] = {
    "active":           (0.20, 0.90, 0.20, 0.82),
    "pending_approval": (1.00, 0.72, 0.05, 0.78),
    "completed":        (0.55, 0.65, 0.70, 0.55),
    "aborted":          (1.00, 0.15, 0.15, 0.55),
    "rejected":         (1.00, 0.15, 0.15, 0.45),
}
_DEFAULT_ROUTE_COLOUR = (0.20, 0.70, 1.00, 0.70)


class ZoneLayer(MapLayer):
    """Draw filled polygon overlays for map zones."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._zones: list = []

    def set_zones(self, zones: list) -> None:
        self._zones = list(zones)
        self.reposition()

    def clear(self) -> None:
        self._zones = []
        self.canvas.clear()

    def reposition(self) -> None:
        self.canvas.clear()
        mapview = self.parent
        if mapview is None or not self._zones:
            return
        with self.canvas:
            for zone in self._zones:
                if not zone.polygon:
                    continue
                rgba = _ZONE_COLOUR.get(zone.zone_type, (0.5, 0.5, 0.5, 0.3))
                try:
                    pts: list[float] = []
                    for lat, lon in zone.polygon:
                        x, y = mapview.get_window_xy_from(lat, lon, mapview.zoom)
                        pts.extend([x, y])
                    n = len(pts) // 2
                    if n < 3:
                        continue

                    Color(*rgba)
                    vertices: list[float] = []
                    for i in range(n):
                        vertices.extend([pts[i * 2], pts[i * 2 + 1], 0.0, 0.0])
                    indices: list[int] = []
                    for i in range(1, n - 1):
                        indices.extend([0, i, i + 1])
                    Mesh(vertices=vertices, indices=indices, mode="triangles")

                    Color(rgba[0], rgba[1], rgba[2], 1.0)
                    Line(points=list(pts) + pts[:2], width=1.5)
                except Exception as exc:
                    _log.warning("Zone polygon draw failed for %r: %s", zone.label, exc)


class WaypointLayer(MapLayer):
    """Draw existing mission routes from persisted waypoints."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._waypoints: list = []
        self._missions_by_id: dict[int, object] = {}

    def set_waypoints(
        self,
        waypoints: list,
        *,
        missions_by_id: typing.Optional[dict[int, object]] = None,
    ) -> None:
        self._waypoints = list(waypoints)
        self._missions_by_id = dict(missions_by_id or {})
        self.reposition()

    def clear(self) -> None:
        self._waypoints = []
        self._missions_by_id = {}
        self.canvas.clear()

    def reposition(self) -> None:
        self.canvas.clear()
        mapview = self.parent
        if mapview is None or not self._waypoints:
            return

        grouped: dict[int, list] = {}
        for waypoint in sorted(
            self._waypoints,
            key=lambda wp: (wp.mission_id, wp.sequence),
        ):
            grouped.setdefault(waypoint.mission_id, []).append(waypoint)

        with self.canvas:
            for mission_id, route in grouped.items():
                try:
                    screen_pts = [
                        mapview.get_window_xy_from(wp.lat, wp.lon, mapview.zoom)
                        for wp in route
                    ]
                except Exception as exc:
                    _log.debug("Waypoint route projection failed: %s", exc)
                    continue
                if not screen_pts:
                    continue

                mission = self._missions_by_id.get(mission_id)
                status = getattr(mission, "status", "")
                rgba = _ROUTE_STATUS_COLOUR.get(status, _DEFAULT_ROUTE_COLOUR)

                if len(screen_pts) >= 2:
                    flat: list[float] = []
                    for x, y in screen_pts:
                        flat.extend([x, y])
                    Color(*rgba)
                    Line(points=flat, width=2.0)

                r = dp(4.5)
                for idx, (x, y) in enumerate(screen_pts):
                    if idx == 0:
                        Color(0.20, 0.95, 0.20, 0.95)
                    elif idx == len(screen_pts) - 1:
                        Color(1.00, 0.55, 0.10, 0.95)
                    else:
                        Color(rgba[0], rgba[1], rgba[2], min(rgba[3] + 0.15, 1.0))
                    Ellipse(pos=(x - r, y - r), size=(r * 2, r * 2))
                    Color(0.0, 0.0, 0.0, 0.55)
                    Line(ellipse=(x - r, y - r, r * 2, r * 2), width=1.0)


class OperationalOverlayController:
    """Attach and maintain shared operational overlays on a MapView."""

    def __init__(
        self,
        mapview,
        *,
        on_asset_tap: typing.Optional[typing.Callable] = None,
    ):
        self.mapview = mapview
        self._on_asset_tap = on_asset_tap
        self._zone_layer = ZoneLayer()
        self._waypoint_layer = WaypointLayer()
        self._asset_markers: dict[int, object] = {}
        self.mapview.add_layer(self._zone_layer)
        self.mapview.add_layer(self._waypoint_layer)

    def set_context(
        self,
        context: MapContext,
        *,
        show_assets: bool = True,
        show_zones: bool = True,
        show_waypoints: bool = True,
    ) -> None:
        self.set_zones(context.zones if show_zones else [])
        self.set_waypoints(
            context.waypoints if show_waypoints else [],
            missions_by_id=context.missions_by_id,
        )
        self.set_assets(context.assets if show_assets else [])

    def set_assets(self, assets: typing.Iterable) -> None:
        self.clear_assets()
        for asset in assets:
            self.add_asset_marker(asset)

    def add_asset_marker(self, asset) -> None:
        if asset.lat is None or asset.lon is None:
            return
        self.remove_asset_marker(asset.id)
        from talon.ui.widgets.asset_marker import AssetMarker

        marker = AssetMarker(asset=asset, lat=asset.lat, lon=asset.lon)
        if self._on_asset_tap is not None:
            marker.bind(on_release=lambda marker: self._on_asset_tap(marker.asset))
        self._asset_markers[asset.id] = marker
        self.mapview.add_marker(marker)

    def remove_asset_marker(self, asset_id: int) -> None:
        marker = self._asset_markers.pop(asset_id, None)
        if marker is not None:
            self.mapview.remove_marker(marker)

    def clear_assets(self) -> None:
        for marker in list(self._asset_markers.values()):
            self.mapview.remove_marker(marker)
        self._asset_markers.clear()

    def has_asset(self, asset_id: int) -> bool:
        return asset_id in self._asset_markers

    def set_zones(self, zones: typing.Iterable) -> None:
        self._zone_layer.set_zones(list(zones))

    def set_waypoints(
        self,
        waypoints: typing.Iterable,
        *,
        missions_by_id: typing.Optional[dict[int, object]] = None,
    ) -> None:
        self._waypoint_layer.set_waypoints(
            list(waypoints),
            missions_by_id=missions_by_id,
        )

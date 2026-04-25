"""
Shared map drawing widgets — tap-to-draw polygon (AO) and waypoint route overlays.

Extracted from mission_screen.py so both MissionScreen and MissionCreateScreen
can import them without circular dependencies.
"""
import typing

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line
from kivy.metrics import dp
from kivy.uix.modalview import ModalView
from kivy_garden.mapview import MapLayer, MapView
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText, MDIconButton
from kivymd.uix.divider import MDDivider
from kivymd.uix.label import MDLabel
from kivymd.uix.selectioncontrol import MDCheckbox

from talon.ui.widgets.map_data import MapContext, load_map_context
from talon.ui.widgets.map_layers import OperationalOverlayController
from talon.ui.widgets.map_sources import DEFAULT_MAP_LAYER, MAP_SOURCES

# Short category abbreviations used in the asset picker overlay.
# Imported by mission_screen.py so the dict lives in one place.
CATEGORY_ABBR: dict[str, str] = {
    "person":      "PER",
    "safe_house":  "SH",
    "cache":       "CCH",
    "rally_point": "RP",
    "vehicle":     "VEH",
    "custom":      "CST",
}

_DEFAULT_LAT = 43.8
_DEFAULT_LON = -71.5
_DEFAULT_ZOOM = 7


def _main_map_viewport() -> tuple[float, float, int]:
    """Return the current tactical map viewport, or the project default."""
    try:
        main = App.get_running_app().root.get_screen("main")
        mw = getattr(main, "map_widget", None)
        if mw is not None:
            return float(mw.lat), float(mw.lon), int(mw.zoom)
    except Exception:
        pass
    return _DEFAULT_LAT, _DEFAULT_LON, _DEFAULT_ZOOM


def _main_map_layer() -> str:
    """Return the active layer from the main map, or the default tile layer."""
    try:
        main = App.get_running_app().root.get_screen("main")
        mw = getattr(main, "map_widget", None)
        if mw is not None:
            return str(getattr(mw, "active_layer", DEFAULT_MAP_LAYER))
    except Exception:
        pass
    return DEFAULT_MAP_LAYER


def _apply_main_map_layer(mapview: MapView) -> None:
    """Use the same tile source as the main tactical map when possible."""
    source = MAP_SOURCES.get(_main_map_layer())
    if source is not None:
        mapview.map_source = source


def _resolve_viewport(
    initial_lat: typing.Optional[float],
    initial_lon: typing.Optional[float],
    initial_zoom: typing.Optional[int],
    *,
    point_zoom: bool = False,
) -> tuple[float, float, int]:
    """Resolve explicit coords → main-map viewport → default viewport."""
    if initial_lat is not None and initial_lon is not None:
        return initial_lat, initial_lon, initial_zoom or (14 if point_zoom else _DEFAULT_ZOOM)
    lat, lon, zoom = _main_map_viewport()
    return lat, lon, initial_zoom or zoom


def _resolve_map_context(
    map_context: typing.Optional[MapContext],
    *,
    all_assets: typing.Optional[list] = None,
) -> MapContext:
    """Load the shared operational context, preserving explicit asset lists."""
    context = map_context
    if context is None:
        try:
            app = App.get_running_app()
            conn = getattr(app, "conn", None)
            context = load_map_context(conn) if conn is not None else MapContext()
        except Exception:
            context = MapContext()
    if all_assets is not None:
        context = context.with_assets(all_assets)
    return context


# ---------------------------------------------------------------------------
# Polygon drawing — in-progress AO overlay
# ---------------------------------------------------------------------------

class PolygonDrawLayer(MapLayer):
    """Canvas overlay that draws the in-progress polygon over a MapView.

    Redraws on every pan / zoom via ``reposition()``, projecting stored
    lat/lon vertices to current screen coordinates each time.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._vertices: list[tuple[float, float]] = []

    def set_vertices(self, vertices: list[tuple[float, float]]) -> None:
        self._vertices = list(vertices)
        self.reposition()

    def reposition(self) -> None:
        self.canvas.clear()
        mapview = self.parent
        if mapview is None or not self._vertices:
            return

        try:
            screen_pts = [
                mapview.get_window_xy_from(lat, lon, mapview.zoom)
                for lat, lon in self._vertices
            ]
        except Exception:
            return

        with self.canvas:
            # Lines connecting consecutive vertices
            if len(screen_pts) >= 2:
                Color(0.2, 0.9, 0.2, 0.9)
                flat: list[float] = []
                for x, y in screen_pts:
                    flat.extend([x, y])
                Line(points=flat, width=2.0)

            # Dashed closing line (last → first) once polygon is closeable
            if len(screen_pts) >= 3:
                lx, ly = screen_pts[-1]
                fx, fy = screen_pts[0]
                Color(0.2, 0.9, 0.2, 0.5)
                Line(
                    points=[lx, ly, fx, fy],
                    width=1.5,
                    dash_offset=5,
                    dash_length=8,
                )

            # Vertex dots — green filled circles
            Color(0.2, 0.9, 0.2, 1.0)
            r = dp(5)
            for x, y in screen_pts[1:]:
                Ellipse(pos=(x - r, y - r), size=(r * 2, r * 2))

            # First vertex in yellow — marks the closing target
            if screen_pts:
                Color(1.0, 0.9, 0.0, 1.0)
                r = dp(6)
                x, y = screen_pts[0]
                Ellipse(pos=(x - r, y - r), size=(r * 2, r * 2))


class PolygonDrawView(MapView):
    """MapView subclass that adds a vertex on each tap.

    Distinguishes taps from pans by checking displacement between touch-down
    and touch-up — the same threshold used by the asset map picker.
    """

    def __init__(self, on_polygon_changed: typing.Optional[typing.Callable] = None, **kwargs):
        kwargs.setdefault("lat", _DEFAULT_LAT)
        kwargs.setdefault("lon", _DEFAULT_LON)
        kwargs.setdefault("zoom", _DEFAULT_ZOOM)
        super().__init__(**kwargs)
        self._vertices: list[tuple[float, float]] = []
        self._on_polygon_changed = on_polygon_changed
        self._touch_start: tuple[float, float] = (0.0, 0.0)
        self.operational_overlays = OperationalOverlayController(self)
        self._draw_layer = PolygonDrawLayer()
        self.add_layer(self._draw_layer)

    # Scroll-wheel and multi-touch-simulated events that must never place a vertex.
    _IGNORED_BUTTONS = frozenset(("scrollup", "scrolldown", "scrollleft", "scrollright"))

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and getattr(touch, "button", None) not in self._IGNORED_BUTTONS:
            self._touch_start = (touch.x, touch.y)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if not self.collide_point(*touch.pos):
            return result
        if getattr(touch, "button", None) in self._IGNORED_BUTTONS:
            return result
        dx = abs(touch.x - self._touch_start[0])
        dy = abs(touch.y - self._touch_start[1])
        if dx < dp(10) and dy < dp(10):
            coord = self.get_latlon_at(touch.x - self.x, touch.y - self.y)
            self._vertices.append((coord.lat, coord.lon))
            self._draw_layer.set_vertices(self._vertices)
            if self._on_polygon_changed:
                self._on_polygon_changed(list(self._vertices))
        return result

    def undo_last(self) -> None:
        if self._vertices:
            self._vertices.pop()
            self._draw_layer.set_vertices(self._vertices)
            if self._on_polygon_changed:
                self._on_polygon_changed(list(self._vertices))

    def clear_polygon(self) -> None:
        self._vertices.clear()
        self._draw_layer.set_vertices([])
        if self._on_polygon_changed:
            self._on_polygon_changed([])

    def get_polygon(self) -> list[tuple[float, float]]:
        return list(self._vertices)


class PolygonDrawModal(ModalView):
    """Full-screen map modal for drawing a mission AO polygon.

    Tapping adds a vertex.  Requires >= 3 vertices to confirm.
    Calls ``on_confirm([[lat, lon], ...])`` and auto-dismisses on CONFIRM.
    """

    def __init__(
        self,
        on_confirm: typing.Callable,
        initial_lat: typing.Optional[float] = None,
        initial_lon: typing.Optional[float] = None,
        initial_zoom: typing.Optional[int] = None,
        assets: typing.Optional[list] = None,
        all_assets: typing.Optional[list] = None,
        map_context: typing.Optional[MapContext] = None,
        **kwargs,
    ):
        super().__init__(size_hint=(0.95, 0.95), auto_dismiss=False, **kwargs)
        self._on_confirm = on_confirm
        self._map_context = _resolve_map_context(map_context, all_assets=all_assets)
        self._all_assets: list = list(self._map_context.assets)
        visible_assets = list(assets) if assets is not None else list(self._map_context.assets)
        init_lat, init_lon, init_zoom = _resolve_viewport(
            initial_lat,
            initial_lon,
            initial_zoom,
        )

        main = MDBoxLayout(orientation="vertical")

        # ── Header ──────────────────────────────────────────────────
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="56dp",
            spacing="4dp",
            padding=("8dp", "0dp"),
        )
        self._vertex_label = MDLabel(
            text="Tap the map to add vertices  (0 placed)",
            font_style="Body",
            role="medium",
        )
        assets_btn = MDIconButton(icon="map-marker-multiple", size_hint_x=None, width="40dp")
        assets_btn.bind(on_release=lambda *_: self._open_asset_picker())
        undo_btn = MDIconButton(icon="undo", size_hint_x=None, width="40dp")
        clear_btn = MDIconButton(icon="eraser", size_hint_x=None, width="40dp")
        undo_btn.bind(on_release=lambda *_: self._map_view.undo_last())
        clear_btn.bind(on_release=lambda *_: self._map_view.clear_polygon())
        header.add_widget(self._vertex_label)
        header.add_widget(assets_btn)
        header.add_widget(undo_btn)
        header.add_widget(clear_btn)
        main.add_widget(header)
        main.add_widget(MDDivider())

        # ── Map ──────────────────────────────────────────────────────
        self._map_view = PolygonDrawView(
            on_polygon_changed=self._on_polygon_changed,
            lat=init_lat,
            lon=init_lon,
            zoom=init_zoom,
        )
        _apply_main_map_layer(self._map_view)
        self._overlays = self._map_view.operational_overlays
        self._overlays.set_context(self._map_context.with_assets(visible_assets))
        main.add_widget(self._map_view)
        main.add_widget(MDDivider())

        # ── Footer ───────────────────────────────────────────────────
        footer = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="56dp",
            spacing="8dp",
            padding=("8dp", "4dp"),
        )
        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="outlined")
        cancel_btn.bind(on_release=lambda *_: self.dismiss())
        self._confirm_btn = MDButton(
            MDButtonText(text="CONFIRM AO"),
            style="elevated",
        )
        self._confirm_btn.disabled = True
        self._confirm_btn.bind(on_release=lambda *_: self._confirm())
        footer.add_widget(cancel_btn)
        footer.add_widget(self._confirm_btn)
        main.add_widget(footer)

        self.add_widget(main)

    def _on_polygon_changed(self, vertices: list) -> None:
        n = len(vertices)
        self._vertex_label.text = f"Tap the map to add vertices  ({n} placed)"
        self._confirm_btn.disabled = n < 3

    def _confirm(self) -> None:
        polygon = [[lat, lon] for lat, lon in self._map_view.get_polygon()]
        if len(polygon) >= 3:
            self._on_confirm(polygon)
        self.dismiss()

    def _open_asset_picker(self) -> None:
        from kivy.uix.scrollview import ScrollView as _SV
        mappable = [a for a in self._all_assets if a.lat is not None and a.lon is not None]
        picker = ModalView(size_hint=(0.40, 0.65), auto_dismiss=True)
        sv = _SV()
        body = MDBoxLayout(
            orientation="vertical",
            adaptive_height=True,
            padding="12dp",
            spacing="6dp",
        )
        body.add_widget(MDLabel(
            text="Assets visible on map",
            font_style="Label",
            role="medium",
            bold=True,
            size_hint_y=None,
            height="28dp",
        ))
        body.add_widget(MDDivider())
        if not mappable:
            body.add_widget(MDLabel(
                text="No assets have location data.",
                theme_text_color="Secondary",
                adaptive_height=True,
            ))
        else:
            for asset in mappable:
                row = MDBoxLayout(
                    orientation="horizontal",
                    adaptive_height=True,
                    spacing="8dp",
                    padding=("0dp", "2dp"),
                )
                chk = MDCheckbox(
                    size_hint_x=None,
                    width="40dp",
                    active=self._overlays.has_asset(asset.id),
                )
                chk.bind(active=lambda cb, val, a=asset: self._toggle_asset(a, val))
                row.add_widget(chk)
                abbr = CATEGORY_ABBR.get(asset.category, "CST")
                row.add_widget(MDLabel(
                    text=f"[{abbr}]  {asset.label}",
                    font_style="Body",
                    role="medium",
                    adaptive_height=True,
                ))
                body.add_widget(row)
        sv.add_widget(body)
        picker.add_widget(sv)
        picker.open()

    def _toggle_asset(self, asset, active: bool) -> None:
        if active:
            self._overlays.add_asset_marker(asset)
        else:
            self._overlays.remove_asset_marker(asset.id)


# ---------------------------------------------------------------------------
# Waypoint route drawing — in-progress route overlay
# ---------------------------------------------------------------------------

class WaypointDrawLayer(MapLayer):
    """Canvas overlay that draws the in-progress route (ordered waypoints).

    Start waypoint is green, end is orange, intermediates are blue.
    Redraws on every pan / zoom via ``reposition()``.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._vertices: list[tuple[float, float]] = []

    def set_vertices(self, vertices: list[tuple[float, float]]) -> None:
        self._vertices = list(vertices)
        self.reposition()

    def reposition(self) -> None:
        self.canvas.clear()
        mapview = self.parent
        if mapview is None or not self._vertices:
            return
        try:
            screen_pts = [
                mapview.get_window_xy_from(lat, lon, mapview.zoom)
                for lat, lon in self._vertices
            ]
        except Exception:
            return

        with self.canvas:
            # Route line connecting waypoints in order
            if len(screen_pts) >= 2:
                Color(0.2, 0.7, 1.0, 0.9)
                flat: list[float] = []
                for x, y in screen_pts:
                    flat.extend([x, y])
                Line(points=flat, width=2.0)

            # Waypoint dots — start green, end orange, middle blue
            r = dp(5)
            for i, (x, y) in enumerate(screen_pts):
                if i == 0:
                    Color(0.2, 0.90, 0.2, 1.0)   # green — start
                elif i == len(screen_pts) - 1:
                    Color(1.0, 0.55, 0.1, 1.0)   # orange — end
                else:
                    Color(0.2, 0.70, 1.0, 1.0)   # blue — intermediate
                Ellipse(pos=(x - r, y - r), size=(r * 2, r * 2))


class WaypointDrawView(MapView):
    """MapView subclass that places a waypoint on each tap."""

    _IGNORED_BUTTONS = frozenset(("scrollup", "scrolldown", "scrollleft", "scrollright"))

    def __init__(self, on_route_changed: typing.Optional[typing.Callable] = None, **kwargs):
        kwargs.setdefault("lat", _DEFAULT_LAT)
        kwargs.setdefault("lon", _DEFAULT_LON)
        kwargs.setdefault("zoom", _DEFAULT_ZOOM)
        super().__init__(**kwargs)
        self._vertices: list[tuple[float, float]] = []
        self._on_route_changed = on_route_changed
        self._touch_start: tuple[float, float] = (0.0, 0.0)
        self.operational_overlays = OperationalOverlayController(self)
        self._draw_layer = WaypointDrawLayer()
        self.add_layer(self._draw_layer)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and getattr(touch, "button", None) not in self._IGNORED_BUTTONS:
            self._touch_start = (touch.x, touch.y)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if not self.collide_point(*touch.pos):
            return result
        if getattr(touch, "button", None) in self._IGNORED_BUTTONS:
            return result
        dx = abs(touch.x - self._touch_start[0])
        dy = abs(touch.y - self._touch_start[1])
        if dx < dp(10) and dy < dp(10):
            coord = self.get_latlon_at(touch.x - self.x, touch.y - self.y)
            self._vertices.append((coord.lat, coord.lon))
            self._draw_layer.set_vertices(self._vertices)
            if self._on_route_changed:
                self._on_route_changed(list(self._vertices))
        return result

    def undo_last(self) -> None:
        if self._vertices:
            self._vertices.pop()
            self._draw_layer.set_vertices(self._vertices)
            if self._on_route_changed:
                self._on_route_changed(list(self._vertices))

    def clear_route(self) -> None:
        self._vertices.clear()
        self._draw_layer.set_vertices([])
        if self._on_route_changed:
            self._on_route_changed([])

    def get_route(self) -> list[tuple[float, float]]:
        return list(self._vertices)


# ---------------------------------------------------------------------------
# Single-point picker — tap once to set a coordinate
# ---------------------------------------------------------------------------

class PointPickerLayer(MapLayer):
    """Canvas overlay that draws a crosshair pin at the picked coordinate."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._point: typing.Optional[tuple[float, float]] = None

    def set_point(self, lat: float, lon: float) -> None:
        self._point = (lat, lon)
        self.reposition()

    def clear(self) -> None:
        self._point = None
        self.canvas.clear()

    def reposition(self) -> None:
        self.canvas.clear()
        mapview = self.parent
        if mapview is None or self._point is None:
            return
        lat, lon = self._point
        try:
            x, y = mapview.get_window_xy_from(lat, lon, mapview.zoom)
        except Exception:
            return
        with self.canvas:
            Color(1.0, 0.85, 0.0, 1.0)
            r = dp(8)
            Ellipse(pos=(x - r, y - r), size=(r * 2, r * 2))
            Color(0.0, 0.0, 0.0, 0.85)
            r2 = dp(3)
            Ellipse(pos=(x - r2, y - r2), size=(r2 * 2, r2 * 2))
            Color(1.0, 0.85, 0.0, 0.9)
            arm = dp(14)
            Line(points=[x - arm, y, x - r, y], width=1.5)
            Line(points=[x + r,   y, x + arm, y], width=1.5)
            Line(points=[x, y - arm, x, y - r], width=1.5)
            Line(points=[x, y + r,   x, y + arm], width=1.5)


class PointPickerView(MapView):
    """MapView that captures a single tap and replaces any previous selection."""

    _IGNORED_BUTTONS = frozenset(("scrollup", "scrolldown", "scrollleft", "scrollright"))

    def __init__(self, on_point_changed: typing.Optional[typing.Callable] = None, **kwargs):
        kwargs.setdefault("lat", _DEFAULT_LAT)
        kwargs.setdefault("lon", _DEFAULT_LON)
        kwargs.setdefault("zoom", _DEFAULT_ZOOM)
        super().__init__(**kwargs)
        self._point: typing.Optional[tuple[float, float]] = None
        self._on_point_changed = on_point_changed
        self._touch_start: tuple[float, float] = (0.0, 0.0)
        self.operational_overlays = OperationalOverlayController(self)
        self._draw_layer = PointPickerLayer()
        self.add_layer(self._draw_layer)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and getattr(touch, "button", None) not in self._IGNORED_BUTTONS:
            self._touch_start = (touch.x, touch.y)
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        result = super().on_touch_up(touch)
        if not self.collide_point(*touch.pos):
            return result
        if getattr(touch, "button", None) in self._IGNORED_BUTTONS:
            return result
        dx = abs(touch.x - self._touch_start[0])
        dy = abs(touch.y - self._touch_start[1])
        if dx < dp(10) and dy < dp(10):
            coord = self.get_latlon_at(touch.x - self.x, touch.y - self.y)
            self._point = (coord.lat, coord.lon)
            self._draw_layer.set_point(coord.lat, coord.lon)
            if self._on_point_changed:
                self._on_point_changed(coord.lat, coord.lon)
        return result

    def clear_point(self) -> None:
        self._point = None
        self._draw_layer.clear()
        if self._on_point_changed:
            self._on_point_changed(None, None)

    def set_point(self, lat: float, lon: float, *, notify: bool = True) -> None:
        """Place the selected point programmatically."""
        self._point = (lat, lon)
        self._draw_layer.set_point(lat, lon)
        if notify and self._on_point_changed:
            self._on_point_changed(lat, lon)

    def get_point(self) -> typing.Optional[tuple[float, float]]:
        return self._point


class PointPickerModal(ModalView):
    """Full-screen map modal for picking a single coordinate.

    Tapping the map sets the pin (replaces any previous pin).
    Calls ``on_confirm(lat, lon)`` and auto-dismisses on CONFIRM.
    """

    def __init__(
        self,
        on_confirm: typing.Callable,
        label: str = 'Pick location',
        initial_lat: typing.Optional[float] = None,
        initial_lon: typing.Optional[float] = None,
        initial_zoom: typing.Optional[int] = None,
        map_context: typing.Optional[MapContext] = None,
        show_operational_context: bool = True,
        **kwargs,
    ):
        super().__init__(size_hint=(0.95, 0.95), auto_dismiss=False, **kwargs)
        self._on_confirm = on_confirm
        self._label_base = label
        self._initial_point = (
            (initial_lat, initial_lon)
            if initial_lat is not None and initial_lon is not None
            else None
        )
        init_lat, init_lon, init_zoom = _resolve_viewport(
            initial_lat,
            initial_lon,
            initial_zoom,
            point_zoom=True,
        )

        main = MDBoxLayout(orientation="vertical")

        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="56dp",
            spacing="4dp",
            padding=("8dp", "0dp"),
        )
        self._point_label = MDLabel(
            text=f"{label}  —  tap map to set",
            font_style="Body",
            role="medium",
        )
        clear_btn = MDIconButton(icon="eraser", size_hint_x=None, width="40dp")
        clear_btn.bind(on_release=lambda *_: self._map_view.clear_point())
        header.add_widget(self._point_label)
        header.add_widget(clear_btn)
        main.add_widget(header)
        main.add_widget(MDDivider())

        self._map_view = PointPickerView(
            on_point_changed=self._on_point_changed,
            lat=init_lat,
            lon=init_lon,
            zoom=init_zoom,
        )
        _apply_main_map_layer(self._map_view)
        if show_operational_context:
            self._overlays = self._map_view.operational_overlays
            self._overlays.set_context(_resolve_map_context(map_context))
        main.add_widget(self._map_view)
        main.add_widget(MDDivider())

        footer = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="56dp",
            spacing="8dp",
            padding=("8dp", "4dp"),
        )
        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="outlined")
        cancel_btn.bind(on_release=lambda *_: self.dismiss())
        self._confirm_btn = MDButton(
            MDButtonText(text="CONFIRM LOCATION"),
            style="elevated",
        )
        self._confirm_btn.disabled = True
        self._confirm_btn.bind(on_release=lambda *_: self._confirm())
        footer.add_widget(cancel_btn)
        footer.add_widget(self._confirm_btn)
        main.add_widget(footer)

        self.add_widget(main)

        if self._initial_point is not None:
            Clock.schedule_once(
                lambda _dt: self._map_view.set_point(*self._initial_point),
                0.1,
            )

    def _on_point_changed(self, lat, lon) -> None:
        if lat is None:
            self._point_label.text = f"{self._label_base}  —  tap map to set"
            self._confirm_btn.disabled = True
        else:
            self._point_label.text = f"{self._label_base}  —  {lat:.5f}, {lon:.5f}"
            self._confirm_btn.disabled = False

    def _confirm(self) -> None:
        point = self._map_view.get_point()
        if point:
            self._on_confirm(*point)
        self.dismiss()


class WaypointRouteModal(ModalView):
    """Full-screen map modal for plotting a mission route via ordered waypoints.

    Tapping places the next waypoint in sequence.  Requires >= 1 waypoint to
    confirm.  Calls ``on_confirm([(lat, lon), ...])`` and auto-dismisses.
    """

    def __init__(
        self,
        on_confirm: typing.Callable,
        initial_lat: typing.Optional[float] = None,
        initial_lon: typing.Optional[float] = None,
        initial_zoom: typing.Optional[int] = None,
        assets: typing.Optional[list] = None,
        all_assets: typing.Optional[list] = None,
        map_context: typing.Optional[MapContext] = None,
        **kwargs,
    ):
        super().__init__(size_hint=(0.95, 0.95), auto_dismiss=False, **kwargs)
        self._on_confirm = on_confirm
        self._map_context = _resolve_map_context(map_context, all_assets=all_assets)
        self._all_assets: list = list(self._map_context.assets)
        visible_assets = list(assets) if assets is not None else list(self._map_context.assets)
        init_lat, init_lon, init_zoom = _resolve_viewport(
            initial_lat,
            initial_lon,
            initial_zoom,
        )

        main = MDBoxLayout(orientation="vertical")

        # ── Header ──────────────────────────────────────────────────
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="56dp",
            spacing="4dp",
            padding=("8dp", "0dp"),
        )
        self._waypoint_label = MDLabel(
            text="Tap the map to place waypoints  (0 placed)",
            font_style="Body",
            role="medium",
        )
        assets_btn = MDIconButton(icon="map-marker-multiple", size_hint_x=None, width="40dp")
        assets_btn.bind(on_release=lambda *_: self._open_asset_picker())
        undo_btn = MDIconButton(icon="undo", size_hint_x=None, width="40dp")
        clear_btn = MDIconButton(icon="eraser", size_hint_x=None, width="40dp")
        undo_btn.bind(on_release=lambda *_: self._map_view.undo_last())
        clear_btn.bind(on_release=lambda *_: self._map_view.clear_route())
        header.add_widget(self._waypoint_label)
        header.add_widget(assets_btn)
        header.add_widget(undo_btn)
        header.add_widget(clear_btn)
        main.add_widget(header)
        main.add_widget(MDDivider())

        # ── Map ──────────────────────────────────────────────────────
        self._map_view = WaypointDrawView(
            on_route_changed=self._on_route_changed,
            lat=init_lat,
            lon=init_lon,
            zoom=init_zoom,
        )
        _apply_main_map_layer(self._map_view)
        self._overlays = self._map_view.operational_overlays
        self._overlays.set_context(self._map_context.with_assets(visible_assets))
        main.add_widget(self._map_view)
        main.add_widget(MDDivider())

        # ── Footer ───────────────────────────────────────────────────
        footer = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="56dp",
            spacing="8dp",
            padding=("8dp", "4dp"),
        )
        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="outlined")
        cancel_btn.bind(on_release=lambda *_: self.dismiss())
        self._confirm_btn = MDButton(
            MDButtonText(text="CONFIRM ROUTE"),
            style="elevated",
        )
        self._confirm_btn.disabled = True
        self._confirm_btn.bind(on_release=lambda *_: self._confirm())
        footer.add_widget(cancel_btn)
        footer.add_widget(self._confirm_btn)
        main.add_widget(footer)

        self.add_widget(main)

    def _on_route_changed(self, vertices: list) -> None:
        n = len(vertices)
        self._waypoint_label.text = f"Tap the map to place waypoints  ({n} placed)"
        self._confirm_btn.disabled = n < 1

    def _confirm(self) -> None:
        route = self._map_view.get_route()
        if route:
            self._on_confirm(route)
        self.dismiss()

    def _open_asset_picker(self) -> None:
        from kivy.uix.scrollview import ScrollView as _SV
        mappable = [a for a in self._all_assets if a.lat is not None and a.lon is not None]
        picker = ModalView(size_hint=(0.40, 0.65), auto_dismiss=True)
        sv = _SV()
        body = MDBoxLayout(
            orientation="vertical",
            adaptive_height=True,
            padding="12dp",
            spacing="6dp",
        )
        body.add_widget(MDLabel(
            text="Assets visible on map",
            font_style="Label",
            role="medium",
            bold=True,
            size_hint_y=None,
            height="28dp",
        ))
        body.add_widget(MDDivider())
        if not mappable:
            body.add_widget(MDLabel(
                text="No assets have location data.",
                theme_text_color="Secondary",
                adaptive_height=True,
            ))
        else:
            for asset in mappable:
                row = MDBoxLayout(
                    orientation="horizontal",
                    adaptive_height=True,
                    spacing="8dp",
                    padding=("0dp", "2dp"),
                )
                chk = MDCheckbox(
                    size_hint_x=None,
                    width="40dp",
                    active=self._overlays.has_asset(asset.id),
                )
                chk.bind(active=lambda cb, val, a=asset: self._toggle_asset(a, val))
                row.add_widget(chk)
                abbr = CATEGORY_ABBR.get(asset.category, "CST")
                row.add_widget(MDLabel(
                    text=f"[{abbr}]  {asset.label}",
                    font_style="Body",
                    role="medium",
                    adaptive_height=True,
                ))
                body.add_widget(row)
        sv.add_widget(body)
        picker.add_widget(sv)
        picker.open()

    def _toggle_asset(self, asset, active: bool) -> None:
        if active:
            self._overlays.add_asset_marker(asset)
        else:
            self._overlays.remove_asset_marker(asset.id)

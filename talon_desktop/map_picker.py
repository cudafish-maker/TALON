"""Reusable PySide6 map coordinate pickers for desktop workflows."""
from __future__ import annotations

import typing

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6 import QtNetwork

from talon_core import TalonCoreSession
from talon_core.utils.logging import get_logger
from talon_desktop.map_data import (
    DEFAULT_MAP_BOUNDS,
    SCENE_HEIGHT,
    SCENE_WIDTH,
    MapBounds,
    build_map_overlays,
)
from talon_desktop.map_tiles import (
    TILE_LAYERS,
    TILE_LAYERS_BY_KEY,
    TileRequest,
    build_tile_plan,
    lat_lon_for_scene_point,
    scene_point_for_lat_lon,
)

_log = get_logger("desktop.map_picker")


class MapPickView(QtWidgets.QGraphicsView):
    """Graphics view that emits latitude/longitude clicks."""

    locationClicked = QtCore.Signal(float, float)

    def __init__(self, scene: QtWidgets.QGraphicsScene, bounds: MapBounds) -> None:
        super().__init__(scene)
        self._bounds = bounds
        self._zoom_steps = 0
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)

    def set_bounds(self, bounds: MapBounds) -> None:
        self._bounds = bounds

    def reset_zoom(self) -> None:
        self._zoom_steps = 0
        self.resetTransform()
        scene = self.scene()
        if scene is not None:
            self.fitInView(scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            lat, lon = lat_lon_for_scene_point(self._bounds, point.x(), point.y())
            self.locationClicked.emit(lat, lon)
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        direction = 1 if delta > 0 else -1
        next_steps = max(-8, min(16, self._zoom_steps + direction))
        if next_steps == self._zoom_steps:
            event.accept()
            return
        factor = 1.18 if direction > 0 else 1 / 1.18
        self.scale(factor, factor)
        self._zoom_steps = next_steps
        event.accept()


class MapCoordinateDialog(QtWidgets.QDialog):
    """Pick a point, polygon, or route on the operational map context."""

    def __init__(
        self,
        *,
        core: TalonCoreSession | None,
        title: str,
        mode: typing.Literal["point", "polygon", "route"],
        initial_points: typing.Iterable[tuple[float, float]] = (),
        minimum_points: int | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._core = core
        self._mode = mode
        self._minimum_points = minimum_points or (3 if mode == "polygon" else 1)
        self._points = [(_clamp_lat(lat), _clamp_lon(lon)) for lat, lon in initial_points]
        self._context: object | None = None
        self._sitrep_entries: list[object] = []
        self._bounds = DEFAULT_MAP_BOUNDS
        self._tile_generation = 0
        self._active_tile_layer_key = "osm"
        self._network = QtNetwork.QNetworkAccessManager(self)
        self._install_tile_cache()

        self.setWindowTitle(title)
        self.setMinimumSize(840, 620)

        self._load_context()
        self._bounds = self._initial_bounds()

        self._scene = QtWidgets.QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, SCENE_WIDTH, SCENE_HEIGHT)
        self.view = MapPickView(self._scene, self._bounds)
        self.view.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing
        )
        self.view.setMinimumSize(760, 460)
        self.view.locationClicked.connect(self._add_point)

        self.layer_group = QtWidgets.QButtonGroup(self)
        self.layer_buttons: dict[str, QtWidgets.QRadioButton] = {}
        layer_row = QtWidgets.QHBoxLayout()
        layer_row.setSpacing(8)
        for layer in TILE_LAYERS:
            button = QtWidgets.QRadioButton(layer.label)
            button.setChecked(layer.key == self._active_tile_layer_key)
            self.layer_group.addButton(button)
            self.layer_buttons[layer.key] = button
            layer_row.addWidget(button)
            button.toggled.connect(
                lambda checked, key=layer.key: self._set_tile_layer(key)
                if checked
                else None
            )
        layer_row.addStretch(1)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.undo_button = QtWidgets.QPushButton("Undo")
        self.use_button = QtWidgets.QPushButton(_use_button_label(mode))
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.clear_button.clicked.connect(self._clear_points)
        self.undo_button.clicked.connect(self._undo_point)
        self.use_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self.status_label, stretch=1)
        button_row.addWidget(self.clear_button)
        button_row.addWidget(self.undo_button)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.use_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(layer_row)
        layout.addWidget(self.view, stretch=1)
        layout.addLayout(button_row)

        self._render()
        self._sync_status()
        QtCore.QTimer.singleShot(0, self.view.reset_zoom)

    @property
    def selected_points(self) -> list[tuple[float, float]]:
        return list(self._points)

    def accept(self) -> None:
        if len(self._points) < self._minimum_points:
            self.status_label.setText(
                f"{_mode_label(self._mode)} requires at least "
                f"{self._minimum_points} point(s)."
            )
            return
        super().accept()

    def _load_context(self) -> None:
        if self._core is None:
            return
        try:
            self._context = self._core.read_model("map.context")
            self._sitrep_entries = list(self._core.read_model("sitreps.list"))
        except Exception as exc:
            _log.debug("Map picker context unavailable: %s", exc)
            self._context = None
            self._sitrep_entries = []

    def _initial_bounds(self) -> MapBounds:
        bounds = DEFAULT_MAP_BOUNDS
        context_loaded = False
        if self._context is not None:
            try:
                bounds = build_map_overlays(
                    self._context,
                    sitrep_entries=self._sitrep_entries,
                ).bounds
                context_loaded = True
            except Exception as exc:
                _log.debug("Map picker overlay bounds unavailable: %s", exc)
        if self._points:
            bounds = _expand_bounds(bounds, self._points) if context_loaded else _bounds_for_points(self._points)
        return bounds

    def _render(self) -> None:
        self._scene.clear()
        self._tile_generation += 1
        self._draw_background()
        self._draw_tile_layer()
        self._draw_context_overlays()
        self._draw_selection()
        self._scene.setSceneRect(0, 0, SCENE_WIDTH, SCENE_HEIGHT)

    def _draw_background(self) -> None:
        self._scene.addRect(
            0,
            0,
            SCENE_WIDTH,
            SCENE_HEIGHT,
            QtGui.QPen(QtGui.QColor("#2f3437")),
            QtGui.QBrush(QtGui.QColor("#111619")),
        ).setZValue(-40)
        grid_pen = QtGui.QPen(QtGui.QColor(236, 240, 241, 34))
        for x in range(100, int(SCENE_WIDTH), 100):
            self._scene.addLine(x, 0, x, SCENE_HEIGHT, grid_pen).setZValue(-5)
        for y in range(100, int(SCENE_HEIGHT), 100):
            self._scene.addLine(0, y, SCENE_WIDTH, y, grid_pen).setZValue(-5)

    def _draw_tile_layer(self) -> None:
        layer = TILE_LAYERS_BY_KEY.get(self._active_tile_layer_key, TILE_LAYERS[0])
        plan = build_tile_plan(layer, self._bounds)
        generation = self._tile_generation
        for request in plan.requests:
            self._request_tile(request, generation)
        item = self._scene.addText(layer.attribution)
        item.setDefaultTextColor(QtGui.QColor("#ecf0f1"))
        item.setZValue(30)
        rect = item.boundingRect()
        item.setPos(SCENE_WIDTH - rect.width() - 12, SCENE_HEIGHT - rect.height() - 8)

    def _draw_context_overlays(self) -> None:
        if self._context is None:
            return
        try:
            bundle = build_map_overlays(
                self._context,
                sitrep_entries=self._sitrep_entries,
                bounds=self._bounds,
            )
        except Exception as exc:
            _log.debug("Map picker overlay render failed: %s", exc)
            return

        for zone in bundle.zones:
            polygon = QtGui.QPolygonF(
                [QtCore.QPointF(point.x, point.y) for point in zone.points]
            )
            item = self._scene.addPolygon(
                polygon,
                QtGui.QPen(QtGui.QColor(143, 188, 187, 150), 1),
                QtGui.QBrush(QtGui.QColor(52, 152, 219, 32)),
            )
            item.setToolTip(f"{zone.label} [{zone.zone_type}]")
            item.setZValue(2)
        for route in bundle.routes:
            path = QtGui.QPainterPath()
            first = route.points[0]
            path.moveTo(first.x, first.y)
            for point in route.points[1:]:
                path.lineTo(point.x, point.y)
            item = self._scene.addPath(path, QtGui.QPen(QtGui.QColor("#f1c40f"), 2))
            item.setToolTip(route.mission_label)
            item.setZValue(6)
        for waypoint in bundle.waypoints:
            item = self._scene.addEllipse(
                waypoint.point.x - 4,
                waypoint.point.y - 4,
                8,
                8,
                QtGui.QPen(QtGui.QColor("#f39c12"), 1),
                QtGui.QBrush(QtGui.QColor("#f1c40f")),
            )
            item.setToolTip(waypoint.label)
            item.setZValue(7)
        for asset in bundle.assets:
            color = QtGui.QColor("#2ecc71") if asset.verified else QtGui.QColor("#e67e22")
            item = self._scene.addEllipse(
                asset.point.x - 7,
                asset.point.y - 7,
                14,
                14,
                QtGui.QPen(QtGui.QColor("#ecf0f1"), 1),
                QtGui.QBrush(color),
            )
            item.setToolTip(asset.label)
            item.setZValue(8)
        for sitrep in bundle.sitreps:
            item = self._scene.addRect(
                sitrep.point.x - 5,
                sitrep.point.y - 24,
                10,
                10,
                QtGui.QPen(QtGui.QColor("#ecf0f1"), 1),
                QtGui.QBrush(QtGui.QColor("#e74c3c")),
            )
            item.setToolTip(f"{sitrep.level} SITREP #{sitrep.id}")
            item.setZValue(9)

    def _draw_selection(self) -> None:
        if not self._points:
            return
        scene_points = [
            QtCore.QPointF(*scene_point_for_lat_lon(self._bounds, lat, lon))
            for lat, lon in self._points
        ]
        pen = QtGui.QPen(QtGui.QColor("#f6fbfb"), 2)
        accent_pen = QtGui.QPen(QtGui.QColor("#ffdf6e"), 3)
        if self._mode == "polygon" and len(scene_points) >= 3:
            polygon = QtGui.QPolygonF(scene_points)
            item = self._scene.addPolygon(
                polygon,
                accent_pen,
                QtGui.QBrush(QtGui.QColor(255, 223, 110, 44)),
            )
            item.setZValue(20)
        elif self._mode == "route" and len(scene_points) >= 2:
            path = QtGui.QPainterPath()
            path.moveTo(scene_points[0])
            for point in scene_points[1:]:
                path.lineTo(point)
            item = self._scene.addPath(path, accent_pen)
            item.setZValue(20)

        for index, point in enumerate(scene_points, start=1):
            ellipse = self._scene.addEllipse(
                point.x() - 8,
                point.y() - 8,
                16,
                16,
                pen,
                QtGui.QBrush(QtGui.QColor("#ffdf6e")),
            )
            ellipse.setZValue(25)
            label = self._scene.addText(str(index))
            label.setDefaultTextColor(QtGui.QColor("#111619"))
            label.setZValue(26)
            rect = label.boundingRect()
            label.setPos(point.x() - rect.width() / 2, point.y() - rect.height() / 2)

    def _request_tile(self, tile: TileRequest, generation: int) -> None:
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(tile.url))
        request.setHeader(
            QtNetwork.QNetworkRequest.UserAgentHeader,
            "TALON Desktop/0.1 PySide6 map picker",
        )
        reply = self._network.get(request)
        reply.finished.connect(
            lambda reply=reply, tile=tile, generation=generation: self._tile_finished(
                reply,
                tile,
                generation,
            )
        )

    def _tile_finished(
        self,
        reply: QtNetwork.QNetworkReply,
        tile: TileRequest,
        generation: int,
    ) -> None:
        try:
            if generation != self._tile_generation:
                return
            if reply.error() != QtNetwork.QNetworkReply.NoError:
                _log.debug("Map picker tile request failed: %s", reply.errorString())
                return
            pixmap = QtGui.QPixmap()
            if not pixmap.loadFromData(reply.readAll()):
                return
            item = self._scene.addPixmap(pixmap)
            item.setTransformationMode(QtCore.Qt.SmoothTransformation)
            item.setPos(tile.scene_x, tile.scene_y)
            item.setTransform(
                QtGui.QTransform().scale(
                    tile.scene_width / pixmap.width(),
                    tile.scene_height / pixmap.height(),
                )
            )
            item.setZValue(-20)
        finally:
            reply.deleteLater()

    def _add_point(self, lat: float, lon: float) -> None:
        point = (_clamp_lat(lat), _clamp_lon(lon))
        if self._mode == "point":
            self._points = [point]
        else:
            self._points.append(point)
        self._render()
        self._sync_status()

    def _clear_points(self) -> None:
        self._points.clear()
        self._render()
        self._sync_status()

    def _undo_point(self) -> None:
        if self._points:
            self._points.pop()
        self._render()
        self._sync_status()

    def _set_tile_layer(self, key: str) -> None:
        if key == self._active_tile_layer_key:
            return
        self._active_tile_layer_key = key
        self._render()

    def _sync_status(self) -> None:
        count = len(self._points)
        if count:
            latest = self._points[-1]
            self.status_label.setText(
                f"{count} point(s). Latest: {latest[0]:.6f}, {latest[1]:.6f}"
            )
        else:
            self.status_label.setText(f"Click the map to set {_mode_label(self._mode).lower()}.")
        self.use_button.setEnabled(count >= self._minimum_points)
        self.undo_button.setEnabled(bool(self._points))
        self.clear_button.setEnabled(bool(self._points))

    def _install_tile_cache(self) -> None:
        if self._core is None:
            return
        cache = QtNetwork.QNetworkDiskCache(self)
        try:
            cache_dir = self._core.paths.data_dir / "cache" / "map_tiles"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache.setCacheDirectory(str(cache_dir))
            self._network.setCache(cache)
        except Exception as exc:
            _log.debug("Map picker tile cache disabled: %s", exc)


def pick_point_on_map(
    *,
    core: TalonCoreSession | None,
    title: str,
    initial_lat: float | None = None,
    initial_lon: float | None = None,
    parent: QtWidgets.QWidget | None = None,
) -> tuple[float, float] | None:
    initial = []
    if initial_lat is not None and initial_lon is not None:
        initial.append((initial_lat, initial_lon))
    dialog = MapCoordinateDialog(
        core=core,
        title=title,
        mode="point",
        initial_points=initial,
        parent=parent,
    )
    if dialog.exec() != QtWidgets.QDialog.Accepted:
        return None
    return dialog.selected_points[0] if dialog.selected_points else None


def pick_path_on_map(
    *,
    core: TalonCoreSession | None,
    title: str,
    mode: typing.Literal["polygon", "route"],
    initial_points: typing.Iterable[tuple[float, float]] = (),
    parent: QtWidgets.QWidget | None = None,
) -> list[tuple[float, float]] | None:
    dialog = MapCoordinateDialog(
        core=core,
        title=title,
        mode=mode,
        initial_points=initial_points,
        parent=parent,
    )
    if dialog.exec() != QtWidgets.QDialog.Accepted:
        return None
    return dialog.selected_points


def format_coordinate(lat: float, lon: float) -> str:
    return f"{lat:.6f}, {lon:.6f}"


def _expand_bounds(bounds: MapBounds, points: typing.Iterable[tuple[float, float]]) -> MapBounds:
    lat_values = [bounds.min_lat, bounds.max_lat]
    lon_values = [bounds.min_lon, bounds.max_lon]
    for lat, lon in points:
        lat_values.append(lat)
        lon_values.append(lon)
    min_lat = min(lat_values)
    max_lat = max(lat_values)
    min_lon = min(lon_values)
    max_lon = max(lon_values)
    lat_pad = max((max_lat - min_lat) * 0.08, 0.01)
    lon_pad = max((max_lon - min_lon) * 0.08, 0.01)
    return MapBounds(
        min_lat=max(-85.0, min_lat - lat_pad),
        max_lat=min(85.0, max_lat + lat_pad),
        min_lon=max(-180.0, min_lon - lon_pad),
        max_lon=min(180.0, max_lon + lon_pad),
    )


def _bounds_for_points(points: typing.Iterable[tuple[float, float]]) -> MapBounds:
    values = list(points)
    if not values:
        return DEFAULT_MAP_BOUNDS
    lats = [lat for lat, _lon in values]
    lons = [lon for _lat, lon in values]
    min_lat = min(lats)
    max_lat = max(lats)
    min_lon = min(lons)
    max_lon = max(lons)
    if min_lat == max_lat:
        min_lat -= 0.04
        max_lat += 0.04
    if min_lon == max_lon:
        min_lon -= 0.04
        max_lon += 0.04
    return _expand_bounds(
        MapBounds(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon),
        (),
    )


def _use_button_label(mode: str) -> str:
    return {
        "point": "Use Point",
        "polygon": "Use Polygon",
        "route": "Use Route",
    }.get(mode, "Use")


def _mode_label(mode: str) -> str:
    return {
        "point": "Point",
        "polygon": "Polygon",
        "route": "Route",
    }.get(mode, "Selection")


def _clamp_lat(value: float) -> float:
    return max(-85.0, min(85.0, float(value)))


def _clamp_lon(value: float) -> float:
    return max(-180.0, min(180.0, float(value)))

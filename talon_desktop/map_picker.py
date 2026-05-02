"""Reusable PySide6 map coordinate pickers for desktop workflows."""
from __future__ import annotations

import dataclasses
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
from talon_desktop.map_scene_tiles import MapTileSceneRenderer
from talon_desktop.map_tiles import (
    TILE_LAYERS,
    TILE_LAYERS_BY_KEY,
    build_tile_plan,
    lat_lon_for_scene_point,
    pan_bounds_by_scene_delta,
    scene_point_for_lat_lon,
    zoom_bounds_around_scene_point,
)
from talon_desktop.mission_icons import (
    draw_mission_location_icon,
    mission_location_icon_key,
)

_log = get_logger("desktop.map_picker")


@dataclasses.dataclass(frozen=True)
class DraftMapOverlay:
    label: str
    mode: typing.Literal["point", "polygon", "route"]
    points: tuple[tuple[float, float], ...]
    icon_key: str = ""


class MapPickView(QtWidgets.QGraphicsView):
    """Graphics view that emits latitude/longitude clicks."""

    locationClicked = QtCore.Signal(float, float)
    zoomRequested = QtCore.Signal(float, float, int)
    panRequested = QtCore.Signal(float, float)
    sceneSizeChanged = QtCore.Signal(float, float)

    def __init__(self, scene: QtWidgets.QGraphicsScene, bounds: MapBounds) -> None:
        super().__init__(scene)
        self._bounds = bounds
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.SmartViewportUpdate)
        self.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._scene_width = SCENE_WIDTH
        self._scene_height = SCENE_HEIGHT
        self._scene_margin = 0.0
        self._pan_active = False
        self._pan_moved = False
        self._last_pan_pos = QtCore.QPoint()
        self._pending_pan_delta = QtCore.QPointF()
        self._pan_timer = QtCore.QTimer(self)
        self._pan_timer.setInterval(16)
        self._pan_timer.setSingleShot(True)
        self._pan_timer.timeout.connect(self._emit_pending_pan)
        self._pending_zoom_delta = 0
        self._pending_zoom_point = QtCore.QPointF()
        self._zoom_timer = QtCore.QTimer(self)
        self._zoom_timer.setInterval(24)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._emit_pending_zoom)

    def set_bounds(self, bounds: MapBounds) -> None:
        self._bounds = bounds

    def set_scene_geometry(
        self,
        width: float,
        height: float,
        margin: float,
    ) -> None:
        self._scene_width = max(1.0, float(width))
        self._scene_height = max(1.0, float(height))
        self._scene_margin = max(0.0, float(margin))

    def reset_zoom(self) -> None:
        self.resetTransform()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.reset_zoom()
        size = self.viewport().size()
        self.sceneSizeChanged.emit(float(size.width()), float(size.height()))

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._pan_active = True
            self._pan_moved = False
            self._last_pan_pos = event.position().toPoint()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._pan_active and event.buttons() & QtCore.Qt.LeftButton:
            current = event.position().toPoint()
            delta = current - self._last_pan_pos
            if delta.manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                self._pan_moved = True
            if self._pan_moved and not delta.isNull():
                last_scene = self.mapToScene(self._last_pan_pos)
                current_scene = self.mapToScene(current)
                self._queue_pan_delta(
                    QtCore.QPointF(
                        current_scene.x() - last_scene.x(),
                        current_scene.y() - last_scene.y(),
                    )
                )
                self._last_pan_pos = current
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton and self._pan_active:
            self._emit_pending_pan()
            self.setCursor(QtCore.Qt.CrossCursor)
            if not self._pan_moved:
                point = self.mapToScene(event.position().toPoint())
                lat, lon = lat_lon_for_scene_point(
                    self._bounds,
                    point.x(),
                    point.y(),
                    scene_width=self._scene_width,
                    scene_height=self._scene_height,
                    scene_margin=self._scene_margin,
                )
                self.locationClicked.emit(lat, lon)
            self._pan_active = False
            self._pan_moved = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        point = self.mapToScene(event.position().toPoint())
        self._pending_zoom_delta += delta
        self._pending_zoom_point = QtCore.QPointF(point.x(), point.y())
        if not self._zoom_timer.isActive():
            self._zoom_timer.start()
        event.accept()

    def _queue_pan_delta(self, delta: QtCore.QPointF) -> None:
        self._pending_pan_delta += delta
        if not self._pan_timer.isActive():
            self._pan_timer.start()

    def _emit_pending_pan(self) -> None:
        if self._pending_pan_delta.isNull():
            return
        delta = QtCore.QPointF(self._pending_pan_delta)
        self._pending_pan_delta = QtCore.QPointF()
        self.panRequested.emit(delta.x(), delta.y())

    def _emit_pending_zoom(self) -> None:
        if self._pending_zoom_delta == 0:
            return
        delta = self._pending_zoom_delta
        point = QtCore.QPointF(self._pending_zoom_point)
        self._pending_zoom_delta = 0
        self.zoomRequested.emit(point.x(), point.y(), delta)


class MapCoordinateDialog(QtWidgets.QDialog):
    """Pick a point, polygon, or route on the operational map context."""

    selectionChanged = QtCore.Signal()

    def __init__(
        self,
        *,
        core: TalonCoreSession | None,
        title: str,
        mode: typing.Literal["point", "polygon", "route"],
        initial_points: typing.Iterable[tuple[float, float]] = (),
        draft_overlays: typing.Iterable[DraftMapOverlay | typing.Mapping[str, object]] = (),
        minimum_points: int | None = None,
        selection_icon_key: str = "",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._core = core
        self._mode = mode
        self._minimum_points = minimum_points or (3 if mode == "polygon" else 1)
        self._points = [(_clamp_lat(lat), _clamp_lon(lon)) for lat, lon in initial_points]
        self._draft_overlays = _normalise_draft_overlays(draft_overlays)
        self._selection_icon_key = _selection_icon_key(selection_icon_key, title)
        self._context: object | None = None
        self._sitrep_entries: list[object] = []
        self._bounds = DEFAULT_MAP_BOUNDS
        self._scene_width = SCENE_WIDTH
        self._scene_height = SCENE_HEIGHT
        self._scene_margin = 0.0
        self._tile_generation = 0
        self._active_tile_layer_key = "osm"
        self._network = QtNetwork.QNetworkAccessManager(self)
        self._install_tile_cache()

        self.setWindowTitle(title)
        self.setMinimumSize(760, 520)

        self._load_context()
        self._bounds = self._initial_bounds()

        self._scene = QtWidgets.QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, SCENE_WIDTH, SCENE_HEIGHT)
        self._tile_renderer = MapTileSceneRenderer(
            scene=self._scene,
            network=self._network,
            user_agent="TALON Desktop/0.1 PySide6 map picker",
            logger=_log,
        )
        self.view = MapPickView(self._scene, self._bounds)
        self.view.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing
        )
        self.view.setMinimumSize(520, 340)
        self.view.locationClicked.connect(self._add_point)
        self.view.zoomRequested.connect(self._zoom_at_scene_point)
        self.view.panRequested.connect(self._pan_by_scene_delta)
        self.view.sceneSizeChanged.connect(self._resize_scene)
        self.view.set_scene_geometry(
            self._scene_width,
            self._scene_height,
            self._scene_margin,
        )

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
        QtCore.QTimer.singleShot(0, self._sync_scene_size_to_view)

    @property
    def selected_points(self) -> list[tuple[float, float]]:
        return list(self._points)

    def configure_selection(
        self,
        *,
        title: str,
        mode: typing.Literal["point", "polygon", "route"],
        initial_points: typing.Iterable[tuple[float, float]] = (),
        draft_overlays: typing.Iterable[DraftMapOverlay | typing.Mapping[str, object]] = (),
        minimum_points: int | None = None,
        selection_icon_key: str = "",
        refit: bool = True,
    ) -> None:
        self._mode = mode
        self._minimum_points = minimum_points or (3 if mode == "polygon" else 1)
        self._points = [
            (_clamp_lat(lat), _clamp_lon(lon))
            for lat, lon in initial_points
        ]
        self._draft_overlays = _normalise_draft_overlays(draft_overlays)
        self._selection_icon_key = _selection_icon_key(selection_icon_key, title)
        self.setWindowTitle(title)
        self.use_button.setText(_use_button_label(mode))
        if refit:
            self._bounds = self._initial_bounds()
            self.view.set_bounds(self._bounds)
        self._render()
        self._sync_status()
        self.selectionChanged.emit()

    def set_draft_overlays(
        self,
        draft_overlays: typing.Iterable[DraftMapOverlay | typing.Mapping[str, object]],
        *,
        refit: bool = False,
    ) -> None:
        self._draft_overlays = _normalise_draft_overlays(draft_overlays)
        if refit:
            self._bounds = self._initial_bounds()
            self.view.set_bounds(self._bounds)
        self._render()

    def selection_error(self) -> str:
        if len(self._points) < self._minimum_points:
            return (
                f"{_mode_label(self._mode)} requires at least "
                f"{self._minimum_points} point(s)."
            )
        return ""

    def accept(self) -> None:
        error = self.selection_error()
        if error:
            self.status_label.setText(error)
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
        draft_points = [
            point
            for overlay in self._draft_overlays
            for point in overlay.points
        ]
        all_points = [*self._points, *draft_points]
        if all_points:
            bounds = (
                _expand_bounds(bounds, all_points)
                if context_loaded
                else _bounds_for_points(all_points)
            )
        return bounds

    def _render(self) -> None:
        self._tile_generation = self._tile_renderer.begin_frame()
        self._draw_background()
        self._draw_tile_layer()
        self._draw_context_overlays()
        self._draw_draft_overlays()
        self._draw_selection()
        self._scene.setSceneRect(0, 0, self._scene_width, self._scene_height)

    def _sync_scene_size_to_view(self) -> None:
        size = self.view.viewport().size()
        self._resize_scene(float(size.width()), float(size.height()))

    def _resize_scene(self, width: float, height: float) -> None:
        next_width = max(1.0, float(width))
        next_height = max(1.0, float(height))
        if (
            abs(next_width - self._scene_width) < 1.0
            and abs(next_height - self._scene_height) < 1.0
        ):
            return
        self._scene_width = next_width
        self._scene_height = next_height
        self._scene.setSceneRect(0, 0, self._scene_width, self._scene_height)
        self.view.set_scene_geometry(
            self._scene_width,
            self._scene_height,
            self._scene_margin,
        )
        self._render()

    def _draw_background(self) -> None:
        self._scene.addRect(
            0,
            0,
            self._scene_width,
            self._scene_height,
            QtGui.QPen(QtGui.QColor("#2f3437")),
            QtGui.QBrush(QtGui.QColor("#111619")),
        ).setZValue(-40)
        grid_pen = QtGui.QPen(QtGui.QColor(236, 240, 241, 34))
        for x in range(100, int(self._scene_width), 100):
            self._scene.addLine(x, 0, x, self._scene_height, grid_pen).setZValue(-5)
        for y in range(100, int(self._scene_height), 100):
            self._scene.addLine(0, y, self._scene_width, y, grid_pen).setZValue(-5)

    def _draw_tile_layer(self) -> None:
        layer = TILE_LAYERS_BY_KEY.get(self._active_tile_layer_key, TILE_LAYERS[0])
        plan = build_tile_plan(
            layer,
            self._bounds,
            scene_width=self._scene_width,
            scene_height=self._scene_height,
            scene_margin=self._scene_margin,
        )
        self._tile_renderer.request_tiles(plan.requests)
        item = self._scene.addText(layer.attribution)
        item.setDefaultTextColor(QtGui.QColor("#ecf0f1"))
        item.setZValue(30)
        rect = item.boundingRect()
        item.setPos(
            self._scene_width - rect.width() - 12,
            self._scene_height - rect.height() - 8,
        )

    def _draw_context_overlays(self) -> None:
        if self._context is None:
            return
        try:
            bundle = build_map_overlays(
                self._context,
                sitrep_entries=self._sitrep_entries,
                bounds=self._bounds,
                scene_width=self._scene_width,
                scene_height=self._scene_height,
                scene_margin=self._scene_margin,
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
            item = self._scene.addPath(path, QtGui.QPen(QtGui.QColor("#3498db"), 2))
            item.setToolTip(route.mission_label)
            item.setZValue(6)
        for waypoint in bundle.waypoints:
            item = self._scene.addEllipse(
                waypoint.point.x - 4,
                waypoint.point.y - 4,
                8,
                8,
                QtGui.QPen(QtGui.QColor("#1f6fa8"), 1),
                QtGui.QBrush(QtGui.QColor("#3498db")),
            )
            item.setToolTip(waypoint.label)
            item.setZValue(7)
        for location in bundle.mission_locations:
            item = draw_mission_location_icon(
                self._scene,
                location.key,
                location.point.x,
                location.point.y,
                z=8,
                size=10,
            )
            item.setToolTip(f"{location.label}: {location.mission_label}")
        for asset in bundle.assets:
            item = _draw_selection_icon(
                self._scene,
                f"asset:{asset.category}",
                asset.point.x,
                asset.point.y,
                z=8,
            )
            item.setToolTip(asset.label)
        for sitrep in bundle.sitreps:
            item = _draw_selection_icon(
                self._scene,
                "sitrep",
                sitrep.point.x,
                sitrep.point.y,
                z=9,
            )
            item.setToolTip(f"{sitrep.level} SITREP #{sitrep.id}")

    def _draw_draft_overlays(self) -> None:
        for overlay in self._draft_overlays:
            scene_points = [
                QtCore.QPointF(
                    *scene_point_for_lat_lon(
                        self._bounds,
                        lat,
                        lon,
                        scene_width=self._scene_width,
                        scene_height=self._scene_height,
                        scene_margin=self._scene_margin,
                    )
                )
                for lat, lon in overlay.points
            ]
            if not scene_points:
                continue
            if overlay.mode == "polygon":
                pen = QtGui.QPen(QtGui.QColor("#3498db"), 2)
                fill = QtGui.QBrush(QtGui.QColor(52, 152, 219, 54))
            elif overlay.mode == "route":
                pen = QtGui.QPen(QtGui.QColor("#3498db"), 2)
                fill = QtGui.QBrush(QtGui.QColor(52, 152, 219, 54))
            else:
                pen = QtGui.QPen(QtGui.QColor(255, 223, 110, 175), 2)
                fill = QtGui.QBrush(QtGui.QColor(255, 223, 110, 34))
            pen.setStyle(QtCore.Qt.DashLine)
            if overlay.mode == "polygon" and len(scene_points) >= 3:
                item = self._scene.addPolygon(QtGui.QPolygonF(scene_points), pen, fill)
                item.setZValue(14)
            elif overlay.mode == "route" and len(scene_points) >= 2:
                path = QtGui.QPainterPath()
                path.moveTo(scene_points[0])
                for point in scene_points[1:]:
                    path.lineTo(point)
                item = self._scene.addPath(path, pen)
                item.setZValue(14)
            else:
                point = scene_points[0]
                if overlay.icon_key:
                    item = _draw_selection_icon(
                        self._scene,
                        overlay.icon_key,
                        point.x(),
                        point.y(),
                        z=15,
                        size=11,
                    )
                else:
                    item = self._scene.addEllipse(
                        point.x() - 7,
                        point.y() - 7,
                        14,
                        14,
                        pen,
                        QtGui.QBrush(QtGui.QColor(255, 223, 110, 155)),
                    )
                    item.setZValue(15)
            item.setToolTip(overlay.label)
            label = self._scene.addText(overlay.label)
            label.setDefaultTextColor(QtGui.QColor("#ffdf6e"))
            label.setZValue(16)
            anchor = scene_points[0]
            label_x = anchor.x() + 8
            label_y = anchor.y() - 24
            rect = label.boundingRect()
            background = self._scene.addRect(
                label_x - 4,
                label_y - 2,
                rect.width() + 8,
                rect.height() + 4,
                QtGui.QPen(QtCore.Qt.NoPen),
                QtGui.QBrush(QtGui.QColor(10, 15, 17, 215)),
            )
            background.setZValue(15)
            label.setPos(label_x, label_y)

    def _draw_selection(self) -> None:
        if not self._points:
            return
        scene_points = [
            QtCore.QPointF(
                *scene_point_for_lat_lon(
                    self._bounds,
                    lat,
                    lon,
                    scene_width=self._scene_width,
                    scene_height=self._scene_height,
                    scene_margin=self._scene_margin,
                )
            )
            for lat, lon in self._points
        ]
        pen = QtGui.QPen(QtGui.QColor("#f6fbfb"), 2)
        accent_pen = QtGui.QPen(QtGui.QColor("#3498db"), 3)
        if self._mode == "polygon" and len(scene_points) >= 3:
            polygon = QtGui.QPolygonF(scene_points)
            item = self._scene.addPolygon(
                polygon,
                accent_pen,
                QtGui.QBrush(QtGui.QColor(52, 152, 219, 54)),
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
            if self._mode == "point" and self._selection_icon_key:
                _draw_selection_icon(
                    self._scene,
                    self._selection_icon_key,
                    point.x(),
                    point.y(),
                    z=25,
                    size=12,
                )
                continue
            ellipse = self._scene.addEllipse(
                point.x() - 8,
                point.y() - 8,
                16,
                16,
                pen,
                QtGui.QBrush(QtGui.QColor("#3498db")),
            )
            ellipse.setZValue(25)
            label = self._scene.addText(str(index))
            label.setDefaultTextColor(QtGui.QColor("#edf3f5"))
            label.setZValue(26)
            rect = label.boundingRect()
            label.setPos(point.x() - rect.width() / 2, point.y() - rect.height() / 2)

    def _add_point(self, lat: float, lon: float) -> None:
        point = (_clamp_lat(lat), _clamp_lon(lon))
        if self._mode == "point":
            self._points = [point]
        else:
            self._points.append(point)
        self._render()
        self._sync_status()
        self.selectionChanged.emit()

    def _clear_points(self) -> None:
        self._points.clear()
        self._render()
        self._sync_status()
        self.selectionChanged.emit()

    def _undo_point(self) -> None:
        if self._points:
            self._points.pop()
        self._render()
        self._sync_status()
        self.selectionChanged.emit()

    def _set_tile_layer(self, key: str) -> None:
        if key == self._active_tile_layer_key:
            return
        self._active_tile_layer_key = key
        self._render()

    def _zoom_at_scene_point(self, x: float, y: float, wheel_delta: int) -> None:
        steps = max(-4, min(4, wheel_delta / 120.0))
        factor = 1.75**steps
        next_bounds = zoom_bounds_around_scene_point(
            self._bounds,
            x,
            y,
            factor,
            scene_width=self._scene_width,
            scene_height=self._scene_height,
            scene_margin=self._scene_margin,
        )
        if next_bounds == self._bounds:
            return
        self._bounds = next_bounds
        self.view.set_bounds(next_bounds)
        self._render()

    def _pan_by_scene_delta(self, delta_x: float, delta_y: float) -> None:
        next_bounds = pan_bounds_by_scene_delta(
            self._bounds,
            delta_x,
            delta_y,
            scene_width=self._scene_width,
            scene_height=self._scene_height,
            scene_margin=self._scene_margin,
        )
        if next_bounds == self._bounds:
            return
        self._bounds = next_bounds
        self.view.set_bounds(next_bounds)
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
    draft_overlays: typing.Iterable[DraftMapOverlay | typing.Mapping[str, object]] = (),
    selection_icon_key: str = "",
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
            draft_overlays=draft_overlays,
            selection_icon_key=selection_icon_key,
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
    draft_overlays: typing.Iterable[DraftMapOverlay | typing.Mapping[str, object]] = (),
    parent: QtWidgets.QWidget | None = None,
) -> list[tuple[float, float]] | None:
    dialog = MapCoordinateDialog(
        core=core,
        title=title,
        mode=mode,
        initial_points=initial_points,
        draft_overlays=draft_overlays,
        parent=parent,
    )
    if dialog.exec() != QtWidgets.QDialog.Accepted:
        return None
    return dialog.selected_points


def format_coordinate(lat: float, lon: float) -> str:
    return f"{lat:.6f}, {lon:.6f}"


def _normalise_draft_overlays(
    overlays: typing.Iterable[DraftMapOverlay | typing.Mapping[str, object]],
) -> tuple[DraftMapOverlay, ...]:
    result: list[DraftMapOverlay] = []
    for overlay in overlays:
        if isinstance(overlay, DraftMapOverlay):
            candidate = overlay
        else:
            mode = str(overlay.get("mode", "point"))
            if mode not in {"point", "polygon", "route"}:
                continue
            points = tuple(
                (_clamp_lat(lat), _clamp_lon(lon))
                for lat, lon in typing.cast(
                    typing.Iterable[tuple[float, float]],
                    overlay.get("points", ()),
                )
            )
            candidate = DraftMapOverlay(
                label=str(overlay.get("label", "Draft")),
                mode=typing.cast(typing.Literal["point", "polygon", "route"], mode),
                points=points,
                icon_key=_selection_icon_key(str(overlay.get("icon_key", "")), ""),
            )
        if candidate.points:
            result.append(candidate)
    return tuple(result)


def _selection_icon_key(icon_key: str, title: str) -> str:
    raw = str(icon_key or "").strip()
    if raw.startswith("asset:"):
        return raw
    if raw in {"assignment", "sitrep", "operator_ping"}:
        return raw
    mission_key = mission_location_icon_key(raw or title)
    if mission_key:
        return mission_key
    return raw


def _draw_selection_icon(
    scene: QtWidgets.QGraphicsScene,
    icon_key: str,
    x: float,
    y: float,
    *,
    z: float,
    size: float = 12.0,
) -> QtWidgets.QGraphicsItem:
    key = _selection_icon_key(icon_key, "")
    if key.startswith("asset:"):
        from talon_desktop.icons import asset_marker_pixmap

        category = key.split(":", 1)[1] or "custom"
        pixmap = asset_marker_pixmap(category, verified=False, selected=True, size=30)
        item = scene.addPixmap(pixmap)
        item.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
        item.setPos(float(x), float(y))
        item.setZValue(z)
        return item
    if key == "assignment":
        point_size = float(size)
        item = scene.addPolygon(
            QtGui.QPolygonF(
                [
                    QtCore.QPointF(x, y - point_size),
                    QtCore.QPointF(x + point_size, y),
                    QtCore.QPointF(x, y + point_size),
                    QtCore.QPointF(x - point_size, y),
                ]
            ),
            QtGui.QPen(QtGui.QColor("#ecf0f1"), 2),
            QtGui.QBrush(QtGui.QColor("#8fbcbb")),
        )
        item.setZValue(z)
        return item
    if key == "sitrep":
        point_size = float(size)
        item = scene.addRect(
            x - point_size,
            y - point_size,
            point_size * 2,
            point_size * 2,
            QtGui.QPen(QtGui.QColor("#ecf0f1"), 2),
            QtGui.QBrush(QtGui.QColor("#e74c3c")),
        )
        item.setRotation(45)
        item.setTransformOriginPoint(x, y)
        item.setZValue(z)
        return item
    if key == "operator_ping":
        radius = float(size)
        item = scene.addEllipse(
            x - radius,
            y - radius,
            radius * 2,
            radius * 2,
            QtGui.QPen(QtGui.QColor("#7fb069"), 2),
            QtGui.QBrush(QtGui.QColor(127, 176, 105, 130)),
        )
        item.setZValue(z)
        return item
    mission_key = mission_location_icon_key(key)
    if mission_key:
        return draw_mission_location_icon(scene, mission_key, x, y, z=z, size=size)
    radius = float(size)
    item = scene.addEllipse(
        x - radius,
        y - radius,
        radius * 2,
        radius * 2,
        QtGui.QPen(QtGui.QColor("#f6fbfb"), 2),
        QtGui.QBrush(QtGui.QColor("#3498db")),
    )
    item.setZValue(z)
    return item


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

"""PySide6 operational map page."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6 import QtNetwork

from talon_core import TalonCoreSession
from talon_core.utils.logging import get_logger
from talon_desktop.map_data import (
    SCENE_HEIGHT,
    SCENE_WIDTH,
    AssetOverlay,
    MapOverlayBundle,
    RouteOverlay,
    SitrepOverlay,
    WaypointOverlay,
    ZoneOverlay,
    build_map_overlays,
)
from talon_desktop.map_tiles import (
    TILE_LAYERS,
    TILE_LAYERS_BY_KEY,
    TileRequest,
    build_tile_plan,
)

_log = get_logger("desktop.map")

_ZONE_COLORS = {
    "AO": QtGui.QColor(52, 152, 219, 70),
    "DANGER": QtGui.QColor(231, 76, 60, 80),
    "RESTRICTED": QtGui.QColor(155, 89, 182, 75),
    "FRIENDLY": QtGui.QColor(46, 204, 113, 70),
    "OBJECTIVE": QtGui.QColor(241, 196, 15, 75),
}


class MapGraphicsView(QtWidgets.QGraphicsView):
    """Graphics view with standard mouse-wheel zoom behavior."""

    def __init__(self, scene: QtWidgets.QGraphicsScene) -> None:
        super().__init__(scene)
        self._zoom_steps = 0
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)

    def reset_zoom(self) -> None:
        self._zoom_steps = 0
        self.resetTransform()
        scene = self.scene()
        if scene is not None:
            self.fitInView(scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

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
        factor = 1.2 if direction > 0 else 1 / 1.2
        self.scale(factor, factor)
        self._zoom_steps = next_steps
        event.accept()


class MapPage(QtWidgets.QWidget):
    """Rendered operational map driven by core map read models."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._scene = QtWidgets.QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, SCENE_WIDTH, SCENE_HEIGHT)
        self._scene.selectionChanged.connect(self._selection_changed)
        self._bundle: MapOverlayBundle | None = None
        self._mission_ids: list[int | None] = [None]
        self._overlay_details: dict[str, str] = {}
        self._tile_generation = 0
        self._active_tile_layer_key = "osm"
        self._network = QtNetwork.QNetworkAccessManager(self)
        self._install_tile_cache()

        self.heading = QtWidgets.QLabel("Map")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.mission_filter = QtWidgets.QComboBox()
        self.mission_filter.currentIndexChanged.connect(lambda _index: self.refresh())
        self.layer_group = QtWidgets.QButtonGroup(self)
        self.layer_buttons: dict[str, QtWidgets.QRadioButton] = {}
        layer_row = QtWidgets.QHBoxLayout()
        layer_row.setSpacing(6)
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
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addLayout(layer_row)
        top_row.addWidget(self.mission_filter)
        top_row.addWidget(self.refresh_button)

        self.view = MapGraphicsView(self._scene)
        self.view.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing
        )
        self.view.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.view.setMinimumSize(720, 480)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self.summary)
        layout.addWidget(self.view, stretch=1)

    def refresh(self) -> None:
        selected_mission_id = self._selected_mission_id()
        try:
            filters = {"mission_id": selected_mission_id} if selected_mission_id else {}
            context = self._core.read_model("map.context", filters)
            sitrep_filters = {"mission_id": selected_mission_id} if selected_mission_id else {}
            sitreps = self._core.read_model("sitreps.list", sitrep_filters)
            self._sync_mission_filter(context, selected_mission_id)
            self._bundle = build_map_overlays(context, sitrep_entries=sitreps)
            self._render_bundle(self._bundle)
        except Exception as exc:
            _log.warning("Could not refresh map: %s", exc)
            self.summary.setText(f"Unable to load map: {exc}")
            return

        assert self._bundle is not None
        self.summary.setText(
            "Map overlays: "
            f"{len(self._bundle.assets)} assets, "
            f"{len(self._bundle.zones)} zones, "
            f"{len(self._bundle.routes)} routes, "
            f"{len(self._bundle.waypoints)} waypoints, "
            f"{len(self._bundle.sitreps)} linked SITREPs."
        )

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        _ = action, record_id
        if table in {"assets", "missions", "zones", "waypoints", "sitreps"}:
            self.refresh()

    def _render_bundle(self, bundle: MapOverlayBundle) -> None:
        self._scene.clear()
        self._overlay_details.clear()
        self._tile_generation += 1
        self._draw_background()
        self._draw_tile_layer(bundle)
        for zone in bundle.zones:
            self._draw_zone(zone)
        for route in bundle.routes:
            self._draw_route(route)
        for waypoint in bundle.waypoints:
            self._draw_waypoint(waypoint)
        for asset in bundle.assets:
            self._draw_asset(asset)
        for sitrep in bundle.sitreps:
            self._draw_sitrep(sitrep)
        self._scene.setSceneRect(0, 0, SCENE_WIDTH, SCENE_HEIGHT)
        self.view.reset_zoom()

    def _draw_background(self) -> None:
        self._scene.addRect(
            0,
            0,
            SCENE_WIDTH,
            SCENE_HEIGHT,
            QtGui.QPen(QtGui.QColor("#2f3437")),
            QtGui.QBrush(QtGui.QColor("#111619")),
        ).setZValue(-30)
        grid_pen = QtGui.QPen(QtGui.QColor(236, 240, 241, 34))
        for x in range(100, int(SCENE_WIDTH), 100):
            item = self._scene.addLine(x, 0, x, SCENE_HEIGHT, grid_pen)
            item.setZValue(-5)
        for y in range(100, int(SCENE_HEIGHT), 100):
            item = self._scene.addLine(0, y, SCENE_WIDTH, y, grid_pen)
            item.setZValue(-5)

    def _draw_tile_layer(self, bundle: MapOverlayBundle) -> None:
        layer = TILE_LAYERS_BY_KEY.get(self._active_tile_layer_key, TILE_LAYERS[0])
        plan = build_tile_plan(layer, bundle.bounds)
        generation = self._tile_generation
        for request in plan.requests:
            self._request_tile(request, generation)
        self._draw_attribution(layer.attribution)

    def _request_tile(self, tile: TileRequest, generation: int) -> None:
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(tile.url))
        request.setHeader(
            QtNetwork.QNetworkRequest.UserAgentHeader,
            "TALON Desktop/0.1 PySide6 map",
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
                _log.debug("Map tile request failed: %s", reply.errorString())
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

    def _draw_attribution(self, text: str) -> None:
        item = self._scene.addText(text)
        item.setDefaultTextColor(QtGui.QColor("#ecf0f1"))
        item.setZValue(30)
        bounds = item.boundingRect()
        item.setPos(
            SCENE_WIDTH - bounds.width() - 12,
            SCENE_HEIGHT - bounds.height() - 8,
        )

    def _draw_zone(self, zone: ZoneOverlay) -> None:
        polygon = QtGui.QPolygonF(
            [QtCore.QPointF(point.x, point.y) for point in zone.points]
        )
        color = _ZONE_COLORS.get(zone.zone_type, QtGui.QColor(149, 165, 166, 70))
        item = self._scene.addPolygon(
            polygon,
            QtGui.QPen(color.darker(130), 2),
            QtGui.QBrush(color),
        )
        self._register_item(
            item,
            key=f"zone:{zone.id}",
            label=zone.label,
            detail=(
                f"Zone #{zone.id}\n"
                f"Label: {zone.label}\n"
                f"Type: {zone.zone_type}\n"
                f"Mission: {zone.mission_id or ''}\n"
                f"Vertices: {len(zone.points)}"
            ),
        )

    def _draw_route(self, route: RouteOverlay) -> None:
        path = QtGui.QPainterPath()
        first = route.points[0]
        path.moveTo(first.x, first.y)
        for point in route.points[1:]:
            path.lineTo(point.x, point.y)
        item = self._scene.addPath(path, QtGui.QPen(QtGui.QColor("#f1c40f"), 3))
        self._register_item(
            item,
            key=f"mission:{route.mission_id}",
            label=route.mission_label,
            detail=(
                f"Mission #{route.mission_id}\n"
                f"Title: {route.mission_label}\n"
                f"Route points: {len(route.points)}"
            ),
        )

    def _draw_waypoint(self, waypoint: WaypointOverlay) -> None:
        item = self._scene.addEllipse(
            waypoint.point.x - 5,
            waypoint.point.y - 5,
            10,
            10,
            QtGui.QPen(QtGui.QColor("#f39c12"), 2),
            QtGui.QBrush(QtGui.QColor("#f1c40f")),
        )
        self._register_item(
            item,
            key=f"waypoint:{waypoint.id}",
            label=waypoint.label,
            detail=(
                f"Waypoint #{waypoint.id}\n"
                f"Label: {waypoint.label}\n"
                f"Mission: {waypoint.mission_id}\n"
                f"Sequence: {waypoint.sequence}\n"
                f"Lat/Lon: {waypoint.point.lat:.6f}, {waypoint.point.lon:.6f}"
            ),
        )

    def _draw_asset(self, asset: AssetOverlay) -> None:
        color = QtGui.QColor("#2ecc71") if asset.verified else QtGui.QColor("#e67e22")
        item = self._scene.addEllipse(
            asset.point.x - 8,
            asset.point.y - 8,
            16,
            16,
            QtGui.QPen(QtGui.QColor("#ecf0f1"), 2),
            QtGui.QBrush(color),
        )
        self._register_item(
            item,
            key=f"asset:{asset.id}",
            label=asset.label,
            detail=(
                f"Asset #{asset.id}\n"
                f"Label: {asset.label}\n"
                f"Category: {asset.category}\n"
                f"Verified: {'Yes' if asset.verified else 'No'}\n"
                f"Mission: {asset.mission_id or ''}\n"
                f"Lat/Lon: {asset.point.lat:.6f}, {asset.point.lon:.6f}"
            ),
        )

    def _draw_sitrep(self, sitrep: SitrepOverlay) -> None:
        size = 7
        polygon = QtGui.QPolygonF(
            [
                QtCore.QPointF(sitrep.point.x, sitrep.point.y - 20 - size),
                QtCore.QPointF(sitrep.point.x + size, sitrep.point.y - 20),
                QtCore.QPointF(sitrep.point.x, sitrep.point.y - 20 + size),
                QtCore.QPointF(sitrep.point.x - size, sitrep.point.y - 20),
            ]
        )
        color = QtGui.QColor("#e74c3c") if sitrep.level.startswith("FLASH") else QtGui.QColor("#3498db")
        item = self._scene.addPolygon(
            polygon,
            QtGui.QPen(QtGui.QColor("#ecf0f1"), 1),
            QtGui.QBrush(color),
        )
        self._register_item(
            item,
            key=f"sitrep:{sitrep.id}",
            label=f"{sitrep.level} #{sitrep.id}",
            detail=(
                f"SITREP #{sitrep.id}\n"
                f"Level: {sitrep.level}\n"
                f"Asset: {sitrep.asset_id}\n"
                f"Mission: {sitrep.mission_id or ''}\n\n"
                f"{sitrep.body}"
            ),
        )

    def _register_item(
        self,
        item: QtWidgets.QGraphicsItem,
        *,
        key: str,
        label: str,
        detail: str,
    ) -> None:
        item.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)
        item.setToolTip(label)
        item.setData(0, key)
        self._overlay_details[key] = detail

    def _selection_changed(self) -> None:
        selected = self._scene.selectedItems()
        if not selected:
            return
        key = selected[-1].data(0)
        detail = self._overlay_details.get(str(key))
        if detail:
            _log.debug("Map overlay selected: %s", detail.replace("\n", " | "))

    def _selected_mission_id(self) -> int | None:
        index = self.mission_filter.currentIndex()
        if index < 0 or index >= len(self._mission_ids):
            return None
        return self._mission_ids[index]

    def _sync_mission_filter(
        self,
        context: object,
        selected_mission_id: int | None,
    ) -> None:
        missions = list(getattr(context, "missions", []) or [])
        options: list[tuple[int | None, str]] = [(None, "All Missions")]
        options.extend(
            (int(getattr(mission, "id")), str(getattr(mission, "title")))
            for mission in missions
        )
        ids = [mission_id for mission_id, _label in options]
        if ids == self._mission_ids:
            return
        self.mission_filter.blockSignals(True)
        self.mission_filter.clear()
        self._mission_ids = ids
        for mission_id, label in options:
            self.mission_filter.addItem(label, mission_id)
        if selected_mission_id in ids:
            self.mission_filter.setCurrentIndex(ids.index(selected_mission_id))
        self.mission_filter.blockSignals(False)

    def _set_tile_layer(self, key: str) -> None:
        if key == self._active_tile_layer_key:
            return
        self._active_tile_layer_key = key
        if self._bundle is not None:
            self._render_bundle(self._bundle)
        else:
            self.refresh()

    def _install_tile_cache(self) -> None:
        cache = QtNetwork.QNetworkDiskCache(self)
        try:
            cache_dir = self._core.paths.data_dir / "cache" / "map_tiles"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache.setCacheDirectory(str(cache_dir))
            self._network.setCache(cache)
        except Exception as exc:
            _log.debug("Map tile cache disabled: %s", exc)

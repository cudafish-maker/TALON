"""PySide6 operational map page."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

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

_log = get_logger("desktop.map")

_ZONE_COLORS = {
    "AO": QtGui.QColor(52, 152, 219, 70),
    "DANGER": QtGui.QColor(231, 76, 60, 80),
    "RESTRICTED": QtGui.QColor(155, 89, 182, 75),
    "FRIENDLY": QtGui.QColor(46, 204, 113, 70),
    "OBJECTIVE": QtGui.QColor(241, 196, 15, 75),
}


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

        self.heading = QtWidgets.QLabel("Map")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.mission_filter = QtWidgets.QComboBox()
        self.mission_filter.currentIndexChanged.connect(lambda _index: self.refresh())
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.mission_filter)
        top_row.addWidget(self.refresh_button)

        self.view = QtWidgets.QGraphicsView(self._scene)
        self.view.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing
        )
        self.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.view.setMinimumSize(720, 480)

        self.context_panel = QtWidgets.QTextEdit()
        self.context_panel.setReadOnly(True)
        self.context_panel.setMinimumWidth(300)

        body = QtWidgets.QSplitter()
        body.addWidget(self.view)
        body.addWidget(self.context_panel)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self.summary)
        layout.addWidget(body, stretch=1)

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
        self.context_panel.setPlainText("Select a map overlay.")

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        _ = action, record_id
        if table in {"assets", "missions", "zones", "waypoints", "sitreps"}:
            self.refresh()

    def _render_bundle(self, bundle: MapOverlayBundle) -> None:
        self._scene.clear()
        self._overlay_details.clear()
        self._draw_background()
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
        self.view.fitInView(self._scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

    def _draw_background(self) -> None:
        self._scene.addRect(
            0,
            0,
            SCENE_WIDTH,
            SCENE_HEIGHT,
            QtGui.QPen(QtGui.QColor("#2f3437")),
            QtGui.QBrush(QtGui.QColor("#111619")),
        )
        grid_pen = QtGui.QPen(QtGui.QColor("#273036"))
        for x in range(100, int(SCENE_WIDTH), 100):
            self._scene.addLine(x, 0, x, SCENE_HEIGHT, grid_pen)
        for y in range(100, int(SCENE_HEIGHT), 100):
            self._scene.addLine(0, y, SCENE_WIDTH, y, grid_pen)

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
            self.context_panel.setPlainText(detail)

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

"""PySide6 operational map page."""
from __future__ import annotations

import math

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6 import QtNetwork

from talon_core import TalonCoreSession
from talon_core.utils.logging import get_logger
from talon_desktop.map_data import (
    SCENE_HEIGHT,
    SCENE_WIDTH,
    AssetOverlay,
    AssignmentOverlay,
    MapBounds,
    MapOverlayBundle,
    RouteOverlay,
    SitrepOverlay,
    WaypointOverlay,
    ZoneOverlay,
    build_map_overlays,
)
from talon_desktop.icons import asset_marker_pixmap
from talon_desktop.map_scene_tiles import MapTileSceneRenderer
from talon_desktop.map_tiles import (
    TILE_LAYERS,
    TILE_LAYERS_BY_KEY,
    WEB_MERCATOR_MAX_LAT,
    build_tile_plan,
    lat_lon_for_scene_point,
    pan_bounds_by_scene_delta,
    zoom_bounds_around_scene_point,
)

_log = get_logger("desktop.map")

_ZONE_COLORS = {
    "AO": QtGui.QColor(52, 152, 219, 70),
    "DANGER": QtGui.QColor(231, 76, 60, 80),
    "RESTRICTED": QtGui.QColor(155, 89, 182, 75),
    "FRIENDLY": QtGui.QColor(46, 204, 113, 70),
    "OBJECTIVE": QtGui.QColor(241, 196, 15, 75),
}
_ASSET_FOCUS_MIN_LAT_SPAN = 0.01
_ASSET_FOCUS_MAX_LAT_SPAN = 0.05
_ASSET_MARKER_SIZE = 32


class MapGraphicsView(QtWidgets.QGraphicsView):
    """Graphics view that delegates wheel zoom to the map page viewport."""

    zoomRequested = QtCore.Signal(float, float, int)
    panRequested = QtCore.Signal(float, float)
    sceneClicked = QtCore.Signal(float, float)
    sceneSizeChanged = QtCore.Signal(float, float)

    def __init__(self, scene: QtWidgets.QGraphicsScene) -> None:
        super().__init__(scene)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.SmartViewportUpdate)
        self.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
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
            self.setCursor(QtCore.Qt.ArrowCursor)
            if not self._pan_moved:
                point = self.mapToScene(event.position().toPoint())
                self.sceneClicked.emit(point.x(), point.y())
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


class MapRightPanelSplitter(QtWidgets.QSplitter):
    """Splitter that never restores into a horizontal map-panel layout."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(QtCore.Qt.Vertical, parent)

    def restoreState(self, state: QtCore.QByteArray) -> bool:
        restored = super().restoreState(state)
        self.setOrientation(QtCore.Qt.Vertical)
        return restored


class AssetMarkerItem(QtWidgets.QGraphicsPixmapItem):
    """Selectable asset marker that preserves verification state while selected."""

    def __init__(self, asset: AssetOverlay) -> None:
        super().__init__()
        self._category = asset.category
        self._verified = asset.verified
        self._sync_pixmap(selected=False)
        self.setPos(asset.point.x, asset.point.y)

    def itemChange(
        self,
        change: QtWidgets.QGraphicsItem.GraphicsItemChange,
        value: object,
    ) -> object:
        if (
            change
            == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged
        ):
            self._sync_pixmap(selected=bool(value))
        return super().itemChange(change, value)

    def _sync_pixmap(self, *, selected: bool) -> None:
        pixmap = asset_marker_pixmap(
            self._category,
            verified=self._verified,
            selected=selected,
            size=_ASSET_MARKER_SIZE,
        )
        self.setPixmap(pixmap)
        self.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)


class MapPage(QtWidgets.QWidget):
    """Rendered operational map driven by core map read models."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._scene = QtWidgets.QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, SCENE_WIDTH, SCENE_HEIGHT)
        self._scene.selectionChanged.connect(self._selection_changed)
        self._bundle: MapOverlayBundle | None = None
        self._map_context: object | None = None
        self._sitrep_entries: list[object] | None = None
        self._view_bounds: MapBounds | None = None
        self._mission_ids: list[int | None] = [None]
        self._overlay_details: dict[str, str] = {}
        self._visible_asset_ids: set[int] | None = None
        self._scene_width = SCENE_WIDTH
        self._scene_height = SCENE_HEIGHT
        self._scene_margin = 0.0
        self._tile_generation = 0
        self._active_tile_layer_key = "osm"
        self._network = QtNetwork.QNetworkAccessManager(self)
        self._tile_renderer = MapTileSceneRenderer(
            scene=self._scene,
            network=self._network,
            user_agent="TALON Desktop/0.1 PySide6 map",
            logger=_log,
        )
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
        self.report_here_button = QtWidgets.QPushButton("Report Here")
        self.report_here_button.clicked.connect(self._report_at_view_center)
        self.asset_filter_button = QtWidgets.QPushButton("Assets")
        self.asset_filter_button.clicked.connect(self._choose_visible_assets)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addLayout(layer_row)
        top_row.addWidget(self.mission_filter)
        top_row.addWidget(self.asset_filter_button)
        top_row.addWidget(self.report_here_button)
        top_row.addWidget(self.refresh_button)

        self.view = MapGraphicsView(self._scene)
        self.view.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing
        )
        self.view.setMinimumSize(320, 280)
        self.view.zoomRequested.connect(self._zoom_at_scene_point)
        self.view.panRequested.connect(self._pan_by_scene_delta)
        self.view.sceneClicked.connect(self._select_overlay_at_scene_point)
        self.view.sceneSizeChanged.connect(self._resize_scene)

        self.left_panel = self._build_left_panel()
        self.right_panel = self._build_right_panel()
        self.left_toggle = self._build_panel_toggle("left")
        self.right_toggle = self._build_panel_toggle("right")
        self._left_panel_collapsed = False
        self._right_panel_collapsed = False

        map_row = QtWidgets.QHBoxLayout()
        map_row.setContentsMargins(0, 0, 0, 0)
        map_row.setSpacing(6)
        map_row.addWidget(self.left_panel)
        map_row.addWidget(self.left_toggle)
        map_row.addWidget(self.view, stretch=1)
        map_row.addWidget(self.right_toggle)
        map_row.addWidget(self.right_panel)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self.summary)
        layout.addLayout(map_row, stretch=1)
        QtCore.QTimer.singleShot(0, self._sync_scene_size_to_view)

    def refresh(self) -> None:
        self._sync_scene_size_to_view(rerender=False)
        selected_mission_id = self._selected_mission_id()
        try:
            filters = {"mission_id": selected_mission_id} if selected_mission_id else {}
            context = self._core.read_model("map.context", filters)
            sitrep_filters = {"mission_id": selected_mission_id} if selected_mission_id else {}
            sitreps = self._core.read_model("sitreps.list", sitrep_filters)
            self._sync_mission_filter(context, selected_mission_id)
            base_bundle = self._build_map_overlays(context, sitrep_entries=sitreps)
            self._map_context = context
            self._sitrep_entries = list(sitreps)
            self._view_bounds = base_bundle.bounds
            self._bundle = base_bundle
            self._render_bundle(self._bundle, refit=True)
            self._refresh_side_panels()
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
            f"{len(self._bundle.assignments)} assignments, "
            f"{len(self._bundle.sitreps)} mapped SITREPs."
        )

    def _sync_scene_size_to_view(self, *, rerender: bool = True) -> None:
        if not hasattr(self, "view"):
            return
        size = self.view.viewport().size()
        self._resize_scene(
            float(size.width()),
            float(size.height()),
            rerender=rerender,
        )

    def _resize_scene(
        self,
        width: float,
        height: float,
        *,
        rerender: bool = True,
    ) -> None:
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
        if not rerender:
            return
        if (
            self._map_context is None
            or self._sitrep_entries is None
            or self._view_bounds is None
        ):
            return
        self._bundle = self._build_map_overlays(
            self._map_context,
            sitrep_entries=self._sitrep_entries,
            bounds=self._view_bounds,
        )
        self._render_bundle(self._bundle)

    def _build_map_overlays(
        self,
        context: object,
        *,
        sitrep_entries: object = (),
        bounds: MapBounds | None = None,
    ) -> MapOverlayBundle:
        return build_map_overlays(
            context,
            sitrep_entries=sitrep_entries,
            bounds=bounds,
            scene_width=self._scene_width,
            scene_height=self._scene_height,
            scene_margin=self._scene_margin,
        )

    def _build_left_panel(self) -> QtWidgets.QFrame:
        panel = QtWidgets.QFrame()
        panel.setObjectName("mapLeftPanel")
        panel.setFixedWidth(210)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Assets")
        title.setObjectName("sideMode")
        self.asset_panel_count = QtWidgets.QLabel("0")
        self.asset_panel_count.setObjectName("sideMode")
        self.asset_panel_count.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        )
        header.addWidget(title)
        header.addWidget(self.asset_panel_count)
        layout.addLayout(header)

        self.asset_panel_list = QtWidgets.QListWidget()
        self.asset_panel_list.setObjectName("mapSideList")
        self.asset_panel_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self.asset_panel_list.itemSelectionChanged.connect(
            self._zoom_to_selected_asset
        )
        layout.addWidget(self.asset_panel_list, stretch=1)
        return panel

    def _build_right_panel(self) -> QtWidgets.QFrame:
        panel = QtWidgets.QFrame()
        panel.setObjectName("mapRightPanel")
        panel.setFixedWidth(230)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.selection_detail = QtWidgets.QTextEdit()
        self.selection_detail.setObjectName("mapSelectionDetail")
        self.selection_detail.setReadOnly(True)
        self.selection_detail.setMinimumHeight(64)
        self._set_selection_detail("")

        self.mission_panel_count = QtWidgets.QLabel("0")
        self.mission_panel_count.setObjectName("sideMode")
        self.mission_panel_count.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        )
        self.mission_panel_list = QtWidgets.QListWidget()
        self.mission_panel_list.setObjectName("mapSideList")
        self.mission_panel_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self.mission_panel_list.setMinimumHeight(72)
        self.mission_panel_list.itemSelectionChanged.connect(
            self._select_mission_from_panel
        )

        self.sitrep_panel_count = QtWidgets.QLabel("0")
        self.sitrep_panel_count.setObjectName("sideMode")
        self.sitrep_panel_count.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        )
        self.sitrep_panel_list = QtWidgets.QListWidget()
        self.sitrep_panel_list.setObjectName("mapSideList")
        self.sitrep_panel_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self.sitrep_panel_list.setMinimumHeight(72)

        self.right_panel_splitter = MapRightPanelSplitter()
        self.right_panel_splitter.setObjectName("mapRightSplitter")
        self.right_panel_splitter.setChildrenCollapsible(False)
        self.right_panel_splitter.addWidget(
            self._build_right_panel_section("Selection", self.selection_detail)
        )
        self.right_panel_splitter.addWidget(
            self._build_right_panel_section(
                "Missions",
                self.mission_panel_list,
                self.mission_panel_count,
            )
        )
        self.right_panel_splitter.addWidget(
            self._build_right_panel_section(
                "SITREPs",
                self.sitrep_panel_list,
                self.sitrep_panel_count,
            )
        )
        self.right_panel_splitter.setStretchFactor(0, 1)
        self.right_panel_splitter.setStretchFactor(1, 2)
        self.right_panel_splitter.setStretchFactor(2, 2)
        self.right_panel_splitter.setSizes([130, 255, 255])
        layout.addWidget(self.right_panel_splitter, stretch=1)
        return panel

    def _build_right_panel_section(
        self,
        title: str,
        content: QtWidgets.QWidget,
        count_label: QtWidgets.QLabel | None = None,
    ) -> QtWidgets.QWidget:
        section = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(title)
        label.setObjectName("sideMode")
        header.addWidget(label)
        if count_label is not None:
            header.addWidget(count_label)
        layout.addLayout(header)
        layout.addWidget(content, stretch=1)
        return section

    def _build_panel_toggle(self, side: str) -> QtWidgets.QFrame:
        strip = QtWidgets.QFrame()
        strip.setObjectName("mapPanelToggleStrip")
        strip.setFixedWidth(22)
        layout = QtWidgets.QVBoxLayout(strip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        button = QtWidgets.QToolButton()
        button.setObjectName("mapPanelToggle")
        button.setText("<" if side == "left" else ">")
        button.setToolTip(
            "Collapse assets panel" if side == "left" else "Collapse context panel"
        )
        button.setFixedSize(22, 54)
        button.clicked.connect(
            lambda _checked=False, target=side: self._toggle_panel(target)
        )
        layout.addWidget(button)
        layout.addStretch(1)
        return strip

    def _toggle_panel(self, side: str) -> None:
        if side == "left":
            self._left_panel_collapsed = not self._left_panel_collapsed
            self.left_panel.setVisible(not self._left_panel_collapsed)
            button = self.left_toggle.findChild(QtWidgets.QToolButton)
            if button is not None:
                button.setText(">" if self._left_panel_collapsed else "<")
                button.setToolTip(
                    "Expand assets panel"
                    if self._left_panel_collapsed
                    else "Collapse assets panel"
                )
            return

        self._right_panel_collapsed = not self._right_panel_collapsed
        self.right_panel.setVisible(not self._right_panel_collapsed)
        button = self.right_toggle.findChild(QtWidgets.QToolButton)
        if button is not None:
            button.setText("<" if self._right_panel_collapsed else ">")
            button.setToolTip(
                "Expand context panel"
                if self._right_panel_collapsed
                else "Collapse context panel"
            )

    def _refresh_side_panels(self) -> None:
        context = self._map_context
        assets = list(getattr(context, "assets", []) or []) if context is not None else []
        missions = list(getattr(context, "missions", []) or []) if context is not None else []
        sitreps = list(self._sitrep_entries or [])

        visible_asset_ids = (
            {asset.id for asset in self._bundle.assets}
            if self._bundle is not None
            else set()
        )
        self.asset_panel_count.setText(f"{len(visible_asset_ids)}/{len(assets)}")
        self.asset_panel_list.blockSignals(True)
        try:
            self.asset_panel_list.clear()
            for asset in assets:
                label = str(getattr(asset, "label", "Asset"))
                category = str(getattr(asset, "category", ""))
                lat = getattr(asset, "lat", None)
                lon = getattr(asset, "lon", None)
                location = (
                    f"{lat:.4f}, {lon:.4f}"
                    if lat is not None and lon is not None
                    else "No GPS"
                )
                suffix = " [mapped]" if getattr(asset, "id", None) in visible_asset_ids else ""
                item = QtWidgets.QListWidgetItem(
                    f"{label}{suffix}\n{category.upper()} - {location}"
                )
                item.setData(QtCore.Qt.UserRole, f"asset:{getattr(asset, 'id', '')}")
                self.asset_panel_list.addItem(item)
        finally:
            self.asset_panel_list.blockSignals(False)

        selected_mission_id = self._selected_mission_id()
        self.mission_panel_count.setText(str(len(missions)))
        self.mission_panel_list.blockSignals(True)
        self.mission_panel_list.clear()
        try:
            for mission in missions:
                mission_id = getattr(mission, "id", "")
                title = str(getattr(mission, "title", "Mission"))
                status = str(getattr(mission, "status", "")).replace("_", " ").upper()
                item = QtWidgets.QListWidgetItem(f"{title}\n#{mission_id} - {status}")
                item.setData(QtCore.Qt.UserRole, f"mission:{mission_id}")
                self.mission_panel_list.addItem(item)
                if (
                    selected_mission_id is not None
                    and str(mission_id) == str(selected_mission_id)
                ):
                    self.mission_panel_list.setCurrentItem(item)
        finally:
            self.mission_panel_list.blockSignals(False)

        self.sitrep_panel_count.setText(str(len(sitreps)))
        self.sitrep_panel_list.clear()
        for entry in sitreps[:24]:
            sitrep = entry[0] if isinstance(entry, tuple) else entry
            sitrep_id = getattr(sitrep, "id", "")
            level = str(getattr(sitrep, "level", "SITREP"))
            raw_body = getattr(sitrep, "body", "")
            body = raw_body.decode("utf-8", errors="replace") if isinstance(raw_body, bytes) else str(raw_body)
            body = body[:72] + ("..." if len(body) > 72 else "")
            item = QtWidgets.QListWidgetItem(f"{level} #{sitrep_id}\n{body}")
            item.setData(QtCore.Qt.UserRole, f"sitrep:{sitrep_id}")
            self.sitrep_panel_list.addItem(item)

    def _zoom_to_selected_asset(self) -> None:
        item = self.asset_panel_list.currentItem()
        if item is None:
            return
        value = str(item.data(QtCore.Qt.UserRole) or "")
        if not value.startswith("asset:"):
            return
        try:
            asset_id = int(value.split(":", 1)[1])
        except ValueError:
            return
        self._zoom_to_asset(asset_id)

    def _zoom_to_asset(self, asset_id: int) -> None:
        if self._map_context is None or self._sitrep_entries is None:
            return
        asset = self._asset_by_id(asset_id)
        if asset is None:
            return
        coordinates = self._asset_coordinates(asset)
        if coordinates is None:
            self._set_selection_detail(f"Asset #{asset_id}\nNo GPS location.")
            return
        lat, lon = coordinates
        next_bounds = self._asset_focus_bounds(lat, lon)
        if next_bounds == self._view_bounds:
            self._select_overlay_by_key(f"asset:{asset_id}")
            return
        self._view_bounds = next_bounds
        self._bundle = self._build_map_overlays(
            self._map_context,
            sitrep_entries=self._sitrep_entries,
            bounds=next_bounds,
        )
        self._render_bundle(self._bundle)
        self._select_overlay_by_key(f"asset:{asset_id}")

    def _select_mission_from_panel(self) -> None:
        item = self.mission_panel_list.currentItem()
        if item is None:
            return
        value = str(item.data(QtCore.Qt.UserRole) or "")
        if not value.startswith("mission:"):
            return
        try:
            mission_id = int(value.split(":", 1)[1])
        except ValueError:
            return
        index = self.mission_filter.findData(mission_id)
        if index < 0 or index == self.mission_filter.currentIndex():
            return
        self.mission_filter.setCurrentIndex(index)

    def _asset_by_id(self, asset_id: int) -> object | None:
        context = self._map_context
        assets = list(getattr(context, "assets", []) or []) if context is not None else []
        for asset in assets:
            try:
                if int(getattr(asset, "id")) == asset_id:
                    return asset
            except (TypeError, ValueError):
                continue
        return None

    def _asset_coordinates(self, asset: object) -> tuple[float, float] | None:
        lat = getattr(asset, "lat", None)
        lon = getattr(asset, "lon", None)
        if lat is None or lon is None:
            return None
        try:
            lat_float = float(lat)
            lon_float = float(lon)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(lat_float) or not math.isfinite(lon_float):
            return None
        return lat_float, lon_float

    def _asset_focus_bounds(self, lat: float, lon: float) -> MapBounds:
        current = (
            self._view_bounds
            or (self._bundle.bounds if self._bundle is not None else None)
        )
        current_lat_span = (
            max(0.0001, abs(current.max_lat - current.min_lat))
            if current is not None
            else 1.0
        )
        current_lon_span = (
            max(0.0001, abs(current.max_lon - current.min_lon))
            if current is not None
            else 1.0
        )
        target_lat_span = min(
            current_lat_span,
            max(
                _ASSET_FOCUS_MIN_LAT_SPAN,
                min(current_lat_span * 0.25, _ASSET_FOCUS_MAX_LAT_SPAN),
            ),
        )
        aspect = max(0.25, min(4.0, self._scene_width / max(1.0, self._scene_height)))
        latitude_scale = max(
            0.25,
            math.cos(math.radians(max(-80.0, min(80.0, lat)))),
        )
        target_lon_span = min(
            current_lon_span,
            max(_ASSET_FOCUS_MIN_LAT_SPAN, target_lat_span * aspect / latitude_scale),
        )
        return MapBounds(
            min_lat=self._clamped_lower(lat, target_lat_span, -WEB_MERCATOR_MAX_LAT),
            max_lat=self._clamped_upper(lat, target_lat_span, WEB_MERCATOR_MAX_LAT),
            min_lon=self._clamped_lower(lon, target_lon_span, -180.0),
            max_lon=self._clamped_upper(lon, target_lon_span, 180.0),
        )

    def _select_overlay_by_key(self, key: str) -> bool:
        self._scene.clearSelection()
        for item in self._scene.items():
            if not (item.flags() & QtWidgets.QGraphicsItem.ItemIsSelectable):
                continue
            if str(item.data(0)) == key:
                item.setSelected(True)
                return True
        return False

    @staticmethod
    def _clamped_lower(center: float, span: float, minimum: float) -> float:
        return max(minimum, center - (span / 2.0))

    @staticmethod
    def _clamped_upper(center: float, span: float, maximum: float) -> float:
        return min(maximum, center + (span / 2.0))

    def _set_selection_detail(self, detail: str) -> None:
        if not hasattr(self, "selection_detail"):
            return
        self.selection_detail.setPlainText(detail or "Select a map item.")

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        _ = action, record_id
        if table in {
            "assets",
            "assignments",
            "checkins",
            "missions",
            "sitrep_followups",
            "sitreps",
            "waypoints",
            "zones",
        }:
            self.refresh()

    def _render_bundle(self, bundle: MapOverlayBundle, *, refit: bool = False) -> None:
        self._tile_generation = self._tile_renderer.begin_frame()
        self._overlay_details.clear()
        self._set_selection_detail("")
        self._draw_background()
        self._draw_tile_layer(bundle)
        for zone in bundle.zones:
            self._draw_zone(zone)
        for route in bundle.routes:
            self._draw_route(route)
        for waypoint in bundle.waypoints:
            self._draw_waypoint(waypoint)
        selected_mission_id = self._selected_mission_id()
        assets = [
            asset for asset in bundle.assets
            if self._visible_asset_ids is None
            or asset.id in self._visible_asset_ids
            or (
                selected_mission_id is not None
                and asset.mission_id == selected_mission_id
            )
        ]
        visible_asset_ids = {asset.id for asset in assets}
        for asset in assets:
            self._draw_asset(asset)
        for assignment in bundle.assignments:
            self._draw_assignment(assignment)
        for sitrep in bundle.sitreps:
            if (
                self._visible_asset_ids is not None
                and sitrep.asset_id is not None
                and sitrep.asset_id not in visible_asset_ids
            ):
                continue
            self._draw_sitrep(sitrep)
        self._scene.setSceneRect(0, 0, self._scene_width, self._scene_height)
        if refit:
            self.view.reset_zoom()

    def _draw_background(self) -> None:
        self._scene.addRect(
            0,
            0,
            self._scene_width,
            self._scene_height,
            QtGui.QPen(QtGui.QColor("#2f3437")),
            QtGui.QBrush(QtGui.QColor("#111619")),
        ).setZValue(-30)
        grid_pen = QtGui.QPen(QtGui.QColor(236, 240, 241, 34))
        for x in range(100, int(self._scene_width), 100):
            item = self._scene.addLine(x, 0, x, self._scene_height, grid_pen)
            item.setZValue(-5)
        for y in range(100, int(self._scene_height), 100):
            item = self._scene.addLine(0, y, self._scene_width, y, grid_pen)
            item.setZValue(-5)

    def _draw_tile_layer(self, bundle: MapOverlayBundle) -> None:
        layer = TILE_LAYERS_BY_KEY.get(self._active_tile_layer_key, TILE_LAYERS[0])
        plan = build_tile_plan(
            layer,
            bundle.bounds,
            scene_width=self._scene_width,
            scene_height=self._scene_height,
            scene_margin=self._scene_margin,
        )
        self.summary.setToolTip(f"{layer.label} tile zoom: {plan.zoom}")
        self._tile_renderer.request_tiles(plan.requests)
        self._draw_attribution(layer.attribution)

    def _draw_attribution(self, text: str) -> None:
        item = self._scene.addText(text)
        item.setDefaultTextColor(QtGui.QColor("#ecf0f1"))
        item.setZValue(30)
        bounds = item.boundingRect()
        item.setPos(
            self._scene_width - bounds.width() - 12,
            self._scene_height - bounds.height() - 8,
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
        item = AssetMarkerItem(asset)
        self._scene.addItem(item)
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

    def _draw_assignment(self, assignment: AssignmentOverlay) -> None:
        color = (
            QtGui.QColor("#e74c3c")
            if assignment.status == "needs_support"
            else QtGui.QColor("#8fbcbb")
        )
        size = 8
        polygon = QtGui.QPolygonF(
            [
                QtCore.QPointF(assignment.point.x, assignment.point.y - size),
                QtCore.QPointF(assignment.point.x + size, assignment.point.y),
                QtCore.QPointF(assignment.point.x, assignment.point.y + size),
                QtCore.QPointF(assignment.point.x - size, assignment.point.y),
            ]
        )
        item = self._scene.addPolygon(
            polygon,
            QtGui.QPen(QtGui.QColor("#ecf0f1"), 1),
            QtGui.QBrush(color),
        )
        self._register_item(
            item,
            key=f"assignment:{assignment.id}",
            label=f"Assignment #{assignment.id}",
            detail=(
                f"Assignment #{assignment.id}\n"
                f"Title: {assignment.title}\n"
                f"Type: {assignment.assignment_type}\n"
                f"Status: {assignment.status}\n"
                f"Priority: {assignment.priority}\n"
                f"Last check-in: {assignment.last_checkin_state or ''}\n"
                f"Lat/Lon: {assignment.point.lat:.6f}, {assignment.point.lon:.6f}"
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
        if sitrep.status in {"resolved", "closed"}:
            color = QtGui.QColor(color.red(), color.green(), color.blue(), 120)
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
                f"Status: {sitrep.status}\n"
                f"Asset: {sitrep.asset_id or ''}\n"
                f"Assignment: {sitrep.assignment_id or ''}\n"
                f"Mission: {sitrep.mission_id or ''}\n\n"
                f"Location: {sitrep.location_label or sitrep.location_source or 'map point'}\n"
                f"Lat/Lon: {sitrep.point.lat:.6f}, {sitrep.point.lon:.6f}\n\n"
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
            self._set_selection_detail("")
            return
        key = selected[-1].data(0)
        detail = self._overlay_details.get(str(key))
        if detail:
            self._set_selection_detail(detail)
            _log.debug("Map overlay selected: %s", detail.replace("\n", " | "))

    def _select_overlay_at_scene_point(self, x: float, y: float) -> None:
        point = QtCore.QPointF(x, y)
        items = [
            item for item in self._scene.items(point)
            if item.flags() & QtWidgets.QGraphicsItem.ItemIsSelectable
        ]
        self._scene.clearSelection()
        if items:
            items[0].setSelected(True)

    def _choose_visible_assets(self) -> None:
        if self._bundle is None:
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Visible Assets")
        dialog.setMinimumWidth(420)
        asset_list = QtWidgets.QListWidget()
        asset_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        for asset in self._bundle.assets:
            item = QtWidgets.QListWidgetItem(f"#{asset.id} {asset.label} [{asset.category}]")
            item.setData(QtCore.Qt.UserRole, asset.id)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            checked = self._visible_asset_ids is None or asset.id in self._visible_asset_ids
            item.setCheckState(QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
            asset_list.addItem(item)

        all_button = QtWidgets.QPushButton("All")
        none_button = QtWidgets.QPushButton("None")
        apply_button = QtWidgets.QPushButton("Apply")
        cancel_button = QtWidgets.QPushButton("Cancel")
        all_button.clicked.connect(
            lambda: [
                asset_list.item(row).setCheckState(QtCore.Qt.Checked)
                for row in range(asset_list.count())
            ]
        )
        none_button.clicked.connect(
            lambda: [
                asset_list.item(row).setCheckState(QtCore.Qt.Unchecked)
                for row in range(asset_list.count())
            ]
        )
        apply_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(all_button)
        buttons.addWidget(none_button)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(apply_button)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(asset_list)
        layout.addLayout(buttons)

        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        selected: set[int] = set()
        for row in range(asset_list.count()):
            item = asset_list.item(row)
            if item.checkState() == QtCore.Qt.Checked:
                selected.add(int(item.data(QtCore.Qt.UserRole)))
        all_ids = {asset.id for asset in self._bundle.assets}
        self._visible_asset_ids = None if selected == all_ids else selected
        self._render_bundle(self._bundle)
        self._refresh_side_panels()

    def _report_at_view_center(self) -> None:
        bounds = self._view_bounds or (self._bundle.bounds if self._bundle is not None else None)
        if bounds is None:
            self.summary.setText("Load the map before creating a map SITREP.")
            return
        lat, lon = lat_lon_for_scene_point(
            bounds,
            self._scene_width / 2.0,
            self._scene_height / 2.0,
            scene_width=self._scene_width,
            scene_height=self._scene_height,
            scene_margin=self._scene_margin,
        )
        body, accepted = QtWidgets.QInputDialog.getMultiLineText(
            self,
            "Report Here",
            f"SITREP at {lat:.6f}, {lon:.6f}",
            "",
        )
        if not accepted:
            return
        body = body.strip()
        if not body:
            self.summary.setText("SITREP body is required.")
            return
        try:
            self._core.command(
                "sitreps.create",
                {
                    "level": "ROUTINE",
                    "body": body,
                    "lat": lat,
                    "lon": lon,
                    "location_label": "Map report",
                    "location_precision": "exact",
                    "location_source": "map",
                    "mission_id": self._selected_mission_id(),
                },
            )
            self.refresh()
        except Exception as exc:
            _log.warning("Map SITREP create failed: %s", exc)
            self.summary.setText(f"SITREP not sent: {exc}")

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

    def _zoom_at_scene_point(self, x: float, y: float, wheel_delta: int) -> None:
        if (
            self._map_context is None
            or self._sitrep_entries is None
            or self._view_bounds is None
        ):
            return
        steps = max(-4, min(4, wheel_delta / 120.0))
        factor = 1.75**steps
        next_bounds = zoom_bounds_around_scene_point(
            self._view_bounds,
            x,
            y,
            factor,
            scene_width=self._scene_width,
            scene_height=self._scene_height,
            scene_margin=self._scene_margin,
        )
        if next_bounds == self._view_bounds:
            return
        self._view_bounds = next_bounds
        self._bundle = self._build_map_overlays(
            self._map_context,
            sitrep_entries=self._sitrep_entries,
            bounds=next_bounds,
        )
        self._render_bundle(self._bundle)

    def _pan_by_scene_delta(self, delta_x: float, delta_y: float) -> None:
        if (
            self._map_context is None
            or self._sitrep_entries is None
            or self._view_bounds is None
        ):
            return
        next_bounds = pan_bounds_by_scene_delta(
            self._view_bounds,
            delta_x,
            delta_y,
            scene_width=self._scene_width,
            scene_height=self._scene_height,
            scene_margin=self._scene_margin,
        )
        if next_bounds == self._view_bounds:
            return
        self._view_bounds = next_bounds
        self._bundle = self._build_map_overlays(
            self._map_context,
            sitrep_entries=self._sitrep_entries,
            bounds=next_bounds,
        )
        self._render_bundle(self._bundle)

    def _install_tile_cache(self) -> None:
        cache = QtNetwork.QNetworkDiskCache(self)
        try:
            cache_dir = self._core.paths.data_dir / "cache" / "map_tiles"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache.setCacheDirectory(str(cache_dir))
            self._network.setCache(cache)
        except Exception as exc:
            _log.debug("Map tile cache disabled: %s", exc)

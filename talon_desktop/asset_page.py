"""PySide6 asset list, detail, and command page."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6 import QtNetwork

from talon_core import TalonCoreSession
from talon_core.utils.logging import get_logger
from talon_desktop.assets import (
    ASSET_CATEGORY_OPTIONS,
    DesktopAssetItem,
    build_create_payload,
    build_update_payload,
    can_verify_asset,
    items_from_assets,
)
from talon_desktop.map_data import (
    DEFAULT_MAP_BOUNDS,
    SCENE_HEIGHT,
    SCENE_WIDTH,
    MapBounds,
    build_map_overlays,
)
from talon_desktop.map_tiles import (
    TILE_LAYERS_BY_KEY,
    TileRequest,
    build_tile_plan,
    lat_lon_for_scene_point,
    scene_point_for_lat_lon,
)
from talon_desktop.map_picker import format_coordinate, pick_point_on_map
from talon_desktop.theme import configure_data_table

_log = get_logger("desktop.assets")


class AssetMapPickView(QtWidgets.QGraphicsView):
    """Map view that converts clicks into latitude/longitude selections."""

    locationPicked = QtCore.Signal(float, float)

    def __init__(self, scene: QtWidgets.QGraphicsScene, bounds: MapBounds) -> None:
        super().__init__(scene)
        self._bounds = bounds
        self._zoom_steps = 0
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)

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
            self.locationPicked.emit(lat, lon)
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
        factor = 1.2 if direction > 0 else 1 / 1.2
        self.scale(factor, factor)
        self._zoom_steps = next_steps
        event.accept()


class AssetLocationMapDialog(QtWidgets.QDialog):
    """Pick an asset location by clicking the operational base map."""

    def __init__(
        self,
        *,
        core: TalonCoreSession | None,
        initial_lat: float | None,
        initial_lon: float | None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._core = core
        self._bounds = _picker_bounds(core, initial_lat, initial_lon)
        self._selected_location: tuple[float, float] | None = None
        self._marker_items: list[QtWidgets.QGraphicsItem] = []
        self._tile_generation = 0
        self._network = QtNetwork.QNetworkAccessManager(self)
        self._install_tile_cache()

        self.setWindowTitle("Asset Location")
        self.setMinimumSize(760, 560)

        self._scene = QtWidgets.QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, SCENE_WIDTH, SCENE_HEIGHT)
        self.view = AssetMapPickView(self._scene, self._bounds)
        self.view.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing
        )
        self.view.setMinimumSize(700, 430)
        self.view.locationPicked.connect(self._set_location)

        self.location_label = QtWidgets.QLabel("")
        self.use_button = QtWidgets.QPushButton("Use Location")
        self.use_button.setEnabled(False)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.use_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self.location_label)
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.use_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.view, stretch=1)
        layout.addLayout(button_row)

        self._render_map()
        if initial_lat is not None and initial_lon is not None:
            self._set_location(initial_lat, initial_lon)
        else:
            self.location_label.setText("Click the map to place the asset.")
        QtCore.QTimer.singleShot(0, self.view.reset_zoom)

    @property
    def selected_location(self) -> tuple[float, float] | None:
        return self._selected_location

    def _render_map(self) -> None:
        self._scene.clear()
        self._marker_items.clear()
        self._tile_generation += 1
        self._draw_background()
        layer = TILE_LAYERS_BY_KEY["osm"]
        plan = build_tile_plan(layer, self._bounds)
        generation = self._tile_generation
        for request in plan.requests:
            self._request_tile(request, generation)
        self._draw_attribution(layer.attribution)

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
            self._scene.addLine(x, 0, x, SCENE_HEIGHT, grid_pen).setZValue(-5)
        for y in range(100, int(SCENE_HEIGHT), 100):
            self._scene.addLine(0, y, SCENE_WIDTH, y, grid_pen).setZValue(-5)

    def _request_tile(self, tile: TileRequest, generation: int) -> None:
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(tile.url))
        request.setHeader(
            QtNetwork.QNetworkRequest.UserAgentHeader,
            "TALON Desktop/0.1 PySide6 asset map picker",
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
                _log.debug("Asset map tile request failed: %s", reply.errorString())
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

    def _set_location(self, lat: float, lon: float) -> None:
        self._selected_location = (lat, lon)
        self.location_label.setText(f"Selected: {lat:.6f}, {lon:.6f}")
        self.use_button.setEnabled(True)
        self._draw_marker(lat, lon)

    def _draw_marker(self, lat: float, lon: float) -> None:
        for item in self._marker_items:
            self._scene.removeItem(item)
        self._marker_items.clear()
        x, y = scene_point_for_lat_lon(self._bounds, lat, lon)
        pen = QtGui.QPen(QtGui.QColor("#f6fbfb"), 2)
        brush = QtGui.QBrush(QtGui.QColor("#e67e22"))
        ellipse = self._scene.addEllipse(x - 9, y - 9, 18, 18, pen, brush)
        vertical = self._scene.addLine(x, y - 18, x, y + 18, pen)
        horizontal = self._scene.addLine(x - 18, y, x + 18, y, pen)
        for item in (ellipse, vertical, horizontal):
            item.setZValue(40)
            self._marker_items.append(item)

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
            _log.debug("Asset map tile cache disabled: %s", exc)


class AssetDialog(QtWidgets.QDialog):
    """Create/edit asset dialog."""

    def __init__(
        self,
        *,
        asset: DesktopAssetItem | None = None,
        core: TalonCoreSession | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._asset = asset
        self._core = core
        self.setWindowTitle("Asset")
        self.setMinimumWidth(460)

        self.category_combo = QtWidgets.QComboBox()
        for category, label in ASSET_CATEGORY_OPTIONS:
            self.category_combo.addItem(label, category)
        self.label_field = QtWidgets.QLineEdit()
        self.description_field = QtWidgets.QTextEdit()
        self.description_field.setFixedHeight(96)
        self.lat_field = QtWidgets.QLineEdit()
        self.lon_field = QtWidgets.QLineEdit()
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        if asset is not None:
            index = self.category_combo.findData(asset.category)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
            self.category_combo.setDisabled(True)
            self.label_field.setText(asset.label)
            self.description_field.setPlainText(asset.description)
            self.lat_field.setText("" if asset.lat is None else str(asset.lat))
            self.lon_field.setText("" if asset.lon is None else str(asset.lon))

        form = QtWidgets.QFormLayout()
        form.addRow("Category", self.category_combo)
        form.addRow("Label", self.label_field)
        form.addRow("Description", self.description_field)
        form.addRow("Latitude", self.lat_field)
        form.addRow("Longitude", self.lon_field)

        self.pick_location_button = QtWidgets.QPushButton("Pick on Map")
        self.pick_location_button.clicked.connect(self._pick_location)
        form.addRow("Map", self.pick_location_button)

        self.save_button = QtWidgets.QPushButton("Save")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.save_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addLayout(button_row)

    def create_payload(self) -> dict[str, object]:
        return build_create_payload(
            category=str(self.category_combo.currentData()),
            label=self.label_field.text(),
            description=self.description_field.toPlainText(),
            lat_text=self.lat_field.text(),
            lon_text=self.lon_field.text(),
        )

    def update_payload(self) -> dict[str, object]:
        if self._asset is None:
            raise ValueError("Asset dialog has no asset to update.")
        return build_update_payload(
            asset_id=self._asset.id,
            label=self.label_field.text(),
            description=self.description_field.toPlainText(),
            lat_text=self.lat_field.text(),
            lon_text=self.lon_field.text(),
        )

    def accept(self) -> None:
        try:
            if self._asset is None:
                self.create_payload()
            else:
                self.update_payload()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        super().accept()

    def _pick_location(self) -> None:
        try:
            initial_lat = _optional_coordinate(
                self.lat_field.text(),
                label="Latitude",
                minimum=-90.0,
                maximum=90.0,
            )
            initial_lon = _optional_coordinate(
                self.lon_field.text(),
                label="Longitude",
                minimum=-180.0,
                maximum=180.0,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        if (initial_lat is None) != (initial_lon is None):
            self.status_label.setText(
                "Both latitude and longitude are required together."
            )
            return

        selected = pick_point_on_map(
            core=self._core,
            title="Asset Location",
            initial_lat=initial_lat,
            initial_lon=initial_lon,
            parent=self,
        )
        if selected is None:
            return
        lat, lon = selected
        self.lat_field.setText(format_coordinate(lat, lon).split(", ")[0])
        self.lon_field.setText(format_coordinate(lat, lon).split(", ")[1])
        self.status_label.clear()


def _picker_bounds(
    core: TalonCoreSession | None,
    initial_lat: float | None,
    initial_lon: float | None,
) -> MapBounds:
    if initial_lat is not None and initial_lon is not None:
        return _bounds_around(initial_lat, initial_lon)
    if core is None:
        return DEFAULT_MAP_BOUNDS
    try:
        context = core.read_model("map.context")
        return build_map_overlays(context).bounds
    except Exception as exc:
        _log.debug("Could not load map context for asset picker: %s", exc)
        return DEFAULT_MAP_BOUNDS


def _bounds_around(lat: float, lon: float) -> MapBounds:
    lat_span = 0.08
    lon_span = 0.08
    return MapBounds(
        min_lat=max(-85.0, lat - lat_span),
        max_lat=min(85.0, lat + lat_span),
        min_lon=max(-180.0, lon - lon_span),
        max_lon=min(180.0, lon + lon_span),
    )


def _optional_coordinate(
    value: str,
    *,
    label: str,
    minimum: float,
    maximum: float,
) -> float | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return parsed


class AssetPage(QtWidgets.QWidget):
    """Desktop asset table, detail panel, and core command wiring."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._items: list[DesktopAssetItem] = []

        self.heading = QtWidgets.QLabel("Assets")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)

        self.category_filter = QtWidgets.QComboBox()
        self.category_filter.addItem("All", None)
        for category, label in ASSET_CATEGORY_OPTIONS:
            self.category_filter.addItem(label, category)
        self.category_filter.currentIndexChanged.connect(lambda _index: self.refresh())

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.new_button = QtWidgets.QPushButton("New")
        self.new_button.clicked.connect(self._create_asset)
        self.edit_button = QtWidgets.QPushButton("Edit")
        self.edit_button.clicked.connect(self._edit_selected)
        self.verify_button = QtWidgets.QPushButton("Verify")
        self.verify_button.clicked.connect(self._toggle_verify_selected)
        self.delete_button = QtWidgets.QPushButton("Request Delete")
        self.delete_button.clicked.connect(self._delete_selected)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.category_filter)
        top_row.addWidget(self.refresh_button)
        top_row.addWidget(self.new_button)
        top_row.addWidget(self.edit_button)
        top_row.addWidget(self.verify_button)
        top_row.addWidget(self.delete_button)

        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Label", "Category", "Verified", "Delete", "Mission", "Location"]
        )
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        configure_data_table(self.table)
        self.table.itemSelectionChanged.connect(self._selection_changed)

        self.detail = QtWidgets.QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumWidth(320)

        body = QtWidgets.QSplitter()
        body.addWidget(self.table)
        body.addWidget(self.detail)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self.summary)
        layout.addWidget(body, stretch=1)

    def refresh(self) -> None:
        try:
            filters: dict[str, object] = {}
            category = self.category_filter.currentData()
            if category:
                filters["category"] = category
            self._items = items_from_assets(self._core.read_model("assets.list", filters))
        except Exception as exc:
            _log.warning("Could not refresh assets: %s", exc)
            self.summary.setText(f"Unable to load assets: {exc}")
            return

        self.table.setRowCount(0)
        for item in self._items:
            self._add_row(item)
        total = len(self._items)
        verified = sum(1 for item in self._items if item.verified)
        requested = sum(1 for item in self._items if item.deletion_requested)
        self.summary.setText(
            f"{total} assets, {verified} verified, {requested} deletion request(s)."
        )
        if total:
            self.table.selectRow(0)
        else:
            self.detail.clear()
        self._selection_changed()

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        _ = action, record_id
        if table == "assets":
            self.refresh()

    def _add_row(self, item: DesktopAssetItem) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            str(item.id),
            item.label,
            item.category_label,
            "Yes" if item.verified else "No",
            "Requested" if item.deletion_requested else "",
            "" if item.mission_id is None else str(item.mission_id),
            item.coordinate_text,
        ]
        for column, value in enumerate(values):
            cell = QtWidgets.QTableWidgetItem(value)
            if column == 0:
                cell.setData(QtCore.Qt.UserRole, item.id)
            self.table.setItem(row, column, cell)

    def _selected_item(self) -> DesktopAssetItem | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def _selection_changed(self) -> None:
        item = self._selected_item()
        has_item = item is not None
        self.edit_button.setEnabled(has_item)
        self.verify_button.setEnabled(has_item and self._can_verify(item))
        self.delete_button.setEnabled(has_item)
        if item is None:
            self.verify_button.setText("Verify")
            self.delete_button.setText("Request Delete")
            return

        self.verify_button.setText("Unverify" if item.verified else "Verify")
        self.delete_button.setText(
            "Delete" if self._core.mode == "server" else "Request Delete"
        )
        self.detail.setPlainText(self._detail_text(item))

    def _create_asset(self) -> None:
        dialog = AssetDialog(core=self._core, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            self._core.command("assets.create", dialog.create_payload())
            self.refresh()
        except Exception as exc:
            _log.warning("Asset create failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Asset", str(exc))

    def _edit_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        dialog = AssetDialog(asset=item, core=self._core, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            self._core.command("assets.update", dialog.update_payload())
            self.refresh()
        except Exception as exc:
            _log.warning("Asset update failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Asset", str(exc))

    def _toggle_verify_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        if not self._can_verify(item):
            QtWidgets.QMessageBox.warning(
                self,
                "Asset",
                "Current operator cannot verify this asset.",
            )
            return
        confirmer_id = self._core.operator_id if not item.verified else None
        if self._core.mode == "server" and item.verified:
            confirmer_id = None
        elif self._core.mode == "server":
            confirmer_id = self._core.operator_id
        try:
            self._core.command(
                "assets.verify",
                asset_id=item.id,
                verified=not item.verified,
                confirmer_id=confirmer_id,
            )
            self.refresh()
        except Exception as exc:
            _log.warning("Asset verification failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Asset", str(exc))

    def _delete_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        try:
            if self._core.mode == "server":
                if (
                    QtWidgets.QMessageBox.question(
                        self,
                        "Asset",
                        "Delete this asset?",
                    )
                    != QtWidgets.QMessageBox.Yes
                ):
                    return
                self._core.command("assets.hard_delete", asset_id=item.id)
            else:
                self._core.command("assets.request_delete", asset_id=item.id)
            self.refresh()
        except Exception as exc:
            _log.warning("Asset delete/request failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Asset", str(exc))

    def _can_verify(self, item: DesktopAssetItem | None) -> bool:
        if item is None:
            return False
        return can_verify_asset(
            mode=self._core.mode,
            operator_id=self._core.operator_id,
            asset_created_by=item.created_by,
        )

    def _detail_text(self, item: DesktopAssetItem) -> str:
        lines = [
            f"#{item.id} {item.label}",
            f"Category: {item.category_label}",
            f"Verified: {'Yes' if item.verified else 'No'}",
            f"Created by: {item.created_by}",
            f"Confirmed by: {item.confirmed_by or ''}",
            f"Mission: {item.mission_id or ''}",
            f"Location: {item.coordinate_text}",
            f"Deletion requested: {'Yes' if item.deletion_requested else 'No'}",
            "",
            item.description,
        ]
        return "\n".join(lines).strip()

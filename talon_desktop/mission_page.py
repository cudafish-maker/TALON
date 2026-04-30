"""PySide6 mission list, detail, create, and lifecycle page."""
from __future__ import annotations

import math
import typing

from PySide6 import QtCore, QtGui, QtWidgets

from talon_core import TalonCoreSession
from talon_core.constants import SITREP_LEVELS
from talon_core.utils.logging import get_logger
from talon_desktop.missions import (
    MISSION_STATUS_OPTIONS,
    DesktopMissionItem,
    build_create_payload,
    format_coordinate_lines,
    items_from_missions,
    line_items,
    parse_coordinate_lines,
    server_actions_for_status,
)
from talon_desktop.map_picker import (
    DraftMapOverlay,
    MapCoordinateDialog,
    format_coordinate,
)
from talon_desktop.theme import configure_data_table

_log = get_logger("desktop.missions")


class MissionDraftPreview(QtWidgets.QGraphicsView):
    """Side-by-side preview for mission geometry while the create form is edited."""

    def __init__(self) -> None:
        self._scene = QtWidgets.QGraphicsScene()
        super().__init__(self._scene)
        self.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing
        )
        self.setMinimumWidth(420)
        self.setMinimumHeight(520)
        self.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.SmartViewportUpdate)
        self._scene.setSceneRect(0, 0, 420, 520)
        self.update_from("", "", "", "", {})

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        size = self.viewport().size()
        self._scene.setSceneRect(0, 0, size.width(), size.height())

    def update_from(
        self,
        ao_text: str,
        route_text: str,
        staging_area: str,
        demob_point: str,
        key_locations: dict[str, str],
    ) -> None:
        width = max(1, self.viewport().width() or 420)
        height = max(1, self.viewport().height() or 520)
        self._scene.clear()
        self._scene.setSceneRect(0, 0, width, height)
        self._draw_background(width, height)

        ao_points = self._parse_points(ao_text, "AO polygon", 3)
        route_points = self._parse_points(route_text, "Route", 1)
        named_points: list[tuple[str, str, tuple[float, float]]] = []
        for label, text, icon in (
            ("Staging Area", staging_area, "staging_area"),
            ("Demob Point", demob_point, "demob_point"),
        ):
            point = self._parse_single_point(text, label)
            if point is not None:
                named_points.append((label, icon, point))
        for key, label in (
            ("incident_command_post", "Incident Command Post"),
            ("staging_area", "Staging Area"),
            ("medical", "Medical"),
            ("evacuation", "Evacuation"),
            ("supply", "Supply"),
        ):
            point = self._parse_single_point(key_locations.get(key, ""), label)
            if point is not None:
                named_points.append((label, key, point))

        all_points = [*ao_points, *route_points, *(point for _label, _icon, point in named_points)]
        bounds = self._bounds_for_points(all_points)
        if len(ao_points) >= 3:
            polygon = QtGui.QPolygonF(
                [QtCore.QPointF(*self._project(point, bounds, width, height)) for point in ao_points]
            )
            self._scene.addPolygon(
                polygon,
                QtGui.QPen(QtGui.QColor("#e74c3c"), 2),
                QtGui.QBrush(QtGui.QColor(231, 76, 60, 76)),
            ).setZValue(5)
        if len(route_points) >= 2:
            path = QtGui.QPainterPath()
            first = self._project(route_points[0], bounds, width, height)
            path.moveTo(*first)
            for point in route_points[1:]:
                path.lineTo(*self._project(point, bounds, width, height))
            self._scene.addPath(path, QtGui.QPen(QtGui.QColor("#3498db"), 3)).setZValue(8)
        for index, point in enumerate(route_points, start=1):
            x, y = self._project(point, bounds, width, height)
            self._scene.addEllipse(
                x - 5,
                y - 5,
                10,
                10,
                QtGui.QPen(QtGui.QColor("#ecf0f1"), 1),
                QtGui.QBrush(QtGui.QColor("#3498db")),
            ).setZValue(10)
            self._draw_label(str(index), x + 8, y - 22, QtGui.QColor("#d7ecff"))
        for label, icon, point in named_points:
            x, y = self._project(point, bounds, width, height)
            self._draw_location_icon(icon, x, y)
            self._draw_label(label, x + 12, y - 22, QtGui.QColor("#ecf0f1"))

    @staticmethod
    def _parse_points(text: str, label: str, minimum_points: int) -> list[tuple[float, float]]:
        if not text.strip():
            return []
        try:
            return parse_coordinate_lines(
                text,
                label=label,
                minimum_points=minimum_points,
                empty_ok=False,
            )
        except ValueError:
            return []

    def _parse_single_point(self, text: str, label: str) -> tuple[float, float] | None:
        points = self._parse_points(text, label, 1)
        return points[0] if points else None

    @staticmethod
    def _bounds_for_points(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
        if not points:
            return 39.95, 40.05, -75.05, -74.95
        lats = [lat for lat, _lon in points]
        lons = [lon for _lat, lon in points]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        if math.isclose(min_lat, max_lat):
            min_lat -= 0.01
            max_lat += 0.01
        if math.isclose(min_lon, max_lon):
            min_lon -= 0.01
            max_lon += 0.01
        lat_pad = (max_lat - min_lat) * 0.12
        lon_pad = (max_lon - min_lon) * 0.12
        return min_lat - lat_pad, max_lat + lat_pad, min_lon - lon_pad, max_lon + lon_pad

    @staticmethod
    def _project(
        point: tuple[float, float],
        bounds: tuple[float, float, float, float],
        width: float,
        height: float,
    ) -> tuple[float, float]:
        min_lat, max_lat, min_lon, max_lon = bounds
        margin = 34.0
        usable_w = max(1.0, width - margin * 2)
        usable_h = max(1.0, height - margin * 2)
        lat, lon = point
        x = margin + ((lon - min_lon) / max(0.000001, max_lon - min_lon)) * usable_w
        y = margin + ((max_lat - lat) / max(0.000001, max_lat - min_lat)) * usable_h
        return x, y

    def _draw_background(self, width: int, height: int) -> None:
        self._scene.addRect(
            0,
            0,
            width,
            height,
            QtGui.QPen(QtGui.QColor("#2f3437")),
            QtGui.QBrush(QtGui.QColor("#101619")),
        ).setZValue(-20)
        pen = QtGui.QPen(QtGui.QColor(236, 240, 241, 30))
        for x in range(80, int(width), 80):
            self._scene.addLine(x, 0, x, height, pen).setZValue(-10)
        for y in range(80, int(height), 80):
            self._scene.addLine(0, y, width, y, pen).setZValue(-10)

    def _draw_location_icon(self, icon: str, x: float, y: float) -> None:
        pen = QtGui.QPen(QtGui.QColor("#ecf0f1"), 2)
        brush = QtGui.QBrush(QtGui.QColor("#1f2930"))
        if icon in {"staging_area", "demob_point"}:
            polygon = QtGui.QPolygonF(
                [
                    QtCore.QPointF(x, y - 10),
                    QtCore.QPointF(x + 10, y),
                    QtCore.QPointF(x, y + 10),
                    QtCore.QPointF(x - 10, y),
                ]
            )
            self._scene.addPolygon(polygon, pen, QtGui.QBrush(QtGui.QColor("#3498db"))).setZValue(12)
            return
        if icon == "medical":
            self._scene.addRect(x - 10, y - 10, 20, 20, pen, QtGui.QBrush(QtGui.QColor("#e74c3c"))).setZValue(12)
            self._scene.addLine(x - 6, y, x + 6, y, QtGui.QPen(QtGui.QColor("#ffffff"), 2)).setZValue(13)
            self._scene.addLine(x, y - 6, x, y + 6, QtGui.QPen(QtGui.QColor("#ffffff"), 2)).setZValue(13)
            return
        if icon == "evacuation":
            polygon = QtGui.QPolygonF(
                [
                    QtCore.QPointF(x, y - 12),
                    QtCore.QPointF(x + 12, y + 10),
                    QtCore.QPointF(x - 12, y + 10),
                ]
            )
            self._scene.addPolygon(polygon, pen, QtGui.QBrush(QtGui.QColor("#f1c40f"))).setZValue(12)
            return
        if icon == "supply":
            polygon = QtGui.QPolygonF(
                [
                    QtCore.QPointF(x - 9, y - 8),
                    QtCore.QPointF(x + 5, y - 8),
                    QtCore.QPointF(x + 11, y),
                    QtCore.QPointF(x + 5, y + 8),
                    QtCore.QPointF(x - 9, y + 8),
                    QtCore.QPointF(x - 13, y),
                ]
            )
            self._scene.addPolygon(polygon, pen, QtGui.QBrush(QtGui.QColor("#8fbcbb"))).setZValue(12)
            return
        self._scene.addRect(x - 10, y - 10, 20, 20, pen, brush).setZValue(12)
        if icon == "incident_command_post":
            flag_pen = QtGui.QPen(QtGui.QColor("#ecf0f1"), 2)
            self._scene.addLine(x - 4, y + 6, x - 4, y - 8, flag_pen).setZValue(13)
            self._scene.addPolygon(
                QtGui.QPolygonF(
                    [
                        QtCore.QPointF(x - 4, y - 8),
                        QtCore.QPointF(x + 7, y - 5),
                        QtCore.QPointF(x - 4, y - 2),
                    ]
                ),
                flag_pen,
                QtGui.QBrush(QtGui.QColor("#e74c3c")),
            ).setZValue(13)

    def _draw_label(self, text: str, x: float, y: float, color: QtGui.QColor) -> None:
        label = self._scene.addText(text)
        label.setDefaultTextColor(color)
        rect = label.boundingRect()
        bg = self._scene.addRect(
            x - 4,
            y - 2,
            rect.width() + 8,
            rect.height() + 4,
            QtGui.QPen(QtCore.Qt.NoPen),
            QtGui.QBrush(QtGui.QColor(10, 15, 17, 215)),
        )
        bg.setZValue(14)
        label.setPos(x, y)
        label.setZValue(15)


class MissionCreateDialog(QtWidgets.QDialog):
    """Extended mission create workflow with assets, timing, map geometry, and support fields."""

    def __init__(
        self,
        core: TalonCoreSession,
        *,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._core = core
        self._updating_map_field = False
        self._map_target: (
            tuple[
                typing.Literal["path", "point"],
                QtWidgets.QPlainTextEdit | QtWidgets.QLineEdit,
                str,
            ]
            | None
        ) = None
        self._key_location_fields: dict[str, QtWidgets.QLineEdit] = {}
        self._constraint_checks: dict[str, QtWidgets.QCheckBox] = {}
        self.setWindowTitle("Mission")
        self.setMinimumSize(1160, 760)

        self.title_field = QtWidgets.QLineEdit()
        self.description_field = QtWidgets.QTextEdit()
        self.description_field.setFixedHeight(96)
        self.type_combo = QtWidgets.QComboBox()
        for mission_type in (
            "Search and Rescue",
            "Medical Support",
            "Logistics",
            "Damage Assessment",
            "Security",
            "Communications",
            "Evacuation",
            "Supply",
            "Animal Recovery",
            "Custom",
        ):
            self.type_combo.addItem(mission_type, mission_type)
        self.priority_combo = QtWidgets.QComboBox()
        for level in SITREP_LEVELS:
            self.priority_combo.addItem(level, level)
        self.lead_combo = QtWidgets.QComboBox()
        self.lead_combo.setEditable(True)
        self._load_leads()
        self.organization_field = QtWidgets.QLineEdit()

        self.activation_enabled = QtWidgets.QCheckBox("Set activation time")
        self.activation_time = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime())
        self.activation_time.setCalendarPopup(True)
        self.activation_time.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.activation_time.setEnabled(False)
        self.activation_enabled.toggled.connect(self.activation_time.setEnabled)
        self.operation_window_enabled = QtWidgets.QCheckBox("Set operation window")
        now = QtCore.QDateTime.currentDateTime()
        self.operation_start_time = QtWidgets.QDateTimeEdit(now)
        self.operation_end_time = QtWidgets.QDateTimeEdit(now.addSecs(8 * 3600))
        for editor in (self.operation_start_time, self.operation_end_time):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("yyyy-MM-dd HH:mm")
            editor.setEnabled(False)
        self.operation_window_enabled.toggled.connect(self.operation_start_time.setEnabled)
        self.operation_window_enabled.toggled.connect(self.operation_end_time.setEnabled)
        self.max_duration_field = QtWidgets.QLineEdit()
        self.staging_area_field = QtWidgets.QLineEdit()
        self.demob_point_field = QtWidgets.QLineEdit()
        self.standdown_field = QtWidgets.QTextEdit()
        self.standdown_field.setFixedHeight(76)
        self.phase_table = self._table(["Name", "Objective", "Duration"])

        self.assets_list = QtWidgets.QListWidget()
        self.assets_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.assets_list.setMinimumHeight(160)
        self._load_assets()

        self.ao_field = QtWidgets.QPlainTextEdit()
        self.ao_field.setPlaceholderText("lat, lon\nlat, lon\nlat, lon")
        self.ao_field.setFixedHeight(112)
        self.route_field = QtWidgets.QPlainTextEdit()
        self.route_field.setPlaceholderText("lat, lon\nlat, lon")
        self.route_field.setFixedHeight(112)
        self.objective_table = self._table(["Label", "Criteria"])

        self.support_medical = self._text_edit()
        self.support_logistics = self._text_edit()
        self.support_comms = self._text_edit()
        self.support_equipment = self._text_edit()
        self.custom_resource_table = self._table(["Label", "Details"])
        self.custom_constraints = QtWidgets.QPlainTextEdit()
        self.custom_constraints.setFixedHeight(78)
        self.custom_constraints.setPlaceholderText("One custom constraint per line")

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._scroll_page(self._overview_tab()), "Overview")
        tabs.addTab(self._scroll_page(self._timing_tab()), "Timing")
        tabs.addTab(self._scroll_page(self._assets_tab()), "Assets")
        tabs.addTab(self._scroll_page(self._area_tab()), "Area / Route")
        tabs.addTab(self._scroll_page(self._support_tab()), "Support")
        self.map_picker = MapCoordinateDialog(
            core=self._core,
            title="Mission Map",
            mode="polygon",
            parent=self,
        )
        self.map_picker.setWindowFlags(QtCore.Qt.Widget)
        self.map_picker.setMinimumSize(420, 520)
        self.map_picker.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        self.map_picker.cancel_button.setVisible(False)
        self.map_picker.use_button.clicked.disconnect()
        self.map_picker.use_button.clicked.connect(self._apply_map_selection)
        self.map_picker.selectionChanged.connect(self._sync_map_apply_state)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        self._wire_map_updates()
        self._activate_path_picker(
            self.ao_field,
            "AO Polygon",
            "polygon",
            3,
        )

        self.save_button = QtWidgets.QPushButton("Create")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.save_button)

        content = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        content.addWidget(tabs)
        content.addWidget(self.map_picker)
        content.setStretchFactor(0, 3)
        content.setStretchFactor(1, 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(content, stretch=1)
        layout.addWidget(self.status_label)
        layout.addLayout(button_row)
        QtCore.QTimer.singleShot(0, self._refresh_embedded_map_drafts)

    def payload(self) -> dict[str, object]:
        return build_create_payload(
            title=self.title_field.text(),
            description=self.description_field.toPlainText(),
            asset_ids=self.selected_asset_ids(),
            mission_type=self.type_combo.currentText(),
            priority=str(self.priority_combo.currentData()),
            lead_coordinator=self.lead_combo.currentText(),
            organization=self.organization_field.text(),
            ao_text=self.ao_field.toPlainText(),
            route_text=self.route_field.toPlainText(),
            activation_time=self._activation_text(),
            operation_window=self._operation_window_text(),
            max_duration=self.max_duration_field.text(),
            staging_area=self.staging_area_field.text(),
            demob_point=self.demob_point_field.text(),
            standdown_criteria=self.standdown_field.toPlainText(),
            phases=self._table_dicts(self.phase_table, ("name", "objective", "duration")),
            constraints=self._constraints(),
            support_medical=self.support_medical.toPlainText(),
            support_logistics=self.support_logistics.toPlainText(),
            support_comms=self.support_comms.toPlainText(),
            support_equipment=self.support_equipment.toPlainText(),
            custom_resources=self._table_dicts(
                self.custom_resource_table,
                ("label", "details"),
            ),
            objectives=self._table_dicts(self.objective_table, ("label", "criteria")),
            key_locations={
                key: field.text()
                for key, field in self._key_location_fields.items()
            },
        )

    def selected_asset_ids(self) -> list[int]:
        selected = []
        for index in range(self.assets_list.count()):
            item = self.assets_list.item(index)
            if item.checkState() == QtCore.Qt.Checked:
                selected.append(int(item.data(QtCore.Qt.UserRole)))
        return selected

    def accept(self) -> None:
        try:
            self.payload()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        super().accept()

    def _load_assets(self) -> None:
        try:
            assets = self._core.read_model("assets.list", {"available_only": True})
        except Exception as exc:
            _log.warning("Could not load assets for mission dialog: %s", exc)
            assets = []
        for asset in assets:
            item = QtWidgets.QListWidgetItem(
                f"#{getattr(asset, 'id')} {getattr(asset, 'label')}"
            )
            item.setData(QtCore.Qt.UserRole, int(getattr(asset, "id")))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked)
            self.assets_list.addItem(item)

    def _load_leads(self) -> None:
        self.lead_combo.addItem("", "")
        try:
            operators = self._core.read_model("operators.list")
        except Exception as exc:
            _log.warning("Could not load operators for mission lead dropdown: %s", exc)
            operators = []
        busy_operator_ids: set[int] = set()
        try:
            board = self._core.read_model("assignments.board")
            for assignment in board.get("assignments", []):
                if getattr(assignment, "mission_id", None) is None:
                    continue
                if getattr(assignment, "status", "") in {"completed", "aborted"}:
                    continue
                for operator_id in getattr(assignment, "assigned_operator_ids", []) or []:
                    busy_operator_ids.add(int(operator_id))
        except Exception as exc:
            _log.debug("Could not filter busy mission operators: %s", exc)
        for operator in operators:
            try:
                operator_id = int(getattr(operator, "id"))
            except (TypeError, ValueError):
                continue
            if operator_id in busy_operator_ids:
                continue
            callsign = str(getattr(operator, "callsign", "") or "").strip()
            if callsign:
                self.lead_combo.addItem(callsign, callsign)

    def _overview_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        form.addRow("Title", self.title_field)
        form.addRow("Description", self.description_field)
        form.addRow("Type", self.type_combo)
        form.addRow("Priority", self.priority_combo)
        form.addRow("Lead", self.lead_combo)
        form.addRow("Organization", self.organization_field)
        return page

    def _timing_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        activation_row = QtWidgets.QHBoxLayout()
        activation_row.addWidget(self.activation_enabled)
        activation_row.addWidget(self.activation_time, stretch=1)
        form.addRow("Activation", activation_row)
        form.addRow("Operation Window", self._operation_window_row())
        form.addRow("Max Duration", self.max_duration_field)
        form.addRow("Staging Area", self._point_row(self.staging_area_field, "Staging Area"))
        form.addRow("Demob Point", self._point_row(self.demob_point_field, "Demob Point"))
        form.addRow("Stand-down Criteria", self.standdown_field)
        form.addRow("Phases", self._table_with_buttons(self.phase_table))
        return page

    def _assets_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(QtWidgets.QLabel("Requested Assets"))
        layout.addWidget(self.assets_list)
        return page

    def _area_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        form.addRow("AO Polygon", self._geometry_row(self.ao_field, self._draw_ao))
        form.addRow("Route / Waypoints", self._geometry_row(self.route_field, self._draw_route))
        form.addRow("Objectives", self._table_with_buttons(self.objective_table))

        key_group = QtWidgets.QGroupBox("Key Locations")
        key_form = QtWidgets.QFormLayout(key_group)
        for key, label in (
            ("incident_command_post", "Incident Command Post"),
            ("staging_area", "Staging Area"),
            ("medical", "Medical"),
            ("evacuation", "Evacuation"),
            ("supply", "Supply"),
        ):
            field = QtWidgets.QLineEdit()
            self._key_location_fields[key] = field
            key_form.addRow(label, self._point_row(field, label))
        form.addRow(key_group)
        return page

    def _support_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        constraints_group = QtWidgets.QGroupBox("Constraints")
        constraints_layout = QtWidgets.QGridLayout(constraints_group)
        for index, label in enumerate(
            (
                "Daylight only",
                "Two-person teams",
                "Medical standby",
                "Comms check required",
                "Avoid restricted zones",
                "Server approval required",
            )
        ):
            check = QtWidgets.QCheckBox(label)
            self._constraint_checks[label] = check
            constraints_layout.addWidget(check, index // 2, index % 2)
        form.addRow(constraints_group)
        form.addRow("Custom Constraints", self.custom_constraints)
        form.addRow("Medical", self.support_medical)
        form.addRow("Logistics", self.support_logistics)
        form.addRow("Comms", self.support_comms)
        form.addRow("Equipment", self.support_equipment)
        form.addRow("Custom Resources", self._table_with_buttons(self.custom_resource_table))
        return page

    def _geometry_row(
        self,
        editor: QtWidgets.QPlainTextEdit,
        callback: typing.Callable[[], None],
    ) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QtWidgets.QPushButton("Draw on Map")
        button.clicked.connect(callback)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button)
        layout.addWidget(editor)
        layout.addLayout(row)
        return container

    def _point_row(self, field: QtWidgets.QLineEdit, title: str) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QtWidgets.QPushButton("Pick on Map")
        button.clicked.connect(lambda _checked=False, f=field, t=title: self._pick_point(f, t))
        layout.addWidget(field, stretch=1)
        layout.addWidget(button)
        return container

    def _operation_window_row(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.addWidget(self.operation_window_enabled, 0, 0, 1, 2)
        layout.addWidget(QtWidgets.QLabel("Start"), 1, 0)
        layout.addWidget(self.operation_start_time, 1, 1)
        layout.addWidget(QtWidgets.QLabel("End"), 2, 0)
        layout.addWidget(self.operation_end_time, 2, 1)
        return container

    def _draw_ao(self) -> None:
        self._activate_path_picker(
            self.ao_field,
            "AO Polygon",
            "polygon",
            3,
        )

    def _draw_route(self) -> None:
        self._activate_path_picker(
            self.route_field,
            "Route / Waypoints",
            "route",
            1,
        )

    def _activate_path_picker(
        self,
        editor: QtWidgets.QPlainTextEdit,
        title: str,
        mode: typing.Literal["polygon", "route"],
        minimum_points: int,
    ) -> None:
        points = self._parse_existing_points(editor, title, minimum_points)
        if points is None:
            return
        self._map_target = ("path", editor, title)
        self.map_picker.configure_selection(
            title=title,
            mode=mode,
            initial_points=points,
            draft_overlays=self._draft_overlays(exclude_widget=editor),
            minimum_points=minimum_points,
        )
        self.map_picker.use_button.setText("Use Selected")
        self.status_label.setText(f"Map target: {title}.")
        self._sync_map_apply_state()

    def _pick_point(self, field: QtWidgets.QLineEdit, title: str) -> None:
        initial_lat = None
        initial_lon = None
        text = field.text().strip()
        if text:
            try:
                points = parse_coordinate_lines(
                    text,
                    label=title,
                    minimum_points=1,
                    empty_ok=False,
                )
                initial_lat, initial_lon = points[0]
            except ValueError as exc:
                self.status_label.setText(str(exc))
                return
        initial = []
        if initial_lat is not None and initial_lon is not None:
            initial.append((initial_lat, initial_lon))
        self._map_target = ("point", field, title)
        self.map_picker.configure_selection(
            title=title,
            mode="point",
            initial_points=initial,
            draft_overlays=self._draft_overlays(exclude_widget=field),
            minimum_points=1,
        )
        self.map_picker.use_button.setText("Use Selected")
        self.status_label.setText(f"Map target: {title}.")
        self._sync_map_apply_state()

    def _apply_map_selection(self) -> None:
        if self._map_target is None:
            self.status_label.setText("Choose a mission field before using a map point.")
            self._sync_map_apply_state()
            return
        error = self.map_picker.selection_error()
        if error:
            self.status_label.setText(error)
            return
        kind, widget, title = self._map_target
        selected = self.map_picker.selected_points
        self._updating_map_field = True
        try:
            if kind == "path":
                typing.cast(QtWidgets.QPlainTextEdit, widget).setPlainText(
                    format_coordinate_lines(selected)
                )
            else:
                typing.cast(QtWidgets.QLineEdit, widget).setText(
                    format_coordinate(*selected[0])
                )
        finally:
            self._updating_map_field = False
        self.status_label.setText(f"Applied {title} from map.")
        self._refresh_embedded_map_drafts()

    def _sync_map_apply_state(self) -> None:
        self.map_picker.use_button.setEnabled(
            self._map_target is not None and not self.map_picker.selection_error()
        )

    def _wire_map_updates(self) -> None:
        self.ao_field.textChanged.connect(self._refresh_embedded_map_drafts)
        self.route_field.textChanged.connect(self._refresh_embedded_map_drafts)
        self.staging_area_field.textChanged.connect(self._refresh_embedded_map_drafts)
        self.demob_point_field.textChanged.connect(self._refresh_embedded_map_drafts)
        for field in self._key_location_fields.values():
            field.textChanged.connect(self._refresh_embedded_map_drafts)

    def _refresh_embedded_map_drafts(self) -> None:
        target_widget = self._map_target[1] if self._map_target is not None else None
        if (
            target_widget is not None
            and self.sender() is target_widget
            and not self._updating_map_field
        ):
            self._reload_active_map_selection_from_field()
            return
        self.map_picker.set_draft_overlays(
            self._draft_overlays(exclude_widget=target_widget),
            refit=False,
        )

    def _reload_active_map_selection_from_field(self) -> None:
        if self._map_target is None:
            return
        kind, widget, title = self._map_target
        if kind == "path":
            editor = typing.cast(QtWidgets.QPlainTextEdit, widget)
            if editor is self.ao_field:
                mode: typing.Literal["polygon", "route"] = "polygon"
                minimum_points = 3
            else:
                mode = "route"
                minimum_points = 1
            points = self._parse_existing_points(editor, title, minimum_points)
            if points is None:
                return
            self.map_picker.configure_selection(
                title=title,
                mode=mode,
                initial_points=points,
                draft_overlays=self._draft_overlays(exclude_widget=widget),
                minimum_points=minimum_points,
                refit=False,
            )
        else:
            field = typing.cast(QtWidgets.QLineEdit, widget)
            points: list[tuple[float, float]] = []
            text = field.text().strip()
            if text:
                try:
                    points = parse_coordinate_lines(
                        text,
                        label=title,
                        minimum_points=1,
                        empty_ok=False,
                    )[:1]
                except ValueError as exc:
                    self.status_label.setText(str(exc))
                    return
            self.map_picker.configure_selection(
                title=title,
                mode="point",
                initial_points=points,
                draft_overlays=self._draft_overlays(exclude_widget=widget),
                minimum_points=1,
                refit=False,
            )
        self.map_picker.use_button.setText("Use Selected")
        self._sync_map_apply_state()

    def _parse_existing_points(
        self,
        editor: QtWidgets.QPlainTextEdit,
        label: str,
        minimum_points: int,
    ) -> list[tuple[float, float]] | None:
        try:
            return parse_coordinate_lines(
                editor.toPlainText(),
                label=label,
                minimum_points=1 if editor.toPlainText().strip() else minimum_points,
                empty_ok=True,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return None

    def _draft_overlays(
        self,
        *,
        exclude_widget: QtWidgets.QWidget | None = None,
    ) -> tuple[DraftMapOverlay, ...]:
        overlays: list[DraftMapOverlay] = []
        self._append_path_overlay(
            overlays,
            label="Draft AO",
            mode="polygon",
            editor=self.ao_field,
            minimum_points=3,
            exclude_widget=exclude_widget,
        )
        self._append_path_overlay(
            overlays,
            label="Draft Route",
            mode="route",
            editor=self.route_field,
            minimum_points=1,
            exclude_widget=exclude_widget,
        )
        self._append_point_overlay(
            overlays,
            label="Draft Staging Area",
            field=self.staging_area_field,
            exclude_widget=exclude_widget,
        )
        self._append_point_overlay(
            overlays,
            label="Draft Demob Point",
            field=self.demob_point_field,
            exclude_widget=exclude_widget,
        )
        for key, field in self._key_location_fields.items():
            self._append_point_overlay(
                overlays,
                label=f"Draft {key.replace('_', ' ').title()}",
                field=field,
                exclude_widget=exclude_widget,
            )
        return tuple(overlays)

    @staticmethod
    def _append_path_overlay(
        overlays: list[DraftMapOverlay],
        *,
        label: str,
        mode: typing.Literal["polygon", "route"],
        editor: QtWidgets.QPlainTextEdit,
        minimum_points: int,
        exclude_widget: QtWidgets.QWidget | None,
    ) -> None:
        if editor is exclude_widget or not editor.toPlainText().strip():
            return
        try:
            points = parse_coordinate_lines(
                editor.toPlainText(),
                label=label,
                minimum_points=minimum_points,
                empty_ok=False,
            )
        except ValueError:
            return
        overlays.append(DraftMapOverlay(label=label, mode=mode, points=tuple(points)))

    @staticmethod
    def _append_point_overlay(
        overlays: list[DraftMapOverlay],
        *,
        label: str,
        field: QtWidgets.QLineEdit,
        exclude_widget: QtWidgets.QWidget | None,
    ) -> None:
        if field is exclude_widget or not field.text().strip():
            return
        try:
            points = parse_coordinate_lines(
                field.text(),
                label=label,
                minimum_points=1,
                empty_ok=False,
            )
        except ValueError:
            return
        overlays.append(DraftMapOverlay(label=label, mode="point", points=tuple(points[:1])))

    def _activation_text(self) -> str:
        if not self.activation_enabled.isChecked():
            return ""
        return self.activation_time.dateTime().toString("yyyy-MM-dd HH:mm")

    def _operation_window_text(self) -> str:
        if not self.operation_window_enabled.isChecked():
            return ""
        start = self.operation_start_time.dateTime()
        end = self.operation_end_time.dateTime()
        if end < start:
            raise ValueError("Operation window end must be after start.")
        return (
            f"{start.toString('yyyy-MM-dd HH:mm')} - "
            f"{end.toString('yyyy-MM-dd HH:mm')}"
        )

    def _constraints(self) -> list[str]:
        values = [
            label for label, check in self._constraint_checks.items()
            if check.isChecked()
        ]
        values.extend(line_items(self.custom_constraints.toPlainText()))
        return values

    @staticmethod
    def _text_edit() -> QtWidgets.QTextEdit:
        edit = QtWidgets.QTextEdit()
        edit.setFixedHeight(76)
        return edit

    @staticmethod
    def _table(headers: list[str]) -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(130)
        return table

    def _table_with_buttons(self, table: QtWidgets.QTableWidget) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        add_button = QtWidgets.QPushButton("Add")
        remove_button = QtWidgets.QPushButton("Remove")
        add_button.clicked.connect(lambda _checked=False, t=table: self._add_table_row(t))
        remove_button.clicked.connect(lambda _checked=False, t=table: self._remove_table_row(t))
        row.addStretch(1)
        row.addWidget(add_button)
        row.addWidget(remove_button)
        layout.addWidget(table)
        layout.addLayout(row)
        return container

    @staticmethod
    def _add_table_row(table: QtWidgets.QTableWidget) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for column in range(table.columnCount()):
            table.setItem(row, column, QtWidgets.QTableWidgetItem(""))
        table.setCurrentCell(row, 0)

    @staticmethod
    def _remove_table_row(table: QtWidgets.QTableWidget) -> None:
        row = table.currentRow()
        if row < 0 and table.rowCount():
            row = table.rowCount() - 1
        if row >= 0:
            table.removeRow(row)

    @staticmethod
    def _table_dicts(
        table: QtWidgets.QTableWidget,
        keys: tuple[str, ...],
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for row in range(table.rowCount()):
            values: dict[str, str] = {}
            has_value = False
            for column, key in enumerate(keys):
                item = table.item(row, column)
                text = item.text().strip() if item is not None else ""
                values[key] = text
                has_value = has_value or bool(text)
            if has_value:
                rows.append(values)
        return rows

    @staticmethod
    def _scroll_page(widget: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll


class MissionApprovalDialog(QtWidgets.QDialog):
    """Server review dialog that can adjust requested asset allocation."""

    def __init__(
        self,
        core: TalonCoreSession,
        mission_id: int,
        *,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._core = core
        self._mission_id = mission_id
        self.setWindowTitle("Approve Mission")
        self.setMinimumSize(560, 620)

        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.asset_list = QtWidgets.QListWidget()
        self.asset_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self.approve_button = QtWidgets.QPushButton("Approve")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.approve_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.approve_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(QtWidgets.QLabel("Asset Allocation"))
        layout.addWidget(self.asset_list, stretch=1)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)
        self._load()

    def selected_asset_ids(self) -> list[int]:
        selected: list[int] = []
        for row in range(self.asset_list.count()):
            item = self.asset_list.item(row)
            if item.checkState() == QtCore.Qt.Checked:
                selected.append(int(item.data(QtCore.Qt.UserRole)))
        return selected

    def _load(self) -> None:
        try:
            context = self._core.read_model(
                "missions.approval_context",
                {"mission_id": self._mission_id},
            )
        except Exception as exc:
            self.status_label.setText(f"Unable to load approval context: {exc}")
            self.approve_button.setDisabled(True)
            return
        mission = context["mission"]
        creator = context.get("creator_callsign", "")
        requested_ids = set(context.get("requested_ids", set()))
        self.summary.setText(
            f"#{mission.id} {mission.title}\n"
            f"Requested by: {creator}\n"
            f"Priority: {getattr(mission, 'priority', '')} | "
            f"Type: {getattr(mission, 'mission_type', '')}"
        )
        for asset in context.get("all_assets", []):
            mission_id = getattr(asset, "mission_id", None)
            if mission_id is not None and int(mission_id) != int(mission.id):
                continue
            requested = int(getattr(asset, "id")) in requested_ids
            label = (
                f"#{asset.id} {asset.label} [{asset.category}]"
                + ("  requested" if requested else "")
            )
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, int(asset.id))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if requested else QtCore.Qt.Unchecked)
            self.asset_list.addItem(item)
        if self.asset_list.count() == 0:
            self.status_label.setText("No allocatable assets are available.")


class MissionPage(QtWidgets.QWidget):
    """Desktop mission list/detail page and lifecycle command wiring."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._items: list[DesktopMissionItem] = []

        self.heading = QtWidgets.QLabel("Missions")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)

        self.status_filter = QtWidgets.QComboBox()
        for status, label in MISSION_STATUS_OPTIONS:
            self.status_filter.addItem(label, status)
        self.status_filter.currentIndexChanged.connect(lambda _index: self.refresh())
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.new_button = QtWidgets.QPushButton("New")
        self.new_button.clicked.connect(self._create_mission)

        self.approve_button = QtWidgets.QPushButton("Approve")
        self.reject_button = QtWidgets.QPushButton("Reject")
        self.abort_button = QtWidgets.QPushButton("Abort")
        self.complete_button = QtWidgets.QPushButton("Complete")
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.approve_button.clicked.connect(lambda: self._run_server_action("approve"))
        self.reject_button.clicked.connect(lambda: self._run_server_action("reject"))
        self.abort_button.clicked.connect(lambda: self._run_server_action("abort"))
        self.complete_button.clicked.connect(lambda: self._run_server_action("complete"))
        self.delete_button.clicked.connect(lambda: self._run_server_action("delete"))
        self._server_buttons = {
            "approve": self.approve_button,
            "reject": self.reject_button,
            "abort": self.abort_button,
            "complete": self.complete_button,
            "delete": self.delete_button,
        }

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.status_filter)
        top_row.addWidget(self.refresh_button)
        top_row.addWidget(self.new_button)
        for button in self._server_buttons.values():
            top_row.addWidget(button)
            button.setVisible(self._core.mode == "server")

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Title", "Status", "Priority", "Type"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        configure_data_table(self.table)
        self.table.itemSelectionChanged.connect(self._selection_changed)

        self.detail = QtWidgets.QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumWidth(360)

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
            filters = {}
            status = self.status_filter.currentData()
            if status:
                filters["status_filter"] = status
            self._items = items_from_missions(self._core.read_model("missions.list", filters))
        except Exception as exc:
            _log.warning("Could not refresh missions: %s", exc)
            self.summary.setText(f"Unable to load missions: {exc}")
            return
        self.table.setRowCount(0)
        for item in self._items:
            self._add_row(item)
        self.summary.setText(f"{len(self._items)} mission(s).")
        if self._items:
            self.table.selectRow(0)
        else:
            self.detail.clear()
        self._selection_changed()

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        _ = action, record_id
        if table in {"missions", "assets", "zones", "waypoints", "sitreps", "channels", "messages"}:
            self.refresh()

    def _add_row(self, item: DesktopMissionItem) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [str(item.id), item.title, item.status_label, item.priority, item.mission_type]
        for column, value in enumerate(values):
            cell = QtWidgets.QTableWidgetItem(value)
            if column == 0:
                cell.setData(QtCore.Qt.UserRole, item.id)
            self.table.setItem(row, column, cell)

    def _selected_item(self) -> DesktopMissionItem | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def _selection_changed(self) -> None:
        item = self._selected_item()
        for button in self._server_buttons.values():
            button.setEnabled(False)
        if item is None:
            return
        if self._core.mode == "server":
            actions = set(server_actions_for_status(item.status))
            for action, button in self._server_buttons.items():
                button.setEnabled(action in actions)
        self.detail.setPlainText(self._detail_text(item.id))

    def _create_mission(self) -> None:
        dialog = MissionCreateDialog(self._core, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            self._core.command("missions.create", dialog.payload())
            self.refresh()
        except Exception as exc:
            _log.warning("Mission create failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Mission", str(exc))

    def _run_server_action(self, action: str) -> None:
        item = self._selected_item()
        if item is None:
            return
        command = {
            "approve": "missions.approve",
            "reject": "missions.reject",
            "abort": "missions.abort",
            "complete": "missions.complete",
            "delete": "missions.delete",
        }[action]
        payload: dict[str, object] = {"mission_id": item.id}
        if action == "approve":
            dialog = MissionApprovalDialog(self._core, item.id, parent=self)
            if dialog.exec() != QtWidgets.QDialog.Accepted:
                return
            payload["asset_ids"] = dialog.selected_asset_ids()
        if action in {"delete", "reject", "abort", "complete"}:
            if (
                QtWidgets.QMessageBox.question(
                    self,
                    "Mission",
                    f"{action.title()} mission #{item.id}?",
                )
                != QtWidgets.QMessageBox.Yes
            ):
                return
        try:
            self._core.command(command, payload)
            self.refresh()
        except Exception as exc:
            _log.warning("Mission %s failed: %s", action, exc)
            QtWidgets.QMessageBox.warning(self, "Mission", str(exc))

    def _detail_text(self, mission_id: int) -> str:
        try:
            detail = self._core.read_model("missions.detail", {"mission_id": mission_id})
        except Exception as exc:
            return f"Unable to load mission detail: {exc}"
        mission = detail["mission"]
        assets = detail.get("assets", [])
        zones = detail.get("zones", [])
        waypoints = detail.get("waypoints", [])
        sitreps = detail.get("sitreps", [])
        phases = getattr(mission, "phases", []) or []
        constraints = getattr(mission, "constraints", []) or []
        objectives = getattr(mission, "objectives", []) or []
        key_locations = getattr(mission, "key_locations", {}) or {}
        custom_resources = getattr(mission, "custom_resources", []) or []
        lines = [
            f"#{mission.id} {mission.title}",
            f"Status: {mission.status}",
            f"Priority: {getattr(mission, 'priority', '')}",
            f"Type: {getattr(mission, 'mission_type', '')}",
            f"Creator: {detail.get('creator_callsign', '')}",
            f"Channel: {detail.get('channel_name', '')}",
            f"Lead: {getattr(mission, 'lead_coordinator', '')}",
            f"Organization: {getattr(mission, 'organization', '')}",
            f"Activation: {getattr(mission, 'activation_time', '')}",
            f"Window: {getattr(mission, 'operation_window', '')}",
            f"Max Duration: {getattr(mission, 'max_duration', '')}",
            f"Staging Area: {getattr(mission, 'staging_area', '')}",
            f"Demob Point: {getattr(mission, 'demob_point', '')}",
            f"Stand-down: {getattr(mission, 'standdown_criteria', '')}",
            "",
            mission.description,
            "",
            "Constraints:",
            *[f"  {constraint}" for constraint in constraints],
            "Phases:",
            *[f"  {_mission_mapping_line(phase, ('name', 'objective', 'duration'))}" for phase in phases],
            "Support:",
            f"  Medical: {getattr(mission, 'support_medical', '')}",
            f"  Logistics: {getattr(mission, 'support_logistics', '')}",
            f"  Comms: {getattr(mission, 'support_comms', '')}",
            f"  Equipment: {getattr(mission, 'support_equipment', '')}",
            *[
                f"  {_mission_mapping_line(resource, ('label', 'details'))}"
                for resource in custom_resources
            ],
            "Objectives:",
            *[
                f"  {_mission_mapping_line(objective, ('label', 'criteria'))}"
                for objective in objectives
            ],
            "Key Locations:",
            *[
                f"  {str(key).replace('_', ' ').title()}: {value}"
                for key, value in key_locations.items()
                if value
            ],
            "Assets:",
            *[f"  #{asset.id} {asset.label}" for asset in assets],
            "Zones:",
            *[f"  #{zone.id} {zone.label} [{zone.zone_type}]" for zone in zones],
            "Waypoints:",
            *[
                f"  {point.sequence}. {point.label} ({point.lat:.6f}, {point.lon:.6f})"
                for point in waypoints
            ],
            "SITREPs:",
            *[f"  #{item[0].id if isinstance(item, tuple) else item.id}" for item in sitreps],
        ]
        return "\n".join(lines).strip()


def _mission_mapping_line(item: object, keys: tuple[str, ...]) -> str:
    if isinstance(item, dict):
        parts = [str(item.get(key, "") or "").strip() for key in keys]
        parts = [part for part in parts if part]
        return " | ".join(parts)
    return str(item)

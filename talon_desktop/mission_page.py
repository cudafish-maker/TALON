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
from talon_desktop.mission_icons import (
    MISSION_LOCATION_ICON_KEYS,
    MISSION_LOCATION_ICON_LABELS,
    draw_mission_location_icon,
    mission_location_icon_pixmap,
    mission_location_icon_key,
)
from talon_desktop.sitreps import AvailableOperatorItem, available_operator_items
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
            ("command_post", "Command Post"),
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
                QtGui.QPen(QtGui.QColor("#3498db"), 2),
                QtGui.QBrush(QtGui.QColor(52, 152, 219, 54)),
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
        draw_mission_location_icon(self._scene, icon, x, y, z=12, size=11)

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
        mission_detail: dict[str, object] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._core = core
        self._mission_detail = mission_detail or {}
        self._mission = self._mission_detail.get("mission")
        self._mission_id = (
            int(getattr(self._mission, "id"))
            if self._mission is not None and getattr(self._mission, "id", None) is not None
            else None
        )
        self._initial_asset_ids = {
            int(getattr(asset, "id"))
            for asset in self._mission_detail.get("assets", []) or []
        }
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
        self.setWindowTitle("Edit Mission" if self._mission_id is not None else "Mission")
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
        self._team_operators: list[AvailableOperatorItem] = []
        self.lead_combo = QtWidgets.QComboBox()
        self.lead_combo.setEditable(False)
        self.lead_combo.currentIndexChanged.connect(lambda _index: self._refresh_member_combo())
        self.team_member_combo = QtWidgets.QComboBox()
        self.team_member_add_button = QtWidgets.QPushButton("Add")
        self.team_member_add_button.clicked.connect(self._add_team_member)
        self.team_member_list = QtWidgets.QListWidget()
        self.team_member_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.team_member_list.setMaximumHeight(100)
        self.team_member_remove_button = QtWidgets.QPushButton("Remove")
        self.team_member_remove_button.clicked.connect(self._remove_team_member)
        self._load_team_operators()

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
        tabs.setCurrentIndex(3)
        self.tabs = tabs
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

        self._populate_initial_values()

        self.save_button = QtWidgets.QPushButton(
            "Save Changes" if self._mission_id is not None else "Create"
        )
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        heading = QtWidgets.QLabel(
            "Edit Mission" if self._mission_id is not None else "Create Mission"
        )
        heading.setObjectName("pageHeading")
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.addWidget(heading)
        toolbar.addStretch(1)
        toolbar.addWidget(self.cancel_button)
        toolbar.addWidget(self.save_button)

        content = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        content.addWidget(tabs)
        content.addWidget(self.map_picker)
        content.setStretchFactor(0, 3)
        content.setStretchFactor(1, 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(content, stretch=1)
        layout.addWidget(self.status_label)
        QtCore.QTimer.singleShot(0, self._refresh_embedded_map_drafts)

    def payload(self) -> dict[str, object]:
        payload = build_create_payload(
            title=self.title_field.text(),
            description=self.description_field.toPlainText(),
            asset_ids=self.selected_asset_ids(),
            mission_type=self.type_combo.currentText(),
            priority=str(self.priority_combo.currentData()),
            lead_coordinator=self.lead_combo.currentText(),
            organization=", ".join(self._selected_team_member_callsigns()),
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
        if self._mission_id is not None:
            payload["mission_id"] = self._mission_id
            payload["replace_ao"] = True
            payload["replace_route"] = True
        return payload

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
            assets = self._core.read_model(
                "assets.list",
                {"available_only": self._mission_id is None},
            )
        except Exception as exc:
            _log.warning("Could not load assets for mission dialog: %s", exc)
            assets = []
        for asset in assets:
            asset_id = int(getattr(asset, "id"))
            mission_id = getattr(asset, "mission_id", None)
            if (
                self._mission_id is not None
                and mission_id is not None
                and int(mission_id) != self._mission_id
                and asset_id not in self._initial_asset_ids
            ):
                continue
            item = QtWidgets.QListWidgetItem(
                f"#{getattr(asset, 'id')} {getattr(asset, 'label')}"
            )
            item.setData(QtCore.Qt.UserRole, asset_id)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.Checked if asset_id in self._initial_asset_ids else QtCore.Qt.Unchecked
            )
            self.assets_list.addItem(item)

    def _load_team_operators(self) -> None:
        self.lead_combo.addItem("", None)
        try:
            operators = self._core.read_model("operators.list")
        except Exception as exc:
            _log.warning("Could not load operators for mission team dropdowns: %s", exc)
            operators = []
        try:
            assignments = self._core.read_model("assignments.list", {"active_only": True})
        except Exception as exc:
            _log.debug("Could not load active assignments for mission team filter: %s", exc)
            assignments = []
        try:
            sitreps = self._core.read_model(
                "sitreps.list",
                {"unresolved_only": True, "limit": 500},
            )
        except Exception as exc:
            _log.debug("Could not load assigned SITREPs for mission team filter: %s", exc)
            sitreps = []
        try:
            missions = self._core.read_model("missions.list", {"status_filter": None})
        except Exception as exc:
            _log.debug("Could not load missions for mission team filter: %s", exc)
            missions = []
        self._team_operators = available_operator_items(
            operators,
            assignments=assignments,
            sitreps=sitreps,
            missions=missions,
            current_mission_id=self._mission_id,
        )
        for item in self._team_operators:
            self.lead_combo.addItem(item.callsign, item.id)
        self._refresh_member_combo()

    def _overview_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        form.addRow("Title", self.title_field)
        form.addRow("Description", self.description_field)
        form.addRow("Type", self.type_combo)
        form.addRow("Priority", self.priority_combo)
        lead_label = "Request Team Lead" if self._core.mode == "client" else "Team Lead"
        members_label = (
            "Request Team Members" if self._core.mode == "client" else "Team Members"
        )
        form.addRow(lead_label, self.lead_combo)
        form.addRow(members_label, self._team_member_widget())
        return page

    def _team_member_widget(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        chooser = QtWidgets.QHBoxLayout()
        chooser.addWidget(self.team_member_combo, stretch=1)
        chooser.addWidget(self.team_member_add_button)
        actions = QtWidgets.QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self.team_member_remove_button)
        layout.addLayout(chooser)
        layout.addWidget(self.team_member_list)
        layout.addLayout(actions)
        return container

    def _refresh_member_combo(self) -> None:
        if not hasattr(self, "team_member_combo"):
            return
        lead_id = self.lead_combo.currentData()
        if lead_id not in (None, ""):
            for row in range(self.team_member_list.count() - 1, -1, -1):
                value = self.team_member_list.item(row).data(QtCore.Qt.UserRole)
                if value is not None and int(value) == int(lead_id):
                    self.team_member_list.takeItem(row)
        selected_ids = self._selected_team_member_ids()
        self.team_member_combo.clear()
        self.team_member_combo.addItem("Select unassigned operator", None)
        for item in self._team_operators:
            if item.id in selected_ids or item.id == lead_id:
                continue
            self.team_member_combo.addItem(item.callsign, item.id)
        self.team_member_add_button.setEnabled(self.team_member_combo.count() > 1)

    def _add_team_member(self) -> None:
        operator_id = self.team_member_combo.currentData()
        if operator_id is None:
            return
        operator = next(
            (item for item in self._team_operators if item.id == int(operator_id)),
            None,
        )
        if operator is None:
            return
        row = QtWidgets.QListWidgetItem(operator.callsign)
        row.setData(QtCore.Qt.UserRole, operator.id)
        row.setData(QtCore.Qt.UserRole + 1, operator.callsign)
        self.team_member_list.addItem(row)
        self._refresh_member_combo()

    def _remove_team_member(self) -> None:
        row = self.team_member_list.currentRow()
        if row < 0 and self.team_member_list.count():
            row = self.team_member_list.count() - 1
        if row >= 0:
            self.team_member_list.takeItem(row)
        self._refresh_member_combo()

    def _selected_team_member_ids(self) -> set[int]:
        ids: set[int] = set()
        if not hasattr(self, "team_member_list"):
            return ids
        for row in range(self.team_member_list.count()):
            value = self.team_member_list.item(row).data(QtCore.Qt.UserRole)
            if value is not None:
                ids.add(int(value))
        return ids

    def _selected_team_member_callsigns(self) -> list[str]:
        callsigns: list[str] = []
        for row in range(self.team_member_list.count()):
            value = self.team_member_list.item(row).data(QtCore.Qt.UserRole + 1)
            callsign = str(value or self.team_member_list.item(row).text()).strip()
            if callsign:
                callsigns.append(callsign)
        return callsigns

    def _populate_initial_values(self) -> None:
        mission = self._mission
        if mission is None:
            return

        self.title_field.setText(str(getattr(mission, "title", "") or ""))
        self.description_field.setPlainText(str(getattr(mission, "description", "") or ""))
        self._set_combo_value(self.type_combo, str(getattr(mission, "mission_type", "") or ""))
        self._set_combo_value(self.priority_combo, str(getattr(mission, "priority", "") or "ROUTINE"))

        lead = str(getattr(mission, "lead_coordinator", "") or "").strip()
        if lead:
            lead_index = self.lead_combo.findText(lead)
            if lead_index < 0:
                self.lead_combo.addItem(lead, None)
                lead_index = self.lead_combo.findText(lead)
            self.lead_combo.setCurrentIndex(lead_index)

        members = str(getattr(mission, "organization", "") or "")
        for callsign in [piece.strip() for piece in members.replace(";", ",").split(",")]:
            if not callsign:
                continue
            operator = next(
                (
                    item for item in self._team_operators
                    if item.callsign.casefold() == callsign.casefold()
                ),
                None,
            )
            row = QtWidgets.QListWidgetItem(callsign)
            row.setData(QtCore.Qt.UserRole, operator.id if operator is not None else None)
            row.setData(QtCore.Qt.UserRole + 1, callsign)
            self.team_member_list.addItem(row)
        self._refresh_member_combo()

        self._set_datetime(self.activation_enabled, self.activation_time, getattr(mission, "activation_time", ""))
        self._set_operation_window(str(getattr(mission, "operation_window", "") or ""))
        self.max_duration_field.setText(str(getattr(mission, "max_duration", "") or ""))
        self.staging_area_field.setText(str(getattr(mission, "staging_area", "") or ""))
        self.demob_point_field.setText(str(getattr(mission, "demob_point", "") or ""))
        self.standdown_field.setPlainText(str(getattr(mission, "standdown_criteria", "") or ""))

        self._set_table_rows(
            self.phase_table,
            getattr(mission, "phases", []) or [],
            ("name", "objective", "duration"),
        )
        self._set_table_rows(
            self.objective_table,
            getattr(mission, "objectives", []) or [],
            ("label", "criteria"),
        )
        self._set_table_rows(
            self.custom_resource_table,
            getattr(mission, "custom_resources", []) or [],
            ("label", "details"),
        )

        known_constraints = set(self._constraint_checks)
        custom_constraints: list[str] = []
        for constraint in getattr(mission, "constraints", []) or []:
            text = str(constraint).strip()
            if not text:
                continue
            if text in self._constraint_checks:
                self._constraint_checks[text].setChecked(True)
            elif text not in known_constraints:
                custom_constraints.append(text)
        self.custom_constraints.setPlainText("\n".join(custom_constraints))

        self.support_medical.setPlainText(str(getattr(mission, "support_medical", "") or ""))
        self.support_logistics.setPlainText(str(getattr(mission, "support_logistics", "") or ""))
        self.support_comms.setPlainText(str(getattr(mission, "support_comms", "") or ""))
        self.support_equipment.setPlainText(str(getattr(mission, "support_equipment", "") or ""))

        ao_zones = self._mission_detail.get("ao_zones", []) or []
        if ao_zones:
            polygon = getattr(ao_zones[0], "polygon", []) or []
            self.ao_field.setPlainText(format_coordinate_lines(tuple(map(tuple, polygon))))
        waypoints = sorted(
            self._mission_detail.get("waypoints", []) or [],
            key=lambda point: int(getattr(point, "sequence", 0) or 0),
        )
        if waypoints:
            self.route_field.setPlainText(
                format_coordinate_lines(
                    (
                        (float(getattr(point, "lat")), float(getattr(point, "lon")))
                        for point in waypoints
                    )
                )
            )
        key_locations = getattr(mission, "key_locations", {}) or {}
        if isinstance(key_locations, dict):
            for key, field in self._key_location_fields.items():
                field.setText(str(key_locations.get(key, "") or ""))

    @staticmethod
    def _set_combo_value(combo: QtWidgets.QComboBox, value: str) -> None:
        if not value:
            return
        index = combo.findData(value)
        if index < 0:
            index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _set_datetime(
        checkbox: QtWidgets.QCheckBox,
        editor: QtWidgets.QDateTimeEdit,
        value: object,
    ) -> None:
        text = str(value or "").strip()
        if not text:
            return
        parsed = QtCore.QDateTime.fromString(text, "yyyy-MM-dd HH:mm")
        if not parsed.isValid():
            return
        checkbox.setChecked(True)
        editor.setDateTime(parsed)

    def _set_operation_window(self, value: str) -> None:
        text = value.strip()
        if not text or " - " not in text:
            return
        start_text, end_text = text.split(" - ", 1)
        start = QtCore.QDateTime.fromString(start_text, "yyyy-MM-dd HH:mm")
        end = QtCore.QDateTime.fromString(end_text, "yyyy-MM-dd HH:mm")
        if not start.isValid() or not end.isValid():
            return
        self.operation_window_enabled.setChecked(True)
        self.operation_start_time.setDateTime(start)
        self.operation_end_time.setDateTime(end)

    @staticmethod
    def _set_table_rows(
        table: QtWidgets.QTableWidget,
        rows: typing.Iterable[object],
        keys: tuple[str, ...],
    ) -> None:
        table.setRowCount(0)
        for row_data in rows:
            if isinstance(row_data, dict):
                values = [str(row_data.get(key, "") or "") for key in keys]
            else:
                values = [str(row_data), *("" for _key in keys[1:])]
            if not any(value.strip() for value in values):
                continue
            row = table.rowCount()
            table.insertRow(row)
            for column, value in enumerate(values):
                table.setItem(row, column, QtWidgets.QTableWidgetItem(value))

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
        form.addRow("Mission Location Icons", self._mission_icon_legend())

        key_group = QtWidgets.QGroupBox("Key Locations")
        key_form = QtWidgets.QFormLayout(key_group)
        for key, label in (
            ("command_post", "Command Post"),
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

    def _mission_icon_legend(self) -> QtWidgets.QWidget:
        grid = QtWidgets.QWidget()
        grid.setObjectName("missionIconLegend")
        layout = QtWidgets.QGridLayout(grid)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)
        for index, key in enumerate(MISSION_LOCATION_ICON_KEYS):
            card = QtWidgets.QFrame()
            card.setFrameShape(QtWidgets.QFrame.StyledPanel)
            card_layout = QtWidgets.QHBoxLayout(card)
            card_layout.setContentsMargins(8, 8, 8, 8)
            icon = QtWidgets.QLabel()
            icon.setFixedSize(38, 38)
            icon.setPixmap(mission_location_icon_pixmap(key))
            icon.setAlignment(QtCore.Qt.AlignCenter)
            label = QtWidgets.QLabel(
                f"<strong>{MISSION_LOCATION_ICON_LABELS[key]}</strong><br>"
                f"<span style='color:#98a8ae;'>Global key: {key}</span>"
            )
            label.setWordWrap(True)
            card_layout.addWidget(icon)
            card_layout.addWidget(label, stretch=1)
            layout.addWidget(card, index // 3, index % 3)
        return grid

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
            selection_icon_key=mission_location_icon_key(title),
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
                selection_icon_key=mission_location_icon_key(title),
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
            icon_key="staging_area",
            field=self.staging_area_field,
            exclude_widget=exclude_widget,
        )
        self._append_point_overlay(
            overlays,
            label="Draft Demob Point",
            icon_key="demob_point",
            field=self.demob_point_field,
            exclude_widget=exclude_widget,
        )
        for key, field in self._key_location_fields.items():
            self._append_point_overlay(
                overlays,
                label=f"Draft {key.replace('_', ' ').title()}",
                icon_key=key,
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
        icon_key: str,
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
        overlays.append(
            DraftMapOverlay(
                label=label,
                mode="point",
                points=tuple(points[:1]),
                icon_key=icon_key,
            )
        )

    def _activation_text(self) -> str:
        if not self.activation_enabled.isChecked():
            return ""
        return self.activation_time.dateTime().toString("yyyy-MM-dd HH:mm")

    def _operation_window_text(self) -> str:
        if not self.operation_window_enabled.isChecked():
            return ""
        start = self.operation_start_time.dateTime()
        end = self.operation_end_time.dateTime()
        start_text = start.toString("yyyy-MM-dd HH:mm")
        end_text = end.toString("yyyy-MM-dd HH:mm")
        if end_text <= start_text:
            raise ValueError("Operation window end must be after start.")
        return f"{start_text} - {end_text}"

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
        if self._core.mode == "client":
            self.new_button.setText("Request New Mission")
        else:
            self.new_button.setText("New Mission")
        self.edit_button = QtWidgets.QPushButton("Edit Mission")
        self.edit_button.clicked.connect(self._edit_mission)
        self.edit_button.setVisible(self._core.mode == "server")

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
        top_row.addWidget(self.edit_button)
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

    def select_mission(self, mission_id: int) -> None:
        all_index = self.status_filter.findData(None)
        if all_index >= 0 and self.status_filter.currentIndex() != all_index:
            self.status_filter.blockSignals(True)
            self.status_filter.setCurrentIndex(all_index)
            self.status_filter.blockSignals(False)
        self.refresh()
        for row, item in enumerate(self._items):
            if item.id == int(mission_id):
                self.table.selectRow(row)
                break

    def _selection_changed(self) -> None:
        item = self._selected_item()
        self.edit_button.setEnabled(False)
        for button in self._server_buttons.values():
            button.setEnabled(False)
        if item is None:
            return
        if self._core.mode == "server":
            self.edit_button.setEnabled(True)
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

    def _edit_mission(self) -> None:
        item = self._selected_item()
        if item is None or self._core.mode != "server":
            return
        try:
            detail = self._core.read_model("missions.detail", {"mission_id": item.id})
        except Exception as exc:
            _log.warning("Mission detail load failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Mission", str(exc))
            return
        dialog = MissionCreateDialog(self._core, mission_detail=detail, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            self._core.command("missions.update", dialog.payload())
            self.refresh()
            self.select_mission(item.id)
        except Exception as exc:
            _log.warning("Mission update failed: %s", exc)
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
            f"Team Lead: {getattr(mission, 'lead_coordinator', '')}",
            f"Team Members: {getattr(mission, 'organization', '')}",
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

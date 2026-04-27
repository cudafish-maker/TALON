"""PySide6 mission list, detail, create, and lifecycle page."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from talon_core import TalonCoreSession
from talon_core.constants import SITREP_LEVELS
from talon_core.utils.logging import get_logger
from talon_desktop.missions import (
    MISSION_STATUS_OPTIONS,
    DesktopMissionItem,
    build_create_payload,
    items_from_missions,
    server_actions_for_status,
)
from talon_desktop.theme import configure_data_table

_log = get_logger("desktop.missions")


class MissionCreateDialog(QtWidgets.QDialog):
    """Compact mission create workflow with asset, AO, and route inputs."""

    def __init__(
        self,
        core: TalonCoreSession,
        *,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._core = core
        self.setWindowTitle("Mission")
        self.setMinimumWidth(620)

        self.title_field = QtWidgets.QLineEdit()
        self.description_field = QtWidgets.QTextEdit()
        self.description_field.setFixedHeight(92)
        self.type_field = QtWidgets.QLineEdit()
        self.priority_combo = QtWidgets.QComboBox()
        for level in SITREP_LEVELS:
            self.priority_combo.addItem(level, level)
        self.lead_field = QtWidgets.QLineEdit()
        self.organization_field = QtWidgets.QLineEdit()

        form = QtWidgets.QFormLayout()
        form.addRow("Title", self.title_field)
        form.addRow("Description", self.description_field)
        form.addRow("Type", self.type_field)
        form.addRow("Priority", self.priority_combo)
        form.addRow("Lead", self.lead_field)
        form.addRow("Organization", self.organization_field)

        self.assets_list = QtWidgets.QListWidget()
        self.assets_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.assets_list.setMinimumHeight(110)
        self._load_assets()

        self.ao_field = QtWidgets.QPlainTextEdit()
        self.ao_field.setPlaceholderText("lat, lon\nlat, lon\nlat, lon")
        self.ao_field.setFixedHeight(90)
        self.route_field = QtWidgets.QPlainTextEdit()
        self.route_field.setPlaceholderText("lat, lon\nlat, lon")
        self.route_field.setFixedHeight(90)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self.save_button = QtWidgets.QPushButton("Create")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.save_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QtWidgets.QLabel("Requested Assets"))
        layout.addWidget(self.assets_list)
        layout.addWidget(QtWidgets.QLabel("AO Polygon"))
        layout.addWidget(self.ao_field)
        layout.addWidget(QtWidgets.QLabel("Route / Waypoints"))
        layout.addWidget(self.route_field)
        layout.addWidget(self.status_label)
        layout.addLayout(button_row)

    def payload(self) -> dict[str, object]:
        return build_create_payload(
            title=self.title_field.text(),
            description=self.description_field.toPlainText(),
            asset_ids=self.selected_asset_ids(),
            mission_type=self.type_field.text(),
            priority=str(self.priority_combo.currentData()),
            lead_coordinator=self.lead_field.text(),
            organization=self.organization_field.text(),
            ao_text=self.ao_field.toPlainText(),
            route_text=self.route_field.toPlainText(),
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
            self._core.command(command, mission_id=item.id)
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
        lines = [
            f"#{mission.id} {mission.title}",
            f"Status: {mission.status}",
            f"Priority: {getattr(mission, 'priority', '')}",
            f"Type: {getattr(mission, 'mission_type', '')}",
            f"Creator: {detail.get('creator_callsign', '')}",
            f"Channel: {detail.get('channel_name', '')}",
            "",
            mission.description,
            "",
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

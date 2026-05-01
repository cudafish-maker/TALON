"""PySide6 community safety assignment board."""
from __future__ import annotations

import dataclasses
import time
import typing

from PySide6 import QtCore, QtGui, QtWidgets

from talon_core import TalonCoreSession
from talon_core.community_safety import (
    ASSIGNMENT_STATUSES,
    ASSIGNMENT_TYPES,
    CHECKIN_STATES,
)
from talon_core.constants import PREDEFINED_SKILLS, SITREP_LEVELS
from talon_core.utils.formatting import format_ts
from talon_core.utils.logging import get_logger
from talon_desktop.community_safety import (
    ASSIGNMENT_STATUS_LABELS,
    ASSIGNMENT_TYPE_LABELS,
    CHECKIN_STATE_LABELS,
    DesktopAssignmentItem,
    assignment_items_from_board,
    build_assignment_payload,
    build_checkin_payload,
    operator_status_items_from_board,
)
from talon_desktop.map_picker import format_coordinate, pick_point_on_map
from talon_desktop.sitreps import (
    AvailableOperatorItem,
    available_operator_items,
    feed_item_from_entry,
    mission_operator_callsigns,
)
from talon_desktop.theme import configure_data_table

_log = get_logger("desktop.community_safety")

_STATUS_COLORS = {
    "planned": QtGui.QColor("#d6b85a"),
    "active": QtGui.QColor("#7fb069"),
    "paused": QtGui.QColor("#d6b85a"),
    "completed": QtGui.QColor("#8fbcbb"),
    "aborted": QtGui.QColor("#93a1a8"),
    "needs_support": QtGui.QColor("#ff5555"),
}

_PRIORITY_RANK = {
    "FLASH_OVERRIDE": 0,
    "FLASH": 1,
    "IMMEDIATE": 2,
    "PRIORITY": 3,
    "ROUTINE": 4,
}


@dataclasses.dataclass(frozen=True)
class AssignmentTargetItem:
    kind: typing.Literal["mission", "sitrep"]
    id: int
    title: str
    priority: str
    created_at: int
    subtitle: str
    mission_type: str = ""


class AssignmentPage(QtWidgets.QWidget):
    """Command-post assignment board for patrols and protective details."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._items: list[DesktopAssignmentItem] = []

        self.heading = QtWidgets.QLabel("Assignment Board")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)

        self.status_filter = QtWidgets.QComboBox()
        self.status_filter.addItem("All active", "__active__")
        self.status_filter.addItem("All statuses", "")
        for status in ASSIGNMENT_STATUSES:
            self.status_filter.addItem(ASSIGNMENT_STATUS_LABELS[status], status)
        self.status_filter.currentIndexChanged.connect(lambda _index: self.refresh())

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.new_button = QtWidgets.QPushButton("New Assignment")
        self.new_button.clicked.connect(self._create_assignment)
        self.checkin_button = QtWidgets.QPushButton(
            "Server Check-In" if self._core.mode == "server" else "Check-In"
        )
        self.checkin_button.clicked.connect(self._create_checkin)
        self.ack_button = QtWidgets.QPushButton("Acknowledge")
        self.ack_button.clicked.connect(self._acknowledge_latest_checkin)
        self.closeout_button = QtWidgets.QPushButton("Close Out")
        self.closeout_button.clicked.connect(lambda: self._close_assignment("completed"))
        self.closeout_button.setVisible(self._core.mode == "server")
        self.abort_button = QtWidgets.QPushButton("Abort")
        self.abort_button.clicked.connect(lambda: self._close_assignment("aborted"))
        self.abort_button.setVisible(self._core.mode == "server")

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.status_filter)
        top_row.addWidget(self.refresh_button)
        top_row.addWidget(self.new_button)

        self.metric_active = _MetricBox("Active Patrols", "0", "")
        self.metric_details = _MetricBox("Protective Details", "0", "")
        self.metric_overdue = _MetricBox("Overdue Check-ins", "0", "")
        self.metric_support = _MetricBox("Needs Support", "0", "")
        self.metric_pending = _MetricBox("Pending Sync", "0", "")
        metric_row = QtWidgets.QHBoxLayout()
        for metric in (
            self.metric_active,
            self.metric_details,
            self.metric_overdue,
            self.metric_support,
            self.metric_pending,
        ):
            metric_row.addWidget(metric)

        self.assignment_table = QtWidgets.QTableWidget(0, 5)
        self.assignment_table.setHorizontalHeaderLabels(
            ["Assignment", "Type", "Lead", "Next Check-in", "State"]
        )
        self.assignment_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.assignment_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.assignment_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.assignment_table.verticalHeader().setVisible(False)
        self.assignment_table.horizontalHeader().setStretchLastSection(True)
        configure_data_table(self.assignment_table)
        self.assignment_table.itemSelectionChanged.connect(self._selection_changed)

        self.operator_table = QtWidgets.QTableWidget(0, 4)
        self.operator_table.setHorizontalHeaderLabels(["Operator", "State", "Assignment", "Skills"])
        self.operator_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.operator_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.operator_table.verticalHeader().setVisible(False)
        self.operator_table.horizontalHeader().setStretchLastSection(True)
        configure_data_table(self.operator_table)

        self.detail = QtWidgets.QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumWidth(280)
        self.detail.setPlaceholderText("Select an assignment")

        self.alerts = QtWidgets.QListWidget()
        self.alerts.setMinimumHeight(160)

        assignment_panel = _panel("Active Assignments", self.assignment_table)
        operator_panel = _panel("Operator Status", self.operator_table)
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(_panel("Selected Assignment", self.detail), stretch=2)
        right_layout.addWidget(_panel("Gaps And Follow-up", self.alerts), stretch=1)
        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(self.checkin_button)
        action_row.addWidget(self.ack_button)
        action_row.addWidget(self.closeout_button)
        action_row.addWidget(self.abort_button)
        right_layout.addLayout(action_row)

        body = QtWidgets.QSplitter()
        body.addWidget(assignment_panel)
        body.addWidget(operator_panel)
        body.addWidget(right_panel)
        body.setStretchFactor(0, 4)
        body.setStretchFactor(1, 3)
        body.setStretchFactor(2, 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self.summary)
        layout.addLayout(metric_row)
        layout.addWidget(body, stretch=1)

    def refresh(self) -> None:
        try:
            board = self._core.read_model("assignments.board")
            items = assignment_items_from_board(board)
            selected_filter = str(self.status_filter.currentData() or "")
            if selected_filter == "__active__":
                items = [
                    item for item in items if item.status not in {"completed", "aborted"}
                ]
            elif selected_filter:
                items = [item for item in items if item.status == selected_filter]
            self._items = items
            operator_items = operator_status_items_from_board(board, items)
        except Exception as exc:
            _log.warning("Could not refresh assignments: %s", exc)
            self.summary.setText(f"Unable to load assignments: {exc}")
            return

        self._populate_assignment_table()
        self._populate_operator_table(operator_items)
        self._populate_metrics(board)
        self._populate_alerts()
        self.summary.setText(
            f"{len(self._items)} assignment(s). The board shows responsibility, "
            "check-in state, and follow-up work; map location remains on the Map page."
        )
        if self._items:
            self.assignment_table.selectRow(0)
        else:
            self.detail.clear()
        self._selection_changed()

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        _ = action, record_id
        if table in {"assignments", "checkins", "operators", "missions"}:
            self.refresh()

    def _populate_assignment_table(self) -> None:
        self.assignment_table.setRowCount(0)
        for item in self._items:
            row = self.assignment_table.rowCount()
            self.assignment_table.insertRow(row)
            values = [
                item.title,
                item.type_label,
                item.team_lead,
                item.next_checkin_label,
                item.status_label,
            ]
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                if column == 0:
                    cell.setData(QtCore.Qt.UserRole, item.id)
                if item.needs_support or item.overdue:
                    warning_color = "#ffb4b4" if item.needs_support else "#f28c28"
                    cell.setForeground(QtGui.QBrush(QtGui.QColor(warning_color)))
                elif column == 4:
                    color = _STATUS_COLORS.get(item.status)
                    if color is not None:
                        cell.setForeground(QtGui.QBrush(color))
                self.assignment_table.setItem(row, column, cell)
        self.assignment_table.resizeColumnsToContents()

    def _populate_operator_table(self, operator_items: typing.Iterable[object]) -> None:
        self.operator_table.setRowCount(0)
        for item in operator_items:
            row = self.operator_table.rowCount()
            self.operator_table.insertRow(row)
            for column, value in enumerate(
                [
                    item.callsign,
                    item.status_label,
                    item.assignment_title,
                    item.skills_label,
                ]
            ):
                cell = QtWidgets.QTableWidgetItem(value)
                if item.status_label in {"Needs support", "Overdue"}:
                    cell.setForeground(QtGui.QBrush(QtGui.QColor("#ffb4b4")))
                self.operator_table.setItem(row, column, cell)
        self.operator_table.resizeColumnsToContents()

    def _populate_metrics(self, board: typing.Mapping[str, typing.Any]) -> None:
        active = [item for item in self._items if item.status not in {"completed", "aborted"}]
        patrols = [
            item
            for item in active
            if item.assignment_type
            in {
                "foot_patrol",
                "vehicle_patrol",
                "escort",
                "welfare_check",
                "supply_run",
                "event_support",
            }
        ]
        details = [
            item for item in active
            if item.assignment_type in {"protective_detail", "fixed_post"}
        ]
        overdue = [item for item in active if item.overdue]
        support = [item for item in active if item.needs_support]
        pending = int(getattr(board.get("sync"), "pending_outbox_count", 0) or 0)
        self.metric_active.set_values(str(len(patrols)), "patrol, escort, welfare, supply")
        self.metric_details.set_values(str(len(details)), "fixed posts and details")
        self.metric_overdue.set_values(str(len(overdue)), "check-ins past threshold")
        self.metric_support.set_values(str(len(support)), "support or duress states")
        self.metric_pending.set_values(str(pending), "local records awaiting sync")

    def _populate_alerts(self) -> None:
        self.alerts.clear()
        for item in self._items:
            if item.needs_support:
                self.alerts.addItem(f"{item.title}: {item.last_checkin_label}")
            elif item.overdue:
                self.alerts.addItem(f"{item.title}: {item.next_checkin_label}")
        if self.alerts.count() == 0:
            self.alerts.addItem("No overdue or support alerts.")

    def _selection_changed(self) -> None:
        item = self._selected_item()
        has_selection = item is not None
        is_open = bool(item is not None and item.status not in {"completed", "aborted"})
        self.checkin_button.setEnabled(has_selection)
        self.ack_button.setEnabled(has_selection)
        self.closeout_button.setEnabled(self._core.mode == "server" and is_open)
        self.abort_button.setEnabled(self._core.mode == "server" and is_open)
        if item is None:
            return
        try:
            detail = self._core.read_model("assignments.detail", {"assignment_id": item.id})
        except Exception as exc:
            self.detail.setPlainText(f"Unable to load assignment detail: {exc}")
            return
        assignment = detail["assignment"]
        checkins = detail.get("checkins", [])
        lines = [
            f"#{assignment.id} {assignment.title}",
            f"Type: {item.type_label}",
            f"Status: {item.status_label}",
            f"Priority: {assignment.priority}",
            f"Mission: {detail.get('mission_title', '') or 'None'}",
            f"Location: {assignment.location_label or 'Not set'}",
            "Map point: "
            + (
                f"{assignment.lat:.6f}, {assignment.lon:.6f}"
                if assignment.lat is not None and assignment.lon is not None
                else "Not set"
            ),
            f"Protected label: {assignment.protected_label or 'None'}",
            f"Lead: {assignment.team_lead or 'Unassigned'}",
            f"Backup: {assignment.backup_operator or 'Open'}",
            f"Escalation: {assignment.escalation_contact or 'Not set'}",
            "Check-in: "
            f"every {assignment.checkin_interval_min} min, "
            f"overdue after {assignment.overdue_threshold_min} min",
            f"Next: {item.next_checkin_label}",
            "",
            "Support reason:",
            assignment.support_reason or "None",
            "",
            "Handoff notes:",
            assignment.handoff_notes or "None",
            "",
            f"Recent check-ins: {len(checkins)}",
            *[
                "  "
                f"{format_ts(checkin.created_at)} - "
                f"{CHECKIN_STATE_LABELS.get(checkin.state, checkin.state)}"
                for checkin in checkins[:5]
            ],
        ]
        self.detail.setPlainText("\n".join(lines))

    def _selected_item(self) -> DesktopAssignmentItem | None:
        rows = self.assignment_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def _create_assignment(self) -> None:
        dialog = AssignmentTargetOperatorDialog(self._core, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        target, operator = dialog.selection()
        try:
            if target.kind == "sitrep":
                self._core.command(
                    "sitreps.assign_followup",
                    {
                        "sitrep_id": target.id,
                        "assigned_to": operator.callsign,
                        "note": f"Assigned from Assignment Board to {operator.callsign}.",
                    },
                )
            else:
                message_dialog = MissionAssignmentMessageDialog(
                    target,
                    operator,
                    parent=self,
                )
                if message_dialog.exec() != QtWidgets.QDialog.Accepted:
                    return
                self._core.command(
                    "assignments.create",
                    {
                        "assignment_type": "custom",
                        "title": target.title,
                        "mission_id": target.id,
                        "status": "planned",
                        "priority": target.priority,
                        "assigned_operator_ids": [operator.id],
                        "team_lead": operator.callsign,
                        "handoff_notes": message_dialog.message_text(),
                    },
                )
                if message_dialog.should_send_message():
                    self._send_direct_assignment_message(
                        operator_id=operator.id,
                        body=message_dialog.message_text(),
                    )
            self.refresh()
        except Exception as exc:
            _log.warning("Assignment create failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Assignment", str(exc))

    def _send_direct_assignment_message(self, *, operator_id: int, body: str) -> None:
        current = self._core.read_model("chat.current_operator")
        if int(current["id"]) == int(operator_id):
            return
        dm_result = self._core.command(
            "chat.get_or_create_dm",
            {
                "operator_a_id": int(current["id"]),
                "operator_b_id": int(operator_id),
            },
        )
        channel = getattr(dm_result, "channel", None)
        channel_id = int(getattr(channel, "id"))
        self._core.command(
            "chat.send_message",
            {
                "channel_id": channel_id,
                "body": body,
                "is_urgent": False,
            },
        )

    def _create_checkin(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        dialog = CheckInDialog(
            item,
            parent=self,
            operators=self._server_checkin_operators() if self._core.mode == "server" else (),
            allow_operator_choice=self._core.mode == "server",
        )
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            self._core.command("assignments.checkin", dialog.payload())
            self.refresh()
        except Exception as exc:
            _log.warning("Check-in failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Check-In", str(exc))

    def _server_checkin_operators(self) -> list[object]:
        if self._core.mode != "server":
            return []
        try:
            return [
                operator
                for operator in self._core.read_model("operators.list")
                if not bool(getattr(operator, "revoked", False))
            ]
        except Exception as exc:
            _log.warning("Could not load operators for server check-in: %s", exc)
            return []

    def _close_assignment(self, status: typing.Literal["completed", "aborted"]) -> None:
        item = self._selected_item()
        if self._core.mode != "server" or item is None:
            return
        if item.status in {"completed", "aborted"}:
            return
        label = "complete" if status == "completed" else "abort"
        response = QtWidgets.QMessageBox.question(
            self,
            "Close Assignment" if status == "completed" else "Abort Assignment",
            (
                f"{label.title()} {item.title}? "
                "Assigned operators will be available for reassignment."
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return
        try:
            self._core.command(
                "assignments.update_status",
                {"assignment_id": item.id, "status": status},
            )
            self.refresh()
        except Exception as exc:
            _log.warning("Assignment closeout failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Assignment", str(exc))

    def _acknowledge_latest_checkin(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        try:
            detail = self._core.read_model("assignments.detail", {"assignment_id": item.id})
            checkins = [
                checkin for checkin in detail.get("checkins", [])
                if checkin.acknowledged_at is None
            ]
            if not checkins:
                self.detail.setPlainText(self.detail.toPlainText() + "\n\nNo unacknowledged check-ins.")
                return
            self._core.command(
                "assignments.acknowledge_checkin",
                {"checkin_id": checkins[0].id, "assignment_id": item.id},
            )
            self.refresh()
        except Exception as exc:
            _log.warning("Check-in acknowledgement failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Acknowledge", str(exc))


class AssignmentTargetOperatorDialog(QtWidgets.QDialog):
    """Select an unassigned mission/SITREP target and an available operator."""

    def __init__(self, core: TalonCoreSession, parent=None) -> None:
        super().__init__(parent)
        self._core = core
        self._targets: list[AssignmentTargetItem] = []
        self._operators: list[AvailableOperatorItem] = []
        self.setWindowTitle("New Assignment")
        self.setMinimumSize(980, 620)

        self.sort_combo = QtWidgets.QComboBox()
        self.sort_combo.addItem("Priority", "priority")
        self.sort_combo.addItem("Oldest", "oldest")
        self.sort_combo.addItem("Newest", "newest")
        self.sort_combo.currentIndexChanged.connect(lambda _index: self._populate_targets())

        self.target_table = QtWidgets.QTableWidget(0, 4)
        self.target_table.setHorizontalHeaderLabels(["Target", "Type", "Priority", "Created"])
        self.target_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.target_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.target_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.target_table.verticalHeader().setVisible(False)
        self.target_table.horizontalHeader().setStretchLastSection(True)
        configure_data_table(self.target_table)
        self.target_table.itemSelectionChanged.connect(self._sync_summary)

        self.operator_table = QtWidgets.QTableWidget(0, 3)
        self.operator_table.setHorizontalHeaderLabels(["Operator", "Status", "Skills"])
        self.operator_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.operator_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.operator_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.operator_table.verticalHeader().setVisible(False)
        self.operator_table.horizontalHeader().setStretchLastSection(True)
        configure_data_table(self.operator_table)
        self.operator_table.itemSelectionChanged.connect(self._sync_summary)

        self.summary_label = QtWidgets.QLabel("")
        self.summary_label.setWordWrap(True)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        target_panel_body = QtWidgets.QWidget()
        target_panel_layout = QtWidgets.QVBoxLayout(target_panel_body)
        target_panel_layout.setContentsMargins(0, 0, 0, 0)
        target_panel_layout.addWidget(_form_row("Sort", self.sort_combo))
        target_panel_layout.addWidget(self.target_table, stretch=1)

        summary_body = QtWidgets.QWidget()
        summary_layout = QtWidgets.QVBoxLayout(summary_body)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.addWidget(self.summary_label)
        summary_layout.addStretch(1)

        columns = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        columns.addWidget(_panel("Unassigned Targets", target_panel_body))
        columns.addWidget(_panel("Unassigned Operators", self.operator_table))
        columns.addWidget(_panel("Selection Summary", summary_body))
        columns.setStretchFactor(0, 4)
        columns.setStretchFactor(1, 4)
        columns.setStretchFactor(2, 2)

        self.assign_button = QtWidgets.QPushButton("Assign and Message")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.assign_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.assign_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(columns, stretch=1)
        layout.addWidget(self.status_label)
        layout.addLayout(button_row)

        self._load()

    def selection(self) -> tuple[AssignmentTargetItem, AvailableOperatorItem]:
        target = self._selected_target()
        operator = self._selected_operator()
        if target is None:
            raise ValueError("Select an unassigned mission or SITREP.")
        if operator is None:
            raise ValueError("Select an unassigned operator.")
        return target, operator

    def accept(self) -> None:
        try:
            self.selection()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        super().accept()

    def _load(self) -> None:
        try:
            operators = self._core.read_model("operators.list")
            assignments = self._core.read_model("assignments.list", {"active_only": True})
            sitreps = self._core.read_model(
                "sitreps.list",
                {"unresolved_only": True, "limit": 500},
            )
            missions = self._core.read_model("missions.list", {"status_filter": None})
        except Exception as exc:
            _log.warning("Could not load assignment target picker: %s", exc)
            self.status_label.setText(f"Unable to load assignment choices: {exc}")
            operators = []
            assignments = []
            sitreps = []
            missions = []

        self._targets = _assignment_targets(missions, sitreps, assignments)
        self._operators = available_operator_items(
            operators,
            assignments=assignments,
            sitreps=sitreps,
            missions=missions,
        )
        self._populate_targets()
        self._populate_operators()
        self._sync_summary()

    def _populate_targets(self) -> None:
        self.target_table.setRowCount(0)
        for target in self._sorted_targets():
            row = self.target_table.rowCount()
            self.target_table.insertRow(row)
            values = [
                target.title,
                "Mission" if target.kind == "mission" else "SITREP",
                target.priority,
                format_ts(target.created_at),
            ]
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                if column == 0:
                    cell.setData(QtCore.Qt.UserRole, target.id)
                    cell.setData(QtCore.Qt.UserRole + 1, target.kind)
                    cell.setToolTip(target.subtitle)
                self.target_table.setItem(row, column, cell)
        self.target_table.resizeColumnsToContents()
        if self.target_table.rowCount():
            self.target_table.selectRow(0)

    def _populate_operators(self) -> None:
        self.operator_table.setRowCount(0)
        for operator in self._operators:
            row = self.operator_table.rowCount()
            self.operator_table.insertRow(row)
            skills = ", ".join(operator.skills[:4]) if operator.skills else "No skills listed"
            for column, value in enumerate((operator.callsign, "Available", skills)):
                cell = QtWidgets.QTableWidgetItem(value)
                if column == 0:
                    cell.setData(QtCore.Qt.UserRole, operator.id)
                self.operator_table.setItem(row, column, cell)
        self.operator_table.resizeColumnsToContents()
        if self.operator_table.rowCount():
            self.operator_table.selectRow(0)

    def _sorted_targets(self) -> list[AssignmentTargetItem]:
        mode = str(self.sort_combo.currentData() or "priority")
        if mode == "oldest":
            return sorted(self._targets, key=lambda item: (item.created_at, item.id))
        if mode == "newest":
            return sorted(self._targets, key=lambda item: (-item.created_at, -item.id))
        return sorted(
            self._targets,
            key=lambda item: (
                _PRIORITY_RANK.get(item.priority, 99),
                item.created_at,
                item.id,
            ),
        )

    def _selected_target(self) -> AssignmentTargetItem | None:
        rows = self.target_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        id_item = self.target_table.item(row, 0)
        if id_item is None:
            return None
        target_id = int(id_item.data(QtCore.Qt.UserRole))
        kind = str(id_item.data(QtCore.Qt.UserRole + 1))
        return next(
            (
                target for target in self._targets
                if target.id == target_id and target.kind == kind
            ),
            None,
        )

    def _selected_operator(self) -> AvailableOperatorItem | None:
        rows = self.operator_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        id_item = self.operator_table.item(row, 0)
        if id_item is None:
            return None
        operator_id = int(id_item.data(QtCore.Qt.UserRole))
        return next(
            (operator for operator in self._operators if operator.id == operator_id),
            None,
        )

    def _sync_summary(self) -> None:
        target = self._selected_target()
        operator = self._selected_operator()
        if target is None or operator is None:
            self.summary_label.setText(
                "Select one unassigned target and one available operator."
            )
            self.assign_button.setEnabled(False)
            return
        action = "Assign and Message" if target.kind == "mission" else "Assign SITREP"
        self.assign_button.setText(action)
        self.assign_button.setEnabled(True)
        self.summary_label.setText(
            f"Target: {target.title}\n"
            f"Type: {'Mission' if target.kind == 'mission' else 'SITREP'}\n"
            f"Priority: {target.priority}\n\n"
            f"Operator: {operator.callsign}\n"
            f"Skills: {', '.join(operator.skills[:4]) if operator.skills else 'No skills listed'}"
        )


class MissionAssignmentMessageDialog(QtWidgets.QDialog):
    """Optional direct-message step before confirming a mission assignment."""

    def __init__(
        self,
        target: AssignmentTargetItem,
        operator: AvailableOperatorItem,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._send_message = True
        self.setWindowTitle("Message Operator Before Mission Assignment")
        self.setMinimumSize(760, 420)
        self.message_field = QtWidgets.QTextEdit()
        self.message_field.setAcceptRichText(False)
        self.message_field.setPlainText(
            f"You are assigned to {target.title}. Review mission details and acknowledge."
        )
        self.message_field.setMinimumHeight(150)
        summary = QtWidgets.QLabel(
            f"Mission: {target.title}\n"
            f"Operator: {operator.callsign}\n"
            f"Priority: {target.priority}\n"
            f"{target.subtitle}"
        )
        summary.setWordWrap(True)

        self.back_button = QtWidgets.QPushButton("Back")
        self.assign_only_button = QtWidgets.QPushButton("Assign Without Message")
        self.send_button = QtWidgets.QPushButton("Send Message and Assign")
        self.back_button.clicked.connect(self.reject)
        self.assign_only_button.clicked.connect(self._assign_without_message)
        self.send_button.clicked.connect(self._send_and_assign)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.back_button)
        buttons.addWidget(self.assign_only_button)
        buttons.addWidget(self.send_button)

        form = QtWidgets.QFormLayout()
        form.addRow("Mission Context", summary)
        form.addRow("Direct Message", self.message_field)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def message_text(self) -> str:
        return self.message_field.toPlainText().strip()

    def should_send_message(self) -> bool:
        return self._send_message and bool(self.message_text())

    def _assign_without_message(self) -> None:
        self._send_message = False
        super().accept()

    def _send_and_assign(self) -> None:
        self._send_message = True
        if not self.message_text():
            self.message_field.setFocus()
            return
        super().accept()


class AssignmentCreateDialog(QtWidgets.QDialog):
    def __init__(self, core: TalonCoreSession, parent=None) -> None:
        super().__init__(parent)
        self._core = core
        self.setWindowTitle("New Assignment")
        self.resize(620, 620)

        self.type_combo = QtWidgets.QComboBox()
        for key in ASSIGNMENT_TYPES:
            self.type_combo.addItem(ASSIGNMENT_TYPE_LABELS[key], key)
        self.priority_combo = QtWidgets.QComboBox()
        for level in SITREP_LEVELS:
            self.priority_combo.addItem(level, level)
        self.status_combo = QtWidgets.QComboBox()
        for status in ASSIGNMENT_STATUSES:
            self.status_combo.addItem(ASSIGNMENT_STATUS_LABELS[status], status)

        self.title_field = QtWidgets.QLineEdit()
        self.protected_field = QtWidgets.QLineEdit()
        self.location_field = QtWidgets.QLineEdit()
        self.location_point_field = QtWidgets.QLineEdit()
        self.location_point_field.setReadOnly(True)
        self.precision_field = QtWidgets.QComboBox()
        self.precision_field.addItems(["general", "exact"])
        self.reason_field = QtWidgets.QLineEdit()
        self.consent_field = QtWidgets.QLineEdit()
        self.lead_field = QtWidgets.QLineEdit()
        self.backup_field = QtWidgets.QLineEdit()
        self.escalation_field = QtWidgets.QLineEdit()
        self.shift_start_field = QtWidgets.QLineEdit()
        self.shift_end_field = QtWidgets.QLineEdit()
        self.interval_spin = QtWidgets.QSpinBox()
        self.interval_spin.setRange(1, 240)
        self.interval_spin.setValue(20)
        self.threshold_spin = QtWidgets.QSpinBox()
        self.threshold_spin.setRange(1, 120)
        self.threshold_spin.setValue(5)
        self.handoff_field = QtWidgets.QTextEdit()
        self.handoff_field.setMinimumHeight(70)
        self.risk_field = QtWidgets.QTextEdit()
        self.risk_field.setMinimumHeight(70)
        self.operator_list = QtWidgets.QListWidget()
        self.operator_list.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.operator_list.setMinimumHeight(120)
        self.skill_list = QtWidgets.QListWidget()
        self.skill_list.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.skill_list.setMinimumHeight(90)
        for skill in PREDEFINED_SKILLS:
            self.skill_list.addItem(skill)
        self.mission_combo = QtWidgets.QComboBox()
        self.mission_combo.addItem("None", None)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self._load_selectors()

        form = QtWidgets.QFormLayout()
        form.addRow("Type", self.type_combo)
        form.addRow("Title", self.title_field)
        form.addRow("Status", self.status_combo)
        form.addRow("Priority", self.priority_combo)
        form.addRow("Mission", self.mission_combo)
        form.addRow("Protected label", self.protected_field)
        form.addRow("Location label", self.location_field)
        form.addRow("Map point", self._location_point_row())
        form.addRow("Location precision", self.precision_field)
        form.addRow("Support reason", self.reason_field)
        form.addRow("Consent/source", self.consent_field)
        form.addRow("Assigned operators", self.operator_list)
        form.addRow("Lead", self.lead_field)
        form.addRow("Backup", self.backup_field)
        form.addRow("Escalation contact", self.escalation_field)
        form.addRow("Required skills", self.skill_list)
        form.addRow("Shift start", self.shift_start_field)
        form.addRow("Shift end", self.shift_end_field)
        form.addRow("Check-in interval", self.interval_spin)
        form.addRow("Overdue threshold", self.threshold_spin)
        form.addRow("Handoff notes", self.handoff_field)
        form.addRow("Risk notes", self.risk_field)
        form.addRow("", self.status_label)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        scroll_body = QtWidgets.QWidget()
        scroll_body.setLayout(form)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(scroll_body)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(buttons)

    def payload(self) -> dict[str, object]:
        lat_text, lon_text = _coordinate_parts(self.location_point_field.text())
        return build_assignment_payload(
            assignment_type=str(self.type_combo.currentData()),
            title=self.title_field.text(),
            status=str(self.status_combo.currentData()),
            priority=str(self.priority_combo.currentData()),
            protected_label=self.protected_field.text(),
            location_label=self.location_field.text(),
            location_precision=self.precision_field.currentText(),
            support_reason=self.reason_field.text(),
            consent_source=self.consent_field.text(),
            assigned_operator_ids=[
                int(item.data(QtCore.Qt.UserRole))
                for item in self.operator_list.selectedItems()
            ],
            team_lead=self.lead_field.text(),
            backup_operator=self.backup_field.text(),
            escalation_contact=self.escalation_field.text(),
            required_skills=[item.text() for item in self.skill_list.selectedItems()],
            shift_start=self.shift_start_field.text(),
            shift_end=self.shift_end_field.text(),
            checkin_interval_min=self.interval_spin.value(),
            overdue_threshold_min=self.threshold_spin.value(),
            handoff_notes=self.handoff_field.toPlainText(),
            risk_notes=self.risk_field.toPlainText(),
            mission_id=self._combo_int(self.mission_combo),
            lat_text=lat_text,
            lon_text=lon_text,
        )

    def accept(self) -> None:
        try:
            self.payload()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        super().accept()

    def _load_selectors(self) -> None:
        try:
            for operator in self._core.read_model("operators.list", {"include_sentinel": True}):
                if getattr(operator, "revoked", False):
                    continue
                item = QtWidgets.QListWidgetItem(str(getattr(operator, "callsign", "")))
                item.setData(QtCore.Qt.UserRole, int(getattr(operator, "id")))
                self.operator_list.addItem(item)
            for mission in self._core.read_model("missions.list", {"status_filter": None}):
                if getattr(mission, "status", "") in {"completed", "aborted", "rejected"}:
                    continue
                self.mission_combo.addItem(str(getattr(mission, "title", "")), int(mission.id))
        except Exception as exc:
            _log.warning("Could not load assignment dialog selectors: %s", exc)

    def _location_point_row(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        pick_button = QtWidgets.QPushButton("Pick on Map")
        clear_button = QtWidgets.QPushButton("Clear")
        pick_button.clicked.connect(self._pick_location)
        clear_button.clicked.connect(self.location_point_field.clear)
        layout.addWidget(self.location_point_field, stretch=1)
        layout.addWidget(pick_button)
        layout.addWidget(clear_button)
        return container

    def _pick_location(self) -> None:
        try:
            lat_text, lon_text = _coordinate_parts(self.location_point_field.text())
            initial_lat = float(lat_text) if lat_text else None
            initial_lon = float(lon_text) if lon_text else None
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        selected = pick_point_on_map(
            core=self._core,
            title=self.location_field.text().strip() or "Assignment Location",
            initial_lat=initial_lat,
            initial_lon=initial_lon,
            parent=self,
        )
        if selected is None:
            return
        self.location_point_field.setText(format_coordinate(*selected))
        precision_index = self.precision_field.findText("exact")
        if precision_index >= 0:
            self.precision_field.setCurrentIndex(precision_index)
        self.status_label.clear()

    @staticmethod
    def _combo_int(combo: QtWidgets.QComboBox) -> int | None:
        value = combo.currentData()
        return int(value) if value is not None else None


class CheckInDialog(QtWidgets.QDialog):
    def __init__(
        self,
        assignment: DesktopAssignmentItem,
        parent=None,
        *,
        operators: typing.Iterable[object] = (),
        allow_operator_choice: bool = False,
    ) -> None:
        super().__init__(parent)
        self._assignment = assignment
        self._allow_operator_choice = allow_operator_choice
        self.setWindowTitle("Assignment Check-In")
        self.operator_combo = QtWidgets.QComboBox()
        self.operator_combo.setVisible(allow_operator_choice)
        if allow_operator_choice:
            self._load_operator_choices(operators)
        self.state_combo = QtWidgets.QComboBox()
        for state in CHECKIN_STATES:
            self.state_combo.addItem(CHECKIN_STATE_LABELS[state], state)
        self.note_field = QtWidgets.QTextEdit()
        self.note_field.setMinimumHeight(90)
        form = QtWidgets.QFormLayout()
        form.addRow("Assignment", QtWidgets.QLabel(assignment.title))
        if allow_operator_choice:
            form.addRow("Operator", self.operator_combo)
        form.addRow("State", self.state_combo)
        form.addRow("Note", self.note_field)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def payload(self) -> dict[str, object]:
        payload = build_checkin_payload(
            assignment_id=self._assignment.id,
            state=str(self.state_combo.currentData()),
            note=self.note_field.toPlainText(),
        )
        if self._allow_operator_choice:
            operator_id = self.operator_combo.currentData()
            if operator_id is None:
                raise ValueError("Operator is required for server check-in.")
            payload["operator_id"] = int(operator_id)
        return payload

    def _load_operator_choices(self, operators: typing.Iterable[object]) -> None:
        assigned = set(self._assignment.assigned_operator_ids)
        first_assigned_index = -1
        for operator in operators:
            try:
                operator_id = int(getattr(operator, "id"))
            except (TypeError, ValueError):
                continue
            callsign = str(getattr(operator, "callsign", "") or f"#{operator_id}")
            self.operator_combo.addItem(callsign, operator_id)
            if operator_id in assigned and first_assigned_index < 0:
                first_assigned_index = self.operator_combo.count() - 1
        if first_assigned_index >= 0:
            self.operator_combo.setCurrentIndex(first_assigned_index)


def _coordinate_parts(text: str) -> tuple[str, str]:
    raw = text.strip()
    if not raw:
        return "", ""
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Assignment map point must be latitude, longitude.")
    return parts[0], parts[1]


def _assignment_targets(
    missions: typing.Iterable[object],
    sitreps: typing.Iterable[object],
    assignments: typing.Iterable[object],
) -> list[AssignmentTargetItem]:
    assigned_mission_ids: set[int] = set()
    for assignment in assignments:
        mission_id = getattr(assignment, "mission_id", None)
        if mission_id is None:
            continue
        if getattr(assignment, "status", "") in {"completed", "aborted"}:
            continue
        if getattr(assignment, "assigned_operator_ids", []) or []:
            assigned_mission_ids.add(int(mission_id))

    targets: list[AssignmentTargetItem] = []
    for mission in missions:
        status = str(getattr(mission, "status", "") or "")
        mission_id = int(getattr(mission, "id"))
        if status in {"completed", "aborted", "rejected"}:
            continue
        if mission_id in assigned_mission_ids:
            continue
        if mission_operator_callsigns(mission):
            continue
        priority = str(getattr(mission, "priority", "ROUTINE") or "ROUTINE")
        mission_type = str(getattr(mission, "mission_type", "") or "")
        created_at = int(getattr(mission, "created_at", 0) or 0)
        targets.append(
            AssignmentTargetItem(
                kind="mission",
                id=mission_id,
                title=str(getattr(mission, "title", "") or f"Mission #{mission_id}"),
                priority=priority,
                created_at=created_at,
                subtitle=(
                    f"{mission_type or 'Mission'} | "
                    f"created {_age_label(created_at)} | no assigned operators"
                ),
                mission_type=mission_type,
            )
        )

    for entry in sitreps:
        item = feed_item_from_entry(entry)
        if item.status in {"resolved", "closed"}:
            continue
        if item.assigned_to.strip():
            continue
        title = item.body.splitlines()[0].strip() if item.body.strip() else ""
        if not title:
            title = f"{item.level} SITREP #{item.id}"
        if len(title) > 80:
            title = title[:77].rstrip() + "..."
        targets.append(
            AssignmentTargetItem(
                kind="sitrep",
                id=item.id,
                title=title,
                priority=item.level,
                created_at=item.created_at,
                subtitle=(
                    f"{item.level} | created {_age_label(item.created_at)} | "
                    f"{item.location_label or 'no location label'}"
                ),
            )
        )
    return targets


def _age_label(created_at: int) -> str:
    if created_at <= 0:
        return "unknown"
    seconds = max(0, int(time.time()) - int(created_at))
    minutes = seconds // 60
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hr ago"
    return format_ts(created_at)


class _MetricBox(QtWidgets.QFrame):
    def __init__(self, title: str, value: str, subtitle: str) -> None:
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumHeight(76)
        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("sideMode")
        self.value = QtWidgets.QLabel(value)
        self.value.setObjectName("sectionHeading")
        self.subtitle = QtWidgets.QLabel(subtitle)
        self.subtitle.setWordWrap(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.subtitle)

    def set_values(self, value: str, subtitle: str) -> None:
        self.value.setText(value)
        self.subtitle.setText(subtitle)


def _panel(title: str, widget: QtWidgets.QWidget) -> QtWidgets.QFrame:
    frame = QtWidgets.QFrame()
    frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
    layout = QtWidgets.QVBoxLayout(frame)
    layout.setContentsMargins(8, 8, 8, 8)
    heading = QtWidgets.QLabel(title)
    heading.setObjectName("sectionHeading")
    layout.addWidget(heading)
    layout.addWidget(widget, stretch=1)
    return frame


def _form_row(label: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
    container = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    caption = QtWidgets.QLabel(label)
    caption.setObjectName("sideMode")
    layout.addWidget(caption)
    layout.addWidget(widget, stretch=1)
    return container

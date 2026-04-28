"""PySide6 operator and server-admin pages."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from talon_core import TalonCoreSession
from talon_core.utils.logging import get_logger
from talon_desktop.operators import (
    DesktopAuditEntryItem,
    DesktopEnrollmentTokenItem,
    DesktopOperatorItem,
    build_operator_update_payload,
    can_edit_operator,
    can_renew_operator,
    can_revoke_operator,
    items_from_audit_entries,
    items_from_enrollment_tokens,
    items_from_operators,
    predefined_skill_set,
)
from talon_desktop.theme import configure_data_table

_log = get_logger("desktop.operators")


class OperatorProfileDialog(QtWidgets.QDialog):
    """Profile and skills editor for an operator."""

    def __init__(
        self,
        item: DesktopOperatorItem,
        *,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._item = item
        self._skill_checks: dict[str, QtWidgets.QCheckBox] = {}
        self.setWindowTitle(f"Operator {item.callsign}")
        self.setMinimumWidth(520)

        self.display_name_field = QtWidgets.QLineEdit(item.display_name)
        self.role_field = QtWidgets.QLineEdit(item.role)
        self.notes_field = QtWidgets.QPlainTextEdit(item.notes)
        self.notes_field.setFixedHeight(96)

        skills_group = QtWidgets.QGroupBox("Skills")
        skills_layout = QtWidgets.QGridLayout(skills_group)
        selected = set(item.skills)
        for index, skill in enumerate(predefined_skill_set()):
            checkbox = QtWidgets.QCheckBox(skill)
            checkbox.setChecked(skill in selected)
            self._skill_checks[skill] = checkbox
            skills_layout.addWidget(checkbox, index // 3, index % 3)

        self.custom_skills_list = QtWidgets.QListWidget()
        self.custom_skills_list.setFixedHeight(92)
        for skill in item.skills:
            if skill not in predefined_skill_set():
                self.custom_skills_list.addItem(skill)
        self.custom_skill_input = QtWidgets.QLineEdit()
        self.custom_skill_input.setPlaceholderText("Custom skill")
        add_skill_button = QtWidgets.QPushButton("Add")
        remove_skill_button = QtWidgets.QPushButton("Remove")
        add_skill_button.clicked.connect(self._add_custom_skill)
        remove_skill_button.clicked.connect(self._remove_custom_skill)
        custom_skill_widget = QtWidgets.QWidget()
        custom_skill_layout = QtWidgets.QVBoxLayout(custom_skill_widget)
        custom_skill_layout.setContentsMargins(0, 0, 0, 0)
        custom_skill_row = QtWidgets.QHBoxLayout()
        custom_skill_row.addWidget(self.custom_skill_input, stretch=1)
        custom_skill_row.addWidget(add_skill_button)
        custom_skill_row.addWidget(remove_skill_button)
        custom_skill_layout.addWidget(self.custom_skills_list)
        custom_skill_layout.addLayout(custom_skill_row)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        save_button = QtWidgets.QPushButton("Save")
        cancel_button = QtWidgets.QPushButton("Cancel")
        save_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)

        form = QtWidgets.QFormLayout()
        form.addRow("Display Name", self.display_name_field)
        form.addRow("Role", self.role_field)
        form.addRow("Notes", self.notes_field)
        form.addRow(skills_group)
        form.addRow("Custom Skills", custom_skill_widget)
        form.addRow("", self.status_label)
        form.addRow("", button_row)
        self.setLayout(form)

    def payload(self) -> dict[str, object]:
        return build_operator_update_payload(
            operator_id=self._item.id,
            display_name=self.display_name_field.text(),
            role=self.role_field.text(),
            notes=self.notes_field.toPlainText(),
            selected_skills=[
                skill for skill, checkbox in self._skill_checks.items()
                if checkbox.isChecked()
            ],
            custom_skills_text=self._custom_skills_text(),
        )

    def accept(self) -> None:
        try:
            self.payload()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        super().accept()

    def _add_custom_skill(self) -> None:
        value = self.custom_skill_input.text().strip().lower()
        if not value:
            return
        existing = {
            self.custom_skills_list.item(row).text()
            for row in range(self.custom_skills_list.count())
        }
        if value not in existing:
            self.custom_skills_list.addItem(value)
        self.custom_skill_input.clear()

    def _remove_custom_skill(self) -> None:
        row = self.custom_skills_list.currentRow()
        if row >= 0:
            self.custom_skills_list.takeItem(row)

    def _custom_skills_text(self) -> str:
        values = [
            self.custom_skills_list.item(row).text()
            for row in range(self.custom_skills_list.count())
        ]
        pending = self.custom_skill_input.text().strip()
        if pending:
            values.append(pending)
        return ", ".join(values)


class OperatorPage(QtWidgets.QWidget):
    """Operator list/profile page with optional server admin controls."""

    def __init__(
        self,
        core: TalonCoreSession,
        *,
        title: str = "Operators",
        admin: bool = False,
    ) -> None:
        super().__init__()
        self._core = core
        self._title = title
        self._admin = admin
        self._items: list[DesktopOperatorItem] = []

        self.heading = QtWidgets.QLabel(title)
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.edit_button = QtWidgets.QPushButton("Edit Profile")
        self.edit_button.clicked.connect(self._edit_selected)
        self.renew_button = QtWidgets.QPushButton("Renew Lease")
        self.renew_button.clicked.connect(self._renew_selected)
        self.revoke_button = QtWidgets.QPushButton("Revoke")
        self.revoke_button.clicked.connect(self._revoke_selected)
        for button in (self.renew_button, self.revoke_button):
            button.setVisible(self._core.mode == "server")

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.refresh_button)
        top_row.addWidget(self.edit_button)
        top_row.addWidget(self.renew_button)
        top_row.addWidget(self.revoke_button)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Callsign", "Status", "Role", "Skills", "Lease"]
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
        layout.addWidget(self.status_label)

    def refresh(self) -> None:
        try:
            operators = self._core.read_model("operators.list")
            self._items = items_from_operators(operators)
        except Exception as exc:
            _log.warning("Could not refresh operators: %s", exc)
            self.status_label.setText(f"Unable to load operators: {exc}")
            return

        self.table.setRowCount(0)
        for item in self._items:
            self._add_row(item)
        active = sum(1 for item in self._items if item.status == "active")
        locked = sum(1 for item in self._items if item.status == "locked")
        revoked = sum(1 for item in self._items if item.revoked)
        self.summary.setText(
            f"{len(self._items)} operator(s), {active} active, "
            f"{locked} locked, {revoked} revoked."
        )
        if self._items:
            self.table.selectRow(0)
        else:
            self.detail.clear()
        self._selection_changed()

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        _ = action, record_id
        if table == "operators":
            self.refresh()

    def _add_row(self, item: DesktopOperatorItem) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            str(item.id),
            item.callsign,
            item.status_label,
            item.role,
            item.skills_label,
            item.lease_label,
        ]
        for column, value in enumerate(values):
            cell = QtWidgets.QTableWidgetItem(value)
            if column == 0:
                cell.setData(QtCore.Qt.UserRole, item.id)
            if item.revoked:
                cell.setForeground(QtGui.QColor("#ff5555"))
            elif item.status == "locked":
                cell.setForeground(QtGui.QColor("#f0c674"))
            self.table.setItem(row, column, cell)

    def _selected_item(self) -> DesktopOperatorItem | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def _selection_changed(self) -> None:
        item = self._selected_item()
        current_id = self._core.operator_id
        self.edit_button.setEnabled(
            can_edit_operator(
                mode=self._core.mode,
                current_operator_id=current_id,
                item=item,
            )
        )
        self.renew_button.setEnabled(can_renew_operator(self._core.mode, item))
        self.revoke_button.setEnabled(can_revoke_operator(self._core.mode, item))
        if item is None:
            return
        self.detail.setPlainText(self._detail_text(item))

    def _edit_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        current_id = self._core.operator_id
        if not can_edit_operator(
            mode=self._core.mode,
            current_operator_id=current_id,
            item=item,
        ):
            self.status_label.setText("Current operator cannot edit this profile.")
            return
        dialog = OperatorProfileDialog(item, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            self._core.command("operators.update", dialog.payload())
        except Exception as exc:
            _log.warning("Operator update failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Operator", str(exc))
            return
        self.status_label.setText("Operator updated.")
        self.refresh()

    def _renew_selected(self) -> None:
        item = self._selected_item()
        if not can_renew_operator(self._core.mode, item):
            return
        try:
            result = self._core.command("operators.renew_lease", operator_id=item.id)
        except Exception as exc:
            _log.warning("Lease renewal failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Lease Renewal", str(exc))
            return
        expiry = getattr(result, "lease_expires_at", None)
        self.status_label.setText(
            f"Lease renewed for {item.callsign}."
            + (f" New expiry: {expiry}." if expiry else "")
        )
        self.refresh()

    def _revoke_selected(self) -> None:
        item = self._selected_item()
        if not can_revoke_operator(self._core.mode, item):
            return
        if (
            QtWidgets.QMessageBox.question(
                self,
                "Revoke Operator",
                f"Permanently revoke {item.callsign}?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            != QtWidgets.QMessageBox.Yes
        ):
            return
        try:
            self._core.command("operators.revoke", operator_id=item.id)
        except Exception as exc:
            _log.warning("Operator revoke failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Revoke Operator", str(exc))
            return
        self.status_label.setText(f"Operator {item.callsign} revoked.")
        self.refresh()

    @staticmethod
    def _detail_text(item: DesktopOperatorItem) -> str:
        lines = [
            f"#{item.id} {item.callsign}",
            f"Display name: {item.display_name or '-'}",
            f"Role: {item.role or '-'}",
            f"Status: {item.status_label}",
            f"Enrolled: {item.enrolled_label}",
            f"Lease expires: {item.lease_label}",
            f"Skills: {item.skills_label}",
            f"RNS hash: {item.rns_hash}",
        ]
        if item.notes:
            lines.extend(("", item.notes))
        return "\n".join(lines)


class EnrollmentPage(QtWidgets.QWidget):
    """Server enrollment token generator and pending-token list."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._items: list[DesktopEnrollmentTokenItem] = []

        self.heading = QtWidgets.QLabel("Enrollment")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self.token_field = QtWidgets.QLineEdit()
        self.token_field.setReadOnly(True)
        self.server_hash_field = QtWidgets.QLineEdit()
        self.server_hash_field.setReadOnly(True)

        self.generate_button = QtWidgets.QPushButton("Generate Token")
        self.generate_button.clicked.connect(self._generate_token)
        self.copy_button = QtWidgets.QPushButton("Copy")
        self.copy_button.clicked.connect(self._copy_token)
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        token_row = QtWidgets.QHBoxLayout()
        token_row.addWidget(self.token_field, stretch=1)
        token_row.addWidget(self.copy_button)

        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(self.heading)
        action_row.addStretch(1)
        action_row.addWidget(self.refresh_button)
        action_row.addWidget(self.generate_button)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Token", "Created", "Expires", "Remaining"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        configure_data_table(self.table)

        form = QtWidgets.QFormLayout()
        form.addRow("Generated Token", token_row)
        form.addRow("Server Hash", self.server_hash_field)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(action_row)
        layout.addWidget(self.summary)
        layout.addLayout(form)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.status_label)

    def refresh(self) -> None:
        try:
            self.server_hash_field.setText(self._core.read_model("enrollment.server_hash") or "")
            self._items = items_from_enrollment_tokens(
                self._core.read_model("enrollment.pending_tokens")
            )
        except Exception as exc:
            _log.warning("Could not refresh enrollment: %s", exc)
            self.status_label.setText(f"Unable to load enrollment: {exc}")
            return
        self.table.setRowCount(0)
        for item in self._items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [item.token_preview, item.created_label, item.expires_label, item.remaining_label]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QtWidgets.QTableWidgetItem(value))
        self.summary.setText(f"{len(self._items)} pending token(s).")

    def _generate_token(self) -> None:
        try:
            result = self._core.command("enrollment.generate_token")
        except Exception as exc:
            _log.warning("Token generation failed: %s", exc)
            self.status_label.setText(f"Token generation failed: {exc}")
            return
        self.token_field.setText(str(getattr(result, "combined", "")))
        self.status_label.setText("Enrollment token generated.")
        self.refresh()

    def _copy_token(self) -> None:
        text = self.token_field.text().strip()
        if not text:
            self.status_label.setText("No generated token to copy.")
            return
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        self.status_label.setText("Token copied.")
        QtCore.QTimer.singleShot(3000, self.status_label.clear)


class AuditPage(QtWidgets.QWidget):
    """Encrypted server audit log viewer."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._items: list[DesktopAuditEntryItem] = []

        self.heading = QtWidgets.QLabel("Audit")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self.filter_field = QtWidgets.QLineEdit()
        self.filter_field.setPlaceholderText("Event filter")
        self.search_button = QtWidgets.QPushButton("Search")
        self.search_button.clicked.connect(self.refresh)
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear_filter)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.filter_field)
        top_row.addWidget(self.search_button)
        top_row.addWidget(self.clear_button)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "Occurred", "Event", "Payload"])
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
        layout.addWidget(self.status_label)

    def refresh(self) -> None:
        filters: dict[str, object] = {"limit": 200}
        event_filter = self.filter_field.text().strip()
        if event_filter:
            filters["event_filter"] = event_filter
        try:
            self._items = items_from_audit_entries(
                self._core.read_model("audit.list", filters)
            )
        except Exception as exc:
            _log.warning("Could not refresh audit log: %s", exc)
            self.status_label.setText(f"Unable to load audit log: {exc}")
            return
        self.table.setRowCount(0)
        for item in self._items:
            self._add_audit_row(item)
        self.summary.setText(f"{len(self._items)} audit entrie(s).")
        if self._items:
            self.table.selectRow(0)
        else:
            self.detail.clear()

    def _add_audit_row(self, item: DesktopAuditEntryItem) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [str(item.id), item.occurred_label, item.event, item.payload_label]
        for column, value in enumerate(values):
            cell = QtWidgets.QTableWidgetItem(value)
            if column == 0:
                cell.setData(QtCore.Qt.UserRole, item.id)
            cell.setForeground(_audit_color(item.severity))
            self.table.setItem(row, column, cell)

    def _selection_changed(self) -> None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return
        row = selected[0].row()
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        payload_lines = [f"{key}: {value}" for key, value in sorted(item.payload.items())]
        self.detail.setPlainText(
            "\n".join(
                [
                    f"#{item.id} {item.event}",
                    f"Occurred: {item.occurred_label}",
                    "",
                    *payload_lines,
                ]
            )
        )

    def _clear_filter(self) -> None:
        self.filter_field.clear()
        self.refresh()


class KeysPage(QtWidgets.QWidget):
    """Server identity and revocation status page."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._items: list[DesktopOperatorItem] = []

        self.heading = QtWidgets.QLabel("Keys")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self.server_hash_field = QtWidgets.QLineEdit()
        self.server_hash_field.setReadOnly(True)
        self.identity_status_field = QtWidgets.QLineEdit()
        self.identity_status_field.setReadOnly(True)
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.rotate_button = QtWidgets.QPushButton("Rotate Group Key")
        self.rotate_button.clicked.connect(self._show_rotation_status)
        self.revoke_button = QtWidgets.QPushButton("Revoke")
        self.revoke_button.clicked.connect(self._revoke_selected)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.refresh_button)
        top_row.addWidget(self.rotate_button)
        top_row.addWidget(self.revoke_button)

        form = QtWidgets.QFormLayout()
        form.addRow("Server Hash", self.server_hash_field)
        form.addRow("Identity Status", self.identity_status_field)

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "Callsign", "Status"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        configure_data_table(self.table)
        self.table.itemSelectionChanged.connect(self._selection_changed)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self.summary)
        layout.addLayout(form)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.status_label)

    def refresh(self) -> None:
        try:
            server_hash = self._core.read_model("enrollment.server_hash") or ""
            sync_status = self._core.read_model("sync.status")
            self._items = items_from_operators(self._core.read_model("operators.list"))
        except Exception as exc:
            _log.warning("Could not refresh key status: %s", exc)
            self.status_label.setText(f"Unable to load key status: {exc}")
            return
        self.server_hash_field.setText(server_hash or "Not initialized.")
        self.identity_status_field.setText(
            "Reticulum started" if sync_status.reticulum_started else "Reticulum stopped"
        )
        self.table.setRowCount(0)
        for item in self._items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [str(item.id), item.callsign, item.status_label]
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                if column == 0:
                    cell.setData(QtCore.Qt.UserRole, item.id)
                self.table.setItem(row, column, cell)
        revoked = sum(1 for item in self._items if item.revoked)
        self.summary.setText(
            f"{len(self._items)} operator identity record(s), {revoked} revoked."
        )
        if self._items:
            self.table.selectRow(0)
        self._selection_changed()

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        _ = action, record_id
        if table == "operators":
            self.refresh()

    def _selected_item(self) -> DesktopOperatorItem | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def _selection_changed(self) -> None:
        self.revoke_button.setEnabled(can_revoke_operator(self._core.mode, self._selected_item()))

    def _revoke_selected(self) -> None:
        item = self._selected_item()
        if not can_revoke_operator(self._core.mode, item):
            return
        if (
            QtWidgets.QMessageBox.question(
                self,
                "Revoke Identity",
                f"Hard-revoke {item.callsign}?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            != QtWidgets.QMessageBox.Yes
        ):
            return
        try:
            self._core.command("operators.revoke", operator_id=item.id)
        except Exception as exc:
            _log.warning("Identity revoke failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Revoke Identity", str(exc))
            return
        self.status_label.setText(f"Identity revoked for {item.callsign}.")
        self.refresh()

    def _show_rotation_status(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "Group Key Rotation",
            "Group key rotation is not implemented yet. This remains a core Phase 2b item.",
        )


def _audit_color(severity: str) -> QtGui.QColor:
    return {
        "danger": QtGui.QColor("#ff5555"),
        "warning": QtGui.QColor("#f0c674"),
        "positive": QtGui.QColor("#8fbc8f"),
        "neutral": QtGui.QColor("#d8dee9"),
    }.get(severity, QtGui.QColor("#d8dee9"))

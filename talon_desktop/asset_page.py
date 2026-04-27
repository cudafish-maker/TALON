"""PySide6 asset list, detail, and command page."""
from __future__ import annotations

import typing

from PySide6 import QtCore, QtWidgets

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
from talon_desktop.theme import configure_data_table

_log = get_logger("desktop.assets")


class AssetDialog(QtWidgets.QDialog):
    """Create/edit asset dialog."""

    def __init__(
        self,
        *,
        asset: DesktopAssetItem | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._asset = asset
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
        dialog = AssetDialog(parent=self)
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
        dialog = AssetDialog(asset=item, parent=self)
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

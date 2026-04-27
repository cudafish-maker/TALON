"""PySide6 document repository page."""
from __future__ import annotations

import pathlib
import threading

from PySide6 import QtCore, QtWidgets

from talon_core import TalonCoreSession
from talon_core.utils.logging import get_logger
from talon_desktop.documents import (
    DesktopDocumentItem,
    build_upload_payload,
    can_delete_document,
    can_download_document,
    can_upload_document,
    document_error_message,
    items_from_document_entries,
)
from talon_desktop.theme import configure_data_table

_log = get_logger("desktop.documents")


class _ActionSignals(QtCore.QObject):
    succeeded = QtCore.Signal(object)
    failed = QtCore.Signal(str)


class DocumentUploadDialog(QtWidgets.QDialog):
    """File picker and description input for server document uploads."""

    def __init__(
        self,
        *,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._payload: dict[str, object] | None = None
        self.setWindowTitle("Upload Document")
        self.setMinimumWidth(560)

        self.path_field = QtWidgets.QLineEdit()
        self.path_field.setReadOnly(True)
        self.browse_button = QtWidgets.QPushButton("Browse")
        self.browse_button.clicked.connect(self._browse)

        file_row = QtWidgets.QHBoxLayout()
        file_row.addWidget(self.path_field, stretch=1)
        file_row.addWidget(self.browse_button)

        self.description_field = QtWidgets.QPlainTextEdit()
        self.description_field.setFixedHeight(86)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self.upload_button = QtWidgets.QPushButton("Upload")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.upload_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.upload_button)

        form = QtWidgets.QFormLayout()
        form.addRow("File", file_row)
        form.addRow("Description", self.description_field)
        form.addRow("", self.status_label)
        form.addRow("", button_row)
        self.setLayout(form)

    def payload(self) -> dict[str, object]:
        if self._payload is None:
            self._payload = build_upload_payload(
                self.path_field.text(),
                description=self.description_field.toPlainText(),
            )
        return self._payload

    def accept(self) -> None:
        try:
            self._payload = build_upload_payload(
                self.path_field.text(),
                description=self.description_field.toPlainText(),
            )
        except Exception as exc:
            self.status_label.setText(document_error_message(exc))
            return
        super().accept()

    def _browse(self) -> None:
        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Document",
        )
        if path:
            self._payload = None
            self.path_field.setText(path)


class DocumentPage(QtWidgets.QWidget):
    """Document list/detail page with core command wiring."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._items: list[DesktopDocumentItem] = []
        self._workers: list[_ActionSignals] = []

        self.heading = QtWidgets.QLabel("Documents")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.upload_button = QtWidgets.QPushButton("Upload")
        self.upload_button.clicked.connect(self._upload_document)
        self.upload_button.setVisible(can_upload_document(self._core.mode))
        self.download_button = QtWidgets.QPushButton("Download")
        self.download_button.clicked.connect(self._download_selected)
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.clicked.connect(self._delete_selected)
        self.delete_button.setVisible(self._core.mode == "server")

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.refresh_button)
        top_row.addWidget(self.upload_button)
        top_row.addWidget(self.download_button)
        top_row.addWidget(self.delete_button)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Filename", "Type", "Size", "Uploader", "Uploaded"]
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
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

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
            self._items = items_from_document_entries(
                self._core.read_model("documents.list")
            )
        except Exception as exc:
            _log.warning("Could not refresh documents: %s", exc)
            self.status_label.setText(f"Unable to load documents: {exc}")
            return

        self.table.setRowCount(0)
        for item in self._items:
            self._add_row(item)
        total_size = sum(item.size_bytes for item in self._items)
        macro_count = sum(1 for item in self._items if item.is_macro_risk)
        self.summary.setText(
            f"{len(self._items)} document(s), "
            f"{self._format_total_size(total_size)} total, "
            f"{macro_count} macro-risk type(s)."
        )
        if self._items:
            self.table.selectRow(0)
        else:
            self.detail.clear()
        self._selection_changed()

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        _ = action, record_id
        if table == "documents":
            self.refresh()

    def _add_row(self, item: DesktopDocumentItem) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            str(item.id),
            item.filename,
            item.mime_type,
            item.size_label,
            item.uploader_callsign,
            item.uploaded_label,
        ]
        for column, value in enumerate(values):
            cell = QtWidgets.QTableWidgetItem(value)
            if column == 0:
                cell.setData(QtCore.Qt.UserRole, item.id)
            self.table.setItem(row, column, cell)

    def _selection_changed(self) -> None:
        item = self._selected_item()
        self.download_button.setEnabled(can_download_document(item))
        self.delete_button.setEnabled(can_delete_document(self._core.mode, item))
        if item is None:
            return
        self.detail.setPlainText(self._detail_text(item))

    def _selected_item(self) -> DesktopDocumentItem | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def _upload_document(self) -> None:
        if not can_upload_document(self._core.mode):
            self.status_label.setText("Upload is available in server mode only.")
            return
        dialog = DocumentUploadDialog(parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            self._core.command("documents.upload", dialog.payload())
        except Exception as exc:
            message = document_error_message(exc)
            _log.warning("Document upload failed: %s", message)
            QtWidgets.QMessageBox.warning(self, "Upload Failed", message)
            return
        self.status_label.setText("Document uploaded.")
        self.refresh()

    def _download_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        self.status_label.setText("Downloading document...")

        signals = _ActionSignals()
        self._workers.append(signals)
        signals.succeeded.connect(self._download_ready)
        signals.failed.connect(self._download_failed)

        def _worker() -> None:
            try:
                result = self._core.command("documents.download", document_id=item.id)
                signals.succeeded.emit((item, result.plaintext))
            except Exception as exc:
                signals.failed.emit(document_error_message(exc))

        threading.Thread(
            target=_worker,
            daemon=True,
            name="talon-desktop-document-download",
        ).start()

    @QtCore.Slot(object)
    def _download_ready(self, payload: object) -> None:
        item, plaintext = payload
        item = item if isinstance(item, DesktopDocumentItem) else self._selected_item()
        if item is None:
            self.status_label.setText("Document selection changed before save.")
            return
        if item.is_macro_risk and not self._confirm_macro_risk(item):
            self.status_label.setText("Download cancelled.")
            return
        save_path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Document",
            item.filename,
        )
        if not save_path:
            self.status_label.setText("Download cancelled.")
            return
        try:
            pathlib.Path(save_path).write_bytes(bytes(plaintext))
        except OSError as exc:
            self.status_label.setText(f"Save failed: {exc}")
            return
        self.status_label.setText(f"Saved {item.filename}.")

    @QtCore.Slot(str)
    def _download_failed(self, message: str) -> None:
        self.status_label.setText(message)
        QtWidgets.QMessageBox.warning(self, "Download Failed", message)

    def _delete_selected(self) -> None:
        item = self._selected_item()
        if not can_delete_document(self._core.mode, item):
            return
        response = QtWidgets.QMessageBox.question(
            self,
            "Delete Document",
            f"Delete {item.filename}? This cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return
        try:
            self._core.command("documents.delete", document_id=item.id)
        except Exception as exc:
            message = document_error_message(exc)
            _log.warning("Document delete failed: %s", message)
            QtWidgets.QMessageBox.warning(self, "Delete Failed", message)
            return
        self.status_label.setText("Document deleted.")
        self.refresh()

    def _confirm_macro_risk(self, item: DesktopDocumentItem) -> bool:
        response = QtWidgets.QMessageBox.warning(
            self,
            "Document Security",
            (
                f"{item.filename} can contain macros or embedded scripts. "
                "Only save and open it if you trust the source."
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return response == QtWidgets.QMessageBox.Yes

    @staticmethod
    def _detail_text(item: DesktopDocumentItem) -> str:
        warning = "Macro-capable type: yes" if item.is_macro_risk else "Macro-capable type: no"
        lines = [
            f"#{item.id} {item.filename}",
            f"Type: {item.mime_type}",
            f"Size: {item.size_label}",
            f"Uploaded by: {item.uploader_callsign}",
            f"Uploaded: {item.uploaded_label}",
            f"SHA-256: {item.hash_preview}",
            warning,
        ]
        if item.description:
            lines.extend(("", item.description))
        return "\n".join(lines)

    @staticmethod
    def _format_total_size(size_bytes: int) -> str:
        from talon_desktop.documents import format_size

        return format_size(size_bytes)

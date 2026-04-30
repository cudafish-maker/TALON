"""PySide6 document repository page."""
from __future__ import annotations

import html
import pathlib
import threading

from PySide6 import QtCore, QtGui, QtWidgets

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

_DOCUMENT_ID_MIME = "application/x-talon-document-id"
_ORIGINAL_TEXT_ROLE = QtCore.Qt.UserRole + 1
_DOCUMENTS_STYLESHEET = """
QWidget#documentsExplorerPage {
    background: #171e22;
}

QFrame#documentsToolbar {
    background: #11181b;
    border-bottom: 1px solid #334047;
}

QLabel#documentsHeading {
    color: #edf3f5;
    font-size: 20px;
    font-weight: 700;
}

QPushButton#documentsButton {
    min-height: 34px;
    border: 1px solid #566973;
    background: #243139;
    color: #edf3f5;
    padding: 7px 11px;
    font-size: 13px;
    font-weight: 600;
}

QPushButton#documentsPrimaryButton {
    min-height: 34px;
    border: 1px solid #d9bd5c;
    background: #ffdf6e;
    color: #151a1d;
    padding: 7px 11px;
    font-size: 13px;
    font-weight: 700;
}

QLabel#documentsSummary {
    padding: 10px 16px;
    border-bottom: 1px solid #334047;
    background: #141b1f;
    color: #98a8ae;
    font-size: 13px;
}

QSplitter#documentsBody::handle {
    background: #334047;
    width: 1px;
}

QFrame#documentsPane {
    background: #101619;
    border-right: 1px solid #334047;
}

QWidget#documentsPaneBody {
    background: #101619;
}

QLabel#documentsPaneTitle {
    padding: 10px 12px;
    border-bottom: 1px solid #334047;
    background: #141b1f;
    color: #98a8ae;
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
}

QTreeWidget#documentFolderTree,
QTableWidget#documentFileTable,
QTextEdit#documentDetail {
    background: #101619;
    color: #edf3f5;
    border: 0;
    selection-background-color: #1b252a;
    selection-color: #edf3f5;
}

QTreeWidget#documentFolderTree::item {
    min-height: 34px;
    padding: 4px 8px;
    border: 1px solid transparent;
}

QTreeWidget#documentFolderTree::item:selected,
QTableWidget#documentFileTable::item:selected {
    background: #1b252a;
    border: 1px solid #60717a;
    color: #edf3f5;
}

QHeaderView::section {
    min-height: 34px;
    padding: 0 10px;
    border: 0;
    border-bottom: 1px solid #334047;
    background: #141b1f;
    color: #98a8ae;
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
}

QTableWidget#documentFileTable::item {
    min-height: 42px;
    padding: 0 10px;
    border-bottom: 1px solid rgba(255,255,255,.05);
}

QTextEdit#documentDetail {
    padding: 10px;
}

QFrame#documentsStatusBar {
    min-height: 32px;
    border-top: 1px solid #334047;
    background: #11181b;
}

QLabel#documentsStatusText {
    color: #98a8ae;
    font-size: 12px;
}

QMenu {
    background: #0f1518;
    border: 1px solid #5a6a72;
    color: #edf3f5;
    padding: 6px 0;
}

QMenu::item {
    min-height: 30px;
    padding: 6px 26px 6px 12px;
}

QMenu::item:selected {
    background: #243139;
}

QMenu::separator {
    height: 1px;
    margin: 6px 0;
    background: #334047;
}
"""
_FOLDER_ICON_CACHE: QtGui.QIcon | None = None
_FILE_ICON_CACHE: QtGui.QIcon | None = None


class _ActionSignals(QtCore.QObject):
    succeeded = QtCore.Signal(object)
    failed = QtCore.Signal(str)


def _folder_icon() -> QtGui.QIcon:
    global _FOLDER_ICON_CACHE
    if _FOLDER_ICON_CACHE is not None:
        return _FOLDER_ICON_CACHE
    pixmap = QtGui.QPixmap(18, 16)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor("#f2d97b"))
    pen.setWidth(1)
    painter.setPen(pen)
    painter.setBrush(QtGui.QColor("#d8b94f"))
    painter.drawRect(1, 5, 16, 10)
    painter.drawRect(1, 2, 9, 4)
    painter.end()
    _FOLDER_ICON_CACHE = QtGui.QIcon(pixmap)
    return _FOLDER_ICON_CACHE


def _file_icon() -> QtGui.QIcon:
    global _FILE_ICON_CACHE
    if _FILE_ICON_CACHE is not None:
        return _FILE_ICON_CACHE
    pixmap = QtGui.QPixmap(16, 16)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtGui.QPen(QtGui.QColor("#8aa0aa")))
    painter.setBrush(QtGui.QColor("#26343c"))
    painter.drawRect(2, 1, 12, 14)
    painter.drawLine(5, 5, 11, 5)
    painter.drawLine(5, 8, 11, 8)
    painter.end()
    _FILE_ICON_CACHE = QtGui.QIcon(pixmap)
    return _FILE_ICON_CACHE


class DocumentTableWidget(QtWidgets.QTableWidget):
    """Document table that can drag the selected document into the folder tree."""

    def mimeData(self, items: list[QtWidgets.QTableWidgetItem]) -> QtCore.QMimeData:
        mime = super().mimeData(items)
        rows = {item.row() for item in items}
        if len(rows) != 1:
            return mime
        id_item = self.item(next(iter(rows)), 0)
        if id_item is None:
            return mime
        document_id = id_item.data(QtCore.Qt.UserRole)
        if document_id is not None:
            mime.setData(_DOCUMENT_ID_MIME, str(int(document_id)).encode("ascii"))
        return mime

    def supportedDragActions(self) -> QtCore.Qt.DropActions:
        return QtCore.Qt.MoveAction


class DocumentFolderTree(QtWidgets.QTreeWidget):
    """Folder tree that accepts document drops."""

    documentDropped = QtCore.Signal(int, str)

    def dragEnterEvent(self, event: QtCore.QEvent) -> None:
        if event.mimeData().hasFormat(_DOCUMENT_ID_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtCore.QEvent) -> None:
        if event.mimeData().hasFormat(_DOCUMENT_ID_MIME):
            event.acceptProposedAction()
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                self.setCurrentItem(item)
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QtCore.QEvent) -> None:
        if not event.mimeData().hasFormat(_DOCUMENT_ID_MIME):
            super().dropEvent(event)
            return
        item = self.itemAt(event.position().toPoint())
        folder_path = "" if item is None else item.data(0, QtCore.Qt.UserRole)
        if folder_path is None:
            folder_path = ""
        document_id = int(bytes(event.mimeData().data(_DOCUMENT_ID_MIME)).decode("ascii"))
        self.documentDropped.emit(document_id, str(folder_path))
        event.acceptProposedAction()


class DocumentUploadDialog(QtWidgets.QDialog):
    """File picker and description input for server document uploads."""

    def __init__(
        self,
        *,
        initial_folder_path: str = "",
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
        self.folder_field = QtWidgets.QLineEdit(initial_folder_path)
        self.folder_field.setPlaceholderText("Root folder")
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
        form.addRow("Folder", self.folder_field)
        form.addRow("Description", self.description_field)
        form.addRow("", self.status_label)
        form.addRow("", button_row)
        self.setLayout(form)

    def payload(self) -> dict[str, object]:
        if self._payload is None:
            self._payload = build_upload_payload(
                self.path_field.text(),
                description=self.description_field.toPlainText(),
                folder_path=self.folder_field.text(),
            )
        return self._payload

    def accept(self) -> None:
        try:
            self._payload = build_upload_payload(
                self.path_field.text(),
                description=self.description_field.toPlainText(),
                folder_path=self.folder_field.text(),
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
        self._visible_items: list[DesktopDocumentItem] = []
        self._workers: list[_ActionSignals] = []
        self._selected_folder_path: str | None = None
        self._known_empty_folders: set[str] = set()
        self._refreshing_table = False
        self._refreshing_folders = False
        self.setObjectName("documentsExplorerPage")
        self.setStyleSheet(_DOCUMENTS_STYLESHEET)

        self.heading = QtWidgets.QLabel("Documents")
        self.heading.setObjectName("documentsHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("documentsSummary")
        self.client_upload_note = QtWidgets.QLabel(
            "Upload is server-only; clients receive documents through sync."
        )
        self.client_upload_note.setWordWrap(True)
        self.client_upload_note.setVisible(not can_upload_document(self._core.mode))

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.setObjectName("documentsButton")
        self.refresh_button.clicked.connect(self.refresh)
        self.upload_button = QtWidgets.QPushButton("Upload")
        self.upload_button.setObjectName("documentsPrimaryButton")
        self.upload_button.clicked.connect(self._upload_document)
        self.upload_button.setVisible(can_upload_document(self._core.mode))
        self.download_button = QtWidgets.QPushButton("Download", self)
        self.download_button.clicked.connect(self._download_selected)
        self.download_button.setVisible(False)
        self.delete_button = QtWidgets.QPushButton("Delete", self)
        self.delete_button.clicked.connect(self._delete_selected)
        self.delete_button.setVisible(False)
        self.move_button = QtWidgets.QPushButton("Move", self)
        self.move_button.clicked.connect(self._move_selected)
        self.move_button.setVisible(False)

        toolbar = QtWidgets.QFrame()
        toolbar.setObjectName("documentsToolbar")
        top_row = QtWidgets.QHBoxLayout(toolbar)
        top_row.setContentsMargins(16, 12, 16, 12)
        top_row.setSpacing(10)
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.refresh_button)
        top_row.addWidget(self.upload_button)

        self.folder_tree = DocumentFolderTree()
        self.folder_tree.setObjectName("documentFolderTree")
        self.folder_tree.setColumnCount(2)
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.setMinimumWidth(220)
        self.folder_tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.folder_tree.setIndentation(18)
        self.folder_tree.setIconSize(QtCore.QSize(16, 16))
        self.folder_tree.itemSelectionChanged.connect(self._folder_selection_changed)
        self.folder_tree.itemChanged.connect(self._folder_item_changed)
        self.folder_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.folder_tree.customContextMenuRequested.connect(
            self._show_folder_context_menu
        )
        self.folder_tree.setAcceptDrops(self._core.mode == "server")
        self.folder_tree.setDragDropMode(QtWidgets.QAbstractItemView.DropOnly)
        self.folder_tree.documentDropped.connect(self._move_document_to_folder)

        self.new_folder_button = QtWidgets.QPushButton("New Folder")
        self.new_folder_button.clicked.connect(self._new_folder)
        self.new_folder_button.setVisible(False)

        left_panel = QtWidgets.QFrame()
        left_panel.setObjectName("documentsPane")
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_title = QtWidgets.QLabel("Repository")
        left_title.setObjectName("documentsPaneTitle")
        left_layout.addWidget(left_title)
        left_content = QtWidgets.QWidget()
        left_content.setObjectName("documentsPaneBody")
        left_content_layout = QtWidgets.QVBoxLayout(left_content)
        left_content_layout.setContentsMargins(10, 10, 10, 10)
        left_content_layout.setSpacing(8)
        left_content_layout.addWidget(self.folder_tree, stretch=1)
        left_layout.addWidget(left_content, stretch=1)

        self.file_title = QtWidgets.QLabel("All Documents")
        self.file_title.setObjectName("documentsPaneTitle")
        file_panel = QtWidgets.QFrame()
        file_panel.setObjectName("documentsPane")
        file_layout = QtWidgets.QVBoxLayout(file_panel)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(0)
        file_layout.addWidget(self.file_title)

        self.table = DocumentTableWidget(0, 4)
        self.table.setObjectName("documentFileTable")
        self.table.setHorizontalHeaderLabels(["Name", "Size", "Uploader", "Uploaded"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditKeyPressed)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Fixed)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 118)
        self.table.setColumnWidth(3, 140)
        self.table.setDragEnabled(self._core.mode == "server")
        self.table.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)
        self.table.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(
            self._show_document_context_menu
        )
        configure_data_table(self.table)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setIconSize(QtCore.QSize(16, 16))
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemChanged.connect(self._document_item_changed)
        file_layout.addWidget(self.table, stretch=1)

        detail_panel = QtWidgets.QFrame()
        detail_panel.setObjectName("documentsPane")
        detail_layout = QtWidgets.QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(0)
        detail_title = QtWidgets.QLabel("Details")
        detail_title.setObjectName("documentsPaneTitle")
        detail_layout.addWidget(detail_title)
        self.detail = QtWidgets.QTextEdit()
        self.detail.setObjectName("documentDetail")
        self.detail.setReadOnly(True)
        self.detail.setMinimumWidth(340)
        detail_layout.addWidget(self.detail, stretch=1)

        self.status_label = QtWidgets.QLabel(
            "Context actions are server-only. Clients keep download and detail actions only."
        )
        self.status_label.setObjectName("documentsStatusText")
        self.status_label.setWordWrap(True)
        self.rename_hint_label = QtWidgets.QLabel("Rename accepts Enter, Escape cancels.")
        self.rename_hint_label.setObjectName("documentsStatusText")

        status_bar = QtWidgets.QFrame()
        status_bar.setObjectName("documentsStatusBar")
        status_layout = QtWidgets.QHBoxLayout(status_bar)
        status_layout.setContentsMargins(12, 7, 12, 7)
        status_layout.addWidget(self.status_label, stretch=1)
        status_layout.addWidget(self.rename_hint_label)

        body = QtWidgets.QSplitter()
        body.setObjectName("documentsBody")
        body.addWidget(left_panel)
        body.addWidget(file_panel)
        body.addWidget(detail_panel)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 0)
        body.setHandleWidth(1)
        body.setSizes([255, 625, 340])

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self.summary)
        layout.addWidget(self.client_upload_note)
        layout.addWidget(body, stretch=1)
        layout.addWidget(status_bar)

    def refresh(self) -> None:
        try:
            self._items = items_from_document_entries(
                self._core.read_model("documents.list")
            )
        except Exception as exc:
            _log.warning("Could not refresh documents: %s", exc)
            self.status_label.setText(f"Unable to load documents: {exc}")
            return

        self._refresh_folder_tree()
        self._refresh_table()
        total_size = sum(item.size_bytes for item in self._items)
        macro_count = sum(1 for item in self._items if item.is_macro_risk)
        self.summary.setText(
            f"{len(self._items)} document(s), "
            f"{self._format_total_size(total_size)} total, "
            f"{macro_count} macro-risk type(s)."
            + (
                " Server mode: context menus manage repository structure."
                if self._core.mode == "server"
                else ""
            )
        )
        if self._visible_items:
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
            item.filename,
            item.size_label,
            item.uploader_callsign,
            self._uploaded_date_label(item.uploaded_label),
        ]
        for column, value in enumerate(values):
            cell = QtWidgets.QTableWidgetItem(value)
            if column == 0:
                cell.setData(QtCore.Qt.UserRole, item.id)
                cell.setData(_ORIGINAL_TEXT_ROLE, item.filename)
                cell.setIcon(_file_icon())
                if self._core.mode == "server":
                    cell.setFlags(
                        cell.flags()
                        | QtCore.Qt.ItemIsEditable
                        | QtCore.Qt.ItemIsDragEnabled
                    )
            else:
                cell.setFlags(cell.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(row, column, cell)

    def _selection_changed(self) -> None:
        item = self._selected_item()
        self.download_button.setEnabled(can_download_document(item))
        self.move_button.setEnabled(self._core.mode == "server" and item is not None)
        self.delete_button.setEnabled(can_delete_document(self._core.mode, item))
        if item is None:
            self.detail.clear()
            return
        self.detail.setHtml(self._detail_html(item))

    def _selected_item(self) -> DesktopDocumentItem | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self._visible_items):
            return None
        return self._visible_items[row]

    def _show_document_context_menu(self, pos: QtCore.QPoint) -> None:
        row = self.table.rowAt(pos.y())
        if row >= 0:
            self.table.selectRow(row)
        item = self._selected_item() if row >= 0 else None
        menu = QtWidgets.QMenu(self)
        if item is None:
            if can_upload_document(self._core.mode):
                upload_action = menu.addAction("Upload Document")
                upload_action.triggered.connect(self._upload_document)
                new_folder_action = menu.addAction("New Folder")
                new_folder_action.triggered.connect(
                    lambda _checked=False: self._new_folder(
                        parent_path=self._selected_upload_folder()
                    )
                )
                menu.addSeparator()
            refresh_action = menu.addAction("Refresh")
            refresh_action.triggered.connect(self.refresh)
        else:
            download_action = menu.addAction("Download")
            download_action.triggered.connect(self._download_selected)
            if self._core.mode == "server":
                rename_action = menu.addAction("Rename")
                rename_action.triggered.connect(self._start_document_rename)
                move_action = menu.addAction("Move To...")
                move_action.triggered.connect(self._move_selected)
                menu.addSeparator()
                delete_action = menu.addAction("Delete Document...")
                delete_action.triggered.connect(self._delete_selected)
        if menu.actions():
            menu.exec(self.table.viewport().mapToGlobal(pos))

    def _show_folder_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self.folder_tree.itemAt(pos)
        if item is not None:
            self.folder_tree.setCurrentItem(item)
        folder_path = "" if item is None else item.data(0, QtCore.Qt.UserRole)
        menu = QtWidgets.QMenu(self)
        if self._core.mode == "server":
            parent_path = "" if folder_path is None else str(folder_path)
            new_folder_action = menu.addAction("New Folder")
            new_folder_action.triggered.connect(
                lambda _checked=False, path=parent_path: self._new_folder(
                    parent_path=path
                )
            )
            upload_action = menu.addAction("Upload Here")
            upload_action.triggered.connect(
                lambda _checked=False, path=parent_path: self._upload_document_to_folder(
                    path
                )
            )
            if folder_path not in (None, ""):
                menu.addSeparator()
                rename_action = menu.addAction("Rename Folder")
                rename_action.triggered.connect(self._start_folder_rename)
                move_action = menu.addAction("Move Folder To...")
                move_action.triggered.connect(self._move_selected_folder)
                delete_action = menu.addAction("Delete Folder...")
                delete_action.triggered.connect(self._delete_selected_folder)
        if menu.actions() and self._core.mode == "server":
            menu.addSeparator()
        refresh_action = menu.addAction("Refresh")
        refresh_action.triggered.connect(self.refresh)
        menu.exec(self.folder_tree.viewport().mapToGlobal(pos))

    def _upload_document(self) -> None:
        self._upload_document_to_folder(self._selected_upload_folder())

    def _upload_document_to_folder(self, folder_path: str) -> None:
        if not can_upload_document(self._core.mode):
            self.status_label.setText("Upload is available in server mode only.")
            return
        dialog = DocumentUploadDialog(
            initial_folder_path=folder_path,
            parent=self,
        )
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

    def _move_selected(self) -> None:
        item = self._selected_item()
        if self._core.mode != "server" or item is None:
            return
        folder_path = self._choose_folder_path(
            title="Move Document",
            label=item.filename,
            current_folder=item.folder_path,
        )
        if folder_path is None:
            return
        self._move_document_to_folder(item.id, folder_path)

    def _choose_folder_path(
        self,
        *,
        title: str,
        label: str,
        current_folder: str = "",
        exclude_folder: str | None = None,
    ) -> str | None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(420)

        folder_combo = QtWidgets.QComboBox()
        folder_combo.setEditable(True)
        folder_combo.addItem("Root", "")
        for folder in self._known_folder_paths():
            if not folder:
                continue
            if exclude_folder and (
                folder == exclude_folder or folder.startswith(exclude_folder + "/")
            ):
                continue
            if folder:
                folder_combo.addItem(folder, folder)
        current_index = folder_combo.findData(current_folder)
        if current_index >= 0:
            folder_combo.setCurrentIndex(current_index)
        else:
            folder_combo.setEditText(current_folder)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Ok
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        form = QtWidgets.QFormLayout(dialog)
        form.addRow("Item", QtWidgets.QLabel(label))
        form.addRow("Folder", folder_combo)
        form.addRow("", buttons)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None

        current_index = folder_combo.currentIndex()
        current_data = folder_combo.currentData()
        if (
            current_index >= 0
            and current_data is not None
            and folder_combo.currentText() == folder_combo.itemText(current_index)
        ):
            folder_path = str(current_data)
        else:
            folder_path = folder_combo.currentText()
        from talon_core.documents import sanitize_folder_path

        try:
            return sanitize_folder_path(folder_path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Folder",
                document_error_message(exc),
            )
            return None

    def _move_document_to_folder(self, document_id: int, folder_path: str) -> None:
        if self._core.mode != "server":
            return
        try:
            result = self._core.command(
                "documents.move",
                document_id=int(document_id),
                folder_path=folder_path,
            )
        except Exception as exc:
            message = document_error_message(exc)
            _log.warning("Document move failed: %s", message)
            QtWidgets.QMessageBox.warning(self, "Move Failed", message)
            return
        moved = getattr(result, "document", None)
        if moved is not None:
            self._selected_folder_path = str(getattr(moved, "folder_path", "") or "")
        self.status_label.setText("Document moved.")
        self.refresh()

    def _new_folder(self, *, parent_path: str | None = None) -> None:
        if self._core.mode != "server":
            return
        from talon_core.documents import sanitize_folder_path

        if parent_path is None:
            parent_path = self._selected_upload_folder()
        text, accepted = QtWidgets.QInputDialog.getText(
            self,
            "New Folder",
            "Folder name",
            text="New Folder",
        )
        if not accepted:
            return
        try:
            folder_name = sanitize_folder_path(text)
            folder_path = sanitize_folder_path(
                f"{parent_path}/{folder_name}" if parent_path else folder_name
            )
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Folder",
                document_error_message(exc),
            )
            return
        if not folder_path:
            self.status_label.setText("Root folder already exists.")
            return
        if folder_path in self._known_folder_paths():
            self._selected_folder_path = folder_path
            self._refresh_folder_tree()
            self._refresh_table()
            self.status_label.setText("Folder already exists.")
            return
        self._known_empty_folders.add(folder_path)
        self._selected_folder_path = folder_path
        self._refresh_folder_tree()
        self._refresh_table()
        self.status_label.setText(
            "Folder is ready. Upload or move a document into it to sync it."
        )

    def _start_document_rename(self) -> None:
        if self._core.mode != "server":
            return
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return
        row = selected[0].row()
        filename_cell = self.table.item(row, 0)
        if filename_cell is not None:
            self.table.setCurrentCell(row, 0)
            self.table.editItem(filename_cell)

    def _document_item_changed(self, cell: QtWidgets.QTableWidgetItem) -> None:
        if self._refreshing_table or cell.column() != 0 or self._core.mode != "server":
            return
        document_id = cell.data(QtCore.Qt.UserRole)
        original = str(cell.data(_ORIGINAL_TEXT_ROLE) or "")
        next_filename = cell.text().strip()
        if document_id is None or not next_filename or next_filename == original:
            if not next_filename:
                self._set_cell_text_without_signal(cell, original)
            return
        try:
            result = self._core.command(
                "documents.rename",
                document_id=int(document_id),
                filename=next_filename,
            )
        except Exception as exc:
            message = document_error_message(exc)
            _log.warning("Document rename failed: %s", message)
            self._set_cell_text_without_signal(cell, original)
            QtWidgets.QMessageBox.warning(self, "Rename Failed", message)
            return
        renamed = getattr(result, "document", None)
        self.status_label.setText("Document renamed.")
        self.refresh()
        if renamed is not None:
            self._select_document_id(int(getattr(renamed, "id")))

    def _start_folder_rename(self) -> None:
        if self._core.mode != "server":
            return
        item = self.folder_tree.currentItem()
        if item is None:
            return
        folder_path = item.data(0, QtCore.Qt.UserRole)
        if folder_path in (None, ""):
            self.status_label.setText("Select a folder to rename.")
            return
        self.folder_tree.editItem(item, 0)

    def _folder_item_changed(
        self,
        item: QtWidgets.QTreeWidgetItem,
        column: int,
    ) -> None:
        if (
            self._refreshing_folders
            or column != 0
            or self._core.mode != "server"
        ):
            return
        folder_path = item.data(0, QtCore.Qt.UserRole)
        if folder_path in (None, ""):
            return
        old_path = str(folder_path)
        parent_path, _separator, _name = old_path.rpartition("/")
        try:
            from talon_core.documents import sanitize_folder_path

            new_name = sanitize_folder_path(item.text(0))
            new_path = sanitize_folder_path(
                f"{parent_path}/{new_name}" if parent_path else new_name
            )
        except Exception as exc:
            self._refresh_folder_tree()
            QtWidgets.QMessageBox.warning(
                self,
                "Rename Failed",
                document_error_message(exc),
            )
            return
        if new_path == old_path:
            return
        self._rename_folder_path(old_path, new_path)

    def _move_selected_folder(self) -> None:
        if self._core.mode != "server":
            return
        item = self.folder_tree.currentItem()
        if item is None:
            return
        folder_path = item.data(0, QtCore.Qt.UserRole)
        if folder_path in (None, ""):
            self.status_label.setText("Select a folder to move.")
            return
        old_path = str(folder_path)
        destination = self._choose_folder_path(
            title="Move Folder",
            label=old_path,
            current_folder="",
            exclude_folder=old_path,
        )
        if destination is None:
            return
        basename = old_path.rsplit("/", 1)[-1]
        new_path = f"{destination}/{basename}".strip("/")
        self._rename_folder_path(old_path, new_path)

    def _rename_folder_path(self, old_path: str, new_path: str) -> None:
        try:
            from talon_core.documents import sanitize_folder_path

            old_path = sanitize_folder_path(old_path)
            new_path = sanitize_folder_path(new_path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Rename Failed",
                document_error_message(exc),
            )
            return
        if not old_path or not new_path:
            self.status_label.setText("Root folder cannot be renamed.")
            self._refresh_folder_tree()
            return
        if old_path == new_path:
            self.status_label.setText("Folder is already in that location.")
            self._refresh_folder_tree()
            return
        if new_path.startswith(old_path + "/"):
            self.status_label.setText("Folder cannot be moved inside itself.")
            self._refresh_folder_tree()
            return
        docs = self._items_in_folder_path(old_path)
        if docs:
            try:
                self._core.command(
                    "documents.rename_folder",
                    folder_path=old_path,
                    new_folder_path=new_path,
                )
            except Exception as exc:
                message = document_error_message(exc)
                _log.warning("Folder rename failed: %s", message)
                QtWidgets.QMessageBox.warning(self, "Rename Failed", message)
                self._refresh_folder_tree()
                return
        self._rewrite_empty_folder_prefix(old_path, new_path)
        self._selected_folder_path = new_path
        self.status_label.setText("Folder renamed.")
        self.refresh()

    def _delete_selected_folder(self) -> None:
        if self._core.mode != "server":
            return
        item = self.folder_tree.currentItem()
        if item is None:
            return
        folder_path = item.data(0, QtCore.Qt.UserRole)
        if folder_path in (None, ""):
            self.status_label.setText("Select a folder to delete.")
            return
        folder_path = str(folder_path)
        docs = self._items_in_folder_path(folder_path)
        empty_descendants = self._empty_folder_descendants(folder_path)
        detail = (
            f"Delete {folder_path} and {len(docs)} document(s)? "
            "This cannot be undone."
            if docs
            else f"Delete empty folder {folder_path}?"
        )
        if empty_descendants and not docs:
            detail = f"Delete empty folder {folder_path} and its empty subfolders?"
        response = QtWidgets.QMessageBox.question(
            self,
            "Delete Folder",
            detail,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return
        if docs:
            try:
                self._core.command("documents.delete_folder", folder_path=folder_path)
            except Exception as exc:
                message = document_error_message(exc)
                _log.warning("Folder delete failed: %s", message)
                QtWidgets.QMessageBox.warning(self, "Delete Failed", message)
                return
        self._drop_empty_folder_prefix(folder_path)
        self._selected_folder_path = self._parent_folder_path(folder_path)
        self.status_label.setText("Folder deleted.")
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

    def _detail_html(self, item: DesktopDocumentItem) -> str:
        description = html.escape(item.description.strip())
        hint = (
            "Right-click this document for file actions. "
            "Drag it onto a folder to move it there."
            if self._core.mode == "server"
            else "Right-click this document to download it."
        )
        rows = (
            ("Folder", self._folder_label(item.folder_path)),
            ("Size", item.size_label),
            ("Uploader", item.uploader_callsign),
            ("Uploaded", item.uploaded_label),
            ("SHA-256", item.hash_preview),
        )
        meta = "\n".join(
            "<tr>"
            f"<th>{html.escape(label)}</th>"
            f"<td>{html.escape(value)}</td>"
            "</tr>"
            for label, value in rows
        )
        description_block = (
            f"<p class=\"description\">{description}</p>" if description else ""
        )
        return f"""
        <html>
        <head>
          <style>
            body {{
              background: #101619;
              color: #edf3f5;
              font-family: Arial, Helvetica, sans-serif;
              font-size: 13px;
            }}
            h2 {{
              margin: 0 0 8px 0;
              color: #edf3f5;
              font-size: 18px;
              font-weight: 700;
            }}
            .muted {{
              color: #98a8ae;
              margin-bottom: 12px;
            }}
            table {{
              width: 100%;
              border-collapse: collapse;
            }}
            th {{
              width: 92px;
              color: #edf3f5;
              text-align: left;
              font-weight: 700;
              padding: 8px 10px 8px 0;
              border-bottom: 1px solid rgba(255,255,255,.08);
            }}
            td {{
              color: #edf3f5;
              padding: 8px 0;
              border-bottom: 1px solid rgba(255,255,255,.08);
            }}
            .description {{
              margin-top: 14px;
              color: #edf3f5;
            }}
          </style>
        </head>
        <body>
          <h2>{html.escape(item.filename)}</h2>
          <div class="muted">{html.escape(hint)}</div>
          <table>{meta}</table>
          {description_block}
        </body>
        </html>
        """

    @staticmethod
    def _format_total_size(size_bytes: int) -> str:
        from talon_desktop.documents import format_size

        return format_size(size_bytes)

    @staticmethod
    def _uploaded_date_label(uploaded_label: str) -> str:
        if len(uploaded_label) >= 10 and uploaded_label[4:5] == "-":
            return uploaded_label[:10]
        return uploaded_label

    def _folder_selection_changed(self) -> None:
        item = self.folder_tree.currentItem()
        if item is None:
            return
        self._selected_folder_path = item.data(0, QtCore.Qt.UserRole)
        self._refresh_table()

    def _refresh_table(self) -> None:
        selected = self._selected_folder_path
        self.file_title.setText(
            "All Documents" if selected is None else self._folder_label(str(selected))
        )
        self._visible_items = [
            item
            for item in self._items
            if selected is None or item.folder_path == selected
        ]
        self._refreshing_table = True
        self.table.setRowCount(0)
        for item in self._visible_items:
            self._add_row(item)
        self._refreshing_table = False
        if self._visible_items:
            self.table.selectRow(0)
        else:
            self._selection_changed()

    def _refresh_folder_tree(self) -> None:
        selected = self._selected_folder_path
        self._refreshing_folders = True
        self.folder_tree.blockSignals(True)
        self.folder_tree.clear()

        all_item = QtWidgets.QTreeWidgetItem(["All Documents", str(len(self._items))])
        all_item.setData(0, QtCore.Qt.UserRole, None)
        all_item.setFlags(all_item.flags() | QtCore.Qt.ItemIsDropEnabled)
        all_item.setTextAlignment(1, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.folder_tree.addTopLevelItem(all_item)

        root_item = QtWidgets.QTreeWidgetItem(
            ["Root", str(self._folder_document_count(""))]
        )
        root_item.setIcon(0, _folder_icon())
        root_item.setData(0, QtCore.Qt.UserRole, "")
        root_item.setFlags(root_item.flags() | QtCore.Qt.ItemIsDropEnabled)
        root_item.setTextAlignment(1, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.folder_tree.addTopLevelItem(root_item)

        path_items: dict[str, QtWidgets.QTreeWidgetItem] = {}
        for folder_path in self._known_folder_paths():
            if not folder_path:
                continue
            parent = self.folder_tree.invisibleRootItem()
            current_path = ""
            for part in folder_path.split("/"):
                current_path = f"{current_path}/{part}".strip("/")
                node = path_items.get(current_path)
                if node is None:
                    node = QtWidgets.QTreeWidgetItem(
                        [part, str(self._folder_document_count(current_path))]
                    )
                    node.setIcon(0, _folder_icon())
                    node.setData(0, QtCore.Qt.UserRole, current_path)
                    node.setFlags(
                        node.flags()
                        | QtCore.Qt.ItemIsDropEnabled
                        | QtCore.Qt.ItemIsEditable
                    )
                    node.setTextAlignment(
                        1,
                        QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                    )
                    parent.addChild(node)
                    path_items[current_path] = node
                parent = node

        self.folder_tree.expandAll()
        self.folder_tree.setColumnWidth(0, 172)
        self.folder_tree.setColumnWidth(1, 42)
        if selected is None:
            target = all_item
            next_selected = None
        elif selected == "":
            target = root_item
            next_selected = ""
        else:
            target = path_items.get(selected)
            next_selected = selected
            if target is None:
                target = all_item
                next_selected = None
        self.folder_tree.setCurrentItem(target)
        self._selected_folder_path = next_selected
        self.folder_tree.blockSignals(False)
        self._refreshing_folders = False

    def _known_folder_paths(self) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()

        def add_path(folder_path: str) -> None:
            current = ""
            if folder_path == "" and folder_path not in seen:
                paths.append(folder_path)
                seen.add(folder_path)
                return
            for part in folder_path.split("/"):
                if not part:
                    continue
                current = f"{current}/{part}".strip("/")
                if current not in seen:
                    paths.append(current)
                    seen.add(current)

        for item in self._items:
            add_path(item.folder_path)
        for folder_path in sorted(self._known_empty_folders):
            add_path(folder_path)
        return paths

    def _selected_upload_folder(self) -> str:
        if self._selected_folder_path is None:
            return ""
        return self._selected_folder_path

    @staticmethod
    def _folder_label(folder_path: str) -> str:
        return folder_path or "Root"

    def _folder_document_count(self, folder_path: str) -> int:
        return sum(1 for item in self._items if item.folder_path == folder_path)

    def _select_document_id(self, document_id: int) -> None:
        for row, item in enumerate(self._visible_items):
            if item.id == document_id:
                self.table.selectRow(row)
                return

    def _set_cell_text_without_signal(
        self,
        cell: QtWidgets.QTableWidgetItem,
        text: str,
    ) -> None:
        self.table.blockSignals(True)
        try:
            cell.setText(text)
        finally:
            self.table.blockSignals(False)

    def _items_in_folder_path(self, folder_path: str) -> list[DesktopDocumentItem]:
        return [
            item
            for item in self._items
            if item.folder_path == folder_path
            or item.folder_path.startswith(folder_path + "/")
        ]

    def _empty_folder_descendants(self, folder_path: str) -> set[str]:
        return {
            path
            for path in self._known_empty_folders
            if path == folder_path or path.startswith(folder_path + "/")
        }

    def _rewrite_empty_folder_prefix(self, old_path: str, new_path: str) -> None:
        rewritten: set[str] = set()
        for path in self._known_empty_folders:
            if path == old_path:
                rewritten.add(new_path)
            elif path.startswith(old_path + "/"):
                rewritten.add(f"{new_path}/{path[len(old_path) + 1:]}")
            else:
                rewritten.add(path)
        if old_path in self._known_empty_folders:
            rewritten.discard(old_path)
        self._known_empty_folders = rewritten

    def _drop_empty_folder_prefix(self, folder_path: str) -> None:
        self._known_empty_folders = {
            path
            for path in self._known_empty_folders
            if path != folder_path and not path.startswith(folder_path + "/")
        }

    @staticmethod
    def _parent_folder_path(folder_path: str) -> str:
        return folder_path.rpartition("/")[0]

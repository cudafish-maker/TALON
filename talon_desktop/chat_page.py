"""PySide6 chat channels, DMs, and message composer."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from talon_core import TalonCoreSession
from talon_core.utils.logging import get_logger
from talon_desktop.chat import (
    DesktopChannelItem,
    DesktopGridReferenceItem,
    DesktopMessageItem,
    DesktopOperatorItem,
    build_create_channel_payload,
    build_dm_payload,
    build_message_payload,
    can_delete_channel,
    can_delete_message,
    grid_reference_items_from_context,
    items_from_channels,
    items_from_messages,
    items_from_operators,
    operator_lookup_from_items,
)
from talon_desktop.theme import configure_data_table

_log = get_logger("desktop.chat")

_URGENT_BACKGROUND = QtGui.QColor("#3a1620")
_URGENT_FOREGROUND = QtGui.QColor("#f0c674")
_GRID_FOREGROUND = QtGui.QColor("#8fbcbb")
_UNREAD_CHANNEL_BACKGROUND = QtGui.QColor("#2a1719")
_UNREAD_CHANNEL_FOREGROUND = QtGui.QColor("#f6fbfb")


class DmDialog(QtWidgets.QDialog):
    """Operator picker for direct-message channel creation."""

    def __init__(
        self,
        core: TalonCoreSession,
        *,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._core = core
        self._current_operator_id: int | None = None
        self._operators: list[DesktopOperatorItem] = []
        self.setWindowTitle("Direct Message")
        self.setMinimumWidth(420)

        self.operator_list = QtWidgets.QListWidget()
        self.operator_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self.start_button = QtWidgets.QPushButton("Open")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.start_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.start_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Operator"))
        layout.addWidget(self.operator_list)
        layout.addWidget(self.status_label)
        layout.addLayout(button_row)

        self._load()

    def payload(self) -> dict[str, object]:
        peer_id = self._selected_peer_id()
        if self._current_operator_id is None:
            raise ValueError("Current operator is unavailable.")
        if peer_id is None:
            raise ValueError("Select an operator.")
        return build_dm_payload(
            current_operator_id=self._current_operator_id,
            peer_operator_id=peer_id,
        )

    def accept(self) -> None:
        try:
            self.payload()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        super().accept()

    def _load(self) -> None:
        try:
            current = self._core.read_model("chat.current_operator")
            self._current_operator_id = int(current["id"])
            operators = items_from_operators(self._core.read_model("chat.operators"))
        except Exception as exc:
            _log.warning("Could not load DM operators: %s", exc)
            self.status_label.setText(f"Unable to load operators: {exc}")
            return

        self._operators = [
            operator for operator in operators
            if operator.id != self._current_operator_id
        ]
        self.operator_list.clear()
        for operator in self._operators:
            label = operator.callsign
            if operator.role:
                label += f" | {operator.role}"
            label += " | online" if operator.online else " | offline"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, operator.id)
            self.operator_list.addItem(item)
        if self._operators:
            self.operator_list.setCurrentRow(0)
        else:
            placeholder = QtWidgets.QListWidgetItem("No other operators.")
            placeholder.setFlags(QtCore.Qt.NoItemFlags)
            self.operator_list.addItem(placeholder)

    def _selected_peer_id(self) -> int | None:
        item = self.operator_list.currentItem()
        if item is None:
            return None
        value = item.data(QtCore.Qt.UserRole)
        if value in (None, ""):
            return None
        return int(value)


class GridReferenceDialog(QtWidgets.QDialog):
    """Picker for map-visible locations that can be attached to a chat message."""

    def __init__(
        self,
        core: TalonCoreSession,
        *,
        current_reference: str = "",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._core = core
        self._current_reference = current_reference
        self._items: list[DesktopGridReferenceItem] = []
        self._visible_items: list[DesktopGridReferenceItem] = []
        self._selected_reference = current_reference
        self.setWindowTitle("Grid Reference")
        self.setMinimumSize(720, 460)

        self.search_field = QtWidgets.QLineEdit()
        self.search_field.setPlaceholderText("Search known positions")
        self.search_field.textChanged.connect(self._populate)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Type", "Name", "Latitude", "Longitude", "Detail"]
        )
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        configure_data_table(self.table)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self._attach_selected())

        self.reference_label = QtWidgets.QLabel("")
        self.reference_label.setWordWrap(True)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self.attach_button = QtWidgets.QPushButton("Attach")
        self.attach_button.clicked.connect(self._attach_selected)
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear_reference)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.clear_button)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.attach_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.search_field)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.reference_label)
        layout.addWidget(self.status_label)
        layout.addLayout(button_row)

        self._load()

    def reference(self) -> str:
        return self._selected_reference

    def _load(self) -> None:
        try:
            context = self._core.read_model("map.context")
            sitreps = self._core.read_model("sitreps.list")
            self._items = grid_reference_items_from_context(
                context,
                sitrep_entries=sitreps,
            )
        except Exception as exc:
            _log.warning("Could not load grid references: %s", exc)
            self.status_label.setText(f"Unable to load map positions: {exc}")
            self._items = []
        self._populate()

    def _populate(self, _text: str = "") -> None:
        search = self.search_field.text().strip().lower()
        self._visible_items = [
            item for item in self._items
            if not search
            or search in item.kind.lower()
            or search in item.label.lower()
            or search in item.detail.lower()
            or search in item.reference.lower()
        ]
        self.table.setRowCount(0)
        for item in self._visible_items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                item.kind,
                item.label,
                f"{item.lat:.6f}",
                f"{item.lon:.6f}",
                item.detail,
            ]
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                cell.setData(QtCore.Qt.UserRole, item.reference)
                self.table.setItem(row, column, cell)
            if item.reference == self._current_reference:
                self.table.selectRow(row)

        if self._visible_items and not self.table.selectedItems():
            self.table.selectRow(0)
        self.status_label.setText(
            f"{len(self._visible_items)} known position(s)."
            if self._visible_items
            else "No known positions with coordinates."
        )
        self._selection_changed()

    def _selection_changed(self) -> None:
        item = self._selected_item()
        if item is None:
            self.reference_label.clear()
            self.attach_button.setEnabled(False)
            return
        self.reference_label.setText(item.reference)
        self.attach_button.setEnabled(True)

    def _selected_item(self) -> DesktopGridReferenceItem | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._visible_items):
            return None
        return self._visible_items[row]

    def _attach_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            self.status_label.setText("Select a known position.")
            return
        self._selected_reference = item.reference
        self.accept()

    def _clear_reference(self) -> None:
        self._selected_reference = ""
        self.accept()


class ChatPage(QtWidgets.QWidget):
    """Desktop chat page backed by talon-core chat commands."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._channels: list[DesktopChannelItem] = []
        self._messages: list[DesktopMessageItem] = []
        self._operators: list[DesktopOperatorItem] = []
        self._active_channel_id: int | None = None
        self._unread_channel_ids: set[int] = set()
        self._pending_grid_ref = ""
        self._blink_on = False
        self._blink_timer = QtCore.QTimer(self)
        self._blink_timer.timeout.connect(self._blink_urgent_messages)

        self.heading = QtWidgets.QLabel("Chat")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.grid_button = QtWidgets.QPushButton("Grid")
        self.grid_button.clicked.connect(self._open_grid_reference_dialog)
        self.new_channel_button = QtWidgets.QPushButton("New Channel")
        self.new_channel_button.clicked.connect(self._create_channel)
        self.new_dm_button = QtWidgets.QPushButton("Direct Message")
        self.new_dm_button.clicked.connect(self._create_dm)
        self.delete_channel_button = QtWidgets.QPushButton("Delete Channel")
        self.delete_channel_button.clicked.connect(self._delete_channel)
        self.delete_channel_button.setVisible(self._core.mode == "server")

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.refresh_button)
        top_row.addWidget(self.grid_button)
        top_row.addWidget(self.new_channel_button)
        top_row.addWidget(self.new_dm_button)
        top_row.addWidget(self.delete_channel_button)

        self.channel_list = QtWidgets.QListWidget()
        self.channel_list.setMinimumWidth(240)
        self.channel_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.channel_list.itemSelectionChanged.connect(self._on_channel_selected)
        self.channel_list.itemClicked.connect(self._on_channel_clicked)
        self.channel_search = QtWidgets.QLineEdit()
        self.channel_search.setPlaceholderText("Search channels")
        self.channel_search.textChanged.connect(lambda _text: self._populate_channels(self._active_channel_id))
        self.user_footer = QtWidgets.QLabel("")
        self.user_footer.setWordWrap(True)
        self.user_footer.setObjectName("summaryLabel")

        channel_panel = QtWidgets.QWidget()
        channel_layout = QtWidgets.QVBoxLayout(channel_panel)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.addWidget(QtWidgets.QLabel("Channels"))
        channel_layout.addWidget(self.channel_search)
        channel_layout.addWidget(self.channel_list)
        channel_layout.addWidget(self.user_footer)

        self.channel_title = QtWidgets.QLabel("")
        self.channel_title.setObjectName("sectionHeading")
        self.dm_security_note = QtWidgets.QLabel(
            "Direct messages are server-readable until Phase 2b E2E encryption lands."
        )
        self.dm_security_note.setWordWrap(True)
        self.dm_security_note.setVisible(False)

        self.message_list = QtWidgets.QListWidget()
        self.message_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.message_list.itemSelectionChanged.connect(self._on_message_selected)

        self.body_field = QtWidgets.QPlainTextEdit()
        self.body_field.setPlaceholderText("Compose message")
        self.body_field.setFixedHeight(92)
        self.urgent_check = QtWidgets.QCheckBox("Urgent")
        self.send_button = QtWidgets.QPushButton("Send")
        self.send_button.clicked.connect(self._send_message)
        self.delete_message_button = QtWidgets.QPushButton("Delete Message")
        self.delete_message_button.clicked.connect(self._delete_message)
        self.delete_message_button.setVisible(self._core.mode == "server")
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        composer_form = QtWidgets.QFormLayout()
        composer_form.addRow("Message", self.body_field)

        composer_actions = QtWidgets.QHBoxLayout()
        composer_actions.addWidget(self.urgent_check)
        composer_actions.addWidget(self.delete_message_button)
        composer_actions.addStretch(1)
        composer_actions.addWidget(self.send_button)
        composer_form.addRow("", composer_actions)
        composer_form.addRow("", self.status_label)

        message_panel = QtWidgets.QWidget()
        message_layout = QtWidgets.QVBoxLayout(message_panel)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.addWidget(self.channel_title)
        message_layout.addWidget(self.dm_security_note)
        message_layout.addWidget(self.message_list, stretch=1)
        message_layout.addLayout(composer_form)

        self.operator_list = QtWidgets.QListWidget()
        self.operator_list.setMinimumWidth(220)
        self.operator_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.alert_list = QtWidgets.QListWidget()
        self.alert_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)

        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QtWidgets.QLabel("Operators"))
        right_layout.addWidget(self.operator_list, stretch=1)
        right_layout.addWidget(QtWidgets.QLabel("Alerts"))
        right_layout.addWidget(self.alert_list, stretch=1)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(channel_panel)
        splitter.addWidget(message_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self.summary)
        layout.addWidget(splitter, stretch=1)

    def refresh(self) -> None:
        current_id = self._selected_channel_id() or self._active_channel_id
        try:
            self._core.command("chat.ensure_defaults")
            self._operators = items_from_operators(self._core.read_model("chat.operators"))
            lookup = operator_lookup_from_items(self._operators)
            self._channels = items_from_channels(
                self._core.read_model("chat.channels"),
                operator_lookup=lookup,
            )
        except Exception as exc:
            _log.warning("Could not refresh chat: %s", exc)
            self.status_label.setText(f"Unable to load chat: {exc}")
            return

        self._populate_channels(current_id)
        self._refresh_side_panel()
        self._refresh_messages()

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        _ = action
        if table in {"channels", "operators"}:
            self.refresh()
        elif table == "messages":
            self._mark_message_channel_unread(record_id)
            self._refresh_messages()

    def mark_unread_channel(self, channel_id: int, *, force: bool = False) -> None:
        channel_id = int(channel_id)
        if not force and channel_id == self._selected_channel_id():
            return
        self._unread_channel_ids.add(channel_id)
        self._populate_channels(self._selected_channel_id() or self._active_channel_id)

    def _populate_channels(self, preferred_id: int | None) -> None:
        self.channel_list.blockSignals(True)
        try:
            self.channel_list.clear()
            search = self.channel_search.text().strip().lower()
            channels = [
                channel for channel in self._channels
                if not search
                or search in channel.display_name.lower()
                or search in channel.group_label.lower()
                or search in channel.name.lower()
            ]
            current_group = ""
            for channel in sorted(channels, key=_channel_sort_key):
                if channel.group_label != current_group:
                    current_group = channel.group_label
                    header = QtWidgets.QListWidgetItem(current_group.upper())
                    header.setFlags(QtCore.Qt.NoItemFlags)
                    header.setForeground(QtGui.QColor("#8fbcbb"))
                    header.setBackground(QtGui.QColor("#10181b"))
                    font = header.font()
                    font.setBold(True)
                    header.setFont(font)
                    header.setSizeHint(QtCore.QSize(0, 30))
                    self.channel_list.addItem(header)
                label = channel.display_name
                item = QtWidgets.QListWidgetItem(label)
                item.setSizeHint(QtCore.QSize(0, 28))
                item.setData(QtCore.Qt.UserRole, channel.id)
                if channel.id in self._unread_channel_ids:
                    item.setBackground(_UNREAD_CHANNEL_BACKGROUND)
                    item.setForeground(_UNREAD_CHANNEL_FOREGROUND)
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                if channel.is_dm:
                    item.setToolTip(
                        "Direct messages are server-readable until Phase 2b E2E encryption lands."
                    )
                self.channel_list.addItem(item)
        finally:
            self.channel_list.blockSignals(False)

        selectable = [
            self.channel_list.item(row)
            for row in range(self.channel_list.count())
            if self.channel_list.item(row).data(QtCore.Qt.UserRole) not in (None, "")
        ]
        if not selectable:
            placeholder = QtWidgets.QListWidgetItem("No channels.")
            placeholder.setFlags(QtCore.Qt.NoItemFlags)
            self.channel_list.addItem(placeholder)
            self._active_channel_id = None
            self._update_controls()
            return

        target_id = preferred_id if self._channel_for_id(preferred_id) else self._channels[0].id
        for row in range(self.channel_list.count()):
            item = self.channel_list.item(row)
            if item.data(QtCore.Qt.UserRole) == target_id:
                self.channel_list.setCurrentRow(row)
                return
        for row in range(self.channel_list.count()):
            item = self.channel_list.item(row)
            if item.data(QtCore.Qt.UserRole) not in (None, ""):
                self.channel_list.setCurrentRow(row)
                return

    def _refresh_messages(self) -> None:
        channel = self._selected_channel()
        if channel is None:
            self._messages = []
            self.message_list.clear()
            self.channel_title.setText("")
            self.summary.setText(f"{len(self._channels)} channel(s).")
            self._update_controls()
            return

        self._active_channel_id = channel.id
        try:
            entries = self._core.read_model(
                "chat.messages",
                {"channel_id": channel.id},
            )
            self._messages = items_from_messages(entries)
        except Exception as exc:
            _log.warning("Could not refresh messages: %s", exc)
            self.status_label.setText(f"Unable to load messages: {exc}")
            return

        self.channel_title.setText(f"{channel.display_name} | {channel.group_label}")
        self.dm_security_note.setVisible(channel.is_dm)
        self.message_list.clear()
        if not self._messages:
            placeholder = QtWidgets.QListWidgetItem("No messages.")
            placeholder.setFlags(QtCore.Qt.NoItemFlags)
            self.message_list.addItem(placeholder)
        else:
            for message in self._messages:
                self.message_list.addItem(self._message_row(message))

        urgent_count = sum(1 for message in self._messages if message.is_urgent)
        self.summary.setText(
            f"{len(self._channels)} channel(s), "
            f"{len(self._messages)} message(s) here, "
            f"{urgent_count} urgent."
        )
        self._update_controls()
        self._sync_blink_timer()

    def _message_row(self, message: DesktopMessageItem) -> QtWidgets.QListWidgetItem:
        header = f"{message.sent_time}  {message.callsign}"
        if message.is_urgent:
            header += "  URGENT"
        text = f"{header}\n{message.body}"
        if message.grid_ref:
            text += f"\nGrid: {message.grid_ref}"
        item = QtWidgets.QListWidgetItem(text)
        item.setData(QtCore.Qt.UserRole, message.id)
        item.setData(QtCore.Qt.UserRole + 1, message.is_urgent)
        if message.is_urgent:
            item.setBackground(_URGENT_BACKGROUND)
            item.setForeground(_URGENT_FOREGROUND)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        elif message.grid_ref:
            item.setForeground(_GRID_FOREGROUND)
        return item

    def _on_channel_selected(self) -> None:
        channel_id = self._selected_channel_id()
        if channel_id is not None and channel_id in self._unread_channel_ids:
            self._unread_channel_ids.discard(channel_id)
            self._populate_channels(channel_id)
        self._refresh_messages()

    def _on_channel_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        value = item.data(QtCore.Qt.UserRole)
        if value in (None, ""):
            return
        channel_id = int(value)
        if channel_id not in self._unread_channel_ids:
            return
        self._unread_channel_ids.discard(channel_id)
        self._populate_channels(channel_id)
        self._refresh_messages()

    def _on_message_selected(self) -> None:
        self._update_controls()

    def _create_channel(self) -> None:
        name, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Channel",
            "Channel name",
        )
        if not accepted:
            return
        try:
            result = self._core.command(
                "chat.create_channel",
                build_create_channel_payload(name),
            )
            channel = getattr(result, "channel", None)
            self._active_channel_id = int(channel.id) if channel is not None else None
            self.status_label.setText("Channel created.")
            self.refresh()
        except Exception as exc:
            _log.warning("Channel create failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Channel", str(exc))

    def _create_dm(self) -> None:
        dialog = DmDialog(self._core, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            result = self._core.command("chat.get_or_create_dm", dialog.payload())
            channel = getattr(result, "channel", None)
            self._active_channel_id = int(channel.id) if channel is not None else None
            self.status_label.setText("Direct message opened.")
            self.refresh()
        except Exception as exc:
            _log.warning("DM create failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Direct Message", str(exc))

    def _send_message(self) -> None:
        channel = self._selected_channel()
        if channel is None:
            self.status_label.setText("Select a channel.")
            return
        try:
            payload = build_message_payload(
                channel_id=channel.id,
                body=self.body_field.toPlainText(),
                is_urgent=self.urgent_check.isChecked(),
                grid_ref=self._pending_grid_ref,
            )
            self._core.command("chat.send_message", payload)
        except Exception as exc:
            _log.warning("Message send failed: %s", exc)
            self.status_label.setText(f"Message not sent: {exc}")
            return

        self.body_field.clear()
        self._pending_grid_ref = ""
        self.urgent_check.setChecked(False)
        self._sync_grid_button()
        self.status_label.setText("Message sent.")
        self._refresh_messages()

    def _open_grid_reference_dialog(self) -> None:
        dialog = GridReferenceDialog(
            self._core,
            current_reference=self._pending_grid_ref,
            parent=self,
        )
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        self._pending_grid_ref = dialog.reference()
        self._sync_grid_button()
        if self._pending_grid_ref:
            self.status_label.setText(f"Grid attached: {self._pending_grid_ref}")
        else:
            self.status_label.setText("Grid reference cleared.")

    def _delete_channel(self) -> None:
        channel = self._selected_channel()
        if not can_delete_channel(self._core.mode, channel):
            return
        response = QtWidgets.QMessageBox.question(
            self,
            "Delete Channel",
            f"Delete {channel.display_name} and all messages?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return
        try:
            self._core.command("chat.delete_channel", channel_id=channel.id)
        except Exception as exc:
            _log.warning("Channel delete failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Channel", str(exc))
            return
        self._active_channel_id = None
        self.status_label.setText("Channel deleted.")
        self.refresh()

    def _delete_message(self) -> None:
        message = self._selected_message()
        if not can_delete_message(self._core.mode, message):
            return
        response = QtWidgets.QMessageBox.question(
            self,
            "Delete Message",
            "Permanently delete this message?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return
        try:
            self._core.command("chat.delete_message", message_id=message.id)
        except Exception as exc:
            _log.warning("Message delete failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Message", str(exc))
            return
        self.status_label.setText("Message deleted.")
        self._refresh_messages()

    def _selected_channel(self) -> DesktopChannelItem | None:
        return self._channel_for_id(self._selected_channel_id())

    def _selected_channel_id(self) -> int | None:
        item = self.channel_list.currentItem()
        if item is None:
            return None
        value = item.data(QtCore.Qt.UserRole)
        if value in (None, ""):
            return None
        return int(value)

    def _channel_for_id(self, channel_id: int | None) -> DesktopChannelItem | None:
        if channel_id is None:
            return None
        return next((channel for channel in self._channels if channel.id == channel_id), None)

    def _selected_message(self) -> DesktopMessageItem | None:
        item = self.message_list.currentItem()
        if item is None:
            return None
        value = item.data(QtCore.Qt.UserRole)
        if value in (None, ""):
            return None
        message_id = int(value)
        return next((message for message in self._messages if message.id == message_id), None)

    def _update_controls(self) -> None:
        channel = self._selected_channel()
        message = self._selected_message()
        self.send_button.setEnabled(channel is not None)
        self.body_field.setEnabled(channel is not None)
        self.grid_button.setEnabled(channel is not None)
        self.urgent_check.setEnabled(channel is not None)
        self.delete_channel_button.setEnabled(can_delete_channel(self._core.mode, channel))
        self.delete_message_button.setEnabled(can_delete_message(self._core.mode, message))
        self._sync_grid_button()

    def _sync_grid_button(self) -> None:
        self.grid_button.setText("Grid Attached" if self._pending_grid_ref else "Grid")
        self.grid_button.setToolTip(self._pending_grid_ref or "Attach a map position")

    def _refresh_side_panel(self) -> None:
        try:
            current = self._core.read_model("chat.current_operator")
        except Exception:
            current = {}
        callsign = current.get("callsign", "") if isinstance(current, dict) else ""
        role = current.get("role", "") if isinstance(current, dict) else ""
        self.user_footer.setText(" | ".join(part for part in (callsign, role) if part))

        self.operator_list.clear()
        for operator in sorted(self._operators, key=lambda item: (not item.online, item.callsign)):
            suffix = "online" if operator.online else "offline"
            label = f"{operator.callsign}  {suffix}"
            if operator.role:
                label += f"  {operator.role}"
            item = QtWidgets.QListWidgetItem(label)
            item.setForeground(QtGui.QColor("#8fbcbb" if operator.online else "#93a1a8"))
            self.operator_list.addItem(item)
        if not self._operators:
            self.operator_list.addItem("No operators.")

        self.alert_list.clear()
        try:
            alerts = self._core.read_model("chat.alerts")
        except Exception as exc:
            self.alert_list.addItem(f"Unable to load alerts: {exc}")
            return
        for alert in alerts:
            text = str(alert.get("text", alert)) if isinstance(alert, dict) else str(alert)
            self.alert_list.addItem(text)
        if not alerts:
            self.alert_list.addItem("No urgent alerts.")

    def _sync_blink_timer(self) -> None:
        has_urgent = any(message.is_urgent for message in self._messages)
        if has_urgent and not self._blink_timer.isActive():
            self._blink_timer.start(650)
        elif not has_urgent and self._blink_timer.isActive():
            self._blink_timer.stop()

    def _blink_urgent_messages(self) -> None:
        self._blink_on = not self._blink_on
        for row in range(self.message_list.count()):
            item = self.message_list.item(row)
            if not item.data(QtCore.Qt.UserRole + 1):
                continue
            item.setBackground(
                QtGui.QColor("#532233") if self._blink_on else _URGENT_BACKGROUND
            )

    def _mark_message_channel_unread(self, message_id: int) -> None:
        try:
            context = self._core.read_model(
                "chat.message_context",
                {"message_id": int(message_id)},
            )
        except Exception as exc:
            _log.debug("Could not load message notification context: %s", exc)
            return
        if not isinstance(context, dict):
            return
        sender_id = int(context.get("sender_id", 0) or 0)
        if (
            self._core.operator_id is not None
            and sender_id == int(self._core.operator_id)
        ):
            return
        channel_id = int(context.get("channel_id", 0) or 0)
        if channel_id <= 0 or channel_id == self._selected_channel_id():
            return
        self._unread_channel_ids.add(channel_id)


def _channel_sort_key(channel: DesktopChannelItem) -> tuple[int, str]:
    order = {
        "Emergency": 0,
        "All Hands": 1,
        "Mission": 2,
        "Squad": 3,
        "Direct": 4,
    }
    return (order.get(channel.group_label, 99), channel.display_name.lower())

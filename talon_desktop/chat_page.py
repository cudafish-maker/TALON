"""PySide6 chat channels, DMs, and message composer."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from talon_core import TalonCoreSession
from talon_core.utils.logging import get_logger
from talon_desktop.chat import (
    DesktopChannelItem,
    DesktopMessageItem,
    DesktopOperatorItem,
    build_create_channel_payload,
    build_dm_payload,
    build_message_payload,
    can_delete_channel,
    can_delete_message,
    items_from_channels,
    items_from_messages,
    items_from_operators,
    operator_lookup_from_items,
)

_log = get_logger("desktop.chat")

_URGENT_BACKGROUND = QtGui.QColor("#3a1620")
_URGENT_FOREGROUND = QtGui.QColor("#f0c674")
_GRID_FOREGROUND = QtGui.QColor("#8fbcbb")


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


class ChatPage(QtWidgets.QWidget):
    """Desktop chat page backed by talon-core chat commands."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._channels: list[DesktopChannelItem] = []
        self._messages: list[DesktopMessageItem] = []
        self._operators: list[DesktopOperatorItem] = []
        self._active_channel_id: int | None = None

        self.heading = QtWidgets.QLabel("Chat")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
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
        top_row.addWidget(self.new_channel_button)
        top_row.addWidget(self.new_dm_button)
        top_row.addWidget(self.delete_channel_button)

        self.channel_list = QtWidgets.QListWidget()
        self.channel_list.setMinimumWidth(240)
        self.channel_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.channel_list.itemSelectionChanged.connect(self._on_channel_selected)

        channel_panel = QtWidgets.QWidget()
        channel_layout = QtWidgets.QVBoxLayout(channel_panel)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.addWidget(QtWidgets.QLabel("Channels"))
        channel_layout.addWidget(self.channel_list)

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
        self.grid_field = QtWidgets.QLineEdit()
        self.grid_field.setPlaceholderText("Grid reference")
        self.send_button = QtWidgets.QPushButton("Send")
        self.send_button.clicked.connect(self._send_message)
        self.delete_message_button = QtWidgets.QPushButton("Delete Message")
        self.delete_message_button.clicked.connect(self._delete_message)
        self.delete_message_button.setVisible(self._core.mode == "server")
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        composer_form = QtWidgets.QFormLayout()
        composer_form.addRow("Message", self.body_field)
        composer_form.addRow("Grid", self.grid_field)

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

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(channel_panel)
        splitter.addWidget(message_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

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
        self._refresh_messages()

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        _ = action, record_id
        if table in {"channels", "operators"}:
            self.refresh()
        elif table == "messages":
            self._refresh_messages()

    def _populate_channels(self, preferred_id: int | None) -> None:
        self.channel_list.blockSignals(True)
        try:
            self.channel_list.clear()
            for channel in self._channels:
                label = f"{channel.display_name}  [{channel.group_label}]"
                item = QtWidgets.QListWidgetItem(label)
                item.setData(QtCore.Qt.UserRole, channel.id)
                if channel.is_dm:
                    item.setToolTip(
                        "Direct messages are server-readable until Phase 2b E2E encryption lands."
                    )
                self.channel_list.addItem(item)
        finally:
            self.channel_list.blockSignals(False)

        if not self._channels:
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
        self.channel_list.setCurrentRow(0)

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

    def _message_row(self, message: DesktopMessageItem) -> QtWidgets.QListWidgetItem:
        header = f"{message.sent_time}  {message.callsign}"
        if message.is_urgent:
            header += "  URGENT"
        text = f"{header}\n{message.body}"
        if message.grid_ref:
            text += f"\nGrid: {message.grid_ref}"
        item = QtWidgets.QListWidgetItem(text)
        item.setData(QtCore.Qt.UserRole, message.id)
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
                grid_ref=self.grid_field.text(),
            )
            self._core.command("chat.send_message", payload)
        except Exception as exc:
            _log.warning("Message send failed: %s", exc)
            self.status_label.setText(f"Message not sent: {exc}")
            return

        self.body_field.clear()
        self.grid_field.clear()
        self.urgent_check.setChecked(False)
        self.status_label.setText("Message sent.")
        self._refresh_messages()

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
        self.grid_field.setEnabled(channel is not None)
        self.urgent_check.setEnabled(channel is not None)
        self.delete_channel_button.setEnabled(can_delete_channel(self._core.mode, channel))
        self.delete_message_button.setEnabled(can_delete_message(self._core.mode, message))

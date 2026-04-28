"""PySide6 SITREP feed and composer."""
from __future__ import annotations

import typing

from PySide6 import QtCore, QtGui, QtWidgets

from talon_core import TalonCoreSession
from talon_core.constants import SITREP_LEVELS
from talon_core.utils.logging import get_logger
from talon_desktop.sitreps import (
    DEFAULT_TEMPLATE_KEY,
    SITREP_TEMPLATES,
    SitrepFeedItem,
    build_create_payload,
    feed_item_from_entry,
    feed_items_from_entries,
    format_created_at,
    severity_counts,
    should_play_audio,
    sitrep_template_for_key,
)

_log = get_logger("desktop.sitreps")

_LEVEL_COLORS = {
    "ROUTINE": "#d8dee9",
    "PRIORITY": "#f0c674",
    "IMMEDIATE": "#f28c28",
    "FLASH": "#ff5555",
    "FLASH_OVERRIDE": "#ff2d75",
}


class SitrepPage(QtWidgets.QWidget):
    """Desktop SITREP feed, composer, and opt-in audio state."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._items: list[SitrepFeedItem] = []
        self._syncing_audio = False

        self.heading = QtWidgets.QLabel("SITREPs")
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.audio_toggle = QtWidgets.QCheckBox("Audio")
        self.audio_toggle.toggled.connect(self._on_audio_toggled)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.audio_toggle)
        top_row.addWidget(self.refresh_button)

        self.feed = QtWidgets.QListWidget()
        self.feed.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        self.level_combo = QtWidgets.QComboBox()
        for level in SITREP_LEVELS:
            self.level_combo.addItem(level, level)

        self.asset_combo = QtWidgets.QComboBox()
        self.mission_combo = QtWidgets.QComboBox()
        self.template_combo = QtWidgets.QComboBox()
        for template in SITREP_TEMPLATES:
            self.template_combo.addItem(template.label, template.key)
        self.template_apply_button = QtWidgets.QPushButton("Apply")
        self.template_apply_button.clicked.connect(self._apply_template)
        self.body_field = QtWidgets.QTextEdit()
        self.body_field.setPlaceholderText("Compose situation report")
        self.body_field.setMinimumHeight(180)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self.send_button = QtWidgets.QPushButton("Send")
        self.send_button.clicked.connect(self._send)
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear_composer)
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.clicked.connect(self._delete_selected)
        self.delete_button.setVisible(self._core.mode == "server")

        composer = QtWidgets.QWidget()
        composer.setMinimumWidth(340)
        composer.setMaximumWidth(420)
        form = QtWidgets.QFormLayout(composer)
        form.addRow("Severity", self.level_combo)
        form.addRow("Asset", self.asset_combo)
        form.addRow("Mission", self.mission_combo)
        template_row = QtWidgets.QHBoxLayout()
        template_row.addWidget(self.template_combo, stretch=1)
        template_row.addWidget(self.template_apply_button)
        form.addRow("Template", template_row)
        form.addRow("Body", self.body_field)
        form.addRow("", self.status_label)

        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(self.clear_button)
        action_row.addWidget(self.delete_button)
        action_row.addStretch(1)
        action_row.addWidget(self.send_button)
        form.addRow("", action_row)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self.feed)
        splitter.addWidget(composer)
        splitter.setStretchFactor(0, 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addWidget(self.summary)
        layout.addWidget(splitter, stretch=1)

    def refresh(self) -> None:
        try:
            self._sync_audio_toggle()
            self._refresh_link_selectors()
            entries = self._core.read_model("sitreps.list")
            self._items = feed_items_from_entries(entries)
        except Exception as exc:
            _log.warning("Could not refresh SITREPs: %s", exc)
            self.status_label.setText(f"Unable to refresh SITREPs: {exc}")
            return

        self.feed.clear()
        counts = severity_counts(self._items)
        self.summary.setText(
            f"{len(self._items)} total | "
            f"Priority {counts.get('PRIORITY', 0)} | "
            f"Immediate {counts.get('IMMEDIATE', 0)} | "
            f"Flash {counts.get('FLASH', 0) + counts.get('FLASH_OVERRIDE', 0)}"
        )
        if not self._items:
            self.feed.addItem("No SITREPs logged.")
            return
        for item in self._items:
            self.feed.addItem(self._list_item(item))

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        if table != "sitreps" or action != "changed":
            return
        self.refresh()

    def _send(self) -> None:
        try:
            payload = build_create_payload(
                level=str(self.level_combo.currentData()),
                body=self.body_field.toPlainText(),
                template=self._selected_template_key(),
                asset_id=self._combo_int(self.asset_combo),
                mission_id=self._combo_int(self.mission_combo),
            )
            self._core.command("sitreps.create", payload)
        except Exception as exc:
            _log.warning("Could not create SITREP: %s", exc)
            self.status_label.setText(f"SITREP not sent: {exc}")
            return

        self._clear_composer()
        self.status_label.setText("SITREP sent.")
        self.refresh()

    def _delete_selected(self) -> None:
        if self._core.mode != "server":
            return
        selected = self.feed.currentItem()
        if selected is None:
            self.status_label.setText("Select a SITREP to delete.")
            return
        sitrep_id = selected.data(QtCore.Qt.UserRole)
        if sitrep_id is None:
            return
        response = QtWidgets.QMessageBox.question(
            self,
            "Delete SITREP",
            "Permanently delete this SITREP?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return
        try:
            self._core.command("sitreps.delete", sitrep_id=int(sitrep_id))
        except Exception as exc:
            _log.warning("Could not delete SITREP: %s", exc)
            self.status_label.setText(f"SITREP not deleted: {exc}")
            return
        self.status_label.setText("SITREP deleted.")
        self.refresh()

    def _clear_composer(self) -> None:
        self.body_field.clear()
        self.asset_combo.setCurrentIndex(0)
        self.mission_combo.setCurrentIndex(0)
        self.template_combo.setCurrentIndex(0)

    def _apply_template(self) -> None:
        key = self._selected_template_id()
        if key == DEFAULT_TEMPLATE_KEY:
            self.status_label.setText("Free text template selected.")
            return
        try:
            template = sitrep_template_for_key(key)
        except KeyError as exc:
            self.status_label.setText(str(exc))
            return
        level_index = self.level_combo.findData(template.level)
        if level_index >= 0:
            self.level_combo.setCurrentIndex(level_index)
        current_body = self.body_field.toPlainText().strip()
        if current_body:
            self.body_field.append("\n" + template.body)
        else:
            self.body_field.setPlainText(template.body)
        self.status_label.setText(f"Applied template: {template.label}.")

    def _sync_audio_toggle(self) -> None:
        enabled = bool(self._core.read_model("settings.audio_enabled"))
        self._syncing_audio = True
        try:
            self.audio_toggle.setChecked(enabled)
        finally:
            self._syncing_audio = False

    def _on_audio_toggled(self, enabled: bool) -> None:
        if self._syncing_audio:
            return
        try:
            self._core.command("settings.set_audio_enabled", enabled=enabled)
        except Exception as exc:
            _log.warning("Could not persist audio setting: %s", exc)
            self.status_label.setText(f"Audio setting not saved: {exc}")
            self._sync_audio_toggle()

    def _refresh_link_selectors(self) -> None:
        current_asset = self._combo_int(self.asset_combo)
        current_mission = self._combo_int(self.mission_combo)

        self.asset_combo.blockSignals(True)
        self.mission_combo.blockSignals(True)
        try:
            self.asset_combo.clear()
            self.asset_combo.addItem("None", None)
            for asset in self._core.read_model("assets.list"):
                self.asset_combo.addItem(str(getattr(asset, "label", asset.id)), int(asset.id))
            self._restore_combo_value(self.asset_combo, current_asset)

            self.mission_combo.clear()
            self.mission_combo.addItem("None", None)
            for mission in self._core.read_model("missions.list", {"status_filter": None}):
                if getattr(mission, "status", "") not in ("pending_approval", "active"):
                    continue
                label = f"{mission.title} [{mission.status}]"
                self.mission_combo.addItem(label, int(mission.id))
            self._restore_combo_value(self.mission_combo, current_mission)
        finally:
            self.asset_combo.blockSignals(False)
            self.mission_combo.blockSignals(False)

    def _list_item(self, item: SitrepFeedItem) -> QtWidgets.QListWidgetItem:
        label = (
            f"{format_created_at(item.created_at)}  {item.level}  "
            f"{item.callsign}: {item.body}"
        )
        if item.asset_label:
            label += f"  [asset: {item.asset_label}]"
        if item.mission_id is not None:
            label += f"  [mission #{item.mission_id}]"
        widget_item = QtWidgets.QListWidgetItem(label)
        widget_item.setData(QtCore.Qt.UserRole, item.id)
        color = _LEVEL_COLORS.get(item.level)
        if color:
            widget_item.setForeground(QtGui.QColor(color))
        if item.is_flash:
            widget_item.setBackground(QtGui.QColor("#3a1620"))
        return widget_item

    @staticmethod
    def _combo_int(combo: QtWidgets.QComboBox) -> int | None:
        value = combo.currentData()
        if value in (None, ""):
            return None
        return int(typing.cast(int, value))

    @staticmethod
    def _restore_combo_value(combo: QtWidgets.QComboBox, value: int | None) -> None:
        if value is None:
            combo.setCurrentIndex(0)
            return
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _selected_template_key(self) -> str:
        key = self._selected_template_id()
        return "" if key == DEFAULT_TEMPLATE_KEY else key

    def _selected_template_id(self) -> str:
        return str(self.template_combo.currentData() or DEFAULT_TEMPLATE_KEY)


class SitrepAlertOverlay(QtWidgets.QFrame):
    """Non-modal dashboard overlay for high-severity SITREP events."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("sitrepAlertOverlay")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self._item: SitrepFeedItem | None = None
        self._auto_hide_timer = QtCore.QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self.hide)

        self.title = QtWidgets.QLabel("")
        self.title.setObjectName("sitrepAlertTitle")
        self.meta = QtWidgets.QLabel("")
        self.meta.setObjectName("sitrepAlertMeta")
        self.body = QtWidgets.QLabel("")
        self.body.setObjectName("sitrepAlertBody")
        self.body.setWordWrap(True)
        self.links = QtWidgets.QLabel("")
        self.links.setObjectName("sitrepAlertMeta")
        self.links.setWordWrap(True)
        self.ack_button = QtWidgets.QPushButton("Acknowledge")
        self.ack_button.clicked.connect(self.hide)

        header = QtWidgets.QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.ack_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.meta)
        layout.addWidget(self.body)
        layout.addWidget(self.links)
        self.hide()

    def show_item(self, item: SitrepFeedItem, *, audio_enabled: bool) -> None:
        self._item = item
        severity = item.level.lower()
        self.setProperty("severity", severity)
        self.title.setText(f"{item.level} SITREP")
        self.title.setStyleSheet(f"color: {_LEVEL_COLORS.get(item.level, '#f6fbfb')};")
        self.meta.setText(f"{item.callsign} | {format_created_at(item.created_at)}")
        self.body.setText(item.body)
        link_parts = []
        if item.asset_label:
            link_parts.append(f"Asset: {item.asset_label}")
        elif item.asset_id is not None:
            link_parts.append(f"Asset #{item.asset_id}")
        if item.mission_id is not None:
            link_parts.append(f"Mission #{item.mission_id}")
        self.links.setText(" | ".join(link_parts))
        self.links.setVisible(bool(link_parts))
        self.style().unpolish(self)
        self.style().polish(self)
        self.reposition()
        self.show()
        self.raise_()
        if item.level in {"ROUTINE", "PRIORITY"}:
            self._auto_hide_timer.start(5000)
        else:
            self._auto_hide_timer.stop()

        if should_play_audio(item.level, audio_enabled):
            QtWidgets.QApplication.beep()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        margin = 18
        width = max(360, parent.width() - (margin * 2))
        hint_height = max(132, self.sizeHint().height())
        height = min(hint_height, max(132, parent.height() - (margin * 2)))
        self.setGeometry(margin, margin, width, height)


def latest_sitrep_item(core: TalonCoreSession, record_id: int) -> SitrepFeedItem | None:
    """Load a changed SITREP from the current feed window if present."""
    for entry in core.read_model("sitreps.list"):
        item = feed_item_from_entry(entry)
        if item.id == record_id:
            return item
    return None

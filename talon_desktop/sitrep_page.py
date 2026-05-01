"""PySide6 SITREP feed and popup composer."""
from __future__ import annotations

import typing

from PySide6 import QtCore, QtGui, QtWidgets

from talon_core import TalonCoreSession
from talon_core.constants import SITREP_LEVELS
from talon_core.utils.logging import get_logger
from talon_desktop.map_picker import MapCoordinateDialog, format_coordinate
from talon_desktop.sitreps import (
    SitrepFeedItem,
    available_operator_items,
    build_create_payload,
    build_filter_payload,
    feed_item_from_entry,
    feed_items_from_entries,
    format_created_at,
    severity_counts,
    should_play_audio,
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
    """Desktop SITREP feed, selected-detail actions, and opt-in audio state."""

    def __init__(self, core: TalonCoreSession) -> None:
        super().__init__()
        self._core = core
        self._items: list[SitrepFeedItem] = []
        self._syncing_audio = False

        self.heading = QtWidgets.QLabel("SITREPs")
        self.heading.setObjectName("pageHeading")
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("sitrepMutedLabel")
        self.status_label.setWordWrap(True)

        self.level_filter = QtWidgets.QComboBox()
        self.level_filter.addItem("All levels", "")
        for level in SITREP_LEVELS:
            self.level_filter.addItem(level, level)
        self.level_filter.currentIndexChanged.connect(lambda _index: self.refresh())
        self.show_closed_filter = QtWidgets.QCheckBox("Show closed")
        self.show_closed_filter.toggled.connect(lambda _checked: self.refresh())

        self.new_button = QtWidgets.QPushButton("New SITREP")
        self.new_button.clicked.connect(self._open_create_dialog)
        self.audio_toggle = QtWidgets.QCheckBox("Audio")
        self.audio_toggle.toggled.connect(self._on_audio_toggled)
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.new_button)
        top_row.addWidget(self.audio_toggle)
        top_row.addWidget(self.refresh_button)

        self.level_counts: dict[str, _SitrepMetricBox] = {}
        count_row = QtWidgets.QHBoxLayout()
        for level in SITREP_LEVELS:
            metric = _SitrepMetricBox(level.replace("_", " "), "0", "")
            if level in {"FLASH", "FLASH_OVERRIDE"}:
                metric.setProperty("tone", "alert")
            elif level == "IMMEDIATE":
                metric.setProperty("tone", "warn")
            self.level_counts[level] = metric
            count_row.addWidget(metric)
        self.pending_metric = _SitrepMetricBox("Pending", "0", "")
        count_row.addWidget(self.pending_metric)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.addWidget(_field_widget("Level", self.level_filter), stretch=1)
        filter_row.addWidget(self.show_closed_filter)
        filter_row.addStretch(3)

        self.feed = QtWidgets.QListWidget()
        self.feed.setObjectName("sitrepFeedList")
        self.feed.setSpacing(6)
        self.feed.setUniformItemSizes(False)
        self.feed.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.feed.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.feed.itemSelectionChanged.connect(self._selection_changed)
        self._feed_cards: dict[int, _SitrepFeedCard] = {}

        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.clicked.connect(self._delete_selected)
        self.delete_button.setVisible(self._core.mode == "server")
        self.delete_button.setEnabled(False)
        self.assign_button = QtWidgets.QPushButton("Assign")
        self.assign_button.clicked.connect(self._assign_selected)
        self.assign_button.setEnabled(False)
        self.append_button = QtWidgets.QPushButton("Append")
        self.append_button.clicked.connect(self._append_selected)
        self.append_button.setEnabled(False)
        self.detail_title_label = QtWidgets.QLabel("Select a SITREP")
        self.detail_title_label.setObjectName("sitrepDetailTitle")
        self.detail_status_tag = _tag_label("Open")
        self.detail_context_label = QtWidgets.QLabel("")
        self.detail_context_label.setObjectName("sitrepMutedLabel")
        self.detail_context_label.setWordWrap(True)
        self.detail_body_field = QtWidgets.QTextEdit()
        self.detail_body_field.setObjectName("sitrepDetailBody")
        self.detail_body_field.setReadOnly(True)
        self.detail_body_field.setAcceptRichText(False)
        self.detail_body_field.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
        self.detail_body_field.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.detail_body_field.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.detail_body_field.setMinimumHeight(118)
        self.detail_body_field.setMaximumHeight(190)
        self.detail_body_field.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed,
        )
        self.activity_list = QtWidgets.QListWidget()
        self.activity_list.setObjectName("sitrepActivityList")
        self.activity_list.setSpacing(8)
        self.activity_list.setUniformItemSizes(False)
        self.activity_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.activity_list.setMinimumHeight(160)
        self.append_field = QtWidgets.QTextEdit()
        self.append_field.setAcceptRichText(False)
        self.append_field.setPlaceholderText("Add information")
        self.append_field.setMinimumHeight(78)
        self.append_field.setMaximumHeight(110)

        feed_body = QtWidgets.QWidget()
        feed_layout = QtWidgets.QVBoxLayout(feed_body)
        feed_layout.setContentsMargins(0, 0, 0, 0)
        feed_layout.setSpacing(10)
        feed_layout.addWidget(self.feed, stretch=1)
        feed_panel = _panel("SITREP List", feed_body)
        feed_panel.setMinimumWidth(260)

        detail_card = QtWidgets.QFrame()
        detail_card.setObjectName("sitrepDetailCard")
        detail_card_layout = QtWidgets.QVBoxLayout(detail_card)
        detail_card_layout.addWidget(self.detail_title_label)
        detail_card_layout.addWidget(self.detail_context_label)
        detail_card_layout.addWidget(self.detail_body_field)
        append_row = QtWidgets.QHBoxLayout()
        append_row.addWidget(self.append_field, stretch=1)
        append_row.addWidget(self.assign_button)
        append_row.addWidget(self.append_button)
        detail_card_layout.addLayout(append_row)
        if self._core.mode == "server":
            delete_row = QtWidgets.QHBoxLayout()
            delete_label = QtWidgets.QLabel("Server-only destructive control")
            delete_label.setObjectName("sitrepMutedLabel")
            delete_row.addWidget(delete_label, stretch=1)
            delete_row.addWidget(self.delete_button)
            detail_card_layout.addLayout(delete_row)

        detail = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(10)
        detail_layout.addWidget(detail_card)
        detail_layout.addWidget(self.activity_list, stretch=1)
        detail_panel = _panel(
            "Selected Detail",
            detail,
            extra_widgets=(self.detail_status_tag,),
        )
        detail_panel.setMinimumWidth(240)

        splitter = _SitrepCommandSplitter()
        splitter.addWidget(feed_panel)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([620, 360])

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addLayout(count_row)
        layout.addLayout(filter_row)
        layout.addWidget(self.status_label)
        layout.addWidget(splitter, stretch=1)

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

    def _list_item(self, item: SitrepFeedItem) -> QtWidgets.QListWidgetItem:
        widget_item = QtWidgets.QListWidgetItem()
        widget_item.setData(QtCore.Qt.UserRole, item.id)
        return widget_item

    def _add_activity_card(self, title: str, note: str) -> None:
        item = QtWidgets.QListWidgetItem()
        card = _SitrepActivityCard(title, note)
        item.setSizeHint(card.sizeHint())
        self.activity_list.addItem(item)
        self.activity_list.setItemWidget(item, card)

    def _sync_feed_card_selection(self, selected_id: int | None) -> None:
        for item_id, card in self._feed_cards.items():
            card.set_selected(selected_id == item_id)

    def _selected_sitrep_id(self) -> int | None:
        selected = self.feed.currentItem()
        if selected is None:
            return None
        value = selected.data(QtCore.Qt.UserRole)
        if value is None:
            return None
        return int(value)

    def select_sitrep(self, sitrep_id: int) -> None:
        all_index = self.level_filter.findData("")
        if all_index >= 0 and self.level_filter.currentIndex() != all_index:
            self.level_filter.blockSignals(True)
            self.level_filter.setCurrentIndex(all_index)
            self.level_filter.blockSignals(False)
        if not self.show_closed_filter.isChecked():
            self.show_closed_filter.blockSignals(True)
            self.show_closed_filter.setChecked(True)
            self.show_closed_filter.blockSignals(False)
        self.refresh()
        for row, item in enumerate(self._items):
            if item.id == int(sitrep_id):
                self.feed.setCurrentRow(row)
                break

    def refresh(self) -> None:
        selected_id = self._selected_sitrep_id()
        try:
            self._sync_audio_toggle()
            base_filters = build_filter_payload(
                unresolved_only=not self.show_closed_filter.isChecked(),
            )
            all_entries = self._core.read_model("sitreps.list", base_filters)
            all_items = feed_items_from_entries(all_entries)
        except Exception as exc:
            _log.warning("Could not refresh SITREPs: %s", exc)
            self.status_label.setText(f"Unable to refresh SITREPs: {exc}")
            return

        level_filter = str(self.level_filter.currentData() or "")
        self._items = [
            item for item in all_items if not level_filter or item.level == level_filter
        ]
        self._update_level_strip(all_items)
        self.feed.clear()
        self._feed_cards.clear()
        if not self._items:
            self.feed.addItem("No SITREPs logged.")
            self._selection_changed()
            return
        restore_row = 0
        for index, item in enumerate(self._items):
            widget_item = self._list_item(item)
            self.feed.addItem(widget_item)
            card = _SitrepFeedCard(item)
            self.feed.setItemWidget(widget_item, card)
            widget_item.setSizeHint(card.sizeHint())
            self._feed_cards[item.id] = card
            if item.id == selected_id:
                restore_row = index
        self.feed.setCurrentRow(restore_row)
        self._selection_changed()

    def _update_level_strip(self, items: list[SitrepFeedItem]) -> None:
        counts = severity_counts(items)
        for level, metric in self.level_counts.items():
            metric.set_metric(str(counts.get(level, 0)), "")
        pending = 0
        try:
            dashboard = self._core.read_model("dashboard.summary")
            sync = getattr(dashboard, "sync", None)
            pending_by_table = getattr(sync, "pending_outbox_by_table", {}) or {}
            pending = sum(
                int(pending_by_table.get(table, 0) or 0)
                for table in ("sitreps", "sitrep_followups")
            )
        except Exception:
            pending = 0
        self.pending_metric.set_metric(str(pending), "")

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        if action != "changed":
            return
        if table in {"sitreps", "sitrep_followups", "assignments", "operators"}:
            self.refresh()

    def _selection_changed(self) -> None:
        sitrep_id = self._selected_sitrep_id()
        has_selection = sitrep_id is not None
        self._sync_feed_card_selection(sitrep_id)
        self.append_button.setEnabled(has_selection)
        self.assign_button.setEnabled(has_selection)
        if self._core.mode == "server":
            self.delete_button.setEnabled(has_selection)
        if sitrep_id is None:
            self._clear_detail_panel()
            return
        try:
            detail = self._core.read_model("sitreps.detail", {"sitrep_id": sitrep_id})
        except Exception as exc:
            self.detail_title_label.setText("Unable to load SITREP detail")
            self.detail_context_label.clear()
            self.detail_body_field.setPlainText(str(exc))
            self.activity_list.clear()
            return
        sitrep = detail["sitrep"]
        title = f"{sitrep.level} SITREP #{sitrep.id}"
        if sitrep.assigned_to:
            title += f" / {sitrep.assigned_to}"
        self.detail_title_label.setText(title)
        self.detail_status_tag.setText(_status_label(sitrep.status))
        self.detail_status_tag.setProperty("tone", _tone_for_text(sitrep.status))
        self.detail_status_tag.style().unpolish(self.detail_status_tag)
        self.detail_status_tag.style().polish(self.detail_status_tag)
        self.detail_context_label.setText(self._detail_context_text(detail))
        self.detail_body_field.setPlainText(_as_text(sitrep.body) or "No body.")

        self.activity_list.clear()
        followups = list(detail.get("followups", []))
        for item in followups[-10:]:
            self._add_activity_card(
                f"{format_created_at(item.created_at)} {item.action.replace('_', ' ').title()}",
                self._followup_note(item),
            )
        if self.activity_list.count() == 0:
            self._add_activity_card("No appended information yet.", "Append updates will appear here.")

    def _detail_context_text(self, detail: dict[str, typing.Any]) -> str:
        sitrep = detail["sitrep"]
        parts = [
            str(detail.get("callsign", "") or "UNKNOWN"),
            format_created_at(sitrep.created_at),
            _status_label(sitrep.status),
        ]
        if sitrep.location_label:
            parts.append(sitrep.location_label)
        if sitrep.assigned_to:
            parts.append(f"Assigned: {sitrep.assigned_to}")
        else:
            parts.append("Unassigned")
        links: list[str] = []
        if detail.get("mission_title") or sitrep.mission_id:
            links.append(f"Mission: {detail.get('mission_title') or sitrep.mission_id}")
        if detail.get("assignment_title") or sitrep.assignment_id:
            links.append(f"Assignment: {detail.get('assignment_title') or sitrep.assignment_id}")
        if detail.get("asset_label") or sitrep.asset_id:
            links.append(f"Asset: {detail.get('asset_label') or sitrep.asset_id}")
        return " | ".join([*parts, *links])

    def _followup_note(self, item: object) -> str:
        action = str(getattr(item, "action", "") or "")
        note = str(getattr(item, "note", "") or "")
        assigned_to = str(getattr(item, "assigned_to", "") or "")
        status = str(getattr(item, "status", "") or "")
        if action == "assigned":
            label = f"Assigned to {assigned_to or note or 'operator'}"
            return f"{label}. {note}" if note and note != assigned_to else label
        if action in {"status", "resolved"}:
            return note or status or "Status updated."
        return note or assigned_to or status or "Information appended."

    def _clear_detail_panel(self) -> None:
        self.detail_title_label.setText("Select a SITREP")
        self.detail_status_tag.setText("Open")
        self.detail_status_tag.setProperty("tone", "red")
        self.detail_status_tag.style().unpolish(self.detail_status_tag)
        self.detail_status_tag.style().polish(self.detail_status_tag)
        self.detail_context_label.clear()
        self.detail_body_field.clear()
        self.append_field.clear()
        self.activity_list.clear()

    def _append_selected(self) -> None:
        sitrep_id = self._selected_sitrep_id()
        if sitrep_id is None:
            return
        note = self.append_field.toPlainText().strip()
        if not note:
            self.status_label.setText("Append text is required.")
            return
        try:
            self._core.command(
                "sitreps.append_note",
                {"sitrep_id": sitrep_id, "note": note},
            )
        except Exception as exc:
            _log.warning("SITREP append failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "SITREP", str(exc))
            return
        self.append_field.clear()
        self.status_label.setText("Information appended.")
        self.refresh()

    def _assign_selected(self) -> None:
        sitrep_id = self._selected_sitrep_id()
        if sitrep_id is None:
            return
        dialog = SitrepAssignDialog(self._core, sitrep_id=sitrep_id, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            payload = dialog.payload()
            payload["sitrep_id"] = sitrep_id
            self._core.command("sitreps.assign_followup", payload)
        except Exception as exc:
            _log.warning("SITREP assign failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "SITREP", str(exc))
            return
        self.status_label.setText("SITREP assigned.")
        self.refresh()

    def _open_create_dialog(self) -> None:
        dialog = SitrepCreateDialog(self._core, parent=self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            self._core.command("sitreps.create", dialog.payload())
        except Exception as exc:
            _log.warning("Could not create SITREP: %s", exc)
            QtWidgets.QMessageBox.warning(self, "SITREP", f"SITREP not sent: {exc}")
            return
        self.status_label.setText("SITREP sent.")
        self.refresh()


def _panel(
    title: str,
    body: QtWidgets.QWidget,
    tags: tuple[str, ...] = (),
    extra_widgets: tuple[QtWidgets.QWidget, ...] = (),
) -> QtWidgets.QFrame:
    panel = QtWidgets.QFrame()
    panel.setObjectName("sitrepPanel")
    panel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
    layout = QtWidgets.QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    header = QtWidgets.QWidget()
    header.setObjectName("sitrepPanelHeader")
    header_layout = QtWidgets.QHBoxLayout(header)
    header_layout.setContentsMargins(10, 8, 10, 8)
    header_layout.setSpacing(6)
    label = QtWidgets.QLabel(title)
    label.setObjectName("sitrepPanelTitle")
    header_layout.addWidget(label, stretch=1)
    for tag in tags:
        header_layout.addWidget(_tag_label(tag))
    for widget in extra_widgets:
        header_layout.addWidget(widget)
    layout.addWidget(header)
    body_holder = QtWidgets.QWidget()
    body_holder.setObjectName("sitrepPanelBody")
    body_layout = QtWidgets.QVBoxLayout(body_holder)
    body_layout.setContentsMargins(10, 10, 10, 10)
    body_layout.addWidget(body)
    layout.addWidget(body_holder, stretch=1)
    return panel


def _field_widget(label: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
    holder = QtWidgets.QWidget()
    holder.setObjectName("sitrepField")
    layout = QtWidgets.QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    caption = QtWidgets.QLabel(label)
    caption.setObjectName("sitrepFieldLabel")
    layout.addWidget(caption)
    layout.addWidget(widget)
    return holder


def _tag_label(text: str, tone: str = "") -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("sitrepTag")
    label.setProperty("tone", tone or _tone_for_text(text))
    return label


def _tone_for_text(text: str) -> str:
    lowered = text.lower()
    if "flash" in lowered or "open" in lowered:
        return "red"
    if "immediate" in lowered or "assigned" in lowered:
        return "orange"
    if "location" in lowered or "ack" in lowered:
        return "blue"
    if "closed" in lowered or "resolved" in lowered:
        return "green"
    return ""


class _SitrepMetricBox(QtWidgets.QFrame):
    def __init__(self, title: str, value: str, subtitle: str, tone: str = "") -> None:
        super().__init__()
        self.setObjectName("sitrepMetric")
        self.setProperty("tone", tone)
        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("sitrepMetricTitle")
        self.value = QtWidgets.QLabel(value)
        self.value.setObjectName("sitrepMetricValue")
        self.subtitle = QtWidgets.QLabel(subtitle)
        self.subtitle.setObjectName("sitrepMetricSubtitle")
        self.subtitle.setWordWrap(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.subtitle)

    def set_metric(self, value: str, subtitle: str) -> None:
        self.value.setText(value)
        self.subtitle.setText(subtitle)


class _SitrepFeedCard(QtWidgets.QFrame):
    def __init__(self, item: SitrepFeedItem) -> None:
        super().__init__()
        self.setObjectName("sitrepFeedCard")
        self.setProperty("severity", item.level.lower())
        self.setProperty("selected", False)
        self.setMinimumHeight(112)
        stamp = QtWidgets.QLabel(format_created_at(item.created_at).replace(" ", "\n"))
        stamp.setObjectName("sitrepFeedStamp")
        title = QtWidgets.QLabel(f"{item.level} / {item.callsign}")
        title.setObjectName("sitrepFeedTitle")
        title.setWordWrap(False)
        body = QtWidgets.QLabel(item.body)
        body.setObjectName("sitrepFeedBody")
        body.setWordWrap(True)
        body.setMinimumHeight(34)
        meta_parts: list[str] = []
        if item.location_label:
            meta_parts.append(f"Location: {item.location_label}")
        elif item.has_location:
            meta_parts.append("Location linked")
        if item.assignment_id is not None:
            meta_parts.append("Assignment")
        if item.asset_label:
            meta_parts.append(f"Asset: {item.asset_label}")
        if item.mission_id is not None:
            meta_parts.append("Mission")
        meta = QtWidgets.QLabel(" | ".join(meta_parts) or "No links")
        meta.setObjectName("sitrepFeedMeta")
        meta.setWordWrap(True)
        text_layout = QtWidgets.QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        text_layout.addWidget(title)
        text_layout.addWidget(body)
        text_layout.addWidget(meta)
        status = _tag_label(_status_label(item.status), _tone_for_text(item.status))
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setHorizontalSpacing(10)
        layout.addWidget(stamp, 0, 0)
        layout.addLayout(text_layout, 0, 1)
        layout.addWidget(status, 0, 2, QtCore.Qt.AlignTop)
        layout.setColumnStretch(1, 1)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(360, 118)


class _SitrepActivityCard(QtWidgets.QFrame):
    def __init__(self, title: str, note: str) -> None:
        super().__init__()
        self.setObjectName("sitrepActivityCard")
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("sitrepActivityTitle")
        title_label.setWordWrap(True)
        note_label = QtWidgets.QLabel(note)
        note_label.setObjectName("sitrepActivityNote")
        note_label.setWordWrap(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        layout.addWidget(title_label)
        layout.addWidget(note_label)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(260, 68)


def _status_label(status: str) -> str:
    if status == "acknowledged":
        return "Acked"
    return status.replace("_", " ").title() if status else "Open"


class _SitrepCommandSplitter(QtWidgets.QSplitter):
    """SITREP splitter that recovers from stale persisted sizes."""

    def __init__(self) -> None:
        super().__init__(QtCore.Qt.Horizontal)
        self.setChildrenCollapsible(False)

    def restoreState(self, state: QtCore.QByteArray) -> bool:
        restored = super().restoreState(state)
        QtCore.QTimer.singleShot(0, self.ensure_command_sizes)
        return restored

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self.ensure_command_sizes)

    def ensure_command_sizes(self) -> None:
        sizes = self.sizes()
        if self.count() != 2:
            return
        if len(sizes) != 2 or sizes[1] < 240 or min(sizes) <= 0:
            width = max(780, sum(sizes) or self.width())
            self.setSizes([int(width * 0.63), int(width * 0.37)])


class SitrepCreateDialog(QtWidgets.QDialog):
    """Minimal SITREP composer with optional collapsed context."""

    def __init__(self, core: TalonCoreSession, parent=None) -> None:
        super().__init__(parent)
        self._core = core
        self._asset_locations: dict[int, tuple[str, float, float]] = {}
        self._location_source = ""
        self.setWindowTitle("New SITREP")
        self.setMinimumSize(980, 620)

        self.level_combo = QtWidgets.QComboBox()
        for level in SITREP_LEVELS:
            self.level_combo.addItem(level, level)
        self.body_field = QtWidgets.QTextEdit()
        self.body_field.setAcceptRichText(False)
        self.body_field.setPlaceholderText("Describe the situation")
        self.body_field.setMinimumHeight(160)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("sitrepMutedLabel")
        self.status_label.setWordWrap(True)

        self.context_group = QtWidgets.QGroupBox("Optional context")
        self.context_group.setCheckable(True)
        self.context_group.setChecked(True)
        self.context_group.toggled.connect(self._sync_context_visibility)
        self.asset_combo = QtWidgets.QComboBox()
        self.mission_combo = QtWidgets.QComboBox()
        self.assignment_combo = QtWidgets.QComboBox()
        self.location_label_field = QtWidgets.QLineEdit()
        self.location_label_field.setPlaceholderText("Location label")
        self.lat_field = QtWidgets.QLineEdit()
        self.lat_field.setPlaceholderText("Latitude")
        self.lon_field = QtWidgets.QLineEdit()
        self.lon_field.setPlaceholderText("Longitude")
        self.pick_location_button = QtWidgets.QPushButton("Pick on Map")
        self.pick_location_button.clicked.connect(self._pick_location_on_map)
        self.asset_location_button = QtWidgets.QPushButton("Use Asset Position")
        self.asset_location_button.clicked.connect(self._use_asset_position)
        self.clear_location_button = QtWidgets.QPushButton("Clear")
        self.clear_location_button.clicked.connect(self._clear_location)

        context_form = QtWidgets.QFormLayout(self.context_group)
        context_form.addRow("Mission", self.mission_combo)
        context_form.addRow("Assignment", self.assignment_combo)
        context_form.addRow("Asset", self.asset_combo)
        context_form.addRow("Location", self.location_label_field)
        coord_row = QtWidgets.QWidget()
        coord_layout = QtWidgets.QGridLayout(coord_row)
        coord_layout.setContentsMargins(0, 0, 0, 0)
        coord_layout.addWidget(self.lat_field, 0, 0)
        coord_layout.addWidget(self.lon_field, 0, 1)
        coord_layout.addWidget(self.pick_location_button, 1, 0)
        coord_layout.addWidget(self.asset_location_button, 1, 1)
        coord_layout.addWidget(self.clear_location_button, 1, 2)
        context_form.addRow("Lat / Lon", coord_row)

        form = QtWidgets.QFormLayout()
        form.addRow("Level", self.level_combo)
        form.addRow("Body", self.body_field)
        form.addRow("", self.context_group)
        form.addRow("", self.status_label)

        form_page = QtWidgets.QWidget()
        form_page.setLayout(form)

        self.map_picker = MapCoordinateDialog(
            core=self._core,
            title="SITREP Location",
            mode="point",
            parent=self,
        )
        self.map_picker.setWindowFlags(QtCore.Qt.Widget)
        self.map_picker.setMinimumSize(420, 460)
        self.map_picker.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        self.map_picker.cancel_button.setVisible(False)
        self.map_picker.use_button.clicked.disconnect()
        self.map_picker.use_button.clicked.connect(self._apply_map_location)
        self.map_picker.selectionChanged.connect(self._sync_map_apply_state)
        self._configure_location_picker()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Send")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        content = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        content.addWidget(form_page)
        content.addWidget(self.map_picker)
        content.setStretchFactor(0, 3)
        content.setStretchFactor(1, 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(content, stretch=1)
        layout.addWidget(buttons)
        self._refresh_link_selectors()
        self._sync_context_visibility(True)
        self._sync_map_apply_state()

    def payload(self) -> dict[str, object]:
        use_context = self.context_group.isChecked()
        payload = build_create_payload(
            level=str(self.level_combo.currentData()),
            body=self.body_field.toPlainText(),
            asset_id=self._combo_int(self.asset_combo) if use_context else None,
            mission_id=self._combo_int(self.mission_combo) if use_context else None,
            assignment_id=self._combo_int(self.assignment_combo) if use_context else None,
            location_label=self.location_label_field.text() if use_context else "",
            lat_text=self.lat_field.text() if use_context else "",
            lon_text=self.lon_field.text() if use_context else "",
            location_source=(self._location_source or "manual")
            if use_context
            and (
                self.location_label_field.text().strip()
                or self.lat_field.text().strip()
                or self.lon_field.text().strip()
            )
            else "",
        )
        return {key: value for key, value in payload.items() if value is not None}

    def accept(self) -> None:
        try:
            self.payload()
        except Exception as exc:
            self.status_label.setText(str(exc))
            return
        super().accept()

    def _refresh_link_selectors(self) -> None:
        self.asset_combo.clear()
        self.asset_combo.addItem("None", None)
        self.mission_combo.clear()
        self.mission_combo.addItem("None", None)
        self.assignment_combo.clear()
        self.assignment_combo.addItem("None", None)
        self._asset_locations.clear()
        try:
            for asset in self._core.read_model("assets.list"):
                asset_id = int(getattr(asset, "id"))
                label = str(getattr(asset, "label", asset.id))
                self.asset_combo.addItem(label, asset_id)
                lat = getattr(asset, "lat", None)
                lon = getattr(asset, "lon", None)
                if lat is not None and lon is not None:
                    self._asset_locations[asset_id] = (label, float(lat), float(lon))
            for mission in self._core.read_model("missions.list", {"status_filter": None}):
                if getattr(mission, "status", "") not in ("pending_approval", "active"):
                    continue
                self.mission_combo.addItem(str(getattr(mission, "title", "Mission")), int(mission.id))
            for assignment in self._core.read_model("assignments.list", {"active_only": True}):
                self.assignment_combo.addItem(
                    str(getattr(assignment, "title", "Assignment")),
                    int(assignment.id),
                )
        except Exception as exc:
            _log.warning("Could not load SITREP context selectors: %s", exc)
            self.status_label.setText(f"Unable to load optional context: {exc}")

    def _sync_context_visibility(self, checked: bool) -> None:
        for widget in (
            self.asset_combo,
            self.mission_combo,
            self.assignment_combo,
            self.location_label_field,
            self.lat_field,
            self.lon_field,
            self.pick_location_button,
            self.asset_location_button,
            self.clear_location_button,
            self.map_picker,
        ):
            widget.setVisible(checked)
        form = self.context_group.layout()
        if form is not None:
            for index in range(form.count()):
                item = form.itemAt(index)
                if item is not None and item.widget() is not None:
                    item.widget().setVisible(checked)

    @staticmethod
    def _combo_int(combo: QtWidgets.QComboBox) -> int | None:
        value = combo.currentData()
        if value in (None, ""):
            return None
        return int(typing.cast(int, value))

    def _configure_location_picker(self) -> None:
        initial: list[tuple[float, float]] = []
        try:
            if self.lat_field.text().strip() and self.lon_field.text().strip():
                initial = [(float(self.lat_field.text()), float(self.lon_field.text()))]
        except ValueError:
            initial = []
        self.map_picker.configure_selection(
            title="SITREP Location",
            mode="point",
            initial_points=initial,
            minimum_points=1,
        )
        self.map_picker.use_button.setText("Use Selected")
        self._sync_map_apply_state()

    def _pick_location_on_map(self) -> None:
        self._configure_location_picker()
        self.status_label.setText("Map target: SITREP location.")

    def _apply_map_location(self) -> None:
        error = self.map_picker.selection_error()
        if error:
            self.status_label.setText(error)
            return
        selected = self.map_picker.selected_points
        if not selected:
            self.status_label.setText("Select a map point first.")
            return
        lat, lon = selected[0]
        self.lat_field.setText(f"{lat:.6f}")
        self.lon_field.setText(f"{lon:.6f}")
        if not self.location_label_field.text().strip():
            self.location_label_field.setText("Map point")
        self._location_source = "map"
        self.status_label.setText(f"Applied SITREP location: {format_coordinate(lat, lon)}.")
        self._sync_map_apply_state()

    def _sync_map_apply_state(self) -> None:
        self.map_picker.use_button.setEnabled(not self.map_picker.selection_error())

    def _use_asset_position(self) -> None:
        asset_id = self._combo_int(self.asset_combo)
        if asset_id is None or asset_id not in self._asset_locations:
            self.status_label.setText("Select an asset with a saved position.")
            return
        label, lat, lon = self._asset_locations[asset_id]
        self.location_label_field.setText(label)
        self.lat_field.setText(f"{lat:.6f}")
        self.lon_field.setText(f"{lon:.6f}")
        self._location_source = "asset"
        self._configure_location_picker()
        self.status_label.setText(f"Applied asset position: {label}.")

    def _clear_location(self) -> None:
        self.location_label_field.clear()
        self.lat_field.clear()
        self.lon_field.clear()
        self._location_source = ""
        self._configure_location_picker()
        self.status_label.clear()


class SitrepAssignDialog(QtWidgets.QDialog):
    """Assign a SITREP to an operator who is not committed elsewhere."""

    def __init__(self, core: TalonCoreSession, *, sitrep_id: int, parent=None) -> None:
        super().__init__(parent)
        self._core = core
        self._sitrep_id = int(sitrep_id)
        self.setWindowTitle("Assign Operator")
        self.resize(460, 420)

        self.operator_list = QtWidgets.QListWidget()
        self.operator_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.operator_list.setMinimumHeight(220)
        self.note_field = QtWidgets.QLineEdit()
        self.note_field.setPlaceholderText("Optional short note")
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("sitrepMutedLabel")
        self.status_label.setWordWrap(True)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.assign_button = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        self.assign_button.setText("Assign Selected")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(_field_widget("Available operators", self.operator_list))
        layout.addWidget(_field_widget("Assignment note", self.note_field))
        layout.addWidget(self.status_label)
        layout.addWidget(buttons)
        self._load_available_operators()

    def payload(self) -> dict[str, object]:
        selected = self.operator_list.currentItem()
        if selected is None:
            raise ValueError("Select an available operator.")
        callsign = str(selected.data(QtCore.Qt.UserRole + 1) or selected.text()).strip()
        note = self.note_field.text().strip()
        return {
            "assigned_to": callsign,
            "note": note,
        }

    def accept(self) -> None:
        try:
            self.payload()
        except Exception as exc:
            self.status_label.setText(str(exc))
            return
        super().accept()

    def _load_available_operators(self) -> None:
        try:
            operators = self._core.read_model("operators.list")
            assignments = self._core.read_model("assignments.list", {"active_only": True})
            sitreps = self._core.read_model(
                "sitreps.list",
                {"unresolved_only": True, "limit": 500},
            )
            missions = self._core.read_model("missions.list", {"status_filter": None})
            items = available_operator_items(
                operators,
                assignments=assignments,
                sitreps=sitreps,
                missions=missions,
                current_sitrep_id=self._sitrep_id,
            )
        except Exception as exc:
            _log.warning("Could not load available operators: %s", exc)
            self.status_label.setText(f"Unable to load available operators: {exc}")
            items = []

        self.operator_list.clear()
        for item in items:
            skill_text = ", ".join(item.skills[:3]) if item.skills else "No skills listed"
            row = QtWidgets.QListWidgetItem(f"{item.callsign}\n{skill_text}")
            row.setData(QtCore.Qt.UserRole, item.id)
            row.setData(QtCore.Qt.UserRole + 1, item.callsign)
            self.operator_list.addItem(row)
        if self.operator_list.count():
            self.operator_list.setCurrentRow(0)
            self.status_label.setText(
                "Only operators without active assignments or unresolved SITREP assignments are shown."
            )
        else:
            self.status_label.setText("No available unassigned operators.")
        self.assign_button.setEnabled(self.operator_list.count() > 0)


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


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)

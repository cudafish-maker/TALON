"""PySide6 SITREP feed and composer."""
from __future__ import annotations

import typing

from PySide6 import QtCore, QtGui, QtWidgets

from talon_core import TalonCoreSession
from talon_core.constants import SITREP_LEVELS
from talon_core.sitrep import SITREP_STATUSES
from talon_core.utils.logging import get_logger
from talon_desktop.sitreps import (
    DEFAULT_TEMPLATE_KEY,
    SITREP_TEMPLATES,
    SitrepFeedItem,
    build_create_payload,
    build_filter_payload,
    feed_item_from_entry,
    feed_items_from_entries,
    format_created_at,
    severity_counts,
    should_play_audio,
    sitrep_template_for_key,
)
from talon_desktop.map_picker import format_coordinate, pick_point_on_map

_log = get_logger("desktop.sitreps")

_LEVEL_COLORS = {
    "ROUTINE": "#d8dee9",
    "PRIORITY": "#f0c674",
    "IMMEDIATE": "#f28c28",
    "FLASH": "#ff5555",
    "FLASH_OVERRIDE": "#ff2d75",
}

_STATUS_COLORS = {
    "open": "#ff5555",
    "acknowledged": "#6aa3d8",
    "assigned": "#d6b85a",
    "resolved": "#7fb069",
    "closed": "#7fb069",
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

        self.level_filter = QtWidgets.QComboBox()
        self.level_filter.addItem("All severities", "")
        for level in SITREP_LEVELS:
            self.level_filter.addItem(level, level)
        self.level_filter.currentIndexChanged.connect(lambda _index: self.refresh())
        self.status_filter = QtWidgets.QComboBox()
        self.status_filter.addItem("All statuses", "")
        for status in SITREP_STATUSES:
            self.status_filter.addItem(status.replace("_", " ").title(), status)
        self.status_filter.currentIndexChanged.connect(lambda _index: self.refresh())
        self.unresolved_filter = QtWidgets.QCheckBox("Unresolved")
        self.unresolved_filter.toggled.connect(lambda _checked: self.refresh())
        self.location_filter = QtWidgets.QCheckBox("Located")
        self.location_filter.toggled.connect(lambda _checked: self.refresh())
        self.pending_filter = QtWidgets.QCheckBox("Pending")
        self.pending_filter.toggled.connect(lambda _checked: self.refresh())

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.audio_toggle = QtWidgets.QCheckBox("Audio")
        self.audio_toggle.toggled.connect(self._on_audio_toggled)
        self.new_button = QtWidgets.QPushButton("New SITREP")
        self.new_button.clicked.connect(self._focus_composer)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.heading)
        top_row.addStretch(1)
        top_row.addWidget(self.refresh_button)
        top_row.addWidget(self.audio_toggle)
        top_row.addWidget(self.new_button)

        self.feed = QtWidgets.QListWidget()
        self.feed.setObjectName("sitrepFeedList")
        self.feed.setSpacing(8)
        self.feed.setUniformItemSizes(False)
        self.feed.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.feed.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.feed.itemSelectionChanged.connect(self._selection_changed)
        self._feed_cards: dict[int, _SitrepFeedCard] = {}

        self.level_combo = QtWidgets.QComboBox()
        for level in SITREP_LEVELS:
            self.level_combo.addItem(level, level)
        self.create_status_combo = QtWidgets.QComboBox()
        for status in SITREP_STATUSES:
            self.create_status_combo.addItem(status.replace("_", " ").title(), status)

        self.asset_combo = QtWidgets.QComboBox()
        self.mission_combo = QtWidgets.QComboBox()
        self.assignment_combo = QtWidgets.QComboBox()
        self.template_combo = QtWidgets.QComboBox()
        for template in SITREP_TEMPLATES:
            self.template_combo.addItem(template.label, template.key)
        self.apply_template_button = QtWidgets.QPushButton("Apply")
        self.apply_template_button.clicked.connect(self._apply_template)
        self._set_template_selection(DEFAULT_TEMPLATE_KEY)
        self.location_label_field = QtWidgets.QLineEdit()
        self.location_label_field.setPlaceholderText("Location label")
        self.lat_field = QtWidgets.QLineEdit()
        self.lat_field.setPlaceholderText("Latitude")
        self.lon_field = QtWidgets.QLineEdit()
        self.lon_field.setPlaceholderText("Longitude")
        self.pick_location_button = QtWidgets.QPushButton("Map")
        self.pick_location_button.setToolTip("Pick on Map")
        self.pick_location_button.clicked.connect(self._pick_location)
        self.location_precision_combo = QtWidgets.QComboBox()
        for label in ("", "general", "approximate", "exact"):
            self.location_precision_combo.addItem(label or "None", label)
        self.location_source_combo = QtWidgets.QComboBox()
        for label in ("", "manual", "device", "map", "asset", "assignment"):
            self.location_source_combo.addItem(label or "None", label)
        self.body_field = QtWidgets.QTextEdit()
        self.body_field.setPlaceholderText("Compose situation report")
        self.body_field.setMinimumHeight(132)
        self.sensitivity_combo = QtWidgets.QComboBox()
        for sensitivity in ("team", "mission", "command", "protected"):
            self.sensitivity_combo.addItem(sensitivity.replace("_", " ").title(), sensitivity)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        self.send_button = QtWidgets.QPushButton("Send")
        self.send_button.clicked.connect(self._send)
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear_composer)
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.clicked.connect(self._delete_selected)
        self.delete_button.setVisible(self._core.mode == "server")
        self.ack_button = QtWidgets.QPushButton("Acknowledge")
        self.ack_button.clicked.connect(self._acknowledge_selected)
        self.assign_button = QtWidgets.QPushButton("Assign")
        self.assign_button.clicked.connect(self._assign_selected)
        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self._close_selected)
        self.incident_button = QtWidgets.QPushButton("Create Incident")
        self.incident_button.clicked.connect(self._create_incident_from_selected)
        self.document_combo = QtWidgets.QComboBox()
        self.link_document_button = QtWidgets.QPushButton("Link Document")
        self.link_document_button.clicked.connect(self._link_document_selected)
        self.detail_title_label = QtWidgets.QLabel("Select a SITREP")
        self.detail_title_label.setObjectName("sitrepDetailTitle")
        self.detail_status_tag = _tag_label("Open")
        self.detail_body_label = QtWidgets.QLabel("")
        self.detail_body_label.setWordWrap(True)
        self.detail_age_metric = _MiniMetaBox("Age", "-")
        self.detail_ack_metric = _MiniMetaBox("Ack", "-")
        self.detail_handler_metric = _MiniMetaBox("Handler", "-")
        self.activity_list = QtWidgets.QListWidget()
        self.activity_list.setObjectName("sitrepActivityList")
        self.activity_list.setSpacing(8)
        self.activity_list.setUniformItemSizes(False)
        self.activity_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.activity_list.setMinimumHeight(188)

        metric_row = QtWidgets.QHBoxLayout()
        self.metric_total = _SitrepMetricBox("Total", "0", "Current feed")
        self.metric_unresolved = _SitrepMetricBox("Unresolved", "0", "Needs action", "warn")
        self.metric_emergency = _SitrepMetricBox("Emergency", "0", "Flash active", "alert")
        self.metric_located = _SitrepMetricBox("With Location", "0", "Native or linked")
        self.metric_pending = _SitrepMetricBox("Pending Sync", "0", "Queued over RNS")
        self.metric_attachments = _SitrepMetricBox("Attachments", "0", "Linked docs")
        for metric in (
            self.metric_total,
            self.metric_unresolved,
            self.metric_emergency,
            self.metric_located,
            self.metric_pending,
            self.metric_attachments,
        ):
            metric_row.addWidget(metric)

        filter_widget = QtWidgets.QWidget()
        filter_layout = QtWidgets.QGridLayout(filter_widget)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setHorizontalSpacing(6)
        filter_layout.setVerticalSpacing(6)
        filter_layout.addWidget(self.level_filter, 0, 0)
        filter_layout.addWidget(self.status_filter, 0, 1)
        filter_layout.addWidget(self.unresolved_filter, 1, 0)
        filter_layout.addWidget(self.location_filter, 1, 1)
        filter_layout.addWidget(self.pending_filter, 1, 2)
        filter_layout.setColumnStretch(0, 1)
        filter_layout.setColumnStretch(1, 1)
        filter_layout.setColumnStretch(2, 1)
        feed_body = QtWidgets.QWidget()
        feed_layout = QtWidgets.QVBoxLayout(feed_body)
        feed_layout.setContentsMargins(0, 0, 0, 0)
        feed_layout.setSpacing(10)
        feed_layout.addWidget(filter_widget)
        feed_layout.addWidget(self.feed, stretch=1)
        feed_panel = _panel("Operational Feed", feed_body, ("FLASH", "IMMEDIATE"))
        feed_panel.setMinimumWidth(260)

        composer = QtWidgets.QWidget()
        form = QtWidgets.QGridLayout(composer)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(9)
        form.addWidget(_field_widget("Severity", self.level_combo), 0, 0)
        form.addWidget(_field_widget("Status", self.create_status_combo), 0, 1)
        form.addWidget(_field_widget("Mission", self.mission_combo), 1, 0)
        form.addWidget(_field_widget("Assignment", self.assignment_combo), 1, 1)
        form.addWidget(_field_widget("Asset", self.asset_combo), 2, 0)
        form.addWidget(_field_widget("Location", self.location_label_field), 2, 1)
        coord_row = QtWidgets.QWidget()
        coord_layout = QtWidgets.QHBoxLayout(coord_row)
        coord_layout.setContentsMargins(0, 0, 0, 0)
        coord_layout.setSpacing(8)
        coord_layout.addWidget(self.lat_field)
        coord_layout.addWidget(self.lon_field)
        coord_layout.addWidget(self.pick_location_button)
        form.addWidget(_field_widget("Lat / Lon", coord_row), 3, 0, 1, 2)
        location_meta_row = QtWidgets.QWidget()
        location_meta_layout = QtWidgets.QHBoxLayout(location_meta_row)
        location_meta_layout.setContentsMargins(0, 0, 0, 0)
        location_meta_layout.setSpacing(8)
        location_meta_layout.addWidget(self.location_precision_combo)
        location_meta_layout.addWidget(self.location_source_combo)
        form.addWidget(_field_widget("Location Meta", location_meta_row), 4, 0, 1, 2)
        form.addWidget(_field_widget("Template", self._template_row()), 5, 0, 1, 2)
        form.addWidget(_field_widget("Body", self.body_field), 6, 0, 1, 2)
        attachment_hint = QtWidgets.QLabel("Link a document after selecting a sent SITREP")
        attachment_hint.setObjectName("sitrepMutedLabel")
        attachment_hint.setWordWrap(True)
        form.addWidget(_field_widget("Attachment", attachment_hint), 7, 0)
        form.addWidget(_field_widget("Privacy", self.sensitivity_combo), 7, 1)
        form.addWidget(self.status_label, 8, 0, 1, 2)
        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(self.clear_button)
        action_row.addWidget(self.delete_button)
        action_row.addStretch(1)
        action_row.addWidget(self.send_button)
        action_holder = QtWidgets.QWidget()
        action_holder.setLayout(action_row)
        form.addWidget(action_holder, 9, 0, 1, 2)
        composer_panel = _panel("Composer", composer, ("Location Native",))
        composer_panel.setMinimumWidth(260)

        detail_card = QtWidgets.QFrame()
        detail_card.setObjectName("sitrepDetailCard")
        detail_card_layout = QtWidgets.QVBoxLayout(detail_card)
        detail_card_layout.addWidget(self.detail_title_label)
        detail_card_layout.addWidget(self.detail_body_label)
        detail_meta_row = QtWidgets.QHBoxLayout()
        for metric in (self.detail_age_metric, self.detail_ack_metric, self.detail_handler_metric):
            detail_meta_row.addWidget(metric)
        detail_card_layout.addLayout(detail_meta_row)
        followup_grid = QtWidgets.QGridLayout()
        followup_grid.setContentsMargins(0, 0, 0, 0)
        followup_grid.addWidget(self.ack_button, 0, 0)
        followup_grid.addWidget(self.assign_button, 0, 1)
        followup_grid.addWidget(self.close_button, 1, 0)
        followup_grid.addWidget(self.incident_button, 1, 1)
        detail_card_layout.addLayout(followup_grid)
        document_row = QtWidgets.QHBoxLayout()
        document_row.addWidget(self.document_combo, stretch=1)
        document_row.addWidget(self.link_document_button)
        detail = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(10)
        detail_layout.addWidget(detail_card)
        detail_layout.addWidget(self.activity_list, stretch=1)
        detail_layout.addLayout(document_row)
        detail_panel = _panel(
            "Selected Detail",
            detail,
            extra_widgets=(self.detail_status_tag,),
        )
        detail_panel.setMinimumWidth(240)

        splitter = _SitrepCommandSplitter()
        splitter.addWidget(feed_panel)
        splitter.addWidget(composer_panel)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 4)
        splitter.setSizes([420, 340, 300])

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_row)
        layout.addLayout(metric_row)
        layout.addWidget(splitter, stretch=1)

    def refresh(self) -> None:
        try:
            self._sync_audio_toggle()
            self._refresh_link_selectors()
            entries = self._core.read_model("sitreps.list", self._filter_payload())
            self._items = feed_items_from_entries(entries)
        except Exception as exc:
            _log.warning("Could not refresh SITREPs: %s", exc)
            self.status_label.setText(f"Unable to refresh SITREPs: {exc}")
            return

        self.feed.clear()
        self._feed_cards.clear()
        counts = severity_counts(self._items)
        self.summary.setText(
            f"{len(self._items)} total | "
            f"Priority {counts.get('PRIORITY', 0)} | "
            f"Immediate {counts.get('IMMEDIATE', 0)} | "
            f"Flash {counts.get('FLASH', 0) + counts.get('FLASH_OVERRIDE', 0)}"
        )
        self._update_metrics(counts)
        if not self._items:
            self.feed.addItem("No SITREPs logged.")
            self._selection_changed()
            return
        for item in self._items:
            widget_item = self._list_item(item)
            self.feed.addItem(widget_item)
            card = _SitrepFeedCard(item)
            self.feed.setItemWidget(widget_item, card)
            widget_item.setSizeHint(card.sizeHint())
            self._feed_cards[item.id] = card
        self.feed.setCurrentRow(0)
        self._selection_changed()

    def _update_metrics(self, counts: dict[str, int]) -> None:
        unresolved = sum(1 for item in self._items if item.unresolved)
        emergency = counts.get("FLASH", 0) + counts.get("FLASH_OVERRIDE", 0)
        located = sum(1 for item in self._items if item.has_location)
        pending = 0
        attachments = 0
        try:
            dashboard = self._core.read_model("dashboard.summary")
            dashboard_counts = getattr(dashboard, "counts", {}) or {}
            sync = getattr(dashboard, "sync", None)
            pending_by_table = getattr(sync, "pending_outbox_by_table", {}) or {}
            pending = sum(
                int(pending_by_table.get(table, 0) or 0)
                for table in ("sitreps", "sitrep_followups", "sitrep_documents")
            )
            attachments = int(dashboard_counts.get("sitrep_documents", 0) or 0)
        except Exception:
            pass
        self.metric_total.set_metric(str(len(self._items)), "Current feed")
        self.metric_unresolved.set_metric(str(unresolved), "Needs action")
        self.metric_emergency.set_metric(str(emergency), "Flash active")
        self.metric_located.set_metric(str(located), "Native or linked")
        self.metric_pending.set_metric(str(pending), "Queued over RNS")
        self.metric_attachments.set_metric(str(attachments), "Linked docs")

    def handle_record_mutation(self, action: str, table: str, record_id: int) -> None:
        if table not in {"sitreps", "sitrep_followups", "sitrep_documents", "incidents"}:
            return
        if action != "changed":
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
                assignment_id=self._combo_int(self.assignment_combo),
                location_label=self.location_label_field.text(),
                lat_text=self.lat_field.text(),
                lon_text=self.lon_field.text(),
                location_precision=str(self.location_precision_combo.currentData() or ""),
                location_source=str(self.location_source_combo.currentData() or ""),
                status=str(self.create_status_combo.currentData() or "open"),
                sensitivity=str(self.sensitivity_combo.currentData() or "team"),
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
        self.assignment_combo.setCurrentIndex(0)
        self.create_status_combo.setCurrentIndex(0)
        self._set_template_selection(DEFAULT_TEMPLATE_KEY)
        self.location_label_field.clear()
        self.lat_field.clear()
        self.lon_field.clear()
        self.location_precision_combo.setCurrentIndex(0)
        self.location_source_combo.setCurrentIndex(0)
        self.sensitivity_combo.setCurrentIndex(0)

    def _pick_location(self) -> None:
        try:
            initial_lat = _optional_coordinate(
                self.lat_field.text(),
                "SITREP latitude",
                -90.0,
                90.0,
            )
            initial_lon = _optional_coordinate(
                self.lon_field.text(),
                "SITREP longitude",
                -180.0,
                180.0,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        if (initial_lat is None) != (initial_lon is None):
            self.status_label.setText(
                "Both latitude and longitude are required for an existing map point."
            )
            return
        selected = pick_point_on_map(
            core=self._core,
            title=self.location_label_field.text().strip() or "SITREP Location",
            initial_lat=initial_lat,
            initial_lon=initial_lon,
            parent=self,
        )
        if selected is None:
            return
        formatted = format_coordinate(*selected).split(", ")
        self.lat_field.setText(formatted[0])
        self.lon_field.setText(formatted[1])
        self._set_combo_value(self.location_precision_combo, "exact")
        self._set_combo_value(self.location_source_combo, "map")
        self.status_label.clear()

    def _filter_payload(self) -> dict[str, object]:
        return build_filter_payload(
            level_filter=str(self.level_filter.currentData() or ""),
            status_filter=str(self.status_filter.currentData() or ""),
            unresolved_only=self.unresolved_filter.isChecked(),
            has_location=self.location_filter.isChecked(),
            pending_sync_only=self.pending_filter.isChecked(),
        )

    def _focus_composer(self) -> None:
        self.body_field.setFocus(QtCore.Qt.OtherFocusReason)

    def _template_row(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.template_combo, stretch=1)
        layout.addWidget(self.apply_template_button)
        return widget

    def _apply_template_key(self, key: str) -> None:
        self._set_template_selection(key)
        self._apply_template()

    def _set_template_selection(self, key: str) -> None:
        index = self.template_combo.findData(key)
        self.template_combo.setCurrentIndex(index if index >= 0 else 0)

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
        current_assignment = self._combo_int(self.assignment_combo)
        current_document = self._combo_int(self.document_combo)

        self.asset_combo.blockSignals(True)
        self.mission_combo.blockSignals(True)
        self.assignment_combo.blockSignals(True)
        self.document_combo.blockSignals(True)
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

            self.assignment_combo.clear()
            self.assignment_combo.addItem("None", None)
            for assignment in self._core.read_model("assignments.list", {"active_only": True}):
                label = f"{getattr(assignment, 'title', 'Assignment')} [{getattr(assignment, 'status', '')}]"
                self.assignment_combo.addItem(label, int(assignment.id))
            self._restore_combo_value(self.assignment_combo, current_assignment)

            self.document_combo.clear()
            self.document_combo.addItem("None", None)
            for item in self._core.read_model("documents.list", {"limit": 100}):
                doc = getattr(item, "document", item)
                self.document_combo.addItem(str(getattr(doc, "filename", "Document")), int(doc.id))
            self._restore_combo_value(self.document_combo, current_document)
        finally:
            self.asset_combo.blockSignals(False)
            self.mission_combo.blockSignals(False)
            self.assignment_combo.blockSignals(False)
            self.document_combo.blockSignals(False)

    def _list_item(self, item: SitrepFeedItem) -> QtWidgets.QListWidgetItem:
        widget_item = QtWidgets.QListWidgetItem()
        widget_item.setData(QtCore.Qt.UserRole, item.id)
        return widget_item

    def _selection_changed(self) -> None:
        sitrep_id = self._selected_sitrep_id()
        has_selection = sitrep_id is not None
        self._sync_feed_card_selection(sitrep_id)
        for button in (
            self.ack_button,
            self.assign_button,
            self.close_button,
            self.incident_button,
            self.link_document_button,
        ):
            button.setEnabled(has_selection)
        if sitrep_id is None:
            self._clear_detail_panel()
            return
        try:
            detail = self._core.read_model("sitreps.detail", {"sitrep_id": sitrep_id})
        except Exception as exc:
            self.detail_title_label.setText("Unable to load SITREP detail")
            self.detail_body_label.setText(str(exc))
            self.activity_list.clear()
            return
        sitrep = detail["sitrep"]
        documents = detail.get("documents", [])
        followups = detail.get("followups", [])
        incidents = detail.get("incidents", [])
        title = f"{sitrep.level} #{sitrep.id} / {sitrep.status.replace('_', ' ').title()}"
        self.detail_title_label.setText(title)
        self.detail_status_tag.setText(_status_label(sitrep.status))
        self.detail_status_tag.setProperty("tone", _tone_for_text(sitrep.status))
        self.detail_status_tag.style().unpolish(self.detail_status_tag)
        self.detail_status_tag.style().polish(self.detail_status_tag)
        location = sitrep.location_label or "No label"
        if sitrep.lat is not None and sitrep.lon is not None:
            location += f" | {sitrep.lat:.6f}, {sitrep.lon:.6f}"
        body_lines = [
            _as_text(sitrep.body) or "No body.",
            "",
            f"Reporter: {detail.get('callsign', '') or 'UNKNOWN'}",
            f"Mission: {detail.get('mission_title', '') or sitrep.mission_id or 'None'}",
            f"Assignment: {detail.get('assignment_title', '') or sitrep.assignment_id or 'None'}",
            f"Asset: {detail.get('asset_label', '') or sitrep.asset_id or 'None'}",
            f"Location: {location}",
            f"Documents: {len(documents)} | Linked incidents: {len(incidents)}",
        ]
        if sitrep.disposition:
            body_lines.append(f"Disposition: {sitrep.disposition}")
        self.detail_body_label.setText("\n".join(body_lines))
        self.detail_age_metric.set_value(format_created_at(sitrep.created_at))
        acknowledged = any(item.action == "acknowledged" for item in followups)
        self.detail_ack_metric.set_value("Command" if acknowledged else "Open")
        self.detail_handler_metric.set_value(sitrep.assigned_to or "Unassigned")

        self.activity_list.clear()
        for item in followups[-8:]:
            note = item.note or item.assigned_to or item.status or item.action
            self._add_activity_card(
                f"{format_created_at(item.created_at)} {item.action.replace('_', ' ').title()}",
                note,
            )
        for entry in documents[:4]:
            document = entry.get("document")
            filename = getattr(document, "filename", "Missing document")
            self._add_activity_card("Document linked", str(filename))
        if incidents:
            self._add_activity_card("Linked incidents", str(len(incidents)))
        if self.activity_list.count() == 0:
            self._add_activity_card("No follow-ups yet.", "Append-only activity will appear here.")

    def _clear_detail_panel(self) -> None:
        self.detail_title_label.setText("Select a SITREP")
        self.detail_status_tag.setText("Open")
        self.detail_status_tag.setProperty("tone", "red")
        self.detail_status_tag.style().unpolish(self.detail_status_tag)
        self.detail_status_tag.style().polish(self.detail_status_tag)
        self.detail_body_label.setText("")
        self.detail_age_metric.set_value("-")
        self.detail_ack_metric.set_value("-")
        self.detail_handler_metric.set_value("-")
        self.activity_list.clear()

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

    def _acknowledge_selected(self) -> None:
        sitrep_id = self._selected_sitrep_id()
        if sitrep_id is None:
            return
        try:
            self._core.command("sitreps.acknowledge", {"sitrep_id": sitrep_id})
            self.refresh()
        except Exception as exc:
            _log.warning("SITREP acknowledge failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "SITREP", str(exc))

    def _assign_selected(self) -> None:
        sitrep_id = self._selected_sitrep_id()
        if sitrep_id is None:
            return
        assignee, accepted = QtWidgets.QInputDialog.getText(
            self,
            "Assign SITREP",
            "Handler or team",
        )
        if not accepted:
            return
        try:
            self._core.command(
                "sitreps.assign_followup",
                {"sitrep_id": sitrep_id, "assigned_to": assignee.strip()},
            )
            self.refresh()
        except Exception as exc:
            _log.warning("SITREP assign failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "SITREP", str(exc))

    def _close_selected(self) -> None:
        sitrep_id = self._selected_sitrep_id()
        if sitrep_id is None:
            return
        disposition, accepted = QtWidgets.QInputDialog.getMultiLineText(
            self,
            "Close SITREP",
            "Disposition",
            "",
        )
        if not accepted:
            return
        try:
            self._core.command(
                "sitreps.update_status",
                {
                    "sitrep_id": sitrep_id,
                    "status": "closed",
                    "note": disposition.strip(),
                },
            )
            self.refresh()
        except Exception as exc:
            _log.warning("SITREP close failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "SITREP", str(exc))

    def _create_incident_from_selected(self) -> None:
        sitrep_id = self._selected_sitrep_id()
        if sitrep_id is None:
            return
        try:
            detail = self._core.read_model("sitreps.detail", {"sitrep_id": sitrep_id})
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "SITREP", str(exc))
            return
        sitrep = detail["sitrep"]
        try:
            from talon_desktop.community_safety_page import IncidentCreateDialog

            dialog = IncidentCreateDialog(
                self._core,
                parent=self,
                linked_assignment_id=sitrep.assignment_id,
                linked_sitrep_id=sitrep.id,
                linked_mission_id=sitrep.mission_id,
                linked_asset_id=sitrep.asset_id,
                default_title=f"{sitrep.level} SITREP #{sitrep.id}",
                default_location=sitrep.location_label,
                default_narrative=_as_text(sitrep.body),
                default_severity=sitrep.level,
            )
            if dialog.exec() != QtWidgets.QDialog.Accepted:
                return
            self._core.command("incidents.create", dialog.payload())
            self.refresh()
        except Exception as exc:
            _log.warning("Incident create from SITREP failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Incident", str(exc))

    def _link_document_selected(self) -> None:
        sitrep_id = self._selected_sitrep_id()
        document_id = self._combo_int(self.document_combo)
        if sitrep_id is None or document_id is None:
            return
        try:
            self._core.command(
                "sitreps.link_document",
                {"sitrep_id": sitrep_id, "document_id": document_id},
            )
            self.refresh()
        except Exception as exc:
            _log.warning("SITREP document link failed: %s", exc)
            QtWidgets.QMessageBox.warning(self, "SITREP", str(exc))

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

    @staticmethod
    def _set_combo_value(combo: QtWidgets.QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _selected_template_key(self) -> str:
        key = self._selected_template_id()
        return "" if key == DEFAULT_TEMPLATE_KEY else key

    def _selected_template_id(self) -> str:
        return str(self.template_combo.currentData() or DEFAULT_TEMPLATE_KEY)


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


class _MiniMetaBox(QtWidgets.QFrame):
    def __init__(self, title: str, value: str) -> None:
        super().__init__()
        self.setObjectName("sitrepMiniMeta")
        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("sitrepMiniMetaTitle")
        self.value = QtWidgets.QLabel(value)
        self.value.setObjectName("sitrepMiniMetaValue")
        self.value.setWordWrap(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


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
    """Three-column SITREP splitter that recovers from old two-column state."""

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
        if self.count() != 3:
            return
        sizes = self.sizes()
        if len(sizes) != 3 or sizes[2] < 240 or min(sizes) <= 0:
            width = max(780, sum(sizes) or self.width())
            self.setSizes([int(width * 0.42), int(width * 0.31), int(width * 0.27)])


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


def _optional_coordinate(
    value: str,
    label: str,
    minimum: float,
    maximum: float,
) -> float | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return parsed

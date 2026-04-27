"""PySide6 desktop application shell."""
from __future__ import annotations

import pathlib
import threading
import typing

from PySide6 import QtCore, QtWidgets

from talon_core import TalonCoreSession
from talon_core.utils.logging import get_logger

from talon_desktop.asset_page import AssetPage
from talon_desktop.chat_page import ChatPage
from talon_desktop.document_page import DocumentPage
from talon_desktop.log_view import LogDialog
from talon_desktop.logs import (
    DesktopLogBuffer,
    desktop_log_buffer,
    install_desktop_log_buffer,
)
from talon_desktop.map_page import MapPage
from talon_desktop.mission_page import MissionPage
from talon_desktop.navigation import DesktopNavItem, navigation_items
from talon_desktop.operator_page import AuditPage, EnrollmentPage, KeysPage, OperatorPage
from talon_desktop.qt_events import CoreEventBridge
from talon_desktop.settings import (
    desktop_settings,
    restore_header_state,
    restore_splitter_state,
    save_header_state,
    save_splitter_state,
    settings_byte_array,
)
from talon_desktop.sitrep_page import SitrepAlertOverlay, SitrepPage, latest_sitrep_item
from talon_desktop.theme import apply_desktop_theme

_log = get_logger("desktop")


class _WorkerSignals(QtCore.QObject):
    succeeded = QtCore.Signal(object)
    failed = QtCore.Signal(str)


class LoginWindow(QtWidgets.QWidget):
    unlockRequested = QtCore.Signal(str)
    enrollRequested = QtCore.Signal(str, str)

    def __init__(self, mode: str) -> None:
        super().__init__()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            apply_desktop_theme(app)
        self._mode = mode
        self.setWindowTitle(f"T.A.L.O.N. Desktop [{mode.upper()}]")
        self.setMinimumWidth(520)
        self.setObjectName("loginWindow")

        title = QtWidgets.QLabel(f"T.A.L.O.N. {mode.upper()} Desktop")
        title.setObjectName("title")
        subtitle = QtWidgets.QLabel("Unlock the local SQLCipher database.")
        subtitle.setObjectName("subtitle")

        self.passphrase = QtWidgets.QLineEdit()
        self.passphrase.setEchoMode(QtWidgets.QLineEdit.Password)
        self.passphrase.setPlaceholderText("Passphrase")
        self.passphrase.returnPressed.connect(self._unlock_clicked)

        self.unlock_button = QtWidgets.QPushButton("Unlock")
        self.unlock_button.clicked.connect(self._unlock_clicked)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("statusLabel")

        form = QtWidgets.QFormLayout()
        form.addRow("Passphrase", self.passphrase)

        self.enrollment_group = QtWidgets.QGroupBox("Client Enrollment")
        enrollment_layout = QtWidgets.QFormLayout(self.enrollment_group)
        self.token_field = QtWidgets.QLineEdit()
        self.token_field.setPlaceholderText("TOKEN:SERVER_HASH")
        self.callsign_field = QtWidgets.QLineEdit()
        self.callsign_field.setPlaceholderText("Callsign")
        self.enroll_button = QtWidgets.QPushButton("Enroll Client")
        self.enroll_button.clicked.connect(self._enroll_clicked)
        enrollment_layout.addRow("Token", self.token_field)
        enrollment_layout.addRow("Callsign", self.callsign_field)
        enrollment_layout.addRow("", self.enroll_button)
        self.enrollment_group.setVisible(False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.unlock_button)
        layout.addWidget(self.status_label)
        layout.addWidget(self.enrollment_group)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.unlock_button.setDisabled(busy)
        self.enroll_button.setDisabled(busy)
        self.passphrase.setDisabled(busy)
        self.status_label.setText(message)

    def show_error(self, message: str) -> None:
        self.set_busy(False)
        self.status_label.setText(message)

    def show_enrollment(self) -> None:
        self.set_busy(False, "This client is unlocked but not enrolled.")
        self.enrollment_group.setVisible(True)

    def _unlock_clicked(self) -> None:
        passphrase = self.passphrase.text()
        if not passphrase.strip():
            self.show_error("Passphrase is required.")
            return
        self.unlockRequested.emit(passphrase)

    def _enroll_clicked(self) -> None:
        token = self.token_field.text().strip()
        callsign = self.callsign_field.text().strip()
        if not token:
            self.show_error("TOKEN:SERVER_HASH is required.")
            return
        if not callsign:
            self.show_error("Callsign is required.")
            return
        self.enrollRequested.emit(token, callsign)


class LockWindow(QtWidgets.QDialog):
    def __init__(self, reason: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        app = QtWidgets.QApplication.instance()
        if app is not None:
            apply_desktop_theme(app)
        self.setWindowTitle("T.A.L.O.N. Locked")
        self.setObjectName("lockWindow")
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setMinimumWidth(420)
        self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)

        title = QtWidgets.QLabel("Session Locked")
        title.setObjectName("title")
        body = QtWidgets.QLabel(_lock_message(reason))
        body.setWordWrap(True)
        quit_button = QtWidgets.QPushButton("Quit")
        quit_button.clicked.connect(QtWidgets.QApplication.instance().quit)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addWidget(quit_button)


class DesktopPage(QtWidgets.QWidget):
    def __init__(self, core: TalonCoreSession, section: DesktopNavItem) -> None:
        super().__init__()
        self._core = core
        self.section = section

        self.heading = QtWidgets.QLabel(section.label)
        self.heading.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("summaryLabel")
        self.list_widget = QtWidgets.QListWidget()
        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(self.summary)
        layout.addWidget(self.list_widget, stretch=1)
        layout.addWidget(self.refresh_button)

    def refresh(self) -> None:
        self.list_widget.clear()
        try:
            summary, rows = self._load_rows()
        except Exception as exc:
            _log.warning("Could not refresh %s: %s", self.section.key, exc)
            self.summary.setText(f"Unable to load {self.section.label}: {exc}")
            return
        self.summary.setText(summary)
        if not rows:
            self.list_widget.addItem("No records.")
            return
        for row in rows:
            self.list_widget.addItem(row)

    def _load_rows(self) -> tuple[str, list[str]]:
        key = self.section.key
        if key == "dashboard":
            return self._dashboard_rows()
        if key == "map":
            context = self._core.read_model("map.context")
            rows = [
                f"Asset #{_field(asset, 'id')}: {_field(asset, 'label')}"
                for asset in context.assets
            ]
            rows.extend(
                f"Mission #{_field(mission, 'id')}: {_field(mission, 'title', 'name')}"
                for mission in context.missions
            )
            rows.extend(
                f"Zone #{_field(zone, 'id')}: {_field(zone, 'label', 'zone_type')}"
                for zone in context.zones
            )
            rows.extend(
                f"Waypoint #{_field(point, 'id')}: {_field(point, 'label')}"
                for point in context.waypoints
            )
            return (
                "Operational map read model: "
                f"{len(context.assets)} assets, {len(context.missions)} missions, "
                f"{len(context.zones)} zones, {len(context.waypoints)} waypoints.",
                rows,
            )
        if key == "sitreps":
            rows = []
            for item in self._core.read_model("sitreps.list"):
                sitrep = item[0] if isinstance(item, tuple) else item
                body = _as_text(_field(sitrep, "body"))
                rows.append(
                    f"#{_field(sitrep, 'id')} {_field(sitrep, 'level')}: {body}"
                )
            return "Latest SITREPs from core.", rows
        if key == "assets":
            rows = [
                (
                    f"#{_field(asset, 'id')} {_field(asset, 'label')} "
                    f"[{_field(asset, 'category')}]"
                )
                for asset in self._core.read_model("assets.list")
            ]
            return "Assets and verification state.", rows
        if key == "missions":
            rows = [
                (
                    f"#{_field(mission, 'id')} "
                    f"{_field(mission, 'title', 'name')} "
                    f"[{_field(mission, 'status')}]"
                )
                for mission in self._core.read_model("missions.list")
            ]
            return "Mission lifecycle and route records.", rows
        if key == "chat":
            rows = [
                f"#{_field(channel, 'id')} {_field(channel, 'name')}"
                for channel in self._core.read_model("chat.channels")
            ]
            return "Channels and direct-message entry points.", rows
        if key == "documents":
            rows = []
            for item in self._core.read_model("documents.list"):
                document = item.document
                rows.append(
                    f"#{_field(document, 'id')} {_field(document, 'filename')} "
                    f"by {item.uploader_callsign}"
                )
            return "Secure document repository.", rows
        if key == "operators":
            return "Known operators.", _operator_rows(self._core)
        if key == "clients":
            return "Server client roster.", _operator_rows(self._core)
        if key == "enrollment":
            rows = [str(token) for token in self._core.read_model("enrollment.pending_tokens")]
            return "Pending one-time enrollment tokens.", rows
        if key == "audit":
            rows = [str(entry) for entry in self._core.read_model("audit.list")]
            return "Encrypted server audit log.", rows
        if key == "keys":
            server_hash = self._core.read_model("enrollment.server_hash")
            return "Server Reticulum identity hash.", [server_hash or "Not initialized."]
        raise KeyError(f"Unsupported desktop page: {key}")

    def _dashboard_rows(self) -> tuple[str, list[str]]:
        summary = self._core.read_model("dashboard.summary")
        sync = summary.sync
        counts = summary.counts
        rows = [
            f"Mode: {summary.mode}",
            f"Unlocked: {summary.unlocked}",
            f"Operator ID: {summary.operator_id}",
            f"Connection: {sync.connection_state}",
            f"Reticulum started: {sync.reticulum_started}",
            f"Sync started: {sync.sync_started}",
            f"Lease monitor started: {sync.lease_monitor_started}",
            f"Pending outbox: {sync.pending_outbox_count}",
            f"Active clients: {sync.active_client_count}",
            f"Last sync: {sync.last_sync_at or 'Never'}",
            f"Last heartbeat: {sync.last_heartbeat_at or 'Never'}",
            f"Database: {summary.paths.db_path}",
            f"Data directory: {summary.paths.data_dir}",
        ]
        if summary.unlocked:
            rows.extend(
                (
                    f"Assets: {counts.get('assets', 0)}",
                    f"SITREPs: {counts.get('sitreps', 0)}",
                    f"Missions: {counts.get('missions', 0)}",
                    f"Documents: {counts.get('documents', 0)}",
                    f"Urgent messages: {counts.get('urgent_messages', 0)}",
                )
            )
        return "Core session and operational summary.", rows


class MainWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        core: TalonCoreSession,
        event_bridge: CoreEventBridge,
        settings: QtCore.QSettings | None = None,
        log_buffer: DesktopLogBuffer | None = None,
    ) -> None:
        super().__init__()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            apply_desktop_theme(app)
        self._core = core
        self._event_bridge = event_bridge
        self._pages: dict[str, QtWidgets.QWidget] = {}
        self._settings = settings if settings is not None else desktop_settings()
        self._log_buffer = log_buffer if log_buffer is not None else desktop_log_buffer()
        self._log_dialog: LogDialog | None = None
        self._settings_prefix = f"{core.mode}/main_window"
        self.setWindowTitle(f"T.A.L.O.N. Desktop [{core.mode.upper()}]")
        self.resize(1180, 760)

        side_bar = QtWidgets.QWidget()
        side_bar.setObjectName("sideBar")
        side_bar.setFixedWidth(210)
        side_title = QtWidgets.QLabel("T.A.L.O.N.")
        side_title.setObjectName("sideTitle")
        side_mode = QtWidgets.QLabel(f"{core.mode.upper()} NODE")
        side_mode.setObjectName("sideMode")

        self.nav = QtWidgets.QListWidget()
        self.nav.setObjectName("navigationList")
        self.stack = QtWidgets.QStackedWidget()

        for section in navigation_items(core.mode):
            item = QtWidgets.QListWidgetItem(section.label)
            item.setData(QtCore.Qt.UserRole, section.key)
            self.nav.addItem(item)
            if section.key == "sitreps":
                page = SitrepPage(core)
            elif section.key == "assets":
                page = AssetPage(core)
            elif section.key == "map":
                page = MapPage(core)
            elif section.key == "missions":
                page = MissionPage(core)
            elif section.key == "chat":
                page = ChatPage(core)
            elif section.key == "documents":
                page = DocumentPage(core)
            elif section.key == "operators":
                page = OperatorPage(core)
            elif section.key == "clients":
                page = OperatorPage(core, title="Clients", admin=True)
            elif section.key == "enrollment":
                page = EnrollmentPage(core)
            elif section.key == "audit":
                page = AuditPage(core)
            elif section.key == "keys":
                page = KeysPage(core)
            else:
                page = DesktopPage(core, section)
            self._pages[section.key] = page
            self.stack.addWidget(page)

        side_layout = QtWidgets.QVBoxLayout(side_bar)
        side_layout.setContentsMargins(14, 16, 14, 12)
        side_layout.setSpacing(8)
        side_layout.addWidget(side_title)
        side_layout.addWidget(side_mode)
        side_layout.addSpacing(8)
        side_layout.addWidget(self.nav, stretch=1)

        self._root_splitter = QtWidgets.QSplitter()
        self._root_splitter.setObjectName("mainSplitter")
        self._root_splitter.addWidget(side_bar)
        self._root_splitter.addWidget(self.stack)
        self._root_splitter.setStretchFactor(1, 1)
        self.setCentralWidget(self._root_splitter)
        self._sitrep_alert_overlay = SitrepAlertOverlay(self.stack)
        self.statusBar().showMessage("Core unlocked.")
        self._log_button = QtWidgets.QPushButton("Logs")
        self._log_button.setObjectName("statusButton")
        self._log_button.clicked.connect(self._show_logs)
        self.statusBar().addPermanentWidget(self._log_button)
        self._log_timer = QtCore.QTimer(self)
        self._log_timer.timeout.connect(self._refresh_log_button)
        self._log_timer.start(2000)

        self.nav.currentRowChanged.connect(self._on_nav_changed)
        self._event_bridge.eventReceived.connect(self._on_core_event)
        self._event_bridge.refreshRequested.connect(self.refresh_section)
        self._event_bridge.recordMutated.connect(self._on_record_mutated)
        self._restore_desktop_state()
        self.nav.setCurrentRow(self._initial_nav_row())
        self.refresh_all()
        self._refresh_log_button()

    def refresh_all(self) -> None:
        for page in self._pages.values():
            if hasattr(page, "refresh"):
                page.refresh()

    @QtCore.Slot(str)
    def refresh_section(self, section_key: str) -> None:
        page = self._pages.get(section_key)
        if page is not None and hasattr(page, "refresh"):
            page.refresh()

    def _on_nav_changed(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        item = self.nav.item(row)
        section_key = item.data(QtCore.Qt.UserRole)
        self._settings.setValue(self._setting_key("last_section"), str(section_key))
        self.refresh_section(str(section_key))

    def closeEvent(self, event: QtCore.QEvent) -> None:
        self._save_desktop_state()
        super().closeEvent(event)

    def resizeEvent(self, event: QtCore.QEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_sitrep_alert_overlay"):
            self._sitrep_alert_overlay.reposition()

    def _restore_desktop_state(self) -> None:
        geometry = settings_byte_array(self._settings.value(self._setting_key("geometry")))
        if geometry is not None:
            self.restoreGeometry(geometry)
        window_state = settings_byte_array(
            self._settings.value(self._setting_key("window_state"))
        )
        if window_state is not None:
            self.restoreState(window_state)
        restore_splitter_state(
            self._root_splitter,
            self._settings,
            self._setting_key("splitters", "main"),
        )
        for section_key, page in self._pages.items():
            self._restore_page_state(section_key, page)

    def _save_desktop_state(self) -> None:
        self._settings.setValue(self._setting_key("geometry"), self.saveGeometry())
        self._settings.setValue(self._setting_key("window_state"), self.saveState())
        save_splitter_state(
            self._root_splitter,
            self._settings,
            self._setting_key("splitters", "main"),
        )
        for section_key, page in self._pages.items():
            self._save_page_state(section_key, page)
        current = self.nav.currentItem()
        if current is not None:
            self._settings.setValue(
                self._setting_key("last_section"),
                str(current.data(QtCore.Qt.UserRole)),
            )
        self._settings.sync()

    def _restore_page_state(self, section_key: str, page: QtWidgets.QWidget) -> None:
        for index, table in enumerate(page.findChildren(QtWidgets.QTableWidget)):
            restore_header_state(
                table,
                self._settings,
                self._setting_key("pages", section_key, "tables", str(index)),
            )
        for index, splitter in enumerate(page.findChildren(QtWidgets.QSplitter)):
            restore_splitter_state(
                splitter,
                self._settings,
                self._setting_key("pages", section_key, "splitters", str(index)),
            )

    def _save_page_state(self, section_key: str, page: QtWidgets.QWidget) -> None:
        for index, table in enumerate(page.findChildren(QtWidgets.QTableWidget)):
            save_header_state(
                table,
                self._settings,
                self._setting_key("pages", section_key, "tables", str(index)),
            )
        for index, splitter in enumerate(page.findChildren(QtWidgets.QSplitter)):
            save_splitter_state(
                splitter,
                self._settings,
                self._setting_key("pages", section_key, "splitters", str(index)),
            )

    def _initial_nav_row(self) -> int:
        last_section = str(self._settings.value(self._setting_key("last_section"), ""))
        if last_section:
            for index in range(self.nav.count()):
                item = self.nav.item(index)
                if item.data(QtCore.Qt.UserRole) == last_section:
                    return index
        return 0

    def _setting_key(self, *parts: str) -> str:
        return "/".join((self._settings_prefix, *parts))

    def _on_core_event(self, event: object) -> None:
        kind = getattr(event, "kind", "event")
        self.statusBar().showMessage(f"Core event: {kind}", 5000)

    @QtCore.Slot()
    def _show_logs(self) -> None:
        if self._log_dialog is None:
            self._log_dialog = LogDialog(self._log_buffer, parent=self)
        self._log_dialog.refresh()
        self._log_dialog.show()
        self._log_dialog.raise_()
        self._log_dialog.activateWindow()

    @QtCore.Slot()
    def _refresh_log_button(self) -> None:
        warnings = self._log_buffer.warning_count()
        self._log_button.setText(f"Logs ({warnings})" if warnings else "Logs")

    def _on_record_mutated(self, action: str, table: str, record_id: int) -> None:
        self.statusBar().showMessage(f"{table} {action}: #{record_id}", 5000)
        if table == "sitreps":
            page = self._pages.get("sitreps")
            if isinstance(page, SitrepPage):
                page.handle_record_mutation(action, table, record_id)
            if action == "changed":
                self._show_sitrep_overlay(record_id)
            map_page = self._pages.get("map")
            if isinstance(map_page, MapPage):
                map_page.handle_record_mutation(action, table, record_id)
        elif table == "assets":
            page = self._pages.get("assets")
            if isinstance(page, AssetPage):
                page.handle_record_mutation(action, table, record_id)
            map_page = self._pages.get("map")
            if isinstance(map_page, MapPage):
                map_page.handle_record_mutation(action, table, record_id)
        elif table in {"missions", "zones", "waypoints", "sitreps"}:
            page = self._pages.get("map")
            if isinstance(page, MapPage):
                page.handle_record_mutation(action, table, record_id)
            mission_page = self._pages.get("missions")
            if isinstance(mission_page, MissionPage):
                mission_page.handle_record_mutation(action, table, record_id)
        elif table in {"channels", "messages"}:
            chat_page = self._pages.get("chat")
            if isinstance(chat_page, ChatPage):
                chat_page.handle_record_mutation(action, table, record_id)
            mission_page = self._pages.get("missions")
            if isinstance(mission_page, MissionPage):
                mission_page.handle_record_mutation(action, table, record_id)
        elif table == "documents":
            document_page = self._pages.get("documents")
            if isinstance(document_page, DocumentPage):
                document_page.handle_record_mutation(action, table, record_id)
        elif table == "operators":
            for key in ("operators", "clients"):
                operator_page = self._pages.get(key)
                if isinstance(operator_page, OperatorPage):
                    operator_page.handle_record_mutation(action, table, record_id)
            keys_page = self._pages.get("keys")
            if isinstance(keys_page, KeysPage):
                keys_page.handle_record_mutation(action, table, record_id)
            chat_page = self._pages.get("chat")
            if isinstance(chat_page, ChatPage):
                chat_page.handle_record_mutation(action, table, record_id)

        if table in {"assets", "sitreps"}:
            mission_page = self._pages.get("missions")
            if isinstance(mission_page, MissionPage):
                mission_page.handle_record_mutation(action, table, record_id)

    def _show_sitrep_overlay(self, record_id: int) -> None:
        try:
            item = latest_sitrep_item(self._core, record_id)
        except Exception as exc:
            _log.warning("Could not load SITREP alert item: %s", exc)
            return
        if item is None or not item.needs_attention:
            return
        try:
            audio_enabled = bool(self._core.read_model("settings.audio_enabled"))
        except Exception as exc:
            _log.warning("Could not load SITREP audio setting: %s", exc)
            audio_enabled = False
        self._sitrep_alert_overlay.show_item(item, audio_enabled=audio_enabled)


class DesktopRuntime(QtCore.QObject):
    lockRequested = QtCore.Signal(str)
    leaseRenewed = QtCore.Signal()

    def __init__(self, core: TalonCoreSession, *, start_sync: bool) -> None:
        super().__init__()
        self.core = core
        self.start_sync = start_sync
        self.event_bridge = CoreEventBridge()
        self.core.subscribe(self.event_bridge.handle_core_event)
        self.event_bridge.lockRequested.connect(self.lockRequested)
        self.lockRequested.connect(self.show_lock)
        self.leaseRenewed.connect(self.close_lock)
        self.login_window: LoginWindow | None = None
        self.main_window: MainWindow | None = None
        self.lock_window: LockWindow | None = None
        self._workers: list[_WorkerSignals] = []

    def show_login(self) -> None:
        self.login_window = LoginWindow(self.core.mode)
        self.login_window.unlockRequested.connect(self.unlock)
        self.login_window.enrollRequested.connect(self.enroll)
        self.login_window.show()

    @QtCore.Slot(str)
    def unlock(self, passphrase: str) -> None:
        assert self.login_window is not None
        self.login_window.set_busy(True, "Unlocking database...")
        try:
            self.core.start_reticulum()
        except Exception as exc:
            _log.warning("Reticulum init warning: %s", exc)

        signals = _WorkerSignals()
        self._workers.append(signals)
        signals.succeeded.connect(self._unlock_succeeded)
        signals.failed.connect(self._unlock_failed)

        def _worker() -> None:
            try:
                result = self.core.unlock(
                    passphrase,
                    start_lease_monitor=True,
                    install_audit=True,
                )
                sync_warning = ""
                if self.start_sync:
                    try:
                        self.core.start_sync(init_reticulum=False)
                    except Exception as exc:
                        if self.core.mode == "server":
                            sync_warning = str(exc)
                            _log.warning("Server sync failed to start: %s", exc)
                        else:
                            raise
                signals.succeeded.emit((result, sync_warning))
            except Exception as exc:
                _log.warning("Desktop unlock failed: %s", exc)
                self.core.close()
                signals.failed.emit(str(exc))

        threading.Thread(target=_worker, daemon=True, name="talon-desktop-unlock").start()

    @QtCore.Slot(object)
    def _unlock_succeeded(self, payload: object) -> None:
        result, sync_warning = typing.cast(tuple[object, str], payload)
        if self.login_window is not None and self.core.mode == "client":
            operator_id = getattr(result, "operator_id", None)
            if operator_id is None:
                self.login_window.show_enrollment()
                return
        self.show_main(sync_warning=sync_warning)

    @QtCore.Slot(str)
    def _unlock_failed(self, message: str) -> None:
        if self.login_window is not None:
            self.login_window.show_error(f"Unlock failed: {message}")

    @QtCore.Slot(str, str)
    def enroll(self, token_and_hash: str, callsign: str) -> None:
        assert self.login_window is not None
        self.login_window.set_busy(True, "Enrolling client...")
        signals = _WorkerSignals()
        self._workers.append(signals)
        signals.succeeded.connect(lambda _payload: self.show_main())
        signals.failed.connect(self._enroll_failed)

        def _worker() -> None:
            try:
                operator_id = self.core.enroll_client(token_and_hash, callsign)
                signals.succeeded.emit(operator_id)
            except Exception as exc:
                _log.warning("Desktop enrollment failed: %s", exc)
                signals.failed.emit(str(exc))

        threading.Thread(target=_worker, daemon=True, name="talon-desktop-enroll").start()

    @QtCore.Slot(str)
    def _enroll_failed(self, message: str) -> None:
        if self.login_window is not None:
            self.login_window.show_error(f"Enrollment failed: {message}")

    def show_main(self, *, sync_warning: str = "") -> None:
        if self.login_window is not None:
            self.login_window.hide()
        self.main_window = MainWindow(self.core, self.event_bridge)
        self.main_window.show()
        if sync_warning:
            self.main_window.statusBar().showMessage(
                f"Unlocked. Sync warning: {sync_warning}",
                8000,
            )

    @QtCore.Slot(str)
    def show_lock(self, reason: str) -> None:
        if self.lock_window is not None:
            return
        parent = self.main_window if self.main_window is not None else self.login_window
        self.lock_window = LockWindow(reason, parent)
        self.lock_window.show()

    @QtCore.Slot()
    def close_lock(self) -> None:
        if self.lock_window is not None:
            self.lock_window.accept()
            self.lock_window = None
        if self.main_window is not None:
            self.main_window.statusBar().showMessage("Lease renewed.", 5000)

    def shutdown(self) -> None:
        self.core.close()


def run_desktop(
    *,
    config_path: pathlib.Path | None = None,
    mode: typing.Literal["server", "client"] | None = None,
    start_sync: bool = True,
) -> int:
    app = QtWidgets.QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QtWidgets.QApplication([])
    app.setOrganizationName("TALON")
    apply_desktop_theme(app)
    app.setApplicationName("T.A.L.O.N.")
    install_desktop_log_buffer()

    runtime_ref: dict[str, DesktopRuntime] = {}

    def _lease_expired() -> None:
        runtime = runtime_ref.get("runtime")
        if runtime is not None:
            runtime.lockRequested.emit("lease_expired")

    def _lease_renewed() -> None:
        runtime = runtime_ref.get("runtime")
        if runtime is not None:
            runtime.leaseRenewed.emit()

    core = TalonCoreSession(
        config_path=config_path,
        mode=mode,
        on_lease_expired=_lease_expired,
        on_lease_renewed=_lease_renewed,
    ).start()
    runtime = DesktopRuntime(core, start_sync=start_sync)
    runtime_ref["runtime"] = runtime
    app.aboutToQuit.connect(runtime.shutdown)
    runtime.show_login()
    return app.exec() if owns_app else 0


def _operator_rows(core: TalonCoreSession) -> list[str]:
    rows = []
    for operator in core.read_model("operators.list", {"include_sentinel": True}):
        profile = _field(operator, "profile", default={})
        role = profile.get("role", "") if isinstance(profile, dict) else ""
        revoked = " revoked" if _field(operator, "revoked", default=False) else ""
        rows.append(f"#{_field(operator, 'id')} {_field(operator, 'callsign')} {role}{revoked}")
    return rows


def _field(obj: object, *names: str, default: object = "") -> object:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)


def _lock_message(reason: str) -> str:
    if reason == "lease_expired":
        return (
            "The local client lease has expired. Sync continues in the background "
            "so a server renewal can unlock the session."
        )
    if reason == "revoked":
        return "This operator has been revoked. Local operation is locked."
    return "The TALON core requested a local lock."

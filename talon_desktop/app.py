"""PySide6 desktop application shell."""
from __future__ import annotations

import pathlib
import threading
import typing

from PySide6 import QtCore, QtGui, QtWidgets

from talon_core import TalonCoreSession
from talon_core.utils.logging import get_logger

from talon_desktop.asset_page import AssetPage
from talon_desktop.chat_page import ChatPage
from talon_desktop.community_safety_page import AssignmentPage, IncidentPage
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
from talon_desktop.reticulum_config_dialog import ReticulumConfigDialog
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

DIRECT_TCP_PRIVACY_WARNING_TITLE = "TCP Connection Privacy Warning"
DIRECT_TCP_PRIVACY_WARNING_TEXT = (
    "This TALON session is using direct TCP, not Yggdrasil, I2P, or LoRa. "
    "A direct TCP path can reveal network addressing metadata to peers, routers, "
    "or local network observers.\n\n"
    "Use Yggdrasil, I2P, LoRa, or a trusted VPN when IP-address privacy matters. "
    "This warning appears every time a new direct TCP connection or session is "
    "established."
)


class _WorkerSignals(QtCore.QObject):
    succeeded = QtCore.Signal(object)
    failed = QtCore.Signal(str)


class LoginWindow(QtWidgets.QWidget):
    unlockRequested = QtCore.Signal(str)
    enrollRequested = QtCore.Signal(str, str)
    networkSetupRequested = QtCore.Signal()

    def __init__(self, mode: str) -> None:
        super().__init__()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            apply_desktop_theme(app)
        self._mode = mode
        self.setWindowTitle(f"T.A.L.O.N. Desktop [{mode.upper()}]")
        self.setMinimumWidth(520)
        self.setObjectName("loginWindow")
        self._unlocked = False

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
        self.network_status_label = QtWidgets.QLabel(
            "Network setup is available after unlock."
        )
        self.network_status_label.setWordWrap(True)
        self.network_status_label.setObjectName("statusLabel")
        self.network_setup_button = QtWidgets.QPushButton("Network Setup")
        self.network_setup_button.setVisible(False)
        self.network_setup_button.setEnabled(False)
        self.network_setup_button.clicked.connect(self.networkSetupRequested.emit)

        form = QtWidgets.QFormLayout()
        form.addRow("Passphrase", self.passphrase)

        self.enrollment_group = QtWidgets.QGroupBox("Client Enrollment")
        enrollment_layout = QtWidgets.QFormLayout(self.enrollment_group)
        self.token_field = QtWidgets.QLineEdit()
        self.token_field.setPlaceholderText("TOKEN:SERVER_HASH")
        self.paste_token_button = QtWidgets.QPushButton("Paste")
        self.paste_token_button.clicked.connect(self._paste_token)
        token_row = QtWidgets.QHBoxLayout()
        token_row.addWidget(self.token_field, stretch=1)
        token_row.addWidget(self.paste_token_button)
        self.callsign_field = QtWidgets.QLineEdit()
        self.callsign_field.setPlaceholderText("Callsign")
        self.enroll_button = QtWidgets.QPushButton("Enroll Client")
        self.enroll_button.clicked.connect(self._enroll_clicked)
        enrollment_layout.addRow("Token", token_row)
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
        layout.addWidget(self.network_status_label)
        layout.addWidget(self.network_setup_button)
        layout.addWidget(self.enrollment_group)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.unlock_button.setDisabled(busy or self._unlocked)
        self.enroll_button.setDisabled(busy)
        self.paste_token_button.setDisabled(busy)
        self.network_setup_button.setDisabled(busy or not self._unlocked)
        self.passphrase.setDisabled(busy or self._unlocked)
        self.status_label.setText(message)

    def show_error(self, message: str) -> None:
        self.set_busy(False)
        self.status_label.setText(message)

    def mark_unlocked(self) -> None:
        self._unlocked = True
        self.network_setup_button.setVisible(True)
        self.network_setup_button.setEnabled(True)
        self.network_status_label.setText("Network setup is available.")
        self.set_busy(False, "")

    def set_network_status(self, message: str) -> None:
        self.network_status_label.setText(message)

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

    def _paste_token(self) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        self.token_field.setText(clipboard.text().strip())


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
            f"Network method: {sync.network_method_label}",
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


class _NavItemProxy:
    def __init__(self, section: DesktopNavItem) -> None:
        self._section = section

    def data(self, role: int) -> str | None:
        if role == QtCore.Qt.UserRole:
            return self._section.key
        return None


class DesktopNavRail(QtWidgets.QWidget):
    """Persistent collapsible icon rail for primary desktop navigation."""

    currentRowChanged = QtCore.Signal(int)

    _COLLAPSED_WIDTH = 64
    _EXPANDED_WIDTH = 210
    _TAB_WIDTH = 16

    def __init__(
        self,
        sections: typing.Iterable[DesktopNavItem],
        *,
        mode: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("navRail")
        self._sections = tuple(sections)
        self._items = tuple(_NavItemProxy(section) for section in self._sections)
        self._buttons: list[QtWidgets.QToolButton] = []
        self._badges: dict[str, int] = {}
        self._current_row = -1
        self._expanded = True

        self._button_group = QtWidgets.QButtonGroup(self)
        self._button_group.setExclusive(True)

        self._content = QtWidgets.QWidget()
        self._content.setObjectName("navRailContent")
        self._content_layout = QtWidgets.QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 14, 8, 10)
        self._content_layout.setSpacing(6)

        self._title = QtWidgets.QLabel("T.A.L.O.N.")
        self._title.setObjectName("sideTitle")
        self._mode_label = QtWidgets.QLabel(f"{mode.upper()} NODE")
        self._mode_label.setObjectName("sideMode")
        self._content_layout.addWidget(self._title)
        self._content_layout.addWidget(self._mode_label)
        self._content_layout.addSpacing(12)

        for index, section in enumerate(self._sections):
            button = QtWidgets.QToolButton()
            button.setObjectName("navRailButton")
            button.setCheckable(True)
            button.setToolTip(section.label)
            button.setIcon(self._icon_for(section.key))
            button.setText(section.label)
            button.setAutoRaise(True)
            button.clicked.connect(lambda _checked=False, row=index: self.setCurrentRow(row))
            self._button_group.addButton(button, index)
            self._buttons.append(button)
            self._content_layout.addWidget(button)

        self._content_layout.addStretch(1)

        self._toggle_button = QtWidgets.QToolButton()
        self._toggle_button.setObjectName("navRailToggle")
        self._toggle_button.setAutoRaise(True)
        self._toggle_button.clicked.connect(self.toggle)

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._content)
        root.addWidget(self._toggle_button)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        self._apply_expanded_state()

    def count(self) -> int:
        return len(self._items)

    def item(self, index: int) -> _NavItemProxy:
        return self._items[index]

    def currentItem(self) -> _NavItemProxy | None:
        if 0 <= self._current_row < len(self._items):
            return self._items[self._current_row]
        return None

    def currentRow(self) -> int:
        return self._current_row

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._apply_expanded_state()

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def setCurrentRow(self, row: int) -> None:
        if row < 0 or row >= len(self._buttons):
            return
        if row == self._current_row:
            return
        self._current_row = row
        self._buttons[row].setChecked(True)
        self.currentRowChanged.emit(row)

    def increment_badge(self, section_key: str) -> None:
        if self.currentItem() is not None and self.currentItem().data(QtCore.Qt.UserRole) == section_key:
            return
        self._badges[section_key] = self._badges.get(section_key, 0) + 1
        self._sync_button_labels()

    def clear_badge(self, section_key: str) -> None:
        if section_key in self._badges:
            self._badges.pop(section_key, None)
            self._sync_button_labels()

    def set_badges(self, badges: dict[str, int]) -> None:
        self._badges = {key: count for key, count in badges.items() if count > 0}
        self._sync_button_labels()

    def _apply_expanded_state(self) -> None:
        content_width = self._EXPANDED_WIDTH if self._expanded else self._COLLAPSED_WIDTH
        self._content.setFixedWidth(content_width)
        self._toggle_button.setFixedWidth(self._TAB_WIDTH)
        self.setFixedWidth(content_width + self._TAB_WIDTH)
        self._title.setVisible(self._expanded)
        self._mode_label.setVisible(self._expanded)
        self._toggle_button.setText("<" if self._expanded else ">")
        style = (
            QtCore.Qt.ToolButtonTextBesideIcon
            if self._expanded
            else QtCore.Qt.ToolButtonIconOnly
        )
        for button in self._buttons:
            button.setToolButtonStyle(style)
            button.setFixedHeight(40)
            button.setIconSize(QtCore.QSize(22, 22))
        self._sync_button_labels()

    def _sync_button_labels(self) -> None:
        for section, button in zip(self._sections, self._buttons):
            count = self._badges.get(section.key, 0)
            label = section.label if not count else f"{section.label} ({count})"
            button.setText(label)
            tooltip = section.label if not count else f"{section.label}: {count} update(s)"
            button.setToolTip(tooltip)

    def _icon_for(self, key: str) -> QtGui.QIcon:
        style = self.style()
        icons = {
            "dashboard": QtWidgets.QStyle.SP_ComputerIcon,
            "map": QtWidgets.QStyle.SP_DialogOpenButton,
            "sitreps": QtWidgets.QStyle.SP_MessageBoxWarning,
            "assets": QtWidgets.QStyle.SP_DriveNetIcon,
            "missions": QtWidgets.QStyle.SP_ArrowForward,
            "chat": QtWidgets.QStyle.SP_FileDialogDetailedView,
            "documents": QtWidgets.QStyle.SP_FileIcon,
            "operators": QtWidgets.QStyle.SP_DirHomeIcon,
            "enrollment": QtWidgets.QStyle.SP_FileDialogNewFolder,
            "clients": QtWidgets.QStyle.SP_DirIcon,
            "audit": QtWidgets.QStyle.SP_FileDialogInfoView,
            "keys": QtWidgets.QStyle.SP_DialogYesButton,
        }
        return style.standardIcon(icons.get(key, QtWidgets.QStyle.SP_FileIcon))


class CurrentPageStack(QtWidgets.QStackedWidget):
    """Stack that sizes the shell from the visible page, not hidden pages."""

    def sizeHint(self) -> QtCore.QSize:
        current = self.currentWidget()
        if current is not None:
            return current.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self) -> QtCore.QSize:
        current = self.currentWidget()
        if current is not None:
            return current.minimumSizeHint()
        return QtCore.QSize(0, 0)

    def setCurrentIndex(self, index: int) -> None:
        super().setCurrentIndex(index)
        self.updateGeometry()

    def setCurrentWidget(self, widget: QtWidgets.QWidget) -> None:
        super().setCurrentWidget(widget)
        self.updateGeometry()


class MainWindow(QtWidgets.QMainWindow):
    networkSetupRequested = QtCore.Signal()

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
        self._last_direct_tcp_warning_session_id: int | None = None
        self._settings_prefix = f"{core.mode}/main_window"
        self._theme_key = str(self._settings.value(self._setting_key("theme"), "dark"))
        self._font_scale = self._read_font_scale()
        self._apply_visual_preferences()
        self.setWindowTitle(f"T.A.L.O.N. Desktop [{core.mode.upper()}]")
        self.resize(self._bounded_initial_size(1180, 760))

        sections = navigation_items(core.mode)
        self.nav = DesktopNavRail(sections, mode=core.mode)
        self.stack = CurrentPageStack()

        for section in sections:
            if section.key == "sitreps":
                page = SitrepPage(core)
            elif section.key == "assets":
                page = AssetPage(core)
            elif section.key == "map":
                page = MapPage(core)
            elif section.key == "missions":
                page = MissionPage(core)
            elif section.key == "assignments":
                page = AssignmentPage(core)
            elif section.key == "incidents":
                page = IncidentPage(core)
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

        self._root_splitter = QtWidgets.QSplitter()
        self._root_splitter.setObjectName("mainSplitter")
        self._root_splitter.addWidget(self.nav)
        self._root_splitter.addWidget(self.stack)
        self._root_splitter.setStretchFactor(1, 1)
        self.setCentralWidget(self._root_splitter)
        self.setMinimumSize(320, 240)
        self._sitrep_alert_overlay = SitrepAlertOverlay(self.stack)
        self.statusBar().showMessage("Core unlocked.")
        self.network_method_badge = QtWidgets.QLabel("Network method unknown")
        self.network_method_badge.setObjectName("networkMethodBadge")
        self.network_setup_button = QtWidgets.QPushButton("Network Setup")
        self.network_setup_button.setObjectName("statusButton")
        self.network_setup_button.clicked.connect(self.networkSetupRequested.emit)
        self._log_button = QtWidgets.QPushButton("Logs")
        self._log_button.setObjectName("statusButton")
        self._log_button.clicked.connect(self._show_logs)
        self._theme_button = QtWidgets.QPushButton("Theme")
        self._theme_button.setObjectName("statusButton")
        self._theme_button.clicked.connect(self._show_theme_menu)
        self._font_button = QtWidgets.QPushButton("Font")
        self._font_button.setObjectName("statusButton")
        self._font_button.clicked.connect(self._show_font_scale_dialog)
        self.statusBar().addPermanentWidget(self.network_method_badge)
        self.statusBar().addPermanentWidget(self.network_setup_button)
        self.statusBar().addPermanentWidget(self._theme_button)
        self.statusBar().addPermanentWidget(self._font_button)
        self.statusBar().addPermanentWidget(self._log_button)
        self._network_status_timer = QtCore.QTimer(self)
        self._network_status_timer.timeout.connect(self._refresh_network_method_status)
        self._network_status_timer.start(2000)
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
        self._refresh_network_method_status()
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

    def set_network_setup_busy(self, busy: bool) -> None:
        self.network_setup_button.setDisabled(busy)

    def show_network_status(self, message: str, timeout_ms: int = 8000) -> None:
        self.statusBar().showMessage(message, timeout_ms)
        self._refresh_network_method_status()

    def _on_nav_changed(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        item = self.nav.item(row)
        section_key = item.data(QtCore.Qt.UserRole)
        self._settings.setValue(self._setting_key("last_section"), str(section_key))
        self.refresh_section(str(section_key))
        self.nav.clear_badge(str(section_key))

    def closeEvent(self, event: QtCore.QEvent) -> None:
        self._save_desktop_state()
        super().closeEvent(event)

    def resizeEvent(self, event: QtCore.QEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_sitrep_alert_overlay"):
            self._sitrep_alert_overlay.reposition()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._fit_to_available_geometry)

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
        self.nav.set_expanded(
            str(self._settings.value(self._setting_key("nav_expanded"), "true")).lower()
            != "false"
        )
        self._fit_to_available_geometry()
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
        self._settings.setValue(
            self._setting_key("nav_expanded"),
            "true" if self.nav.is_expanded() else "false",
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

    def _bounded_initial_size(self, width: int, height: int) -> QtCore.QSize:
        available = self._available_geometry()
        if available is None:
            return QtCore.QSize(width, height)
        return QtCore.QSize(
            min(width, max(320, available.width())),
            min(height, max(240, available.height())),
        )

    def _fit_to_available_geometry(self) -> None:
        if self.isFullScreen() or self.isMaximized():
            return
        available = self._available_geometry()
        if available is None:
            return

        bounded_width = min(self.width(), max(320, available.width()))
        bounded_height = min(self.height(), max(240, available.height()))
        if bounded_width != self.width() or bounded_height != self.height():
            self.resize(bounded_width, bounded_height)

        geometry = self.geometry()
        left = available.left()
        top = available.top()
        right = available.x() + available.width()
        bottom = available.y() + available.height()
        if geometry.width() <= available.width():
            left = min(max(geometry.x(), left), right - geometry.width())
        if geometry.height() <= available.height():
            top = min(max(geometry.y(), top), bottom - geometry.height())
        if geometry.x() != left or geometry.y() != top:
            self.move(left, top)

    def _available_geometry(self) -> QtCore.QRect | None:
        screen = QtGui.QGuiApplication.screenAt(self.geometry().center())
        if screen is None:
            screen = self.screen()
        if screen is None:
            screen = QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return None
        return screen.availableGeometry()

    def _read_font_scale(self) -> float:
        try:
            return float(self._core.read_model("settings.font_scale"))
        except Exception:
            return 1.0

    def _apply_visual_preferences(self) -> None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            apply_desktop_theme(
                app,
                theme_key=self._theme_key,
                font_scale=self._font_scale,
            )

    @QtCore.Slot()
    def _show_theme_menu(self) -> None:
        menu = QtWidgets.QMenu(self)
        options = (
            ("dark", "Dark"),
            ("high_contrast", "High Contrast"),
            ("field", "Field"),
        )
        for key, label in options:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(key == self._theme_key)
            action.triggered.connect(lambda _checked=False, k=key: self._set_theme(k))
        menu.exec(self._theme_button.mapToGlobal(QtCore.QPoint(0, self._theme_button.height())))

    def _set_theme(self, theme_key: str) -> None:
        self._theme_key = theme_key
        self._settings.setValue(self._setting_key("theme"), theme_key)
        self._apply_visual_preferences()

    @QtCore.Slot()
    def _show_font_scale_dialog(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Font Scale")
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(0.8, 1.6)
        spin.setSingleStep(0.05)
        spin.setDecimals(2)
        spin.setValue(self._font_scale)
        save = QtWidgets.QPushButton("Save")
        cancel = QtWidgets.QPushButton("Cancel")
        save.clicked.connect(dialog.accept)
        cancel.clicked.connect(dialog.reject)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        form = QtWidgets.QFormLayout(dialog)
        form.addRow("Scale", spin)
        form.addRow("", buttons)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        self._font_scale = float(spin.value())
        try:
            self._core.command(
                "settings.set_meta",
                key="global_font_scale",
                value=self._font_scale,
            )
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Font Scale", str(exc))
            return
        self._apply_visual_preferences()

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

    def _refresh_network_method_status(self) -> None:
        try:
            sync = self._core.read_model("sync.status")
        except Exception as exc:
            self.network_method_badge.setText("Network method unknown")
            self.network_method_badge.setProperty("warning", False)
            self.network_method_badge.setToolTip(f"Unable to read network status: {exc}")
            self._refresh_widget_style(self.network_method_badge)
            return

        label = str(getattr(sync, "network_method_label", "Unknown") or "Unknown")
        method = str(getattr(sync, "network_method", "unknown") or "unknown")
        warning = bool(getattr(sync, "network_method_exposes_ip", False))
        if method == "unknown":
            text = "Network method unknown"
        elif bool(getattr(sync, "connected", False)):
            text = f"Connected via {label}"
        elif bool(getattr(sync, "sync_started", False)):
            text = (
                f"Listening via {label}"
                if self._core.mode == "server"
                else f"Using {label}"
            )
        else:
            text = f"Configured via {label}"

        self.network_method_badge.setText(text)
        self.network_method_badge.setProperty("warning", warning)
        self.network_method_badge.setToolTip(
            "Direct TCP can reveal IP-address metadata. Use Yggdrasil, I2P, "
            "LoRa, or a trusted VPN when privacy matters."
            if warning
            else f"TALON network method: {label}"
        )
        self._refresh_widget_style(self.network_method_badge)
        self._maybe_show_direct_tcp_warning(sync)

    def _maybe_show_direct_tcp_warning(self, sync: object) -> None:
        if not bool(getattr(sync, "network_method_exposes_ip", False)):
            return
        if not bool(getattr(sync, "sync_started", False)):
            return
        session_id = int(getattr(sync, "connection_session_id", 0) or 0)
        warning_id = session_id if session_id > 0 else -1
        if self._last_direct_tcp_warning_session_id == warning_id:
            return
        self._last_direct_tcp_warning_session_id = warning_id
        QtCore.QTimer.singleShot(0, self._show_direct_tcp_privacy_warning)

    def _show_direct_tcp_privacy_warning(self) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(DIRECT_TCP_PRIVACY_WARNING_TITLE)
        box.setText(DIRECT_TCP_PRIVACY_WARNING_TEXT)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        dismiss = box.button(QtWidgets.QMessageBox.Ok)
        if dismiss is not None:
            dismiss.setText("Dismiss")
        box.exec()

    @staticmethod
    def _refresh_widget_style(widget: QtWidgets.QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)

    def _on_record_mutated(self, action: str, table: str, record_id: int) -> None:
        self.statusBar().showMessage(f"{table} {action}: #{record_id}", 5000)
        self._mark_badges_for_mutation(table)
        if table == "sitreps":
            page = self._pages.get("sitreps")
            if isinstance(page, SitrepPage):
                page.handle_record_mutation(action, table, record_id)
            if action == "changed":
                self._show_sitrep_overlay(record_id)
            map_page = self._pages.get("map")
            if isinstance(map_page, MapPage):
                map_page.handle_record_mutation(action, table, record_id)
        elif table in {"sitrep_followups", "sitrep_documents"}:
            page = self._pages.get("sitreps")
            if isinstance(page, SitrepPage):
                page.handle_record_mutation(action, table, record_id)
            map_page = self._pages.get("map")
            if isinstance(map_page, MapPage):
                map_page.handle_record_mutation(action, table, record_id)
            if table == "sitrep_documents":
                document_page = self._pages.get("documents")
                if isinstance(document_page, DocumentPage):
                    document_page.handle_record_mutation(action, table, record_id)
        elif table == "assets":
            page = self._pages.get("assets")
            if isinstance(page, AssetPage):
                page.handle_record_mutation(action, table, record_id)
            map_page = self._pages.get("map")
            if isinstance(map_page, MapPage):
                map_page.handle_record_mutation(action, table, record_id)
        elif table in {"assignments", "checkins"}:
            assignment_page = self._pages.get("assignments")
            if isinstance(assignment_page, AssignmentPage):
                assignment_page.handle_record_mutation(action, table, record_id)
            map_page = self._pages.get("map")
            if isinstance(map_page, MapPage):
                map_page.handle_record_mutation(action, table, record_id)
            mission_page = self._pages.get("missions")
            if isinstance(mission_page, MissionPage):
                mission_page.handle_record_mutation(action, table, record_id)
        elif table == "incidents":
            incident_page = self._pages.get("incidents")
            if isinstance(incident_page, IncidentPage):
                incident_page.handle_record_mutation(action, table, record_id)
            assignment_page = self._pages.get("assignments")
            if isinstance(assignment_page, AssignmentPage):
                assignment_page.handle_record_mutation(action, table, record_id)
            page = self._pages.get("sitreps")
            if isinstance(page, SitrepPage):
                page.handle_record_mutation(action, table, record_id)
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

        if table in {"assets", "sitreps", "assignments", "checkins", "incidents"}:
            mission_page = self._pages.get("missions")
            if isinstance(mission_page, MissionPage):
                mission_page.handle_record_mutation(action, table, record_id)

    def _mark_badges_for_mutation(self, table: str) -> None:
        sections_by_table = {
            "assets": ("assets", "map", "dashboard"),
            "missions": ("missions", "map", "dashboard"),
            "zones": ("map", "dashboard"),
            "waypoints": ("map", "dashboard"),
            "sitreps": ("sitreps", "map", "dashboard"),
            "sitrep_followups": ("sitreps", "map", "dashboard"),
            "sitrep_documents": ("sitreps", "documents", "map", "dashboard"),
            "assignments": ("assignments", "map", "missions", "dashboard"),
            "checkins": ("assignments", "map", "dashboard"),
            "incidents": ("incidents", "assignments", "sitreps", "map", "dashboard"),
            "channels": ("chat",),
            "messages": ("chat", "dashboard"),
            "documents": ("documents",),
            "operators": ("operators", "clients", "keys", "chat"),
        }
        for section in sections_by_table.get(table, ()):
            if section in self._pages:
                self.nav.increment_badge(section)

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
        self.login_window.networkSetupRequested.connect(self.configure_network)
        self.login_window.show()

    @QtCore.Slot(str)
    def unlock(self, passphrase: str) -> None:
        assert self.login_window is not None
        self.login_window.set_busy(True, "Unlocking database...")

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
                signals.succeeded.emit(result)
            except Exception as exc:
                _log.warning("Desktop unlock failed: %s", exc)
                self.core.close()
                signals.failed.emit(str(exc))

        threading.Thread(target=_worker, daemon=True, name="talon-desktop-unlock").start()

    @QtCore.Slot(object)
    def _unlock_succeeded(self, payload: object) -> None:
        result = payload
        sync_warning = ""
        assert self.login_window is not None
        self.login_window.mark_unlocked()
        if self.start_sync:
            network_result = self._start_network_for_unlocked_session()
            if network_result is None:
                return
            sync_warning = network_result
        if self.login_window is not None and self.core.mode == "client":
            operator_id = getattr(result, "operator_id", None)
            if operator_id is None:
                self.login_window.show_enrollment()
                return
        self.show_main(sync_warning=sync_warning)

    def _start_network_for_unlocked_session(self) -> str | None:
        assert self.login_window is not None
        self.login_window.set_busy(True, "Checking Reticulum configuration...")
        if not self._ensure_reticulum_config_ready():
            return None
        self.login_window.set_busy(True, "Starting Reticulum...")
        try:
            self.core.start_reticulum()
        except Exception as exc:
            _log.warning("Reticulum failed to start: %s", exc)
            self.login_window.show_error(f"Reticulum failed to start: {exc}")
            return None
        self.login_window.set_network_status(
            "Network started. Network changes require restarting TALON."
        )
        self.login_window.set_busy(True, "Starting sync...")
        try:
            self.core.start_sync(init_reticulum=False)
        except Exception as exc:
            if self.core.mode == "server":
                _log.warning("Server sync failed to start: %s", exc)
                return str(exc)
            _log.warning("Client sync failed to start: %s", exc)
            self.login_window.show_error(f"Sync failed to start: {exc}")
            return None
        return ""

    def _ensure_reticulum_config_ready(self) -> bool:
        assert self.login_window is not None
        try:
            status = self.core.reticulum_config_status()
        except Exception as exc:
            self.login_window.show_error(f"Reticulum setup failed: {exc}")
            return False
        if status.needs_setup:
            try:
                dialog = ReticulumConfigDialog(self.core, self.login_window)
                accepted = dialog.exec() == QtWidgets.QDialog.Accepted
            except Exception as exc:
                self.login_window.show_error(f"Reticulum setup failed: {exc}")
                return False
            if not accepted:
                self.login_window.show_error(
                    "Reticulum setup is required before network startup."
                )
                return False
            try:
                status = self.core.reticulum_config_status()
            except Exception as exc:
                self.login_window.show_error(f"Reticulum setup failed: {exc}")
                return False
        if not status.exists:
            self.login_window.show_error(
                f"Reticulum config is missing: {status.path}"
            )
            return False
        if not status.valid:
            self.login_window.show_error(
                "Reticulum config is invalid: " + "; ".join(status.errors)
            )
            return False
        return True

    @QtCore.Slot(str)
    def _unlock_failed(self, message: str) -> None:
        if self.login_window is not None:
            self.login_window.show_error(f"Unlock failed: {message}")

    @QtCore.Slot()
    def configure_network(self) -> None:
        parent = self.main_window if self.main_window is not None else self.login_window
        using_main_window = self.main_window is not None
        if self.main_window is not None:
            self.main_window.set_network_setup_busy(True)
            self.main_window.show_network_status("Opening network setup...", 0)
        elif self.login_window is not None:
            self.login_window.set_busy(True, "Opening network setup...")
        try:
            if not self.core.is_unlocked:
                if self.login_window is not None:
                    self.login_window.show_error(
                        "Unlock the database before network setup."
                    )
                if self.main_window is not None:
                    self.main_window.show_network_status(
                        "Unlock the database before network setup."
                    )
                    self.main_window.set_network_setup_busy(False)
                return
            dialog = ReticulumConfigDialog(self.core, parent)
            accepted = dialog.exec() == QtWidgets.QDialog.Accepted
        except Exception as exc:
            if self.login_window is not None:
                self.login_window.show_error(f"Reticulum setup failed: {exc}")
            if self.main_window is not None:
                self.main_window.show_network_status(f"Reticulum setup failed: {exc}")
                self.main_window.set_network_setup_busy(False)
            return
        if self.main_window is not None:
            self.main_window.set_network_setup_busy(False)
        elif self.login_window is not None:
            self.login_window.set_busy(False)
        if not accepted:
            if self.main_window is not None:
                self.main_window.show_network_status("Network setup cancelled.")
            return
        if self.core.reticulum_started:
            if self.login_window is not None:
                self.login_window.set_network_status(
                    "Network settings saved. Restart TALON to use changes."
                )
            if self.main_window is not None:
                self.main_window.show_network_status(
                    "Network settings saved. Restart TALON to use changes."
                )
            return
        if not self.start_sync:
            if self.login_window is not None:
                self.login_window.set_network_status("Network settings saved.")
            if self.main_window is not None:
                self.main_window.show_network_status("Network settings saved.")
            return
        if using_main_window:
            self.main_window.show_network_status(
                "Network settings saved. Restart TALON to start networking."
            )
            return
        network_result = self._start_network_for_unlocked_session()
        if network_result is None:
            return
        if self.login_window is not None and self.core.mode == "client":
            self.login_window.show_enrollment()
            return
        self.show_main(sync_warning=network_result)

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
        self.main_window.networkSetupRequested.connect(self.configure_network)
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

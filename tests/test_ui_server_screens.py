# tests/test_ui_server_screens.py
# Tests for the server UI screens — login, main, dashboard, registry,
# reauth, audit, enrollment.
#
# Kivy is mocked via conftest.py. Tests exercise state management,
# navigation logic, property defaults, color maps, and helper methods.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import time
from unittest.mock import MagicMock, patch

# ================================================================
# Server App — TalonServerApp
# ================================================================
from talon.ui.server.app import TalonServerApp


class TestServerAppHexToRgba:
    def test_black(self):
        assert TalonServerApp._hex_to_rgba("#000000") == (0.0, 0.0, 0.0, 1.0)

    def test_white(self):
        assert TalonServerApp._hex_to_rgba("#ffffff") == (1.0, 1.0, 1.0, 1.0)

    def test_amber(self):
        r, g, b, a = TalonServerApp._hex_to_rgba("#f5a623")
        assert abs(r - 245 / 255) < 0.001
        assert abs(g - 166 / 255) < 0.001
        assert abs(b - 35 / 255) < 0.001


# ================================================================
# Server LoginScreen
# ================================================================

from talon.ui.server.screens.login import ServerLoginScreen


class TestServerLoginDefaults:
    def test_error_text_empty(self):
        screen = ServerLoginScreen(name="server_login")
        assert screen.error_text == ""

    def test_is_loading_false(self):
        screen = ServerLoginScreen(name="server_login")
        assert screen.is_loading is False


class TestServerLoginShowError:
    def test_show_error_sets_text_and_stops_loading(self):
        screen = ServerLoginScreen(name="server_login")
        screen.is_loading = True
        screen.show_error("Wrong passphrase")
        assert screen.error_text == "Wrong passphrase"
        assert screen.is_loading is False


class TestServerLoginSubmit:
    def _make_ids(self, text):
        ids = MagicMock()
        ids.passphrase_field.text = text
        return ids

    def test_empty_passphrase_sets_error(self):
        screen = ServerLoginScreen(name="server_login")
        screen.ids = self._make_ids("   ")
        screen.on_submit()
        assert screen.error_text == "Passphrase is required."

    def test_valid_passphrase_calls_do_login(self):
        screen = ServerLoginScreen(name="server_login")
        screen.ids = self._make_ids("server-passphrase")

        mock_app = MagicMock()
        with patch("kivy.app.App") as MockApp:
            MockApp.get_running_app.return_value = mock_app
            screen.on_submit()

        assert screen.is_loading is True
        assert screen.error_text == ""
        mock_app.do_login.assert_called_once_with("server-passphrase")

    def test_typing_clears_error(self):
        screen = ServerLoginScreen(name="server_login")
        screen.error_text = "old error"
        screen.on_passphrase_text(None, "a")
        assert screen.error_text == ""


# ================================================================
# Server MainScreen
# ================================================================

from talon.ui.server.screens.main import SERVER_NAV, ServerMainScreen


class TestServerNavItems:
    def test_has_five_entries(self):
        assert len(SERVER_NAV) == 5

    def test_sections_are_correct(self):
        sections = [item[2] for item in SERVER_NAV]
        assert "dashboard" in sections
        assert "registry" in sections
        assert "reauth" in sections
        assert "audit" in sections
        assert "enrollment" in sections


class TestServerMainDefaults:
    def test_default_section(self):
        screen = ServerMainScreen(name="server_main")
        assert screen.active_section == "dashboard"

    def test_default_online_count_zero(self):
        screen = ServerMainScreen(name="server_main")
        assert screen.online_count == 0

    def test_default_pending_reauth_zero(self):
        screen = ServerMainScreen(name="server_main")
        assert screen.pending_reauth == 0

    def test_default_transport_offline(self):
        screen = ServerMainScreen(name="server_main")
        assert screen.transport_name == "offline"

    def test_default_uptime_text(self):
        screen = ServerMainScreen(name="server_main")
        assert screen.uptime_text == "--:--"


class TestServerMainNavigation:
    def test_navigate_updates_section(self):
        screen = ServerMainScreen(name="server_main")
        screen.ids = {}  # No server_content — widget swap is no-op
        screen.navigate_to("audit")
        assert screen.active_section == "audit"

    def test_on_nav_item_selected_delegates(self):
        screen = ServerMainScreen(name="server_main")
        screen.ids = {}
        screen.on_nav_item_selected("enrollment")
        assert screen.active_section == "enrollment"


class TestServerMainSectionWidgets:
    def test_unknown_section_returns_none(self):
        screen = ServerMainScreen(name="server_main")
        assert screen._get_section_widget("nonexistent") is None

    def test_dashboard_widget(self):
        screen = ServerMainScreen(name="server_main")
        assert screen._get_section_widget("dashboard") is not None

    def test_registry_widget(self):
        screen = ServerMainScreen(name="server_main")
        assert screen._get_section_widget("registry") is not None

    def test_reauth_widget(self):
        screen = ServerMainScreen(name="server_main")
        assert screen._get_section_widget("reauth") is not None

    def test_audit_widget(self):
        screen = ServerMainScreen(name="server_main")
        assert screen._get_section_widget("audit") is not None

    def test_enrollment_widget(self):
        screen = ServerMainScreen(name="server_main")
        assert screen._get_section_widget("enrollment") is not None


class TestServerMainUptime:
    def test_uptime_format_zero(self):
        screen = ServerMainScreen(name="server_main")
        screen._start_time = time.time()
        screen._update_uptime(0)
        assert screen.uptime_text == "00:00"

    def test_uptime_format_after_delay(self):
        screen = ServerMainScreen(name="server_main")
        screen._start_time = time.time() - 3661  # 1h 1m 1s ago
        screen._update_uptime(0)
        assert screen.uptime_text == "01:01"

    def test_uptime_no_start_time(self):
        screen = ServerMainScreen(name="server_main")
        screen._start_time = None
        screen._update_uptime(0)
        assert screen.uptime_text == "--:--"  # Unchanged from default


class TestServerMainRefreshCounts:
    def test_refresh_counts_online(self):
        screen = ServerMainScreen(name="server_main")
        mock_server = MagicMock()
        mock_server.client_registry.get_online_clients.return_value = [
            {"callsign": "W1"},
            {"callsign": "W2"},
            {"callsign": "W3"},
        ]
        mock_server.client_registry.clients = {
            "c1": {"status": "ONLINE"},
            "c2": {"status": "ONLINE"},
            "c3": {"status": "ONLINE"},
        }
        screen._talon = mock_server
        screen._refresh_counts()
        assert screen.online_count == 3
        assert screen.pending_reauth == 0

    def test_refresh_counts_with_soft_locked(self):
        screen = ServerMainScreen(name="server_main")
        mock_server = MagicMock()
        mock_server.client_registry.get_online_clients.return_value = [{"callsign": "W1"}]
        mock_server.client_registry.clients = {
            "c1": {"status": "ONLINE"},
            "c2": {"status": "SOFT_LOCKED"},
            "c3": {"status": "SOFT_LOCKED"},
        }
        screen._talon = mock_server
        screen._refresh_counts()
        assert screen.online_count == 1
        assert screen.pending_reauth == 2


# ================================================================
# Audit screen — color maps and filter constants
# ================================================================

from talon.ui.server.screens.audit_screen import (
    EVENT_COLORS,
    FILTER_OPTIONS,
    AuditPanel,
)


class TestAuditEventColors:
    def test_sitrep_created_is_blue(self):
        assert EVENT_COLORS["SITREP_CREATED"] == "#4a9eff"

    def test_sitrep_deleted_is_red(self):
        assert EVENT_COLORS["SITREP_DELETED"] == "#ff3b3b"

    def test_client_enrolled_is_green(self):
        assert EVENT_COLORS["CLIENT_ENROLLED"] == "#00e5a0"

    def test_client_revoked_is_red(self):
        assert EVENT_COLORS["CLIENT_REVOKED"] == "#ff3b3b"

    def test_client_stale_is_amber(self):
        assert EVENT_COLORS["CLIENT_STALE"] == "#f5a623"

    def test_reauth_approved_is_green(self):
        assert EVENT_COLORS["REAUTH_APPROVED"] == "#00e5a0"

    def test_reauth_denied_is_red(self):
        assert EVENT_COLORS["REAUTH_DENIED"] == "#ff3b3b"

    def test_server_started_is_blue(self):
        assert EVENT_COLORS["SERVER_STARTED"] == "#4a9eff"

    def test_all_colors_are_valid_hex(self):
        for event, color in EVENT_COLORS.items():
            assert color.startswith("#") and len(color) == 7, f"Bad color for {event}"


class TestAuditFilterOptions:
    def test_filter_options_count(self):
        assert len(FILTER_OPTIONS) == 7

    def test_all_is_first(self):
        assert FILTER_OPTIONS[0] == "ALL"

    def test_expected_filters(self):
        expected = {"ALL", "AUTH", "SITREP", "ASSET", "MISSION", "CHAT", "SYSTEM"}
        assert set(FILTER_OPTIONS) == expected


class TestAuditPanelState:
    def test_default_filter(self):
        panel = AuditPanel()
        assert panel._active_filter == "ALL"

    def test_default_search_empty(self):
        panel = AuditPanel()
        assert panel._search_text == ""

    def test_load_events_no_server(self):
        panel = AuditPanel()
        assert panel._load_events(None) == []

    def test_load_events_no_db(self):
        server = MagicMock()
        server.db = None
        panel = AuditPanel()
        assert panel._load_events(server) == []

    def test_load_events_with_filter(self):
        """Test that filter builds correct SQL conditions."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (time.time(), "WOLF-1", "SITREP_CREATED", "test"),
        ]
        server = MagicMock()
        server.db.execute.return_value = mock_cursor

        panel = AuditPanel()
        panel._active_filter = "SITREP"
        result = panel._load_events(server)
        assert len(result) == 1

        # Verify the SQL was called with SITREP% pattern
        call_args = server.db.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "LIKE" in sql
        assert "SITREP%" in params


# ================================================================
# Enrollment panel
# ================================================================

from talon.ui.server.screens.enrollment import EnrollmentPanel


class TestEnrollmentPanel:
    def test_initial_state(self):
        panel = EnrollmentPanel()
        assert panel._talon is None
        assert panel._last_token is None
        assert panel._last_callsign is None

    def test_generate_creates_token(self):
        """Test the generate flow delegates to TalonServer."""
        panel = EnrollmentPanel()
        panel._talon = MagicMock()
        panel._talon.create_enrollment_token.return_value = "a" * 32

        mock_field = MagicMock()
        mock_field.text = "wolf-5"
        panel._callsign_field = mock_field

        panel._generate()

        assert panel._last_token == "a" * 32
        assert panel._last_callsign == "WOLF-5"  # Uppercased
        panel._talon.create_enrollment_token.assert_called_once_with("WOLF-5")

    def test_generate_empty_callsign_does_nothing(self):
        panel = EnrollmentPanel()
        mock_field = MagicMock()
        mock_field.text = "   "
        panel._callsign_field = mock_field
        panel._generate()
        assert panel._last_token is None

    def test_generate_no_talon_does_nothing(self):
        panel = EnrollmentPanel()
        panel._talon = None
        mock_field = MagicMock()
        mock_field.text = "WOLF-5"
        panel._callsign_field = mock_field
        panel._generate()
        assert panel._last_token is None

    def test_copy_token_calls_clipboard(self):
        with patch("talon.ui.server.screens.enrollment.Clipboard") as mock_clip:
            # MDSnackbar is mocked but needs .open() to work
            mock_snackbar = MagicMock()
            with patch("kivymd.uix.snackbar.MDSnackbar", return_value=mock_snackbar):
                panel = EnrollmentPanel()
                panel._copy_token("abc123")
            mock_clip.copy.assert_called_once_with("abc123")


# ================================================================
# Registry panel — status colors
# ================================================================

from talon.ui.server.screens.registry import STATUS_COLORS as REG_STATUS_COLORS
from talon.ui.server.screens.registry import RegistryPanel


class TestRegistryStatusColors:
    def test_online_is_green(self):
        assert REG_STATUS_COLORS["ONLINE"] == "#00e5a0"

    def test_stale_is_amber(self):
        assert REG_STATUS_COLORS["STALE"] == "#f5a623"

    def test_revoked_is_red(self):
        assert REG_STATUS_COLORS["REVOKED"] == "#ff3b3b"

    def test_soft_locked_is_amber(self):
        assert REG_STATUS_COLORS["SOFT_LOCKED"] == "#f5a623"


class TestRegistryPanel:
    def test_initial_state(self):
        panel = RegistryPanel()
        assert panel._talon is None
        assert panel._confirm_dialog is None


# ================================================================
# Reauth panel
# ================================================================

from talon.ui.server.screens.reauth import ReauthPanel


class TestReauthPanel:
    def test_initial_state(self):
        panel = ReauthPanel()
        assert panel._talon is None
        assert panel._dialog is None

    def test_get_pending_no_server(self):
        panel = ReauthPanel()
        assert panel._get_pending_requests(None) == []

    def test_get_pending_with_soft_locked(self):
        server = MagicMock()
        server.client_registry.clients = {
            "c1": {"status": "ONLINE", "callsign": "W1"},
            "c2": {
                "status": "SOFT_LOCKED",
                "callsign": "W2",
                "locked_at": time.time(),
                "lease_expires_at": time.time() - 3600,
            },
            "c3": {"status": "REVOKED", "callsign": "W3"},
        }
        panel = ReauthPanel()
        pending = panel._get_pending_requests(server)
        assert len(pending) == 1
        assert pending[0]["callsign"] == "W2"

    def test_get_pending_none_when_all_online(self):
        server = MagicMock()
        server.client_registry.clients = {
            "c1": {"status": "ONLINE", "callsign": "W1"},
            "c2": {"status": "ONLINE", "callsign": "W2"},
        }
        panel = ReauthPanel()
        assert panel._get_pending_requests(server) == []


# ================================================================
# Dashboard panel — helper functions
# ================================================================

from talon.ui.server.screens.dashboard import (
    STATUS_COLORS as DASH_STATUS_COLORS,
)
from talon.ui.server.screens.dashboard import (
    DashboardPanel,
)


class TestDashboardStatusColors:
    def test_online_is_green(self):
        assert DASH_STATUS_COLORS["ONLINE"] == "#00e5a0"

    def test_stale_is_amber(self):
        assert DASH_STATUS_COLORS["STALE"] == "#f5a623"

    def test_revoked_is_red(self):
        assert DASH_STATUS_COLORS["REVOKED"] == "#ff3b3b"

    def test_offline_is_grey(self):
        assert DASH_STATUS_COLORS["OFFLINE"] == "#3d4f63"


class TestDashboardPanel:
    def test_initial_state(self):
        panel = DashboardPanel()
        assert panel._talon is None
        assert panel._refresh_event is None

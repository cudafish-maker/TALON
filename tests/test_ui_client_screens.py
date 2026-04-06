# tests/test_ui_client_screens.py
# Tests for the client UI screens — login, lock, main screen logic,
# and content panel construction / navigation.
#
# Kivy is mocked via conftest.py. Tests exercise state management,
# navigation logic, property defaults, and helper methods.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import MagicMock, patch

# ================================================================
# Client App — TalonApp
# ================================================================
from talon.ui.app import TalonApp


class TestTalonAppHexToRgba:
    def test_black(self):
        assert TalonApp._hex_to_rgba("#000000") == (0.0, 0.0, 0.0, 1.0)

    def test_white(self):
        assert TalonApp._hex_to_rgba("#ffffff") == (1.0, 1.0, 1.0, 1.0)

    def test_tactical_green(self):
        r, g, b, a = TalonApp._hex_to_rgba("#00e5a0")
        assert r == 0.0
        assert abs(g - 229 / 255) < 0.001
        assert abs(b - 160 / 255) < 0.001
        assert a == 1.0

    def test_base_bg(self):
        r, g, b, a = TalonApp._hex_to_rgba("#0a0e14")
        assert r == 10 / 255
        assert abs(g - 14 / 255) < 0.001
        assert abs(b - 20 / 255) < 0.001

    def test_alpha_always_one(self):
        _, _, _, a = TalonApp._hex_to_rgba("#ff3b3b")
        assert a == 1.0


# ================================================================
# LoginScreen
# ================================================================

from talon.ui.screens.login import LoginScreen


class TestLoginScreenDefaults:
    def test_error_text_initially_empty(self):
        screen = LoginScreen(name="login")
        assert screen.error_text == ""

    def test_is_loading_initially_false(self):
        screen = LoginScreen(name="login")
        assert screen.is_loading is False


class TestLoginScreenShowError:
    def test_show_error_sets_text(self):
        screen = LoginScreen(name="login")
        screen.is_loading = True
        screen.show_error("Bad passphrase")
        assert screen.error_text == "Bad passphrase"
        assert screen.is_loading is False

    def test_clear_error(self):
        screen = LoginScreen(name="login")
        screen.error_text = "some error"
        screen.clear_error()
        assert screen.error_text == ""


class TestLoginScreenSubmit:
    def _make_ids(self, text):
        """Create a Kivy-like ids namespace with a passphrase_field."""
        ids = MagicMock()
        ids.passphrase_field.text = text
        # Also support dict access
        ids.__getitem__ = lambda self_, key: getattr(self_, key)
        ids.get = lambda key, default=None: getattr(ids, key, default)
        return ids

    def test_empty_passphrase_sets_error(self):
        screen = LoginScreen(name="login")
        screen.ids = self._make_ids("   ")
        screen.on_submit()
        assert screen.error_text == "Passphrase is required."
        assert screen.is_loading is False

    def test_valid_passphrase_clears_error_and_starts_loading(self):
        screen = LoginScreen(name="login")
        screen.ids = self._make_ids("my-passphrase")

        mock_app = MagicMock()
        with patch("kivy.app.App") as MockApp:
            MockApp.get_running_app.return_value = mock_app
            screen.on_submit()

        assert screen.error_text == ""
        assert screen.is_loading is True
        mock_app.do_login.assert_called_once_with("my-passphrase")

    def test_typing_clears_error(self):
        screen = LoginScreen(name="login")
        screen.error_text = "Bad passphrase"
        screen.on_passphrase_text(None, "a")
        assert screen.error_text == ""

    def test_typing_empty_does_not_clear(self):
        screen = LoginScreen(name="login")
        screen.error_text = "Bad passphrase"
        screen.on_passphrase_text(None, "")
        assert screen.error_text == "Bad passphrase"


class TestLoginScreenEnrollment:
    def test_check_enrolled_returns_bool(self):
        # Static method, doesn't need instance
        result = LoginScreen._check_enrolled()
        assert isinstance(result, bool)

    def test_check_enrolled_false_when_no_identity(self):
        """Without the identity file, _check_enrolled returns False."""
        with patch("os.path.isfile", return_value=False):
            assert LoginScreen._check_enrolled() is False


# ================================================================
# LockScreen
# ================================================================

from talon.ui.screens.lock import LockScreen


class TestLockScreenDefaults:
    def test_default_status_text(self):
        screen = LockScreen(name="lock")
        assert "expired" in screen.status_text.lower()

    def test_default_not_requesting(self):
        screen = LockScreen(name="lock")
        assert screen.is_requesting is False

    def test_default_not_approved(self):
        screen = LockScreen(name="lock")
        assert screen.is_approved is False


class TestLockScreenReauth:
    def test_no_connection_shows_error(self):
        screen = LockScreen(name="lock")
        mock_app = MagicMock()
        mock_app.talon.connection = None

        with patch("kivy.app.App") as MockApp:
            MockApp.get_running_app.return_value = mock_app
            screen.on_request_reauth()

        assert "cannot reach" in screen.status_text.lower() or "network" in screen.status_text.lower()
        assert screen.is_requesting is False

    def test_successful_request_sets_requesting(self):
        screen = LockScreen(name="lock")
        mock_app = MagicMock()
        mock_app.talon.connection = MagicMock()
        mock_app.talon.auth.request_reauth = MagicMock()

        with patch("kivy.app.App") as MockApp:
            MockApp.get_running_app.return_value = mock_app
            screen.on_request_reauth()

        assert screen.is_requesting is True
        assert "waiting" in screen.status_text.lower()

    def test_failed_request_shows_error(self):
        screen = LockScreen(name="lock")
        mock_app = MagicMock()
        mock_app.talon.connection = MagicMock()
        mock_app.talon.auth.request_reauth.side_effect = RuntimeError("timeout")

        with patch("kivy.app.App") as MockApp:
            MockApp.get_running_app.return_value = mock_app
            screen.on_request_reauth()

        assert "timeout" in screen.status_text.lower()
        assert screen.is_requesting is False


class TestLockScreenPolling:
    def test_poll_unlocks_when_lease_valid(self):
        screen = LockScreen(name="lock")
        mock_app = MagicMock()
        mock_app.talon.auth.check_lease.return_value = {"locked": False}

        with patch("kivy.app.App") as MockApp:
            MockApp.get_running_app.return_value = mock_app
            screen._poll_for_approval(0)

        assert screen.is_approved is True
        assert "renewed" in screen.status_text.lower()

    def test_poll_stays_locked_when_still_locked(self):
        screen = LockScreen(name="lock")
        mock_app = MagicMock()
        mock_app.talon.auth.check_lease.return_value = {"locked": True}

        with patch("kivy.app.App") as MockApp:
            MockApp.get_running_app.return_value = mock_app
            screen._poll_for_approval(0)

        assert screen.is_approved is False


# ================================================================
# MainScreen
# ================================================================

from talon.ui.screens.main import NAV_ITEMS, MainScreen


class TestMainScreenNavItems:
    def test_nav_items_has_five_entries(self):
        assert len(NAV_ITEMS) == 5

    def test_nav_items_are_tuples_of_three(self):
        for item in NAV_ITEMS:
            assert len(item) == 3

    def test_nav_items_sections(self):
        sections = [item[2] for item in NAV_ITEMS]
        assert "sitreps" in sections
        assert "missions" in sections
        assert "assets" in sections
        assert "chat" in sections
        assert "documents" in sections


class TestMainScreenDefaults:
    def test_default_section(self):
        screen = MainScreen(name="main")
        assert screen.active_section == "sitreps"

    def test_default_offline(self):
        screen = MainScreen(name="main")
        assert screen.is_online is False

    def test_default_transport(self):
        screen = MainScreen(name="main")
        assert screen.transport_name == "offline"

    def test_default_callsign_empty(self):
        screen = MainScreen(name="main")
        assert screen.operator_callsign == ""

    def test_default_flash_text_empty(self):
        screen = MainScreen(name="main")
        assert screen.flash_text == ""


class TestMainScreenConnectionCallbacks:
    def test_on_connected_sets_online(self):
        screen = MainScreen(name="main")
        screen._on_connected("yggdrasil")
        assert screen.is_online is True
        assert screen.transport_name == "yggdrasil"

    def test_on_disconnected_sets_offline(self):
        screen = MainScreen(name="main")
        screen.is_online = True
        screen.transport_name = "yggdrasil"
        screen._on_disconnected()
        assert screen.is_online is False
        assert screen.transport_name == "offline"


class TestMainScreenFlash:
    def test_flash_notification_sets_text(self):
        screen = MainScreen(name="main")
        screen._on_flash_notification("sitrep-123", "Enemy contact grid 4521")
        assert "FLASH" in screen.flash_text
        assert "Enemy contact" in screen.flash_text

    def test_dismiss_flash_clears_text(self):
        screen = MainScreen(name="main")
        screen.flash_text = "FLASH — something"
        screen._dismiss_flash(None)
        assert screen.flash_text == ""

    def test_on_flash_tapped_navigates_and_dismisses(self):
        screen = MainScreen(name="main")
        screen.flash_text = "FLASH — test"
        screen.ids = {}  # navigate_to needs ids, will no-op
        screen.on_flash_tapped()
        assert screen.active_section == "sitreps"
        assert screen.flash_text == ""


class TestMainScreenNavigation:
    def test_navigate_updates_active_section(self):
        screen = MainScreen(name="main")
        screen.ids = {}  # No content_area — widget swap is a no-op
        screen.navigate_to("chat")
        assert screen.active_section == "chat"

    def test_get_callsign_no_talon(self):
        screen = MainScreen(name="main")
        screen._talon = None
        assert screen._get_callsign() == "UNKNOWN"

    def test_get_callsign_no_cache(self):
        screen = MainScreen(name="main")
        screen._talon = MagicMock()
        screen._talon.cache = None
        assert screen._get_callsign() == "UNKNOWN"

    def test_get_callsign_from_cache(self):
        screen = MainScreen(name="main")
        screen._talon = MagicMock()
        screen._talon.cache.get_my_callsign.return_value = "WOLF-1"
        assert screen._get_callsign() == "WOLF-1"


class TestMainScreenSectionWidgets:
    def test_get_section_widget_returns_none_for_unknown(self):
        screen = MainScreen(name="main")
        result = screen._get_section_widget("nonexistent")
        assert result is None

    def test_get_section_widget_sitreps(self):
        screen = MainScreen(name="main")
        widget = screen._get_section_widget("sitreps")
        assert widget is not None

    def test_get_section_widget_missions(self):
        screen = MainScreen(name="main")
        widget = screen._get_section_widget("missions")
        assert widget is not None

    def test_get_section_widget_assets(self):
        screen = MainScreen(name="main")
        widget = screen._get_section_widget("assets")
        assert widget is not None

    def test_get_section_widget_chat(self):
        screen = MainScreen(name="main")
        widget = screen._get_section_widget("chat")
        assert widget is not None

    def test_get_section_widget_documents(self):
        screen = MainScreen(name="main")
        widget = screen._get_section_widget("documents")
        assert widget is not None


# ================================================================
# SITREP panel — importance color map
# ================================================================

from talon.ui.screens.sitreps import SITREPPanel


class TestSITREPPanel:
    def test_initial_state(self):
        panel = SITREPPanel()
        assert panel._talon is None
        assert panel._sitreps == []
        assert panel._active_sitrep is None

    def test_refresh_no_talon(self):
        panel = SITREPPanel()
        panel.refresh(None)
        assert panel._sitreps == []

    def test_refresh_no_cache(self):
        mock_talon = MagicMock()
        mock_talon.cache = None
        panel = SITREPPanel()
        panel.refresh(mock_talon)
        assert panel._sitreps == []


# ================================================================
# Assets panel — verification color map
# ================================================================

from talon.ui.screens.assets import VERIFY_COLORS, AssetsPanel


class TestVerifyColors:
    def test_verified_is_green(self):
        assert VERIFY_COLORS["verified"] == "#00e5a0"

    def test_unverified_is_amber(self):
        assert VERIFY_COLORS["unverified"] == "#f5a623"

    def test_compromised_is_red(self):
        assert VERIFY_COLORS["compromised"] == "#ff3b3b"


class TestAssetsPanel:
    def test_initial_state(self):
        panel = AssetsPanel()
        assert panel._talon is None
        assert panel._assets == []

    def test_get_my_callsign_no_talon(self):
        panel = AssetsPanel()
        panel._talon = None
        assert panel._get_my_callsign() == ""

    def test_get_my_callsign_with_cache(self):
        panel = AssetsPanel()
        panel._talon = MagicMock()
        panel._talon.cache.get_my_callsign.return_value = "EAGLE-2"
        assert panel._get_my_callsign() == "EAGLE-2"


# ================================================================
# Missions panel — status color maps
# ================================================================

from talon.ui.screens.missions import OBJ_STATUS_COLORS, STATUS_COLORS, MissionsPanel


class TestMissionStatusColors:
    def test_active_is_green(self):
        assert STATUS_COLORS["ACTIVE"] == "#00e5a0"

    def test_aborted_is_red(self):
        assert STATUS_COLORS["ABORTED"] == "#ff3b3b"

    def test_obj_complete_is_green(self):
        assert OBJ_STATUS_COLORS["COMPLETE"] == "#00e5a0"

    def test_obj_in_progress_is_amber(self):
        assert OBJ_STATUS_COLORS["IN_PROGRESS"] == "#f5a623"

    def test_obj_cancelled_is_red(self):
        assert OBJ_STATUS_COLORS["CANCELLED"] == "#ff3b3b"


class TestMissionsPanel:
    def test_initial_state(self):
        panel = MissionsPanel()
        assert panel._talon is None
        assert panel._missions == []


# ================================================================
# Chat panel
# ================================================================

from talon.ui.screens.chat import ChatPanel


class TestChatPanel:
    def test_initial_state(self):
        panel = ChatPanel()
        assert panel._talon is None
        assert panel._channels == []
        assert panel._active_channel is None

    def test_refresh_no_talon(self):
        panel = ChatPanel()
        panel.refresh(None)
        assert panel._channels == []

    def test_get_my_callsign_no_talon(self):
        panel = ChatPanel()
        panel._talon = None
        assert panel._get_my_callsign() == ""


# ================================================================
# Documents panel — access color map
# ================================================================

from talon.ui.screens.documents import ACCESS_COLORS, DocumentsPanel


class TestAccessColors:
    def test_all_is_green(self):
        assert ACCESS_COLORS["ALL"] == "#00e5a0"

    def test_restricted_is_amber(self):
        assert ACCESS_COLORS["RESTRICTED"] == "#f5a623"


class TestDocumentsPanel:
    def test_initial_state(self):
        panel = DocumentsPanel()
        assert panel._talon is None
        assert panel._documents == []

    def test_get_my_callsign_no_talon(self):
        panel = DocumentsPanel()
        panel._talon = None
        assert panel._get_my_callsign() == ""

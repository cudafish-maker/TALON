# talon/ui/screens/main.py
# Main application screen — shown after login.
#
# Layout adapts based on window width:
#
#   Desktop / laptop (width >= 900dp):
#   ┌──────┬─────────────────────────┬────────────────┐
#   │ Nav  │                         │                │
#   │ rail │       MAP (always       │  Context panel │
#   │      │        visible)         │  (active screen│
#   │[SIT] │                         │   content)     │
#   │[MSN] │                         │                │
#   │[AST] │                         │                │
#   │[CHT] │                         │                │
#   │[DOC] │                         │                │
#   └──────┴─────────────────────────┴────────────────┘
#   Status bar (transport, connection, operator callsign)
#
#   Android landscape (width < 900dp):
#   ┌─────────────────────────────────┐
#   │        MAP (top half)           │
#   ├─────────────────────────────────┤
#   │   Active screen (bottom half)   │
#   └─────────────────────────────────┘
#   [SIT][MSN][AST][CHT][DOC]  ← bottom nav bar
#
# The map is ALWAYS visible. It never collapses.

from kivy.properties import BooleanProperty, StringProperty
from kivymd.uix.screen import MDScreen

# Navigation items — (icon, label, screen_name)
NAV_ITEMS = [
    ("file-alert-outline", "SITREPs", "sitreps"),
    ("flag-outline", "Missions", "missions"),
    ("package-variant", "Assets", "assets"),
    ("forum-outline", "Chat", "chat"),
    ("file-document-outline", "Documents", "documents"),
]


class MainScreen(MDScreen):
    """Main operator screen with persistent map and content panels.

    Properties:
        active_section:   Which nav item is currently selected.
        is_online:        Whether the client has a server connection.
        transport_name:   Active transport (yggdrasil/rnode/offline).
        operator_callsign: The logged-in operator's callsign.
        flash_text:       If non-empty, shows the FLASH alert banner.
    """

    active_section = StringProperty("sitreps")
    is_online = BooleanProperty(False)
    transport_name = StringProperty("offline")
    operator_callsign = StringProperty("")
    flash_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._talon = None  # TalonClient reference, set after login
        self._is_mobile = False  # Current layout mode

    # ------------------------------------------------------------------
    # Called by TalonApp after login succeeds
    # ------------------------------------------------------------------

    def on_client_ready(self, talon_client):
        """Wire the main screen to the running TalonClient.

        Args:
            talon_client: The started TalonClient instance.
        """
        self._talon = talon_client

        # Pull initial state
        self.is_online = talon_client.is_online
        self.operator_callsign = self._get_callsign()

        # Wire up connection status callback
        talon_client.connection.on_connected = self._on_connected
        talon_client.connection.on_disconnected = self._on_disconnected

        # Wire notification handler to show FLASH banners
        talon_client.notifications.on_flash = self._on_flash_notification

        # Navigate to SITREPs by default
        self.navigate_to("sitreps")

    def on_layout_changed(self, is_mobile: bool):
        """Called by TalonApp when the window crosses the layout breakpoint.

        Args:
            is_mobile: True if the window is now narrow (mobile layout).
        """
        self._is_mobile = is_mobile
        # The KV layout responds to is_mobile_layout on the app object,
        # so we just need to trigger a layout recalculation.
        self.do_layout()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def navigate_to(self, section: str):
        """Switch the context panel to a different section.

        Args:
            section: One of 'sitreps', 'missions', 'assets', 'chat', 'documents'.
        """
        self.active_section = section

        # Load the target section widget into the context panel
        content_area = self.ids.get("content_area")
        if not content_area:
            return

        widget = self._get_section_widget(section)
        if widget is None:
            return

        content_area.clear_widgets()
        content_area.add_widget(widget)

        # Refresh the section with current data
        if hasattr(widget, "refresh"):
            widget.refresh(self._talon)

    def _get_section_widget(self, section: str):
        """Return the widget for a given section name.

        Widgets are imported lazily so Kivy has finished loading KV
        files before we try to instantiate screens.
        """
        try:
            if section == "sitreps":
                from talon.ui.screens.sitreps import SITREPPanel

                return SITREPPanel()
            elif section == "missions":
                from talon.ui.screens.missions import MissionsPanel

                return MissionsPanel()
            elif section == "assets":
                from talon.ui.screens.assets import AssetsPanel

                return AssetsPanel()
            elif section == "chat":
                from talon.ui.screens.chat import ChatPanel

                return ChatPanel()
            elif section == "documents":
                from talon.ui.screens.documents import DocumentsPanel

                return DocumentsPanel()
        except ImportError:
            return None

    # ------------------------------------------------------------------
    # Connection callbacks (wired in on_client_ready)
    # ------------------------------------------------------------------

    def _on_connected(self, transport_name: str):
        """Called when the client connects to the server."""
        self.is_online = True
        self.transport_name = transport_name

    def _on_disconnected(self):
        """Called when the client loses the server connection."""
        self.is_online = False
        self.transport_name = "offline"

    # ------------------------------------------------------------------
    # FLASH notification banner
    # ------------------------------------------------------------------

    def _on_flash_notification(self, sitrep_id: str, content: str):
        """Show the FLASH alert banner at the top of the screen.

        The banner auto-dismisses after 10 seconds, but the operator
        can also tap it to navigate to the SITREP.

        Args:
            sitrep_id: ID of the triggering SITREP.
            content:   Brief summary text.
        """
        self.flash_text = f"FLASH — {content}"
        self._flash_sitrep_id = sitrep_id

        from kivy.clock import Clock

        Clock.schedule_once(self._dismiss_flash, 10)

    def on_flash_tapped(self):
        """Operator tapped the FLASH banner — navigate to SITREPs."""
        self.navigate_to("sitreps")
        self._dismiss_flash(None)

    def _dismiss_flash(self, dt):
        self.flash_text = ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_callsign(self) -> str:
        """Read the operator callsign from the client cache."""
        if not self._talon or not self._talon.cache:
            return "UNKNOWN"
        try:
            return self._talon.cache.get_my_callsign() or "UNKNOWN"
        except Exception:
            return "UNKNOWN"

    def on_nav_item_selected(self, section: str):
        """Called by KV when a nav rail or bottom nav item is pressed."""
        self.navigate_to(section)

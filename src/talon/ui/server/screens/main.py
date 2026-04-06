# talon/ui/server/screens/main.py
# Server main screen — the "chair" operator's full command view.
#
# Layout (always desktop — server runs on a laptop/desktop, not Android):
#
#   ┌──────┬─────────────────────────┬────────────────────┐
#   │ Nav  │                         │                    │
#   │ rail │    MAP (all operators,  │  Active panel      │
#   │      │    assets, zones)       │  (dashboard /      │
#   │[DSH] │                         │   registry /       │
#   │[REG] │                         │   reauth /         │
#   │[AUD] │                         │   audit /          │
#   │[ENR] │                         │   enrollment)      │
#   │      │                         │                    │
#   └──────┴─────────────────────────┴────────────────────┘
#   Status bar  (clients online, transport, uptime)
#
# The server operator is "Server" — they can see everything including
# DM channels (they route the messages but content is E2E encrypted).
#
# Key server-only actions:
#   - Approve / deny re-auth requests
#   - Revoke a client (hard shred trigger)
#   - Generate enrollment tokens
#   - View full audit log with filters

from kivy.clock import Clock
from kivy.properties import NumericProperty, StringProperty
from kivymd.uix.screen import MDScreen

# Nav items for the server rail
SERVER_NAV = [
    ("view-dashboard-outline", "DASH", "dashboard"),
    ("account-group-outline", "CLIENTS", "registry"),
    ("shield-account-outline", "REAUTH", "reauth"),
    ("text-box-outline", "AUDIT", "audit"),
    ("account-plus-outline", "ENROLL", "enrollment"),
]


class ServerMainScreen(MDScreen):
    """Main server operator screen.

    Properties:
        active_section:     Currently selected nav item.
        online_count:       Number of currently online clients.
        pending_reauth:     Number of pending re-auth requests.
        transport_name:     Active transport.
        uptime_text:        Server uptime string (updated every minute).
    """

    active_section = StringProperty("dashboard")
    online_count = NumericProperty(0)
    pending_reauth = NumericProperty(0)
    transport_name = StringProperty("offline")
    uptime_text = StringProperty("--:--")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._talon = None
        self._start_time = None
        self._uptime_event = None

    # ------------------------------------------------------------------
    # Called by TalonServerApp after server starts
    # ------------------------------------------------------------------

    def on_server_ready(self, talon_server):
        """Wire the screen to the running TalonServer.

        Args:
            talon_server: The started TalonServer instance.
        """
        import time

        self._talon = talon_server
        self._start_time = time.time()

        # Start uptime counter
        self._uptime_event = Clock.schedule_interval(self._update_uptime, 60)
        self._update_uptime(0)

        # Wire heartbeat monitor status changes to update online count
        talon_server.heartbeat_monitor.status_change_callback = self._on_client_status_change

        # Start on dashboard
        self.navigate_to("dashboard")
        self._refresh_counts()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def navigate_to(self, section: str):
        """Switch the right panel to the given section.

        Args:
            section: One of 'dashboard', 'registry', 'reauth', 'audit', 'enrollment'.
        """
        self.active_section = section

        content_area = self.ids.get("server_content")
        if not content_area:
            return

        widget = self._get_section_widget(section)
        if widget is None:
            return

        content_area.clear_widgets()
        content_area.add_widget(widget)

        if hasattr(widget, "refresh"):
            widget.refresh(self._talon)

    def _get_section_widget(self, section: str):
        try:
            if section == "dashboard":
                from talon.ui.server.screens.dashboard import DashboardPanel

                return DashboardPanel()
            elif section == "registry":
                from talon.ui.server.screens.registry import RegistryPanel

                return RegistryPanel()
            elif section == "reauth":
                from talon.ui.server.screens.reauth import ReauthPanel

                return ReauthPanel()
            elif section == "audit":
                from talon.ui.server.screens.audit_screen import AuditPanel

                return AuditPanel()
            elif section == "enrollment":
                from talon.ui.server.screens.enrollment import EnrollmentPanel

                return EnrollmentPanel()
        except ImportError:
            return None

    def on_nav_item_selected(self, section: str):
        """Called by KV when a nav item is pressed."""
        self.navigate_to(section)

    # ------------------------------------------------------------------
    # Live status updates
    # ------------------------------------------------------------------

    def _refresh_counts(self):
        """Update online client count and pending re-auth count."""
        if not self._talon:
            return
        online = self._talon.client_registry.get_online_clients()
        self.online_count = len(online)

        # Count pending re-auths from soft-locked clients
        self.pending_reauth = sum(
            1 for c in self._talon.client_registry.clients.values() if c.get("status") == "SOFT_LOCKED"
        )

    def _on_client_status_change(self, callsign: str, status: str):
        """Called when a client's heartbeat status changes."""
        self._refresh_counts()
        # If on dashboard or registry, refresh the panel
        if self.active_section in ("dashboard", "registry"):
            self.navigate_to(self.active_section)

    def _update_uptime(self, dt):
        """Update the uptime display."""
        import time

        if not self._start_time:
            return
        elapsed = int(time.time() - self._start_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes = remainder // 60
        self.uptime_text = f"{hours:02d}:{minutes:02d}"

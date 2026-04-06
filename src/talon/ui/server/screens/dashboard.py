# talon/ui/server/screens/dashboard.py
# Server dashboard — the first thing the server operator sees after login.
#
# Layout:
#   ┌─────────────────────────────────┐
#   │  DASHBOARD                      │
#   ├──────────────┬──────────────────┤
#   │  4 ONLINE    │  2 STALE         │
#   │  clients     │  clients         │
#   ├──────────────┴──────────────────┤
#   │  ONLINE NOW                     │
#   │  ● WOLF-1   yggdrasil  14:32    │
#   │  ● WOLF-2   rnode      14:28    │
#   ├─────────────────────────────────┤
#   │  RECENT ACTIVITY                │
#   │  14:33  WOLF-1  SITREP_CREATED  │
#   │  14:31  WOLF-2  ASSET_UPDATED   │
#   └─────────────────────────────────┘
#
# Auto-refreshes every 30 seconds.

import time

from kivy.clock import Clock
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.scrollview import MDScrollView

STATUS_COLORS = {
    "ONLINE": "#00e5a0",
    "STALE": "#f5a623",
    "REVOKED": "#ff3b3b",
    "OFFLINE": "#3d4f63",
}


class DashboardPanel(MDBoxLayout):
    """Server dashboard — overview of all clients and recent activity."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._talon = None
        self._refresh_event = None

    def refresh(self, talon_server):
        self._talon = talon_server
        self.clear_widgets()
        self._build(talon_server)

        # Auto-refresh every 30s
        if self._refresh_event:
            self._refresh_event.cancel()
        self._refresh_event = Clock.schedule_interval(lambda dt: self.refresh(self._talon), 30)

    def on_leave(self):
        if self._refresh_event:
            self._refresh_event.cancel()

    def _build(self, server):
        from kivymd.uix.divider import MDDivider

        # Header
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="52dp",
            padding=["16dp", "8dp"],
            md_bg_color="#0f1520",
        )
        header.add_widget(
            MDLabel(
                text="DASHBOARD",
                font_style="Button",
                bold=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )
        self.add_widget(header)
        self.add_widget(MDDivider(color="#1e2d3d"))

        # --- Stats row ---
        clients = server.client_registry.clients if server else {}
        online = [c for c in clients.values() if c.get("status") == "ONLINE"]
        stale = [c for c in clients.values() if c.get("status") == "STALE"]
        revoked = [c for c in clients.values() if c.get("status") == "REVOKED"]

        stats_row = MDBoxLayout(
            size_hint_y=None,
            height="72dp",
            padding=["8dp", "8dp"],
            spacing="8dp",
        )

        for count, label, color in [
            (len(online), "ONLINE", "#00e5a0"),
            (len(stale), "STALE", "#f5a623"),
            (len(revoked), "REVOKED", "#ff3b3b"),
        ]:
            card = MDBoxLayout(
                orientation="vertical",
                size_hint_x=1,
                padding=["8dp", "4dp"],
                md_bg_color="#151d2b",
            )
            card.add_widget(
                MDLabel(
                    text=str(count),
                    font_style="H5",
                    bold=True,
                    halign="center",
                    theme_text_color="Custom",
                    text_color=color,
                )
            )
            card.add_widget(
                MDLabel(
                    text=label,
                    font_style="Caption",
                    halign="center",
                    theme_text_color="Custom",
                    text_color="#8a9bb0",
                )
            )
            stats_row.add_widget(card)

        self.add_widget(stats_row)
        self.add_widget(MDDivider(color="#1e2d3d"))

        # Scrollable lower section
        scroll = MDScrollView(size_hint_y=1)
        content = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=["0dp", "0dp"],
            spacing="0dp",
        )
        content.bind(minimum_height=content.setter("height"))

        # --- Online clients ---
        content.add_widget(_section_header("ONLINE NOW"))

        online_clients = server.client_registry.get_online_clients() if server else []
        if online_clients:
            for client in online_clients:
                content.add_widget(_client_row(client))
        else:
            content.add_widget(_empty_label("No clients online."))

        content.add_widget(MDDivider(color="#1e2d3d"))

        # --- Recent audit events ---
        content.add_widget(_section_header("RECENT ACTIVITY"))

        recent = []
        if server and server.db:
            try:
                cursor = server.db.execute(
                    "SELECT event_type, client_callsign, timestamp, details "
                    "FROM audit_log ORDER BY timestamp DESC LIMIT 20"
                )
                recent = cursor.fetchall()
            except Exception:
                pass

        if recent:
            for row in recent:
                event_type, callsign, ts, details = row
                ts_str = time.strftime("%H:%M", time.localtime(ts)) if ts else "--:--"
                content.add_widget(_audit_row(ts_str, callsign or "SYSTEM", event_type))
        else:
            content.add_widget(_empty_label("No recent activity."))

        scroll.add_widget(content)
        self.add_widget(scroll)


# --- Shared helper widget constructors ---


def _section_header(text: str) -> MDBoxLayout:
    box = MDBoxLayout(
        size_hint_y=None,
        height="32dp",
        padding=["16dp", "8dp"],
        md_bg_color="#0f1520",
    )
    box.add_widget(
        MDLabel(
            text=text,
            font_style="Overline",
            theme_text_color="Custom",
            text_color="#8a9bb0",
        )
    )
    return box


def _client_row(client: dict) -> MDBoxLayout:
    """One row in the client list — callsign, transport, last-seen."""
    status = client.get("status", "OFFLINE")
    color = STATUS_COLORS.get(status, "#3d4f63")
    transport = client.get("transport", "—")
    callsign = client.get("callsign", "?")

    last_sync = client.get("last_sync")
    if last_sync:
        ts_str = time.strftime("%H:%M", time.localtime(last_sync))
    else:
        ts_str = "—"

    row = MDBoxLayout(
        size_hint_y=None,
        height="40dp",
        padding=["16dp", "4dp"],
        spacing="8dp",
        md_bg_color="#151d2b",
    )

    row.add_widget(
        MDLabel(
            text=f"[color={color}]●[/color]",
            markup=True,
            size_hint_x=None,
            width="16dp",
            theme_text_color="Custom",
            text_color=color,
            font_size="10sp",
        )
    )
    row.add_widget(
        MDLabel(
            text=callsign,
            font_style="Body2",
            bold=True,
            theme_text_color="Custom",
            text_color="#e8edf4",
        )
    )
    row.add_widget(
        MDLabel(
            text=transport.upper(),
            font_style="Caption",
            theme_text_color="Custom",
            text_color="#8a9bb0",
            size_hint_x=None,
            width="80dp",
            halign="center",
        )
    )
    row.add_widget(
        MDLabel(
            text=ts_str,
            font_style="Caption",
            theme_text_color="Custom",
            text_color="#3d4f63",
            size_hint_x=None,
            width="48dp",
            halign="right",
        )
    )
    return row


def _audit_row(ts: str, callsign: str, event_type: str) -> MDBoxLayout:
    """One row in the recent activity list."""
    row = MDBoxLayout(
        size_hint_y=None,
        height="32dp",
        padding=["16dp", "4dp"],
        spacing="12dp",
        md_bg_color="#0f1520",
    )
    row.add_widget(
        MDLabel(
            text=ts,
            font_style="Caption",
            theme_text_color="Custom",
            text_color="#3d4f63",
            size_hint_x=None,
            width="40dp",
        )
    )
    row.add_widget(
        MDLabel(
            text=callsign,
            font_style="Caption",
            bold=True,
            theme_text_color="Custom",
            text_color="#8a9bb0",
            size_hint_x=None,
            width="80dp",
        )
    )
    row.add_widget(
        MDLabel(
            text=event_type,
            font_style="Caption",
            theme_text_color="Custom",
            text_color="#e8edf4",
        )
    )
    return row


def _empty_label(text: str) -> MDLabel:
    return MDLabel(
        text=text,
        halign="center",
        font_style="Caption",
        theme_text_color="Custom",
        text_color="#3d4f63",
        size_hint_y=None,
        height="32dp",
        padding=["16dp", "4dp"],
    )

# talon/ui/server/screens/audit_screen.py
# Audit log panel — full scrollable event history with filters.
#
# Layout:
#   ┌─────────────────────────────────────────────┐
#   │  AUDIT LOG          [ALL ▼] [SEARCH...]     │
#   ├──────────┬──────────┬────────────────────── ┤
#   │  TIME    │  CLIENT  │  EVENT                │
#   ├──────────┼──────────┼───────────────────────┤
#   │  14:33   │  WOLF-1  │  SITREP_CREATED       │
#   │  14:31   │  WOLF-2  │  ASSET_UPDATED        │
#   │  14:28   │  SYSTEM  │  CLIENT_ENROLLED      │
#   └──────────┴──────────┴───────────────────────┘
#
# Filter by event type category:
#   ALL / AUTH / SITREP / ASSET / MISSION / CHAT / SYSTEM
#
# The audit log is append-only and stored only on the server.
# Clients never see the raw audit log.

import time

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField


# Map filter names to SQL LIKE patterns
FILTER_PATTERNS = {
    "ALL":     "%",
    "AUTH":    "%ENROLL%|%REVOKE%|%REAUTH%|%LOGIN%",
    "SITREP":  "SITREP%",
    "ASSET":   "ASSET%",
    "MISSION": "MISSION%|OBJECTIVE%",
    "CHAT":    "MESSAGE%|CHANNEL%",
    "SYSTEM":  "SERVER%|CLIENT_STALE%|CLIENT_ENROLLED%",
}

# Color per event category
EVENT_COLORS = {
    "SITREP_CREATED":    "#4a9eff",
    "SITREP_DELETED":    "#ff3b3b",
    "ASSET_CREATED":     "#00e5a0",
    "ASSET_UPDATED":     "#00e5a0",
    "ASSET_VERIFIED":    "#00e5a0",
    "CLIENT_ENROLLED":   "#00e5a0",
    "CLIENT_REVOKED":    "#ff3b3b",
    "CLIENT_STALE":      "#f5a623",
    "REAUTH_APPROVED":   "#00e5a0",
    "REAUTH_DENIED":     "#ff3b3b",
    "SERVER_STARTED":    "#4a9eff",
    "SERVER_STOPPED":    "#f5a623",
}

FILTER_OPTIONS = ["ALL", "AUTH", "SITREP", "ASSET", "MISSION", "CHAT", "SYSTEM"]


class AuditPanel(MDBoxLayout):
    """Full audit log with filtering."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._talon = None
        self._active_filter = "ALL"
        self._search_text = ""

    def refresh(self, talon_server):
        self._talon = talon_server
        self.clear_widgets()
        self._build(talon_server)

    def _build(self, server):
        from kivymd.uix.divider import MDDivider

        # Header row with filter buttons
        header = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height="88dp",
            md_bg_color="#0f1520",
        )

        title_row = MDBoxLayout(
            size_hint_y=None,
            height="44dp",
            padding=["16dp", "8dp"],
        )
        title_row.add_widget(MDLabel(
            text="AUDIT LOG",
            font_style="Button",
            bold=True,
            theme_text_color="Custom",
            text_color="#e8edf4",
        ))
        header.add_widget(title_row)

        # Filter buttons row
        filter_row = MDBoxLayout(
            size_hint_y=None,
            height="36dp",
            padding=["8dp", "4dp"],
            spacing="4dp",
        )
        for f in FILTER_OPTIONS:
            is_active = (f == self._active_filter)
            btn = MDFlatButton(
                text=f,
                theme_text_color="Custom",
                text_color="#00e5a0" if is_active else "#8a9bb0",
                font_size="10sp",
                size_hint_x=None,
                on_release=lambda x, filt=f: self._set_filter(filt),
            )
            if is_active:
                from kivy.graphics import Color, Rectangle
                with btn.canvas.before:
                    Color(0.11, 0.18, 0.23, 1)
                    Rectangle(pos=btn.pos, size=btn.size)
            filter_row.add_widget(btn)
        header.add_widget(filter_row)
        self.add_widget(header)
        self.add_widget(MDDivider(color="#1e2d3d"))

        # Column headers
        col_hdr = MDBoxLayout(
            size_hint_y=None,
            height="24dp",
            padding=["12dp", "4dp"],
            spacing="8dp",
            md_bg_color="#0a0e14",
        )
        col_hdr.add_widget(MDLabel(
            text="TIME",
            font_style="Overline",
            theme_text_color="Custom",
            text_color="#3d4f63",
            size_hint_x=None,
            width="44dp",
        ))
        col_hdr.add_widget(MDLabel(
            text="CLIENT",
            font_style="Overline",
            theme_text_color="Custom",
            text_color="#3d4f63",
            size_hint_x=None,
            width="80dp",
        ))
        col_hdr.add_widget(MDLabel(
            text="EVENT",
            font_style="Overline",
            theme_text_color="Custom",
            text_color="#3d4f63",
        ))
        self.add_widget(col_hdr)
        self.add_widget(MDDivider(color="#1e2d3d"))

        # Event rows
        scroll = MDScrollView(size_hint_y=1)
        rows = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing="1dp",
        )
        rows.bind(minimum_height=rows.setter("height"))

        events = self._load_events(server)

        if not events:
            rows.add_widget(MDLabel(
                text="No audit events recorded yet.",
                halign="center",
                font_style="Caption",
                theme_text_color="Custom",
                text_color="#3d4f63",
                size_hint_y=None,
                height="48dp",
                padding=["16dp", "8dp"],
            ))
        else:
            for event in events:
                rows.add_widget(self._event_row(event))

        scroll.add_widget(rows)
        self.add_widget(scroll)

    def _load_events(self, server, limit: int = 200) -> list:
        """Query audit_log from the server database.

        Returns a list of (timestamp, client_callsign, event_type, details) tuples.
        """
        if not server or not server.db:
            return []

        try:
            # Build filter condition
            if self._active_filter == "ALL":
                condition = "1=1"
                params = []
            else:
                # Map filter to event type prefix
                prefix_map = {
                    "AUTH":    ("ENROLL", "REVOKE", "REAUTH", "LOGIN"),
                    "SITREP":  ("SITREP",),
                    "ASSET":   ("ASSET",),
                    "MISSION": ("MISSION", "OBJECTIVE"),
                    "CHAT":    ("MESSAGE", "CHANNEL"),
                    "SYSTEM":  ("SERVER", "CLIENT"),
                }
                prefixes = prefix_map.get(self._active_filter, ())
                if prefixes:
                    placeholders = " OR ".join(
                        "event_type LIKE ?" for _ in prefixes
                    )
                    condition = f"({placeholders})"
                    params = [f"{p}%" for p in prefixes]
                else:
                    condition = "1=1"
                    params = []

            cursor = server.db.execute(
                f"SELECT timestamp, client_callsign, event_type, details "
                f"FROM audit_log WHERE {condition} "
                f"ORDER BY timestamp DESC LIMIT {limit}",
                params,
            )
            return cursor.fetchall()
        except Exception:
            return []

    def _event_row(self, event: tuple) -> MDBoxLayout:
        ts, callsign, event_type, details = event

        ts_str   = time.strftime("%H:%M", time.localtime(ts)) if ts else "--:--"
        color    = EVENT_COLORS.get(event_type, "#8a9bb0")
        callsign = callsign or "SYSTEM"

        row = MDBoxLayout(
            size_hint_y=None,
            height="28dp",
            padding=["12dp", "2dp"],
            spacing="8dp",
            md_bg_color="#0f1520",
        )
        row.add_widget(MDLabel(
            text=ts_str,
            font_style="Caption",
            theme_text_color="Custom",
            text_color="#3d4f63",
            size_hint_x=None,
            width="44dp",
        ))
        row.add_widget(MDLabel(
            text=callsign,
            font_style="Caption",
            bold=True,
            theme_text_color="Custom",
            text_color="#8a9bb0",
            size_hint_x=None,
            width="80dp",
        ))
        row.add_widget(MDLabel(
            text=event_type,
            font_style="Caption",
            theme_text_color="Custom",
            text_color=color,
        ))
        return row

    def _set_filter(self, filter_name: str):
        self._active_filter = filter_name
        self.refresh(self._talon)

# talon/ui/widgets/status_bar.py
# Status bar widget — persistent indicator at the bottom of the main screen.
#
# Shows:
#   ● (green/amber/red dot)  transport name    callsign    sync state
#
# Examples:
#   ● YGGDRASIL    WOLF-1    SYNCED
#   ● RNODE        WOLF-1    PENDING (2)
#   ● OFFLINE      WOLF-1    CACHED
#
# The dot colour indicates connection quality:
#   green  → broadband (yggdrasil / i2p / tcp)
#   amber  → LoRa only (rnode)
#   red    → offline
#
# This widget is embedded in the main.kv layout at the bottom of
# the nav rail on desktop, and at the bottom of the screen on mobile.

from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel

from talon.ui.theme import TRANSPORT_COLORS


class StatusBar(MDBoxLayout):
    """Persistent connection and sync status indicator.

    Properties (bind these to MainScreen properties):
        transport:       Active transport name (e.g. 'yggdrasil', 'rnode', 'offline').
        callsign:        Logged-in operator callsign.
        is_online:       Whether a server connection is active.
        pending_count:   Number of outbox items waiting to sync.
    """

    transport = StringProperty("offline")
    callsign = StringProperty("")
    is_online = BooleanProperty(False)
    pending_count = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height="28dp",
            padding=["12dp", "4dp"],
            spacing="12dp",
            md_bg_color="#0f1520",
            **kwargs,
        )
        self._dot = None
        self._transport_label = None
        self._callsign_label = None
        self._sync_label = None
        self._build()
        self.bind(
            transport=self._update,
            callsign=self._update,
            is_online=self._update,
            pending_count=self._update,
        )

    def _build(self):
        # Status dot
        self._dot = MDLabel(
            text="●",
            font_size="10sp",
            size_hint_x=None,
            width="16dp",
            theme_text_color="Custom",
            text_color=self._dot_color(),
        )
        self.add_widget(self._dot)

        # Transport name
        self._transport_label = MDLabel(
            text=self.transport.upper(),
            font_style="Body",
            role="small",
            bold=True,
            size_hint_x=None,
            width="96dp",
            theme_text_color="Custom",
            text_color=self._dot_color(),
        )
        self.add_widget(self._transport_label)

        # Spacer
        from kivy.uix.widget import Widget

        self.add_widget(Widget())

        # Callsign
        self._callsign_label = MDLabel(
            text=self.callsign,
            font_style="Body",
            role="small",
            bold=True,
            size_hint_x=None,
            width="96dp",
            halign="center",
            theme_text_color="Custom",
            text_color="#e8edf4",
        )
        self.add_widget(self._callsign_label)

        # Spacer
        self.add_widget(Widget())

        # Sync state
        self._sync_label = MDLabel(
            text=self._sync_text(),
            font_style="Body",
            role="small",
            size_hint_x=None,
            width="96dp",
            halign="right",
            theme_text_color="Custom",
            text_color=self._sync_color(),
        )
        self.add_widget(self._sync_label)

    def _update(self, *args):
        """Refresh all displayed values."""
        dot_color = self._dot_color()
        if self._dot:
            self._dot.text_color = dot_color
        if self._transport_label:
            self._transport_label.text = self.transport.upper()
            self._transport_label.text_color = dot_color
        if self._callsign_label:
            self._callsign_label.text = self.callsign
        if self._sync_label:
            self._sync_label.text = self._sync_text()
            self._sync_label.text_color = self._sync_color()

    def _dot_color(self) -> str:
        """Return the indicator colour for the current transport."""
        return TRANSPORT_COLORS.get(
            self.transport.lower(),
            "#ff3b3b",  # Default to red (offline)
        )

    def _sync_text(self) -> str:
        if not self.is_online:
            return "CACHED"
        if self.pending_count > 0:
            return f"PENDING ({self.pending_count})"
        return "SYNCED"

    def _sync_color(self) -> str:
        if not self.is_online:
            return "#8a9bb0"
        if self.pending_count > 0:
            return "#f5a623"
        return "#00e5a0"

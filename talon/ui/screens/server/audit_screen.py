"""
Audit log screen (server only) — encrypted audit log viewer.

Entries are decrypted on the fly using the server's db_key.
Supports filtering by event type (exact match against the event column).
Entries are read-only; deletion is not permitted from the UI.
"""
import datetime

from kivy.app import App
from kivy.metrics import dp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

from talon.ui.theme import COLOR_ACCENT, COLOR_DANGER, COLOR_PRIMARY, COLOR_TEXT_SECONDARY
from talon.utils.logging import get_logger

_log = get_logger("ui.server.audit")


def _fmt_payload(payload: dict) -> str:
    """
    Format a payload dict as compact 'key=value' pairs for display.
    Truncates at 120 chars so it fits in the row.
    """
    if not payload:
        return ""
    parts = [f"{k}={v}" for k, v in payload.items()]
    text = "  ".join(parts)
    if len(text) > 120:
        text = text[:117] + "\u2026"
    return text


def _event_color(event: str) -> tuple:
    """
    Return an RGBA color for an event name based on its semantic weight.
      Red    — revocation, hard shred, key burn
      Amber  — lock, expiry, rotation (caution)
      Green  — enrollment, renewal, approval (positive)
      Grey   — everything else (neutral)
    """
    ev = event.lower()
    if any(k in ev for k in ("revok", "shred", "burn", "delet")):
        return COLOR_DANGER
    if any(k in ev for k in ("lock", "expir", "rotat", "abort")):
        return COLOR_ACCENT
    if any(k in ev for k in ("enroll", "renew", "approv", "creat", "complet")):
        return COLOR_PRIMARY
    return COLOR_TEXT_SECONDARY


class AuditScreen(MDScreen):
    """Encrypted audit log viewer."""

    def on_pre_enter(self) -> None:
        self._load(event_filter=None)

    def on_refresh_pressed(self) -> None:
        self.ids.filter_field.text = ""
        self._load(event_filter=None)

    def on_back_pressed(self) -> None:
        self.manager.current = "main"

    def on_search_pressed(self) -> None:
        ef = self.ids.filter_field.text.strip() or None
        self._load(event_filter=ef)

    # ------------------------------------------------------------------

    def _load(self, event_filter: str | None) -> None:
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            entries = app.core_session.read_model(
                "audit.list",
                {
                    "event_filter": event_filter,
                    "limit": 200,
                },
            )
            log_list = self.ids.log_list
            log_list.clear_widgets()
            if not entries:
                log_list.add_widget(MDLabel(
                    text="No entries found.",
                    theme_text_color="Secondary",
                    size_hint_y=None,
                    height=dp(48),
                    halign="center",
                ))
                return
            for entry in entries:
                log_list.add_widget(_AuditRow(
                    occurred_at=entry.occurred_at,
                    event=entry.event,
                    payload=entry.payload,
                ))
        except Exception as exc:
            _log.error("Failed to load audit log: %s", exc)


# ---------------------------------------------------------------------------
# Audit row widget
# ---------------------------------------------------------------------------

class _AuditRow(MDBoxLayout):
    """
    Two-line audit log entry.

    Line 1 (top):    [timestamp]  [event — colour-coded]
    Line 2 (bottom): [payload key=value preview — secondary text]
    """

    def __init__(self, occurred_at: int, event: str, payload: dict, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            height=dp(56),
            padding=(dp(4), dp(2)),
            spacing=dp(2),
            **kwargs,
        )

        ts = datetime.datetime.fromtimestamp(occurred_at).strftime("%m-%d %H:%M:%S")
        color = _event_color(event)

        # ── Line 1: timestamp + event name ──────────────────────────────
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(24),
            spacing=dp(8),
        )
        header.add_widget(MDLabel(
            text=ts,
            size_hint_x=None,
            width=dp(120),
            theme_text_color="Secondary",
            font_style="Body",
            role="small",
        ))
        header.add_widget(MDLabel(
            text=event,
            theme_text_color="Custom",
            text_color=color,
            bold=True,
        ))
        self.add_widget(header)

        # ── Line 2: payload summary ──────────────────────────────────────
        self.add_widget(MDLabel(
            text=_fmt_payload(payload),
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(24),
            padding=(dp(128), 0, 0, 0),  # indent to align under event name
        ))

"""
Enrollment screen (server only) — token generation and pending token list.

Workflow:
  1. Server operator presses "Generate Token".
  2. A one-time token is created and displayed as text.
  3. Token is delivered out-of-band to the new operator.
  4. Pending tokens list (unused + unexpired) is shown below the token display.
"""
import time

from kivy.app import App
from kivy.clock import Clock
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

from talon.utils.logging import get_logger

_log = get_logger("ui.server.enroll")


class EnrollScreen(MDScreen):
    """Enrollment token generation and management."""

    def on_pre_enter(self) -> None:
        """Refresh the pending token list whenever this screen is shown."""
        self._refresh_pending()

    def on_generate_pressed(self) -> None:
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            result = app.core_session.command("enrollment.generate_token")
            combined = result.combined
            if not result.server_hash:
                _log.warning(
                    "server_rns_hash not set in meta — net_handler may not have started"
                )

            self.ids.token_display.text = combined
            _log.info("Enrollment token generated via UI (combined=%s)", bool(server_hash))
            self._refresh_pending()
        except Exception as exc:
            self.ids.token_display.text = f"Error: {exc}"
            _log.error("Token generation failed: %s", exc)

    def on_copy_pressed(self) -> None:
        text = self.ids.token_display.text
        if not text or text.startswith("Generated") or text.startswith("Error"):
            self.ids.copy_status.text = "Nothing to copy."
            return
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(text)
        self.ids.copy_status.text = "Copied!"
        # Clear the status message after 3 seconds.
        from kivy.clock import Clock
        Clock.schedule_once(lambda dt: setattr(self.ids.copy_status, "text", ""), 3)

    def on_back_pressed(self) -> None:
        self.manager.current = "main"

    # ------------------------------------------------------------------

    def _refresh_pending(self) -> None:
        app = App.get_running_app()
        if not app.core_session.is_unlocked:
            return
        try:
            tokens = app.core_session.read_model("enrollment.pending_tokens")
            token_list = self.ids.pending_list
            token_list.clear_widgets()
            if not tokens:
                token_list.add_widget(
                    MDLabel(text="No pending tokens.", theme_text_color="Secondary")
                )
                return
            now = int(time.time())
            for t in tokens:
                remaining = max(0, t.expires_at - now)
                row = _TokenRow(
                    token=t.token,
                    info=f"Expires in {remaining // 60} min",
                )
                token_list.add_widget(row)
        except Exception as exc:
            _log.error("Failed to load pending tokens: %s", exc)


class _TokenRow(MDBoxLayout):
    def __init__(self, token: str, info: str, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None, height="40dp",
                         spacing="8dp", **kwargs)
        self.add_widget(MDLabel(
            # Show 32 of 64 hex chars — enough to distinguish concurrent tokens.
            text=token[:32] + "\u2026",
            size_hint_x=0.6,
        ))
        self.add_widget(MDLabel(
            text=info,
            theme_text_color="Secondary",
            size_hint_x=0.4,
        ))

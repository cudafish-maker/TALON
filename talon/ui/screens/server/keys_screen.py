"""
Keys screen (server only) — key revocation and identity management.

Actions:
  - Hard-revoke an operator's identity by callsign or ID (delegates to
    revocation.py; requires explicit confirmation).
  - Group key rotation placeholder (no group key mechanism implemented yet;
    shows the current status and a manual trigger button for when it is wired).

All destructive actions require confirmation dialogs.
"""
from kivy.app import App
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.dialog import (
    MDDialog,
    MDDialogButtonContainer,
    MDDialogHeadlineText,
    MDDialogSupportingText,
)
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

from talon.utils.logging import get_logger

_log = get_logger("ui.server.keys")


class KeysScreen(MDScreen):
    """Key revocation and identity management screen."""

    def on_pre_enter(self) -> None:
        self._refresh_operator_list()

    def on_back_pressed(self) -> None:
        self.manager.current = "main"

    def on_rotate_group_key_pressed(self) -> None:
        """Placeholder — group key distribution not yet implemented."""
        dialog = MDDialog(
            MDDialogHeadlineText(text="Group Key Rotation"),
            MDDialogSupportingText(
                text="Group key rotation is not yet implemented.\n"
                     "When wired, this will re-key all connected operators."
            ),
            MDDialogButtonContainer(
                MDButton(
                    MDButtonText(text="OK"),
                    style="text",
                    on_release=lambda btn: dialog.dismiss(),
                ),
            ),
        )
        dialog.open()

    def on_revoke_identity_pressed(self, operator_id: int, callsign: str) -> None:
        self._confirm_revoke(operator_id, callsign)

    def _confirm_revoke(self, operator_id: int, callsign: str) -> None:
        dialog = MDDialog(
            MDDialogHeadlineText(text="Revoke Identity"),
            MDDialogSupportingText(
                text=f"Hard-revoke [{callsign}]?\n"
                     "The identity file will be securely wiped. This cannot be undone."
            ),
            MDDialogButtonContainer(
                MDButton(
                    MDButtonText(text="CANCEL"),
                    style="text",
                    on_release=lambda btn: dialog.dismiss(),
                ),
                MDButton(
                    MDButtonText(text="REVOKE"),
                    style="filled",
                    on_release=lambda btn: self._do_revoke(dialog, operator_id, callsign),
                ),
                spacing="8dp",
            ),
        )
        dialog.open()

    def _do_revoke(self, dialog: MDDialog, operator_id: int, callsign: str) -> None:
        dialog.dismiss()
        app = App.get_running_app()
        if app.conn is None:
            return
        try:
            from talon.services.operators import revoke_operator_command

            result = revoke_operator_command(app.conn, operator_id)
            app.dispatch_domain_events(result.events)
            _log.warning("Identity revoked via Keys screen: %s (id=%s)", callsign, operator_id)
            self._refresh_operator_list()
        except Exception as exc:
            _log.error("Revocation failed: %s", exc)

    def _refresh_operator_list(self) -> None:
        app = App.get_running_app()
        if app.conn is None:
            return
        try:
            rows = app.conn.execute(
                "SELECT id, callsign, revoked FROM operators ORDER BY enrolled_at DESC"
            ).fetchall()
            op_list = self.ids.operator_list
            op_list.clear_widgets()
            if not rows:
                op_list.add_widget(
                    MDLabel(text="No operators.", theme_text_color="Secondary")
                )
                return
            for row in rows:
                op_id, callsign, revoked = row
                if op_id == 1:
                    # Skip the SERVER sentinel — revoking it would destroy all
                    # history authored by id=1 and is never a valid operation.
                    continue
                op_list.add_widget(_KeyOperatorRow(
                    operator_id=op_id,
                    callsign=callsign,
                    is_revoked=bool(revoked),
                    screen=self,
                ))
        except Exception as exc:
            _log.error("Failed to load operators: %s", exc)


class _KeyOperatorRow(MDBoxLayout):
    def __init__(
        self, operator_id: int, callsign: str, is_revoked: bool,
        screen: KeysScreen, **kwargs
    ):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height="48dp",
            spacing="8dp",
            padding="4dp",
            **kwargs,
        )
        self.add_widget(MDLabel(text=callsign, size_hint_x=0.5))
        status = "REVOKED" if is_revoked else "Active"
        self.add_widget(MDLabel(
            text=status,
            theme_text_color="Secondary" if is_revoked else "Primary",
            size_hint_x=0.3,
        ))
        if not is_revoked:
            btn = MDButton(MDButtonText(text="REVOKE"), style="filled", size_hint_x=0.2)
            btn.bind(on_release=lambda b: screen.on_revoke_identity_pressed(operator_id, callsign))
            self.add_widget(btn)
        else:
            self.add_widget(MDLabel(size_hint_x=0.2))

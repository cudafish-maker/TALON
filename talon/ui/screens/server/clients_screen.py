"""
Clients screen (server only) — enrolled operator list and lease management.

Displays all operators with callsign, RNS hash, lease status, and actions:
  - Edit profile + skills (_ProfileDialog)
  - Renew lease (extends by LEASE_DURATION_S)
  - Revoke (hard shred — requires confirmation dialog)
"""
import math
import time
import typing

from kivy.app import App
from kivy.metrics import dp
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText, MDIconButton
from kivymd.uix.dialog import (
    MDDialog,
    MDDialogButtonContainer,
    MDDialogHeadlineText,
    MDDialogSupportingText,
)
from kivymd.uix.divider import MDDivider
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.selectioncontrol import MDCheckbox
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText

from talon.constants import LEASE_DURATION_S, PREDEFINED_SKILLS
from talon.ui.theme import COLOR_ACCENT, COLOR_DANGER, COLOR_PRIMARY, COLOR_SURFACE
from talon.utils.logging import get_logger

_log = get_logger("ui.server.clients")


class ClientsScreen(MDScreen):
    """Enrolled operator list with lease management."""

    def on_pre_enter(self) -> None:
        self._refresh()

    def on_refresh_pressed(self) -> None:
        self._refresh()

    def on_back_pressed(self) -> None:
        self.manager.current = "main"

    def on_renew_pressed(self, operator_id: int, callsign: str) -> None:
        app = App.get_running_app()
        if app.conn is None:
            return
        try:
            from talon.services.operators import renew_operator_lease_command

            result = renew_operator_lease_command(
                app.conn,
                operator_id,
                LEASE_DURATION_S,
            )
            app.dispatch_domain_events(result.events)
            _log.info("Lease renewed via UI: operator_id=%s", operator_id)
            self._refresh()
        except Exception as exc:
            _log.error("Renew failed: %s", exc)

    def on_edit_pressed(self, operator_id: int) -> None:
        """Open the profile / skills editor for the given operator."""
        app = App.get_running_app()
        if app.conn is None:
            return
        try:
            from talon.operators import get_operator
            operator = get_operator(app.conn, operator_id)
            if operator is None:
                _log.warning("on_edit_pressed: operator %s not found", operator_id)
                return
            _ProfileDialog(
                operator=operator,
                on_save=lambda skills, profile: self._save_profile(
                    operator_id, skills, profile
                ),
            ).open()
        except Exception as exc:
            _log.error("Failed to open profile editor: %s", exc)

    def _save_profile(
        self, operator_id: int, skills: list, profile: dict
    ) -> None:
        app = App.get_running_app()
        if app.conn is None:
            return
        try:
            from talon.services.operators import update_operator_command

            result = update_operator_command(
                app.conn,
                operator_id,
                skills=skills,
                profile=profile,
            )
            app.dispatch_domain_events(result.events)
            _log.info("Profile saved: operator_id=%s", operator_id)
            self._refresh()
        except Exception as exc:
            _log.error("Failed to save profile: %s", exc)

    def on_revoke_pressed(self, operator_id: int, callsign: str) -> None:
        self._confirm_revoke(operator_id, callsign)

    def _confirm_revoke(self, operator_id: int, callsign: str) -> None:
        dialog = MDDialog(
            MDDialogHeadlineText(text="Revoke Operator"),
            MDDialogSupportingText(
                text=f"Permanently revoke [{callsign}]?\nThis is irreversible."
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
            _log.warning("Operator revoked via UI: %s (id=%s)", callsign, operator_id)
            self._refresh()
        except Exception as exc:
            _log.error("Revocation failed: %s", exc)

    def _refresh(self) -> None:
        app = App.get_running_app()
        if app.conn is None:
            return
        try:
            rows = app.conn.execute(
                "SELECT id, callsign, rns_hash, lease_expires_at, revoked "
                "FROM operators ORDER BY enrolled_at DESC"
            ).fetchall()
            op_list = self.ids.operator_list
            op_list.clear_widgets()
            now = int(time.time())
            added = 0
            for row in rows:
                op_id, callsign, rns_hash, lease_expires, revoked = row
                # Skip the internal SERVER sentinel — not a real enrolled client.
                if op_id == 1:
                    continue
                if revoked:
                    status = "REVOKED"
                elif lease_expires < now:
                    status = "LOCKED"
                else:
                    remaining = math.ceil((lease_expires - now) / 3600)
                    status = f"OK ({remaining}h)"
                op_list.add_widget(_OperatorRow(
                    operator_id=op_id,
                    callsign=callsign,
                    rns_hash=rns_hash[:16] + "\u2026",
                    status=status,
                    is_revoked=bool(revoked),
                    screen=self,
                ))
                added += 1
            if added == 0:
                op_list.add_widget(
                    MDLabel(text="No operators enrolled.", theme_text_color="Secondary")
                )
        except Exception as exc:
            _log.error("Failed to load operators: %s", exc)


class _OperatorRow(MDBoxLayout):
    def __init__(
        self, operator_id: int, callsign: str, rns_hash: str,
        status: str, is_revoked: bool, screen: ClientsScreen, **kwargs
    ):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height="48dp",
            spacing="8dp",
            padding="4dp",
            **kwargs,
        )
        if status == "REVOKED":
            status_color = COLOR_DANGER
        elif status == "LOCKED":
            status_color = COLOR_ACCENT
        else:
            status_color = COLOR_PRIMARY

        self.add_widget(MDLabel(text=callsign, size_hint_x=0.18))
        self.add_widget(MDLabel(text=rns_hash, size_hint_x=0.26,
                                theme_text_color="Secondary"))
        self.add_widget(MDLabel(
            text=status,
            size_hint_x=0.16,
            theme_text_color="Custom",
            text_color=status_color,
            bold=True,
        ))

        edit_btn = MDIconButton(
            icon="account-edit",
            size_hint_x=None,
            width=dp(44),
        )
        edit_btn.bind(on_release=lambda btn: screen.on_edit_pressed(operator_id))
        self.add_widget(edit_btn)

        if not is_revoked:
            renew_btn = MDButton(MDButtonText(text="RENEW"), style="text", size_hint_x=0.2)
            renew_btn.bind(on_release=lambda btn: screen.on_renew_pressed(operator_id, callsign))
            self.add_widget(renew_btn)

            revoke_btn = MDButton(MDButtonText(text="REVOKE"), style="filled", size_hint_x=0.2)
            revoke_btn.bind(on_release=lambda btn: screen.on_revoke_pressed(operator_id, callsign))
            self.add_widget(revoke_btn)
        else:
            self.add_widget(MDLabel(size_hint_x=0.4))


# ---------------------------------------------------------------------------
# Profile / Skills editor dialog
# ---------------------------------------------------------------------------

class _ProfileDialog:
    """Modal dialog for editing an operator's profile fields and skills.

    Profile fields: display_name, notes (stored in operators.profile JSON).
    Skills: predefined toggles (checkboxes) + custom free-text entries
    (stored together in operators.skills JSON array).

    on_save(skills: list[str], profile: dict) is called on SAVE.
    """

    def __init__(
        self,
        operator: typing.Any,
        on_save: typing.Callable[[list, dict], None],
    ) -> None:
        self._operator = operator
        self._on_save = on_save
        self._skill_checkboxes: dict[str, MDCheckbox] = {}
        self._custom_skills: list[str] = [
            s for s in operator.skills if s not in PREDEFINED_SKILLS
        ]
        self._modal = self._build()

    def open(self) -> None:
        self._modal.open()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> ModalView:
        modal = ModalView(
            size_hint=(0.65, 0.90),
            auto_dismiss=False,
            background_color=(0, 0, 0, 0),
        )
        card = MDBoxLayout(
            orientation="vertical",
            md_bg_color=COLOR_SURFACE,
            radius=[dp(12)] * 4,
        )

        # Scrollable body
        scroll = ScrollView()
        body = MDBoxLayout(
            orientation="vertical",
            padding=dp(20),
            spacing=dp(12),
            adaptive_height=True,
        )

        body.add_widget(MDLabel(
            text=f"Edit Operator — {self._operator.callsign}",
            font_style="Title",
            role="medium",
            size_hint_y=None,
            height=dp(40),
        ))
        body.add_widget(MDDivider())

        # ── Profile ────────────────────────────────────────────────────
        body.add_widget(self._section_label("Profile"))

        self._display_name_field = MDTextField(adaptive_height=True)
        self._display_name_field.add_widget(
            MDTextFieldHintText(text="Display name (optional)")
        )
        self._display_name_field.text = self._operator.profile.get("display_name", "")
        body.add_widget(self._display_name_field)

        self._notes_field = MDTextField(adaptive_height=True, multiline=True)
        self._notes_field.add_widget(
            MDTextFieldHintText(text="Notes (optional)")
        )
        self._notes_field.text = self._operator.profile.get("notes", "")
        body.add_widget(self._notes_field)
        body.add_widget(MDDivider())

        # ── Predefined skills ──────────────────────────────────────────
        body.add_widget(self._section_label("Predefined Skills"))

        grid = GridLayout(
            cols=2,
            size_hint_y=None,
            row_default_height=dp(40),
            row_force_default=True,
            spacing=dp(4),
        )
        grid.bind(minimum_height=grid.setter("height"))

        for skill in PREDEFINED_SKILLS:
            row = MDBoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(40),
                spacing=dp(6),
            )
            cb = MDCheckbox(
                size_hint_x=None,
                width=dp(40),
                active=(skill in self._operator.skills),
            )
            self._skill_checkboxes[skill] = cb
            row.add_widget(cb)
            row.add_widget(MDLabel(text=skill, valign="center"))
            grid.add_widget(row)

        body.add_widget(grid)
        body.add_widget(MDDivider())

        # ── Custom skills ──────────────────────────────────────────────
        body.add_widget(self._section_label("Custom Skills"))

        add_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            spacing=dp(8),
        )
        self._custom_input = MDTextField(adaptive_height=True)
        self._custom_input.add_widget(
            MDTextFieldHintText(text="Add custom skill…")
        )
        add_btn = MDButton(
            MDButtonText(text="ADD"),
            style="outlined",
            size_hint_x=None,
            width=dp(76),
        )
        add_btn.bind(on_release=lambda _: self._add_custom_skill())
        add_row.add_widget(self._custom_input)
        add_row.add_widget(add_btn)
        body.add_widget(add_row)

        self._custom_list = MDBoxLayout(
            orientation="vertical",
            adaptive_height=True,
            spacing=dp(2),
        )
        body.add_widget(self._custom_list)
        self._refresh_custom_list()

        scroll.add_widget(body)
        card.add_widget(scroll)

        # ── Footer ─────────────────────────────────────────────────────
        footer = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            spacing=dp(8),
            padding=(dp(20), dp(8)),
        )
        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="text")
        cancel_btn.bind(on_release=lambda _: modal.dismiss())
        save_btn = MDButton(MDButtonText(text="SAVE"), style="elevated")
        save_btn.bind(on_release=lambda _: self._save())
        footer.add_widget(cancel_btn)
        footer.add_widget(save_btn)
        card.add_widget(footer)

        modal.add_widget(card)
        return modal

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _section_label(text: str) -> MDLabel:
        return MDLabel(
            text=text,
            theme_text_color="Secondary",
            font_style="Label",
            role="medium",
            size_hint_y=None,
            height=dp(28),
        )

    def _add_custom_skill(self) -> None:
        skill = self._custom_input.text.strip().lower()
        if not skill:
            return
        if skill in PREDEFINED_SKILLS or skill in self._custom_skills:
            self._custom_input.text = ""
            return
        self._custom_skills.append(skill)
        self._custom_input.text = ""
        self._refresh_custom_list()

    def _remove_custom_skill(self, skill: str) -> None:
        if skill in self._custom_skills:
            self._custom_skills.remove(skill)
        self._refresh_custom_list()

    def _refresh_custom_list(self) -> None:
        self._custom_list.clear_widgets()
        if not self._custom_skills:
            self._custom_list.add_widget(MDLabel(
                text="No custom skills.",
                theme_text_color="Secondary",
                size_hint_y=None,
                height=dp(28),
            ))
            return
        for skill in self._custom_skills:
            row = MDBoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(36),
                spacing=dp(4),
            )
            row.add_widget(MDLabel(text=f"• {skill}", valign="center"))
            rm_btn = MDIconButton(
                icon="close",
                size_hint_x=None,
                width=dp(36),
            )
            rm_btn.bind(on_release=lambda _, s=skill: self._remove_custom_skill(s))
            row.add_widget(rm_btn)
            self._custom_list.add_widget(row)

    def _save(self) -> None:
        active_predefined = [
            s for s, cb in self._skill_checkboxes.items() if cb.active
        ]
        all_skills = active_predefined + self._custom_skills

        profile: dict = {}
        dn = self._display_name_field.text.strip()
        if dn:
            profile["display_name"] = dn
        notes = self._notes_field.text.strip()
        if notes:
            profile["notes"] = notes

        self._modal.dismiss()
        self._on_save(all_skills, profile)

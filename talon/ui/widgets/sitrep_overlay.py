"""
SITREP notification overlay.

Scales with severity:
  ROUTINE        — small auto-dismissing dialog (3 s)
  PRIORITY       — auto-dismissing dialog (5 s)
  IMMEDIATE      — half-screen modal, explicit dismiss required
  FLASH          — full-screen modal, explicit dismiss required
  FLASH_OVERRIDE — full-screen modal, explicit dismiss required

Audio: NEVER triggered automatically.  Playback is gated by the user's
opt-in audio alert setting — checked in SitrepScreen, not here.
"""
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.modalview import ModalView
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.dialog import (
    MDDialog,
    MDDialogButtonContainer,
    MDDialogHeadlineText,
    MDDialogSupportingText,
)
from kivymd.uix.label import MDLabel

from talon.ui.theme import SITREP_COLORS


class SitrepOverlay(Widget):
    """Severity-scaled notification overlay for incoming SITREPs."""

    def show(self, sitrep) -> None:
        """Display the overlay appropriate for sitrep.level."""
        level = getattr(sitrep, "level", "ROUTINE")
        color = SITREP_COLORS.get(level, SITREP_COLORS["ROUTINE"])
        raw = getattr(sitrep, "body", b"")
        body = (
            raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        )
        if level in ("FLASH", "FLASH_OVERRIDE"):
            self._show_modal(level, color, body, full_screen=True)
        elif level == "IMMEDIATE":
            self._show_modal(level, color, body, full_screen=False)
        elif level == "PRIORITY":
            self._show_dialog(level, body, duration=5)
        else:  # ROUTINE
            self._show_dialog(level, body, duration=3)

    # ------------------------------------------------------------------
    # ROUTINE / PRIORITY — auto-dismissing MDDialog
    # ------------------------------------------------------------------

    def _show_dialog(self, level: str, body: str, *, duration: float) -> None:
        """MDDialog that auto-dismisses after `duration` seconds."""
        dismiss_btn = MDButton(MDButtonText(text="OK"), style="text")
        dialog = MDDialog(
            MDDialogHeadlineText(text=level),
            MDDialogSupportingText(text=body[:300]),
            MDDialogButtonContainer(dismiss_btn, spacing="8dp"),
        )
        dismiss_btn.bind(on_release=lambda _: dialog.dismiss())
        dialog.open()
        # Auto-dismiss; safe to call on an already-dismissed dialog.
        Clock.schedule_once(lambda dt, d=dialog: d.dismiss(), duration)

    # ------------------------------------------------------------------
    # IMMEDIATE / FLASH / FLASH_OVERRIDE — blocking modal
    # ------------------------------------------------------------------

    def _show_modal(self, level: str, color: tuple, body: str, *, full_screen: bool) -> None:
        """ModalView that blocks input until the operator acknowledges."""
        size_hint = (1, 1) if full_screen else (0.85, 0.55)
        modal = ModalView(
            size_hint=size_hint,
            auto_dismiss=False,
            background_color=(0, 0, 0, 0.6),
        )
        # Colored content panel — severity color as background.
        content = MDBoxLayout(
            orientation="vertical",
            padding=dp(32),
            spacing=dp(16),
            md_bg_color=(*color[:3], 0.95),
        )
        content.add_widget(MDLabel(
            text=level,
            halign="center",
            font_style="Headline",
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
        ))
        content.add_widget(MDLabel(
            text=body[:500],
            halign="center",
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
        ))
        ack_btn = MDButton(
            MDButtonText(text="ACKNOWLEDGE"),
            style="elevated",
            pos_hint={"center_x": 0.5},
        )
        ack_btn.bind(on_release=lambda _: modal.dismiss())
        content.add_widget(ack_btn)
        modal.add_widget(content)
        modal.open()

# talon/ui/screens/login.py
# Login / passphrase entry screen.
#
# This is the first screen an operator sees. It collects the passphrase
# used to unlock the local encrypted database and derive the session key.
#
# Two states:
#   ENROLLED   — operator has been enrolled before; just enter passphrase
#   UNENROLLED — first run; show enrollment token entry instead
#
# The screen doesn't validate the passphrase itself — it passes it to
# TalonApp.do_login(), which runs the full startup sequence and shows
# an error here if the passphrase is wrong.

import os

from kivymd.uix.screen import MDScreen
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.textfield import MDTextField
from kivy.properties import StringProperty, BooleanProperty

from talon.ui.theme import (
    BG_BASE, BG_SURFACE, COLOR_PRIMARY, COLOR_RED,
    TEXT_PRIMARY, TEXT_SECONDARY,
    PADDING_MD, PADDING_LG,
)


class LoginScreen(MDScreen):
    """Passphrase entry screen.

    Properties (set by KV or code):
        error_text:     Shown in red below the passphrase field.
        is_loading:     True while the backend is starting up.
    """

    error_text  = StringProperty("")
    is_loading  = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Check enrollment state from the data directory.
        # If no identity file exists yet, the operator needs to enroll.
        self.is_enrolled = self._check_enrolled()

    # ------------------------------------------------------------------
    # Public interface (called by TalonApp)
    # ------------------------------------------------------------------

    def show_error(self, message: str):
        """Display an error message and re-enable the login button.

        Args:
            message: Human-readable error string.
        """
        self.is_loading = False
        self.error_text = message

    def clear_error(self):
        """Clear any displayed error."""
        self.error_text = ""

    # ------------------------------------------------------------------
    # KV event handlers
    # ------------------------------------------------------------------

    def on_submit(self):
        """Called when the operator presses Login or hits Enter.

        Reads the passphrase field, clears any error, and hands off
        to TalonApp.do_login() to run the startup sequence.
        """
        passphrase = self.ids.passphrase_field.text.strip()

        if not passphrase:
            self.error_text = "Passphrase is required."
            return

        self.clear_error()
        self.is_loading = True

        # Hand off to the app — it calls TalonClient.start()
        from kivy.app import App
        App.get_running_app().do_login(passphrase)

    def on_passphrase_text(self, field, text):
        """Clear the error as soon as the operator starts typing."""
        if text and self.error_text:
            self.clear_error()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_enrolled() -> bool:
        """Check whether this client has been enrolled before.

        Returns True if an identity file exists in the default data dir.
        This is a best-effort check — the full enrollment status is
        confirmed during TalonClient.start().
        """
        identity_path = os.path.join("data", "client", "identity")
        return os.path.isfile(identity_path)

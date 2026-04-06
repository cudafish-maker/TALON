# talon/ui/server/screens/login.py
# Server login screen — passphrase entry for the server operator.
#
# Visually similar to the client login screen but clearly marked
# as the server ("the chair") so the operator knows which app they're
# launching.

from kivy.properties import BooleanProperty, StringProperty
from kivymd.uix.screen import MDScreen


class ServerLoginScreen(MDScreen):
    """Passphrase screen for the server operator."""

    error_text = StringProperty("")
    is_loading = BooleanProperty(False)

    def show_error(self, message: str):
        self.is_loading = False
        self.error_text = message

    def on_submit(self):
        passphrase = self.ids.passphrase_field.text.strip()
        if not passphrase:
            self.error_text = "Passphrase is required."
            return
        self.error_text = ""
        self.is_loading = True

        from kivy.app import App

        App.get_running_app().do_login(passphrase)

    def on_passphrase_text(self, field, text):
        if text and self.error_text:
            self.error_text = ""

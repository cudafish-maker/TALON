# talon/ui/server/screens/setup.py
# First-run setup screen — choose the server operator passphrase.
#
# Shown only when no salt file exists on disk (i.e. the encrypted
# database has never been initialised). The operator must type the
# passphrase twice; on submit we hand off to the same do_login()
# entry point as the regular login screen, which creates the salt
# and the encrypted database.

from kivy.properties import BooleanProperty, StringProperty
from kivymd.uix.screen import MDScreen

# Minimum passphrase length for the server credential. The server
# passphrase derives the database key and the lease-signing secret,
# so it deserves a stricter floor than the 6-char client minimum.
MIN_PASSPHRASE_LENGTH = 12


class ServerSetupScreen(MDScreen):
    """First-run passphrase setup for the server operator.

    Properties:
        error_text:  Validation or backend error to show in red.
        is_loading:  True while the server is starting after submit.
    """

    error_text = StringProperty("")
    is_loading = BooleanProperty(False)

    def show_error(self, message: str):
        self.is_loading = False
        self.error_text = message

    def on_submit(self):
        # Reject re-entry while a start is already in flight — see the
        # matching guard in ServerLoginScreen.on_submit for context.
        if self.is_loading:
            return
        passphrase = self.ids.passphrase_field.text
        confirm = self.ids.confirm_field.text

        if not passphrase:
            self.error_text = "Passphrase is required."
            return
        if len(passphrase) < MIN_PASSPHRASE_LENGTH:
            self.error_text = f"Passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters."
            return
        if passphrase != confirm:
            self.error_text = "Passphrases do not match."
            return

        self.error_text = ""
        self.is_loading = True

        from kivy.app import App

        App.get_running_app().do_login(passphrase)

    def on_passphrase_text(self, field, text):
        if text and self.error_text:
            self.error_text = ""

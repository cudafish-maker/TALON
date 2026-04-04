# talon/ui/screens/lock.py
# Soft-lock screen — shown when the operator's 24hr lease has expired.
#
# The operator cannot use the app until the server operator approves
# a re-authentication request. This screen:
#   1. Shows that the session is locked and why
#   2. Lets the operator send a re-auth request to the server
#   3. Polls for approval (server sends a new lease token)
#   4. On approval, transitions to the main screen

from kivymd.uix.screen import MDScreen
from kivy.properties import StringProperty, BooleanProperty
from kivy.clock import Clock


class LockScreen(MDScreen):
    """24hr soft-lock screen.

    Properties:
        status_text:    Current status message shown to the operator.
        is_requesting:  True while a re-auth request is in flight.
        is_approved:    True after the server approves re-auth.
    """

    status_text   = StringProperty("Your session has expired.")
    is_requesting = BooleanProperty(False)
    is_approved   = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._poll_event = None

    def on_enter(self):
        """Called by Kivy when this screen becomes active.

        Start polling for server approval every 30 seconds.
        """
        self._poll_event = Clock.schedule_interval(
            self._poll_for_approval, 30
        )

    def on_leave(self):
        """Called when navigating away from this screen."""
        if self._poll_event:
            self._poll_event.cancel()
            self._poll_event = None

    def on_request_reauth(self):
        """Operator pressed "Request Re-Authentication".

        Sends a re-auth request to the server via the connection manager.
        """
        from kivy.app import App
        app = App.get_running_app()

        if not app.talon.connection:
            self.status_text = "Cannot reach server — check network."
            return

        self.is_requesting = True
        self.status_text = "Re-authentication request sent. Waiting for server approval..."

        # The actual request is sent through the connection manager.
        # The server operator sees a pending re-auth in their UI and
        # approves it, triggering a new lease token to be sent back.
        try:
            app.talon.auth.request_reauth(app.talon.connection)
        except Exception as e:
            self.status_text = f"Request failed: {e}"
            self.is_requesting = False

    def _poll_for_approval(self, dt):
        """Check whether the server has sent a new lease token.

        Called every 30 seconds by the Clock scheduler.
        """
        from kivy.app import App
        app = App.get_running_app()

        if not app.talon.auth:
            return

        lease_status = app.talon.auth.check_lease()
        if not lease_status["locked"]:
            # Lease renewed — unlock the app
            self.is_approved = True
            self.status_text = "Session renewed. Resuming..."
            if self._poll_event:
                self._poll_event.cancel()
            Clock.schedule_once(self._transition_to_main, 1.0)

    def _transition_to_main(self, dt):
        """Navigate to the main screen after approval."""
        from kivy.app import App
        app = App.get_running_app()
        app.screen_manager.current = "main"
        main = app.screen_manager.get_screen("main")
        main.on_client_ready(app.talon)

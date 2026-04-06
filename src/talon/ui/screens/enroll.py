# talon/ui/screens/enroll.py
# First-run enrollment screen.
#
# Shown when the client has never enrolled before (no lease.json).
# Collects:
#   - Server destination hash (from server operator)
#   - Enrollment token (single-use, from server operator)
#   - Callsign (operator's chosen display name)
#   - Passphrase (to encrypt local database)
#
# On submit, the client connects to the server over Reticulum,
# sends the enrollment request, and saves the returned lease.

import threading

from kivy.clock import Clock
from kivy.properties import BooleanProperty, StringProperty
from kivymd.uix.screen import MDScreen


class EnrollScreen(MDScreen):
    """First-run enrollment screen.

    Properties:
        status_text:  Status or error message shown below the form.
        is_loading:   True while enrollment is in progress.
        is_error:     True if status_text is an error (red text).
    """

    status_text = StringProperty("")
    is_loading = BooleanProperty(False)
    is_error = BooleanProperty(False)

    def on_field_text(self):
        """Clear status when the operator starts typing."""
        if self.status_text:
            self.status_text = ""
            self.is_error = False

    def on_enroll(self):
        """Called when the operator presses ENROLL."""
        server_hash = self.ids.server_hash_field.text.strip()
        token = self.ids.token_field.text.strip()
        callsign = self.ids.callsign_field.text.strip().upper()
        passphrase = self.ids.passphrase_field.text.strip()

        # Validation
        if not server_hash:
            self._show_error("Server destination hash is required.")
            return
        if len(server_hash) < 20:
            self._show_error("Server hash looks too short.")
            return
        if not token:
            self._show_error("Enrollment token is required.")
            return
        if len(token) != 32:
            self._show_error("Token must be 32 hex characters.")
            return
        if not callsign:
            self._show_error("Callsign is required.")
            return
        if not passphrase:
            self._show_error("Passphrase is required.")
            return
        if len(passphrase) < 6:
            self._show_error("Passphrase must be at least 6 characters.")
            return

        self.is_loading = True
        self.is_error = False
        self.status_text = "Connecting to server..."

        # Run enrollment in background thread
        from kivy.app import App

        app = App.get_running_app()
        thread = threading.Thread(
            target=self._do_enroll,
            args=(app, server_hash, token, callsign, passphrase),
            daemon=True,
        )
        thread.start()

    def _do_enroll(self, app, server_hash, token, callsign, passphrase):
        """Background thread: connect to server and request enrollment."""
        try:
            talon = app.talon

            # Initialize config and network so we can connect
            talon.load_config()

            # Store the server hash in config for ConnectionManager
            talon.config["server_destination_hash"] = server_hash

            # Set up data directory
            data_dir = talon.config.get("database", {}).get("path", "data/client")
            data_dir = data_dir.rsplit("/", 1)[0] if "/" in data_dir else "data"

            talon.setup_auth(data_dir)
            talon.setup_network()

            # Build the enrollment request
            enrollment_msg = talon.auth.request_enrollment(token, callsign)

            # Connect to the server
            Clock.schedule_once(lambda dt: self._update_status("Connecting to server..."), 0)

            from talon.net.link_manager import ClientLinkManager

            link_manager = ClientLinkManager(
                identity=talon.identity,
                server_dest_hash=bytes.fromhex(server_hash),
            )

            if not link_manager.connect(timeout=20):
                Clock.schedule_once(
                    lambda dt: self._show_error("Cannot reach server. Check the hash and try again."), 0
                )
                return

            Clock.schedule_once(lambda dt: self._update_status("Sending enrollment request..."), 0)

            # Send enrollment request and wait for response
            response = link_manager.send_and_receive(enrollment_msg, timeout=30)
            link_manager.disconnect()

            if not response:
                Clock.schedule_once(lambda dt: self._show_error("No response from server. Try again."), 0)
                return

            if not response.get("success"):
                error = response.get("error", "Enrollment rejected by server.")
                Clock.schedule_once(lambda dt, e=error: self._show_error(e), 0)
                return

            # Save the lease
            lease_data = {
                "token": response["lease"]["token"],
                "issued_at": response["lease"]["issued_at"],
                "expires_at": response["lease"]["expires_at"],
                "signature": response["signature"],
                "callsign": callsign,
                "server_hash": server_hash,
            }
            talon.auth.save_lease(lease_data)

            # Save server hash to client config for future connections
            import os

            import yaml

            config_dir = talon.config_path or os.path.join(os.path.dirname(__file__), "..", "..", "..", "config")
            client_config_path = os.path.join(config_dir, "client.yaml")
            client_cfg = {}
            if os.path.isfile(client_config_path):
                with open(client_config_path, "r") as f:
                    client_cfg = yaml.safe_load(f) or {}
            client_cfg["server_destination_hash"] = server_hash
            client_cfg["callsign"] = callsign
            os.makedirs(os.path.dirname(client_config_path) or ".", exist_ok=True)
            with open(client_config_path, "w") as f:
                yaml.dump(client_cfg, f)

            # Now do the full client startup with the passphrase
            Clock.schedule_once(lambda dt: self._enrollment_complete(app, passphrase), 0)

        except Exception as e:
            Clock.schedule_once(lambda dt, err=str(e): self._show_error(f"Error: {err}"), 0)

    def _enrollment_complete(self, app, passphrase):
        """Called on main thread after successful enrollment."""
        self.is_loading = False
        self.status_text = ""
        app.do_login(passphrase)

    def _show_error(self, message):
        """Show an error message (main thread safe)."""
        self.is_loading = False
        self.is_error = True
        self.status_text = message

    def _update_status(self, message):
        """Update the status text (main thread safe)."""
        self.is_error = False
        self.status_text = message

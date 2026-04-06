# talon/ui/server/app.py
# KivyMD application entry point for the T.A.L.O.N. server ("the chair").
#
# The server UI is a separate application from the client UI.
# It runs on the server operator's machine alongside TalonServer.
#
# The server operator has full authority:
#   - See all connected clients and their status
#   - Approve or deny re-authentication requests
#   - Revoke a compromised client (triggers group key rotation)
#   - Generate enrollment tokens for new operators
#   - View the full audit log
#   - See all operator positions on the map
#   - Manage missions, assets, channels across the whole team
#
# Startup flow:
#   1. build()     — create screen manager, apply theme
#   2. on_start()  — show server login screen
#   3. After passphrase → start TalonServer → show server main screen
#   4. on_stop()   — shutdown TalonServer cleanly

import os

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivymd.app import MDApp
from kivymd.uix.screenmanager import MDScreenManager

from talon.server.app import TalonServer
from talon.ui.theme import BG_BASE, KIVYMD_THEME
from talon.ui.widgets import MapWidget, StatusBar  # noqa: F401 — register with Factory

KV_DIR = os.path.join(os.path.dirname(__file__), "kv")


class TalonServerApp(MDApp):
    """Main Kivy application class for the T.A.L.O.N. server operator UI.

    This is the "chair" interface — full situational awareness across
    all connected operators.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = "T.A.L.O.N. — SERVER"
        self.talon = TalonServer()
        self.screen_manager = None

    # ------------------------------------------------------------------
    # KivyMD lifecycle
    # ------------------------------------------------------------------

    def build(self):
        """Set up theme, load KV files, create screen manager."""
        self.theme_cls.theme_style = KIVYMD_THEME["theme_style"]
        self.theme_cls.primary_palette = KIVYMD_THEME["primary_palette"]

        Window.clearcolor = self._hex_to_rgba(BG_BASE)

        self._load_kv_files()

        self.screen_manager = MDScreenManager()
        self._register_screens()
        return self.screen_manager

    def on_start(self):
        self.screen_manager.current = "server_login"

    def on_stop(self):
        if self.talon.running:
            self.talon.shutdown()

    # ------------------------------------------------------------------
    # Screen registration
    # ------------------------------------------------------------------

    def _register_screens(self):
        from talon.ui.server.screens.login import ServerLoginScreen
        from talon.ui.server.screens.main import ServerMainScreen

        self.screen_manager.add_widget(ServerLoginScreen(name="server_login"))
        self.screen_manager.add_widget(ServerMainScreen(name="server_main"))

    # ------------------------------------------------------------------
    # Backend bridge
    # ------------------------------------------------------------------

    def do_login(self, passphrase: str):
        """Start TalonServer with the given passphrase."""
        Clock.schedule_once(lambda dt: self._start_server(passphrase), 0.1)

    def _start_server(self, passphrase: str):
        try:
            self.talon.start(passphrase)
        except Exception as e:
            login = self.screen_manager.get_screen("server_login")
            login.show_error(str(e))
            return

        self.screen_manager.current = "server_main"
        main = self.screen_manager.get_screen("server_main")
        main.on_server_ready(self.talon)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _hex_to_rgba(hex_color: str) -> tuple:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
        return (r, g, b, 1.0)

    def _load_kv_files(self):
        if not os.path.isdir(KV_DIR):
            return
        for filename in sorted(os.listdir(KV_DIR)):
            if filename.endswith(".kv"):
                Builder.load_file(os.path.join(KV_DIR, filename))


def run_server(config_path: str = None):
    """Launch the T.A.L.O.N. server application.

    Args:
        config_path: Optional path to config directory.
    """
    app = TalonServerApp()
    if config_path:
        app.talon.config_path = config_path
    app.run()

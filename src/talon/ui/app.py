# talon/ui/app.py
# KivyMD application entry point for the T.A.L.O.N. client.
#
# This class sits between Kivy's event loop and TalonClient.
# It owns the screen manager, applies the tactical theme, and
# bridges UI events (button presses, screen transitions) to
# backend calls (sync, auth, notifications).
#
# Launch flow:
#   1. build() — create the screen manager, register all screens
#   2. on_start() — show the login screen
#   3. After passphrase entered → start TalonClient → show main layout
#   4. on_stop() — clean shutdown of TalonClient

import os

from kivy.lang import Builder
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.clock import Clock

from kivymd.app import MDApp
from kivymd.uix.screenmanager import MDScreenManager

from talon.client.app import TalonClient
from talon.ui.theme import KIVYMD_THEME, BG_BASE, DESKTOP_MIN_WIDTH


# Load all KV layout files at import time.
# Each screen registers itself via its KV string or .kv file.
KV_DIR = os.path.join(os.path.dirname(__file__), "kv")


class TalonApp(MDApp):
    """Main Kivy application class for T.A.L.O.N. client.

    MDApp is the KivyMD base class. It manages the theme, the root
    widget tree, and the Kivy event loop (Clock, input, rendering).

    Usage:
        app = TalonApp()
        app.run()
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = "T.A.L.O.N."
        self.talon = TalonClient()        # Backend client instance
        self.screen_manager = None        # Kivy screen manager
        self.is_mobile_layout = False     # True on Android / narrow window

    # ------------------------------------------------------------------
    # KivyMD lifecycle
    # ------------------------------------------------------------------

    def build(self):
        """Called by Kivy before the window opens.

        Sets up the theme, loads KV files, creates the screen manager,
        and returns the root widget.
        """
        # Apply tactical dark theme
        self.theme_cls.theme_style      = KIVYMD_THEME["theme_style"]
        self.theme_cls.primary_palette  = KIVYMD_THEME["primary_palette"]
        self.theme_cls.accent_palette   = KIVYMD_THEME["accent_palette"]
        self.theme_cls.primary_hue      = KIVYMD_THEME["primary_hue"]
        self.theme_cls.accent_hue       = KIVYMD_THEME["accent_hue"]

        # Force the window background to our base colour.
        # KivyMD's dark theme is grey — we want near-black.
        Window.clearcolor = self._hex_to_rgba(BG_BASE)

        # Detect layout mode based on window width.
        # This runs once at build; window resize is handled by on_size().
        self.is_mobile_layout = (Window.width < dp(DESKTOP_MIN_WIDTH))
        Window.bind(on_resize=self._on_window_resize)

        # Load all KV layout files
        self._load_kv_files()

        # Create the screen manager
        self.screen_manager = MDScreenManager()
        self._register_screens()

        return self.screen_manager

    def on_start(self):
        """Called after build(), once the window is ready.

        Navigate to the login screen to collect the passphrase.
        """
        self.screen_manager.current = "login"

    def on_stop(self):
        """Called when the user closes the app.

        Cleanly shuts down the backend client (closes DB, disconnects).
        """
        if self.talon.running:
            self.talon.shutdown()

    # ------------------------------------------------------------------
    # Screen registration
    # ------------------------------------------------------------------

    def _register_screens(self):
        """Add all screens to the screen manager.

        Screens are imported here (not at module level) to avoid
        circular imports and to ensure KV files are loaded first.
        """
        from talon.ui.screens.login import LoginScreen
        from talon.ui.screens.main import MainScreen
        from talon.ui.screens.lock import LockScreen

        self.screen_manager.add_widget(LoginScreen(name="login"))
        self.screen_manager.add_widget(MainScreen(name="main"))
        self.screen_manager.add_widget(LockScreen(name="lock"))

    # ------------------------------------------------------------------
    # Backend bridge — called by UI screens
    # ------------------------------------------------------------------

    def do_login(self, passphrase: str):
        """Start the backend client with the given passphrase.

        Called by the login screen when the operator submits their
        passphrase. Runs the startup sequence in the background so
        the UI doesn't freeze.

        Args:
            passphrase: The operator's passphrase string.
        """
        # Schedule on next frame so the login button animation completes
        Clock.schedule_once(
            lambda dt: self._start_client(passphrase), 0.1
        )

    def _start_client(self, passphrase: str):
        """Run TalonClient startup and navigate to the correct screen.

        Called from do_login() after one frame delay.
        """
        try:
            self.talon.start(passphrase)
        except Exception as e:
            # Bad passphrase or corrupt database
            login_screen = self.screen_manager.get_screen("login")
            login_screen.show_error(str(e))
            return

        # Check if the lease is soft-locked
        lease_status = self.talon.auth.check_lease()
        if lease_status["locked"]:
            self.screen_manager.current = "lock"
        else:
            self.screen_manager.current = "main"
            # Trigger initial sync display
            main_screen = self.screen_manager.get_screen("main")
            main_screen.on_client_ready(self.talon)

    def do_logout(self):
        """Log out and return to the login screen."""
        if self.talon.running:
            self.talon.shutdown()
        # Reset the client so it can be re-initialized
        self.talon = TalonClient()
        self.screen_manager.current = "login"

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _on_window_resize(self, window, width, height):
        """Respond to window resize events.

        On desktop, the user may resize the window narrow enough to
        warrant switching to the mobile layout. The main screen
        handles the actual layout swap.
        """
        was_mobile = self.is_mobile_layout
        self.is_mobile_layout = (width < dp(DESKTOP_MIN_WIDTH))

        if was_mobile != self.is_mobile_layout:
            # Layout mode changed — notify the main screen
            if self.screen_manager.current == "main":
                main_screen = self.screen_manager.get_screen("main")
                main_screen.on_layout_changed(self.is_mobile_layout)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _hex_to_rgba(hex_color: str) -> tuple:
        """Convert a CSS hex color string to a Kivy RGBA tuple (0.0–1.0).

        Args:
            hex_color: e.g. "#0a0e14"

        Returns:
            (r, g, b, 1.0) with each channel in [0, 1].
        """
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        return (r, g, b, 1.0)

    def _load_kv_files(self):
        """Load all .kv layout files from the kv/ directory.

        Files are loaded in alphabetical order. Each .kv file registers
        its widget classes with Kivy's Builder automatically.
        """
        if not os.path.isdir(KV_DIR):
            return

        for filename in sorted(os.listdir(KV_DIR)):
            if filename.endswith(".kv"):
                Builder.load_file(os.path.join(KV_DIR, filename))


def run_client(config_path: str = None):
    """Launch the T.A.L.O.N. client application.

    This is the main entry point called by the launcher script or
    PyInstaller bundle.

    Args:
        config_path: Optional path to the config directory.
                     Defaults to the bundled config/.
    """
    app = TalonApp()
    if config_path:
        app.talon.config_path = config_path
    app.run()

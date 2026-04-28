"""
Login screen — passphrase entry → Argon2id KDF → unlock SQLCipher DB.

Flow:
  1. User types passphrase.
  2. TalonCoreSession loads/creates salt and derives the DB key.
  3. TalonCoreSession opens SQLCipher, verifies the key, and applies migrations.
  4. On server: the encrypted audit hook is installed; ServerNetHandler is started.
  7a. On server: app transitions to "main".
  7b. On client, already enrolled: ClientSyncManager is started; app transitions to "main".
  7c. On client, first run (not enrolled): enrollment dialog is shown.
       - User pastes TOKEN:SERVER_HASH + callsign → Enroll button.
       - On success: ClientSyncManager starts, app transitions to "main".
       - On failure: error shown in dialog, dialog stays open.
  Wrong passphrase shows an error and stays on the login screen.
"""
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.modalview import ModalView
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText

from talon.utils.logging import get_logger

_log = get_logger("ui.login")


class LoginScreen(MDScreen):
    """Passphrase entry screen."""

    def on_kv_post(self, base_widget) -> None:
        app = App.get_running_app()
        mode_label = "Server" if app.mode == "server" else "Client"
        self.ids.title_label.text = f"T.A.L.O.N. {mode_label}"

    def on_login_pressed(self, passphrase: str) -> None:
        """Called by the KV login button."""
        if not passphrase.strip():
            self.ids.error_label.text = "Passphrase is required."
            return
        self.ids.error_label.text = "Deriving key\u2026"
        self.ids.unlock_button.disabled = True

        threading.Thread(
            target=self._do_login, args=(passphrase,), daemon=True
        ).start()

    # ------------------------------------------------------------------
    # Background thread
    # ------------------------------------------------------------------

    def _do_login(self, passphrase: str) -> None:
        try:
            app = App.get_running_app()
            result = app.core_session.unlock(
                passphrase,
                start_lease_monitor=True,
                install_audit=True,
            )

            # ----------------------------------------------------------
            # Start network sync through core.
            # ----------------------------------------------------------
            try:
                self._start_reticulum_on_ui_thread()
                app.core_session.start_sync(init_reticulum=False)
            except Exception as exc:
                if app.mode == "server":
                    # Preserve legacy behavior: a server network startup issue
                    # should not prevent local login.
                    _log.warning("ServerNetHandler failed to start: %s", exc)
                else:
                    raise
            finally:
                try:
                    app._sync_core_runtime_refs()
                except Exception as exc:
                    _log.warning("Could not sync core runtime refs: %s", exc)

            # Decide next step in the UI thread.
            if app.mode == "client" and result.operator_id is None:
                # First-run client — show enrollment dialog instead of going to main.
                Clock.schedule_once(lambda dt: self._show_enroll_dialog())
            else:
                Clock.schedule_once(lambda dt: self._on_success())

        except Exception as exc:
            _log.warning("Login failed: %s", exc)
            try:
                app = App.get_running_app()
                if app and getattr(app, "core_session", None) is not None:
                    app.core_session.close()
                    app._sync_core_runtime_refs()
            except Exception as close_exc:
                _log.debug("Could not close core session after login failure: %s", close_exc)
            err_msg = str(exc)  # BUG-016: capture before exc is deleted by PEP 3110
            Clock.schedule_once(lambda dt: self._on_error(err_msg))

    def _start_reticulum_on_ui_thread(self) -> None:
        app = App.get_running_app()
        done = threading.Event()
        result: dict[str, Exception] = {}

        def _run(_dt) -> None:
            try:
                app.core_session.start_reticulum()
            except Exception as exc:
                result["error"] = exc
            finally:
                done.set()

        Clock.schedule_once(_run, 0)
        done.wait()
        if "error" in result:
            raise result["error"]

    # ------------------------------------------------------------------
    # UI thread callbacks
    # ------------------------------------------------------------------

    def _on_success(self) -> None:
        app = App.get_running_app()
        if app and hasattr(app, "apply_stored_theme"):
            app.apply_stored_theme()
        self.ids.unlock_button.disabled = False
        self.ids.error_label.text = ""
        self.manager.current = "main"

    def _on_error(self, message: str) -> None:
        self.ids.unlock_button.disabled = False
        self.ids.error_label.text = f"Unlock failed: {message}"

    # ------------------------------------------------------------------
    # Enrollment dialog (client first-run)
    # ------------------------------------------------------------------

    def _show_enroll_dialog(self) -> None:
        """Show a modal enrollment dialog for a client that is not yet enrolled."""
        self.ids.unlock_button.disabled = False
        self.ids.error_label.text = ""

        modal = ModalView(size_hint=(0.55, None), height=dp(360), auto_dismiss=False)
        content = MDBoxLayout(orientation="vertical", padding=dp(20), spacing=dp(12))

        content.add_widget(MDLabel(
            text="Enroll This Client",
            bold=True,
            size_hint_y=None,
            height=dp(32),
            halign="center",
        ))
        content.add_widget(MDLabel(
            text="Paste the TOKEN:SERVER_HASH string from the server's Enrollment screen.",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(36),
            halign="center",
        ))

        # TOKEN field + PASTE button on the same row
        token_row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(56), spacing=dp(8)
        )
        token_field = MDTextField(mode="outlined")
        token_field.add_widget(MDTextFieldHintText(text="TOKEN:SERVER_HASH"))
        paste_btn = MDButton(
            MDButtonText(text="PASTE"),
            style="tonal",
            size_hint_x=None,
            width=dp(80),
        )
        paste_btn.bind(on_release=lambda _: self._paste_token(token_field))
        token_row.add_widget(token_field)
        token_row.add_widget(paste_btn)
        content.add_widget(token_row)

        callsign_field = MDTextField(mode="outlined", size_hint_y=None, height=dp(56))
        callsign_field.add_widget(MDTextFieldHintText(text="Callsign (e.g. ALPHA-1)"))
        content.add_widget(callsign_field)

        status_label = MDLabel(
            text="",
            theme_text_color="Error",
            size_hint_y=None,
            height=dp(24),
            halign="center",
        )
        content.add_widget(status_label)

        btn_row = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8)
        )
        enroll_btn = MDButton(MDButtonText(text="ENROLL"), style="filled")
        enroll_btn.bind(on_release=lambda _: self._do_enroll(
            modal, token_field, callsign_field, status_label, enroll_btn
        ))
        btn_row.add_widget(enroll_btn)
        content.add_widget(btn_row)

        modal.add_widget(content)
        modal.open()

    def _paste_token(self, token_field: MDTextField) -> None:
        from kivy.core.clipboard import Clipboard
        text = Clipboard.paste()
        if text:
            token_field.text = text.strip()

    def _do_enroll(
        self,
        modal: ModalView,
        token_field: MDTextField,
        callsign_field: MDTextField,
        status_label: MDLabel,
        enroll_btn: MDButton,
    ) -> None:
        combined = token_field.text.strip()
        callsign = callsign_field.text.strip()

        if not combined:
            status_label.text = "TOKEN:SERVER_HASH is required."
            return
        if not callsign:
            status_label.text = "Callsign is required."
            return

        status_label.theme_text_color = "Secondary"
        status_label.text = "Enrolling\u2026"
        enroll_btn.disabled = True

        app = App.get_running_app()
        core_session = getattr(app, "core_session", None)
        if core_session is None:
            status_label.text = "Internal error: core session not initialised."
            enroll_btn.disabled = False
            return

        def _enroll_worker() -> None:
            try:
                operator_id = core_session.enroll_client(combined, callsign)
            except Exception as exc:
                _on_error(str(exc))
                return
            _on_success(operator_id)

        def _on_success(operator_id: int) -> None:
            def _ui(dt: float) -> None:
                modal.dismiss()
                # Start the heartbeat loop now that we are enrolled.
                _app = App.get_running_app()
                if _app:
                    try:
                        _app._sync_core_runtime_refs()
                    except Exception as exc:
                        _log.warning("Could not sync core runtime refs after enrollment: %s", exc)
                    if hasattr(_app, "apply_stored_theme"):
                        _app.apply_stored_theme()
                self.manager.current = "main"
            Clock.schedule_once(_ui)

        def _on_error(message: str) -> None:
            def _ui(dt: float) -> None:
                status_label.theme_text_color = "Error"
                status_label.text = message
                enroll_btn.disabled = False
            Clock.schedule_once(_ui)

        threading.Thread(
            target=_enroll_worker,
            daemon=True,
            name="talon-core-enroll",
        ).start()

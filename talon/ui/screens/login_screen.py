"""
Login screen — passphrase entry → Argon2id KDF → unlock SQLCipher DB.

Flow:
  1. User types passphrase.
  2. Salt is loaded from disk (or created on first run).
  3. Argon2id derives the DB key (run in a background thread — ~1-2 s).
  4. DB is opened; a test read verifies the key is correct.
  5. Schema migrations are applied (idempotent).
  6. On server: the encrypted audit hook is installed; ServerNetHandler is started.
  7a. On server: app transitions to "main".
  7b. On client, already enrolled: ClientSyncManager is started; app transitions to "main".
  7c. On client, first run (not enrolled): enrollment dialog is shown.
       - User pastes TOKEN:SERVER_HASH + callsign → Enroll button.
       - On success: ClientSyncManager starts, app transitions to "main".
       - On failure: error shown in dialog, dialog stays open.
  Wrong passphrase shows an error and stays on the login screen.
"""
import threading
import typing

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

        # Initialise Reticulum here on the main thread — RNS.Reticulum() installs
        # signal handlers (SIGINT etc.) which Python only permits on the main thread.
        # Safe to call on re-login; RNS treats it as a singleton internally.
        app = App.get_running_app()
        try:
            from talon.config import get_rns_config_dir
            from talon.network.node import init_reticulum
            init_reticulum(get_rns_config_dir(app.cfg), mode=app.mode)
        except Exception as exc:
            _log.warning("Reticulum init warning: %s", exc)

        threading.Thread(
            target=self._do_login, args=(passphrase,), daemon=True
        ).start()

    # ------------------------------------------------------------------
    # Background thread
    # ------------------------------------------------------------------

    def _do_login(self, passphrase: str) -> None:
        conn = None
        try:
            app = App.get_running_app()

            from talon.config import get_db_path, get_salt_path
            from talon.crypto.keystore import derive_key, load_or_create_salt
            from talon.db.connection import open_db
            from talon.db.migrations import apply_migrations

            cfg = app.cfg
            salt = load_or_create_salt(get_salt_path(cfg))
            key = derive_key(passphrase, salt)

            # Derive a separate audit key with domain separation so that a
            # compromised DB key does not also expose the encrypted audit log.
            audit_key: typing.Optional[bytes] = None
            if app.mode == "server":
                audit_key = derive_key(passphrase + ":audit", salt)

            # BUG-008: best-effort passphrase clear — reduce window it lingers in memory.
            passphrase = "\x00" * len(passphrase)  # noqa: SIM909 (intentional zeroing)
            del passphrase

            # BUG-004: guard against a silent None return from derive_key.
            if key is None:
                raise ValueError("DB key derivation returned None — cannot proceed.")

            db_path = get_db_path(cfg)
            conn = open_db(db_path, key)

            # Verify the key is correct — will raise on an existing DB with a
            # wrong key, because SQLCipher decryption will produce garbage.
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()

            apply_migrations(conn)

            if app.mode == "server":
                from talon.server.audit import install_hook
                install_hook(conn, audit_key)  # type: ignore[arg-type]

            app.conn = conn
            app.db_key = key

            from talon.operators import resolve_local_operator_id

            operator_id = resolve_local_operator_id(
                conn,
                mode=app.mode,
                allow_server_sentinel=(app.mode == "server"),
            )

            # Stop any stale engine from a previous login (defensive).
            if app.sync_engine is not None:
                app.sync_engine.stop()

            from talon.network.sync import SyncEngine

            def _on_lease_expired_cb() -> None:
                def _lock(dt: float) -> None:
                    _app = App.get_running_app()
                    if _app and _app.root:
                        _app.root.current = "lock"
                Clock.schedule_once(_lock)

            def _on_lease_renewed_cb() -> None:
                def _unlock(dt: float) -> None:
                    _app = App.get_running_app()
                    if _app and _app.root:
                        try:
                            lock_screen = _app.root.get_screen("lock")
                            lock_screen.on_lease_renewed()
                        except Exception as _exc:
                            _log.warning("Could not notify lock screen of renewal: %s", _exc)
                Clock.schedule_once(_unlock)

            app.operator_id = operator_id
            app.sync_engine = SyncEngine(
                conn=conn,
                operator_id=operator_id,
                on_lease_expired=_on_lease_expired_cb,
                on_lease_renewed=_on_lease_renewed_cb,
            )
            app.sync_engine.start()

            # ----------------------------------------------------------
            # Server: start net_handler so clients can connect.
            # ----------------------------------------------------------
            if app.mode == "server":
                if app.net_handler is not None:
                    try:
                        app.net_handler.stop()
                    except Exception:
                        pass
                from talon.server.net_handler import ServerNetHandler
                handler = ServerNetHandler(conn, cfg, key)
                try:
                    handler.start()
                except Exception as exc:
                    _log.warning("ServerNetHandler failed to start: %s", exc)
                app.net_handler = handler

            # ----------------------------------------------------------
            # Client: create ClientSyncManager; start immediately if enrolled.
            # ----------------------------------------------------------
            if app.mode == "client":
                if app.client_sync is not None:
                    try:
                        app.client_sync.stop()
                    except Exception:
                        pass
                from talon.network.client_sync import ClientSyncManager
                mgr = ClientSyncManager(conn, cfg, key)
                app.client_sync = mgr
                mgr.start()  # no-op if not enrolled yet

            conn = None  # ownership transferred to app; do not close in finally

            # Decide next step in the UI thread.
            if app.mode == "client" and operator_id is None:
                # First-run client — show enrollment dialog instead of going to main.
                Clock.schedule_once(lambda dt: self._show_enroll_dialog())
            else:
                Clock.schedule_once(lambda dt: self._on_success())

        except Exception as exc:
            _log.warning("Login failed: %s", exc)
            err_msg = str(exc)  # BUG-016: capture before exc is deleted by PEP 3110
            Clock.schedule_once(lambda dt: self._on_error(err_msg))
        finally:
            # BUG-003: close the connection if ownership was not transferred (error path).
            if conn is not None:
                try:
                    from talon.db.connection import close_db
                    close_db(conn)
                except Exception:
                    pass

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
        if app.client_sync is None:
            status_label.text = "Internal error: client sync manager not initialised."
            enroll_btn.disabled = False
            return

        def _on_success(operator_id: int) -> None:
            def _ui(dt: float) -> None:
                modal.dismiss()
                # Start the heartbeat loop now that we are enrolled.
                _app = App.get_running_app()
                if _app:
                    _app.operator_id = operator_id
                    if _app.sync_engine:
                        try:
                            _app.sync_engine.set_operator_id(operator_id)
                        except Exception as exc:
                            _log.warning("Could not update lease monitor operator_id: %s", exc)
                    if _app.client_sync:
                        _app.client_sync.start_after_enroll()
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

        app.client_sync.enroll(combined, callsign, _on_success, _on_error)

# talon/ui/server/screens/reauth.py
# Re-authentication approval panel.
#
# When an operator's 24hr lease expires, they see the lock screen and
# send a re-auth request to the server. This panel shows those pending
# requests so the server operator can approve or deny them.
#
# Layout:
#   ┌─────────────────────────────────┐
#   │  RE-AUTHENTICATION REQUESTS     │
#   ├─────────────────────────────────┤
#   │  WOLF-1    requested 14:22      │
#   │  lease expired 2 hours ago      │
#   │  [APPROVE]           [DENY]     │
#   ├─────────────────────────────────┤
#   │  (empty state if no requests)   │
#   └─────────────────────────────────┘
#
# Approving issues a new 24hr lease token and pushes it to the client.
# Denying leaves the client locked — they must contact the server operator
# in person if they believe this is an error.

import time

from kivy.clock import Clock
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.scrollview import MDScrollView


class ReauthPanel(MDBoxLayout):
    """Pending re-authentication request panel."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._talon = None
        self._refresh_event = None
        self._dialog = None

    def refresh(self, talon_server):
        self._talon = talon_server
        self.clear_widgets()
        self._build(talon_server)

        # Poll every 15 seconds — re-auth requests arrive asynchronously
        if self._refresh_event:
            self._refresh_event.cancel()
        self._refresh_event = Clock.schedule_interval(lambda dt: self.refresh(self._talon), 15)

    def on_leave(self):
        if self._refresh_event:
            self._refresh_event.cancel()

    def _build(self, server):
        from kivymd.uix.divider import MDDivider

        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="52dp",
            padding=["16dp", "8dp"],
            md_bg_color="#0f1520",
        )
        header.add_widget(
            MDLabel(
                text="RE-AUTHENTICATION REQUESTS",
                font_style="Button",
                bold=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )
        self.add_widget(header)
        self.add_widget(MDDivider(color="#1e2d3d"))

        # Gather pending requests — clients in SOFT_LOCKED state who have
        # sent a reauth request.
        pending = self._get_pending_requests(server)

        scroll = MDScrollView(size_hint_y=1)
        content = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing="1dp",
            padding=["0dp", "0dp"],
        )
        content.bind(minimum_height=content.setter("height"))

        if not pending:
            content.add_widget(
                MDLabel(
                    text="No pending re-authentication requests.",
                    halign="center",
                    font_style="Body1",
                    theme_text_color="Custom",
                    text_color="#3d4f63",
                    size_hint_y=None,
                    height="80dp",
                    padding=["16dp", "16dp"],
                )
            )
        else:
            for req in pending:
                content.add_widget(self._request_card(req))

        scroll.add_widget(content)
        self.add_widget(scroll)

    def _get_pending_requests(self, server) -> list:
        """Return list of pending re-auth request dicts from the server.

        A pending request is a client that is soft-locked and has sent
        a request (stored in the server auth module's pending queue).
        """
        if not server:
            return []

        pending = []

        # Check clients marked SOFT_LOCKED in the registry
        clients = server.client_registry.clients if server else {}
        for client_id, client in clients.items():
            if client.get("status") == "SOFT_LOCKED":
                pending.append(
                    {
                        "client_id": client_id,
                        "callsign": client.get("callsign", "?"),
                        "requested_at": client.get("locked_at"),
                        "lease_expired_at": client.get("lease_expires_at"),
                    }
                )

        return pending

    def _request_card(self, req: dict) -> MDBoxLayout:
        """Widget for a single pending re-auth request."""
        from kivymd.uix.divider import MDDivider

        callsign = req.get("callsign", "?")
        client_id = req.get("client_id", "")
        requested_at = req.get("requested_at")
        expired_at = req.get("lease_expired_at")

        req_ts = time.strftime("%H:%M", time.localtime(requested_at)) if requested_at else "—"
        exp_ts = time.strftime("%H:%M %Y-%m-%d", time.localtime(expired_at)) if expired_at else "—"

        # How long ago did the lease expire?
        if expired_at:
            ago_secs = time.time() - expired_at
            ago_hours = ago_secs / 3600
            if ago_hours < 1:
                ago_str = f"{int(ago_secs / 60)} minutes ago"
            else:
                ago_str = f"{ago_hours:.1f} hours ago"
        else:
            ago_str = "unknown"

        card = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=["16dp", "12dp"],
            spacing="8dp",
            md_bg_color="#151d2b",
        )
        card.bind(minimum_height=card.setter("height"))

        # Callsign + request time
        top_row = MDBoxLayout(
            size_hint_y=None,
            height="28dp",
            spacing="8dp",
        )
        top_row.add_widget(
            MDLabel(
                text=f"[b]{callsign}[/b]",
                markup=True,
                font_style="Body1",
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )
        top_row.add_widget(
            MDLabel(
                text=f"requested {req_ts}",
                font_style="Caption",
                halign="right",
                theme_text_color="Custom",
                text_color="#8a9bb0",
            )
        )
        card.add_widget(top_row)

        # Expiry info
        card.add_widget(
            MDLabel(
                text=f"Lease expired {ago_str}  ({exp_ts})",
                font_style="Caption",
                theme_text_color="Custom",
                text_color="#f5a623",
                size_hint_y=None,
                height="20dp",
            )
        )

        card.add_widget(MDDivider(color="#1e2d3d"))

        # Action buttons
        btn_row = MDBoxLayout(
            size_hint_y=None,
            height="44dp",
            spacing="8dp",
            padding=["0dp", "4dp"],
        )
        btn_row.add_widget(
            MDRaisedButton(
                text="APPROVE",
                md_bg_color="#00e5a0",
                theme_text_color="Custom",
                text_color="#0a0e14",
                on_release=lambda x, cid=client_id, cs=callsign: self._approve_reauth(cid, cs),
            )
        )
        btn_row.add_widget(
            MDRaisedButton(
                text="DENY",
                md_bg_color="#ff3b3b",
                theme_text_color="Custom",
                text_color="#ffffff",
                on_release=lambda x, cid=client_id, cs=callsign: self._deny_reauth(cid, cs),
            )
        )
        card.add_widget(btn_row)

        return card

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _approve_reauth(self, client_id: str, callsign: str):
        """Issue a new 24hr lease and push it to the client."""
        if not self._talon:
            return

        try:
            from talon.server.auth import approve_reauth

            result = approve_reauth(client_id, self._talon.server_secret)

            if result.get("success"):
                # Hex-encode bytes for JSON transport
                lease = result["lease"]
                if isinstance(lease.get("token"), bytes):
                    lease["token"] = lease["token"].hex()
                sig = result["signature"]
                if isinstance(sig, bytes):
                    sig = sig.hex()

                # Push the new lease to the client over RNS
                lease_msg = {
                    "type": "lease_renewal",
                    "lease": lease,
                    "signature": sig,
                    "reauth": True,
                }
                if self._talon.link_manager:
                    self._talon.link_manager.send_to_client(client_id, lease_msg)

                # Update client status back to ONLINE
                self._talon.client_registry.update_heartbeat(client_id)

                from talon.server.audit import log_event

                log_event("REAUTH_APPROVED", "Server", target=callsign)
            else:
                self._show_result(
                    f"Approval failed: {result.get('error', 'unknown')}",
                    "#ff3b3b",
                )
                return

        except Exception as e:
            self._show_result(f"Approval failed: {e}", "#ff3b3b")
            return

        self._show_result(f"{callsign} — re-authentication approved.", "#00e5a0")
        Clock.schedule_once(lambda dt: self.refresh(self._talon), 1.5)

    def _deny_reauth(self, client_id: str, callsign: str):
        """Deny the re-auth request — client remains locked."""
        if self._dialog:
            self._dialog.dismiss()

        self._dialog = MDDialog(
            title="Deny Re-Authentication",
            text=(f"Deny re-auth for [b]{callsign}[/b]?\n\nThey will remain locked until approved or revoked."),
            buttons=[
                MDFlatButton(
                    text="CANCEL",
                    theme_text_color="Custom",
                    text_color="#8a9bb0",
                    on_release=lambda x: self._dialog.dismiss(),
                ),
                MDRaisedButton(
                    text="DENY",
                    md_bg_color="#ff3b3b",
                    theme_text_color="Custom",
                    text_color="#ffffff",
                    on_release=lambda x: self._do_deny(client_id, callsign),
                ),
            ],
        )
        self._dialog.open()

    def _do_deny(self, client_id: str, callsign: str):
        self._dialog.dismiss()
        from talon.server.audit import log_event

        log_event("REAUTH_DENIED", "Server", target=callsign)
        # Update registry to keep SOFT_LOCKED but clear the pending request
        if self._talon:
            client = self._talon.client_registry.clients.get(client_id, {})
            client["reauth_requested"] = False
        self.refresh(self._talon)

    def _show_result(self, message: str, color: str):
        """Briefly show a result message at the top of the panel."""
        from kivymd.uix.snackbar import MDSnackbar

        MDSnackbar(
            MDLabel(
                text=message,
                theme_text_color="Custom",
                text_color=color,
            )
        ).open()

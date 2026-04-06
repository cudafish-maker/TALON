# talon/ui/server/screens/registry.py
# Client registry panel — the server operator's view of all enrolled clients.
#
# Layout:
#   ┌─────────────────────────────────────────────────┐
#   │  CLIENT REGISTRY                                │
#   ├─────────────────────────────────────────────────┤
#   │  ● WOLF-1   ONLINE   yggdrasil   [STALE] [REV] │
#   │  ● WOLF-2   STALE    rnode       [STALE] [REV] │
#   │  ✕ WOLF-3   REVOKED  —           [DENY LIST]   │
#   └─────────────────────────────────────────────────┘
#
# Actions per client:
#   MARK STALE  — manually mark a client as stale (e.g. radio silence)
#   REVOKE      — hard revoke: triggers group key rotation, identity burn
#
# Revocation is irreversible without in-person re-enrollment.
# A confirmation dialog is shown before any destructive action.

import time

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton
from kivymd.uix.dialog import (
    MDDialog,
    MDDialogButtonContainer,
    MDDialogHeadlineText,
    MDDialogSupportingText,
)
from kivymd.uix.label import MDLabel
from kivymd.uix.scrollview import MDScrollView

STATUS_COLORS = {
    "ONLINE": "#00e5a0",
    "STALE": "#f5a623",
    "REVOKED": "#ff3b3b",
    "SOFT_LOCKED": "#f5a623",
}


class RegistryPanel(MDBoxLayout):
    """Client registry — list all enrolled clients with action buttons."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._talon = None
        self._confirm_dialog = None

    def refresh(self, talon_server):
        self._talon = talon_server
        self.clear_widgets()
        self._build(talon_server)

    def _build(self, server):
        from kivymd.uix.divider import MDDivider

        # Header
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="52dp",
            padding=["16dp", "8dp"],
            md_bg_color="#0f1520",
        )
        header.add_widget(
            MDLabel(
                text="CLIENT REGISTRY",
                font_style="Button",
                bold=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )
        # Total count
        total = len(server.client_registry.clients) if server else 0
        header.add_widget(
            MDLabel(
                text=f"{total} enrolled",
                font_style="Caption",
                halign="right",
                theme_text_color="Custom",
                text_color="#8a9bb0",
            )
        )
        self.add_widget(header)
        self.add_widget(MDDivider(color="#1e2d3d"))

        # Column headers
        col_header = MDBoxLayout(
            size_hint_y=None,
            height="28dp",
            padding=["16dp", "4dp"],
            spacing="4dp",
            md_bg_color="#0a0e14",
        )
        for text, hint_x in [
            ("CALLSIGN", 1),
            ("STATUS", None),
            ("TRANSPORT", None),
            ("LAST SYNC", None),
            ("", None),  # Actions
        ]:
            lbl = MDLabel(
                text=text,
                font_style="Overline",
                theme_text_color="Custom",
                text_color="#3d4f63",
            )
            if hint_x is None:
                lbl.size_hint_x = None
                lbl.width = "80dp"
            col_header.add_widget(lbl)
        self.add_widget(col_header)
        self.add_widget(MDDivider(color="#1e2d3d"))

        # Client list
        scroll = MDScrollView(size_hint_y=1)
        rows = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing="1dp",
        )
        rows.bind(minimum_height=rows.setter("height"))

        clients = server.client_registry.clients if server else {}
        if not clients:
            rows.add_widget(
                MDLabel(
                    text="No clients enrolled.",
                    halign="center",
                    theme_text_color="Custom",
                    text_color="#3d4f63",
                    size_hint_y=None,
                    height="48dp",
                    padding=["16dp", "8dp"],
                )
            )
        else:
            # Sort: online first, then stale, then revoked
            priority = {"ONLINE": 0, "SOFT_LOCKED": 1, "STALE": 2, "REVOKED": 3}
            sorted_clients = sorted(clients.values(), key=lambda c: priority.get(c.get("status", ""), 9))
            for client in sorted_clients:
                rows.add_widget(self._client_row(client))

        scroll.add_widget(rows)
        self.add_widget(scroll)

    def _client_row(self, client: dict) -> MDBoxLayout:
        """One row per enrolled client."""
        status = client.get("status", "OFFLINE")
        color = STATUS_COLORS.get(status, "#3d4f63")
        callsign = client.get("callsign", "?")
        client_id = client.get("client_id", "")
        transport = client.get("transport", "—").upper()
        last_sync = client.get("last_sync")
        ts_str = time.strftime("%H:%M", time.localtime(last_sync)) if last_sync else "—"
        is_revoked = status == "REVOKED"

        row = MDBoxLayout(
            size_hint_y=None,
            height="44dp",
            padding=["16dp", "4dp"],
            spacing="4dp",
            md_bg_color="#151d2b",
        )

        # Status dot + callsign
        row.add_widget(
            MDLabel(
                text=f"[color={color}]●[/color]  [b]{callsign}[/b]",
                markup=True,
                font_style="Body2",
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )

        # Status label
        row.add_widget(
            MDLabel(
                text=status,
                font_style="Caption",
                theme_text_color="Custom",
                text_color=color,
                size_hint_x=None,
                width="80dp",
            )
        )

        # Transport
        row.add_widget(
            MDLabel(
                text=transport,
                font_style="Caption",
                theme_text_color="Custom",
                text_color="#8a9bb0",
                size_hint_x=None,
                width="80dp",
            )
        )

        # Last sync
        row.add_widget(
            MDLabel(
                text=ts_str,
                font_style="Caption",
                theme_text_color="Custom",
                text_color="#3d4f63",
                size_hint_x=None,
                width="48dp",
            )
        )

        # Action buttons (hidden if already revoked)
        if not is_revoked:
            action_row = MDBoxLayout(
                size_hint_x=None,
                width="100dp",
                spacing="4dp",
            )
            # Mark stale button
            stale_btn = MDButton(
                style="text",
                text="STALE",
                theme_text_color="Custom",
                text_color="#f5a623",
                font_size="10sp",
                size_hint_x=None,
                width="44dp",
                on_release=lambda x, cid=client_id, cs=callsign: self._confirm_mark_stale(cid, cs),
            )
            # Revoke button
            revoke_btn = MDButton(
                style="text",
                text="REVOKE",
                theme_text_color="Custom",
                text_color="#ff3b3b",
                font_size="10sp",
                size_hint_x=None,
                width="52dp",
                on_release=lambda x, cid=client_id, cs=callsign: self._confirm_revoke(cid, cs),
            )
            action_row.add_widget(stale_btn)
            action_row.add_widget(revoke_btn)
            row.add_widget(action_row)
        else:
            row.add_widget(
                MDLabel(
                    text="DENY LIST",
                    font_style="Caption",
                    theme_text_color="Custom",
                    text_color="#ff3b3b",
                    size_hint_x=None,
                    width="100dp",
                    halign="center",
                )
            )

        return row

    # ------------------------------------------------------------------
    # Confirmation dialogs — destructive actions require confirmation
    # ------------------------------------------------------------------

    def _confirm_mark_stale(self, client_id: str, callsign: str):
        """Show confirmation before marking a client stale."""
        if self._confirm_dialog:
            self._confirm_dialog.dismiss()

        self._confirm_dialog = MDDialog(
            MDDialogHeadlineText(text="Mark Client Stale"),
            MDDialogSupportingText(
                text=f"Mark [b]{callsign}[/b] as STALE?\n\nThis flags the client as "
                f"non-responsive. They can still re-connect."
            ),
            MDDialogButtonContainer(
                MDButton(
                    style="text",
                    text="CANCEL",
                    theme_text_color="Custom",
                    text_color="#8a9bb0",
                    on_release=lambda x: self._confirm_dialog.dismiss(),
                ),
                MDButton(
                    style="elevated",
                    text="MARK STALE",
                    md_bg_color="#f5a623",
                    theme_text_color="Custom",
                    text_color="#0a0e14",
                    on_release=lambda x: self._do_mark_stale(client_id),
                ),
            ),
        )
        self._confirm_dialog.open()

    def _do_mark_stale(self, client_id: str):
        self._confirm_dialog.dismiss()
        if self._talon:
            self._talon.client_registry.mark_stale(client_id)
        self.refresh(self._talon)

    def _confirm_revoke(self, client_id: str, callsign: str):
        """Show confirmation before revoking — this is irreversible."""
        if self._confirm_dialog:
            self._confirm_dialog.dismiss()

        self._confirm_dialog = MDDialog(
            MDDialogHeadlineText(text="REVOKE CLIENT"),
            MDDialogSupportingText(
                text=(
                    f"[b][color=#ff3b3b]REVOKE {callsign}?[/color][/b]\n\n"
                    f"This will:\n"
                    f"  • Add {callsign} to the deny list\n"
                    f"  • Rotate the group encryption key\n"
                    f"  • Require in-person re-enrollment to restore access\n\n"
                    f"[b]This action cannot be undone.[/b]"
                )
            ),
            MDDialogButtonContainer(
                MDButton(
                    style="text",
                    text="CANCEL",
                    theme_text_color="Custom",
                    text_color="#8a9bb0",
                    on_release=lambda x: self._confirm_dialog.dismiss(),
                ),
                MDButton(
                    style="elevated",
                    text="REVOKE",
                    md_bg_color="#ff3b3b",
                    theme_text_color="Custom",
                    text_color="#ffffff",
                    on_release=lambda x: self._do_revoke(client_id, callsign),
                ),
            ),
        )
        self._confirm_dialog.open()

    def _do_revoke(self, client_id: str, callsign: str):
        """Execute the revocation."""
        self._confirm_dialog.dismiss()

        if not self._talon:
            return

        # Revoke in the client registry
        self._talon.client_registry.revoke(client_id, reason="Revoked by server operator")

        # Rotate the group key — all remaining clients will need the new key
        from talon.crypto.group_key import rotate_group_key

        rotation_result = rotate_group_key()

        # Log the event
        from talon.server.audit import log_event

        log_event(
            "CLIENT_REVOKED",
            "Server",
            target=callsign,
            details=f"Group key rotated at {rotation_result['rotated_at']}",
        )

        self.refresh(self._talon)

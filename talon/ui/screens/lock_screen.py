"""
Lock screen — shown when the operator's lease has expired.

The operator cannot navigate elsewhere until the server re-approves their
lease via renew_lease(). The sync engine continues running in the background
so the server's re-auth message can be received.
"""
from kivymd.uix.screen import MDScreen


class LockScreen(MDScreen):
    """Soft-lock screen displayed on lease expiry."""

    def on_lease_renewed(self) -> None:
        """Called by the sync engine when a new lease arrives from the server."""
        self.manager.current = "main"

# talon/net/transport.py
# Transport detection, priority, and fallback.
#
# T.A.L.O.N. can communicate over multiple network types simultaneously.
# This module detects which transports are available and manages
# automatic fallback when a transport goes down.
#
# Priority order (highest bandwidth to lowest):
# 1. Yggdrasil — encrypted mesh network over the internet
# 2. I2P — anonymous overlay network
# 3. TCP — direct internet (WARNING: exposes IP)
# 4. RNode — LoRa radio (very low bandwidth, no internet needed)
#
# The system always uses the best available transport. If Yggdrasil
# drops, it falls back to I2P, then TCP, then LoRa. When a higher
# priority transport comes back, it switches automatically.

from talon.constants import TransportType


class TransportManager:
    """Manages available transports and selects the best one.

    Monitors all configured network interfaces and tracks which
    ones are currently reachable. Provides the rest of the app
    with the current best transport for making decisions about
    what data to send (e.g., skip large files over LoRa).
    """

    # Transport priority — lower number = higher priority
    PRIORITY = {
        TransportType.YGGDRASIL: 1,
        TransportType.I2P: 2,
        TransportType.TCP: 3,
        TransportType.RNODE: 4,
    }

    def __init__(self):
        # Tracks which transports are currently available.
        # Key = TransportType, Value = True/False
        self._available = {
            TransportType.YGGDRASIL: False,
            TransportType.I2P: False,
            TransportType.TCP: False,
            TransportType.RNODE: False,
        }
        # The transport currently being used for communication
        self._active_transport = None
        # Whether we have manually pinned a specific transport
        self._pinned = None

    def set_available(self, transport: TransportType, available: bool) -> None:
        """Mark a transport as available or unavailable.

        Called by the interface monitors when connectivity changes.

        Args:
            transport: Which transport changed status.
            available: True if it's now reachable, False if it dropped.
        """
        self._available[transport] = available
        # Re-evaluate which transport to use
        if self._pinned is None:
            self._active_transport = self._select_best()

    def get_active(self) -> TransportType:
        """Get the currently active transport.

        Returns:
            The TransportType currently being used, or None if
            no transports are available.
        """
        if self._pinned and self._available.get(self._pinned):
            return self._pinned
        return self._active_transport

    def pin_transport(self, transport: TransportType) -> None:
        """Manually pin a specific transport.

        The operator can force the use of a specific transport
        (e.g., LoRa only for radio silence). The pinned transport
        is used as long as it's available.

        Args:
            transport: The transport to force, or None to unpin.
        """
        self._pinned = transport

    def is_broadband(self) -> bool:
        """Check if the current transport is high-bandwidth.

        Used to decide whether to sync large items (documents,
        map tiles) or defer them.

        Returns:
            True for Yggdrasil, I2P, or TCP.
            False for RNode (LoRa).
        """
        active = self.get_active()
        return active in (
            TransportType.YGGDRASIL,
            TransportType.I2P,
            TransportType.TCP,
        )

    def get_all_available(self) -> list:
        """Get a list of all currently available transports.

        Used for the status bar display.

        Returns:
            List of TransportType values that are currently available.
        """
        return [t for t, avail in self._available.items() if avail]

    def _select_best(self) -> TransportType:
        """Pick the highest-priority available transport.

        Returns:
            The best available TransportType, or None if nothing
            is available.
        """
        available = self.get_all_available()
        if not available:
            return None
        # Sort by priority and return the best
        return min(available, key=lambda t: self.PRIORITY.get(t, 99))

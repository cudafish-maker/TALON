# talon/net/heartbeat.py
# Heartbeat system for T.A.L.O.N.
#
# The heartbeat is a periodic "I'm alive" signal between clients
# and the server. It serves multiple purposes:
#
# 1. CONNECTIVITY — confirms the link is still working
# 2. POSITION — piggybacks the client's GPS coordinates
# 3. LEASE — the server refreshes the client's lease on each heartbeat
# 4. STATUS — the server reports any pending alerts or sync needs
# 5. MONITORING — the server tracks which clients are active/stale
#
# Intervals:
# - Broadband (Yggdrasil/I2P/TCP): every 60 seconds
# - LoRa (RNode): every 120 seconds (2 minutes)
#
# If the server misses 3 consecutive heartbeats from a client,
# that client is marked as STALE.

import time
import threading


class HeartbeatSender:
    """Sends periodic heartbeats from a client to the server.

    Runs in a background thread so it doesn't block the UI.
    Automatically adjusts the interval based on the current
    transport type (faster over broadband, slower over LoRa).
    """

    def __init__(self, broadband_interval: int = 60, lora_interval: int = 120):
        """
        Args:
            broadband_interval: Seconds between heartbeats on fast connections.
            lora_interval: Seconds between heartbeats on LoRa radio.
        """
        self.broadband_interval = broadband_interval
        self.lora_interval = lora_interval
        self._running = False
        self._thread = None
        # Callback function that sends the actual heartbeat packet.
        # Set this to the function that transmits over Reticulum.
        self.send_callback = None
        # Function that returns the current position as (lat, lon) or None.
        self.position_callback = None
        # Function that returns True if current transport is broadband.
        self.is_broadband_callback = None

    def start(self) -> None:
        """Start sending heartbeats in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop sending heartbeats."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _heartbeat_loop(self) -> None:
        """Main heartbeat loop — runs in background thread."""
        while self._running:
            # Build the heartbeat payload
            payload = {
                "timestamp": time.time(),
                "position": None,
                "transport": None,
            }

            # Include GPS position if available
            if self.position_callback:
                payload["position"] = self.position_callback()

            # Send the heartbeat
            if self.send_callback:
                self.send_callback(payload)

            # Wait for the appropriate interval
            if self.is_broadband_callback and self.is_broadband_callback():
                time.sleep(self.broadband_interval)
            else:
                time.sleep(self.lora_interval)


class HeartbeatMonitor:
    """Monitors incoming heartbeats on the server.

    Tracks when each client last sent a heartbeat and marks
    clients as STALE if they miss too many.
    """

    def __init__(self, missed_threshold: int = 3):
        """
        Args:
            missed_threshold: How many missed heartbeats before
                              marking a client as STALE.
        """
        self.missed_threshold = missed_threshold
        # Key = client callsign, Value = dict with last heartbeat info
        self._clients = {}
        # Callback when a client's status changes
        self.status_change_callback = None

    def record_heartbeat(self, callsign: str, payload: dict) -> None:
        """Record a heartbeat received from a client.

        Args:
            callsign: The client's callsign (e.g., "WOLF-1").
            payload: The heartbeat data (timestamp, position, etc.).
        """
        self._clients[callsign] = {
            "last_heartbeat": time.time(),
            "position": payload.get("position"),
            "transport": payload.get("transport"),
            "missed_count": 0,
        }

    def check_stale(self, broadband_interval: int = 60, lora_interval: int = 120) -> list:
        """Check for clients that have missed heartbeats.

        Call this periodically (e.g., every 30 seconds) to detect
        clients that have gone silent.

        Args:
            broadband_interval: Expected heartbeat interval for broadband.
            lora_interval: Expected heartbeat interval for LoRa.

        Returns:
            List of callsigns that are now STALE.
        """
        now = time.time()
        stale = []
        # Use the longer interval (LoRa) as the baseline — we don't
        # want to falsely mark a LoRa client as stale.
        max_silence = lora_interval * self.missed_threshold

        for callsign, info in self._clients.items():
            elapsed = now - info["last_heartbeat"]
            if elapsed > max_silence:
                stale.append(callsign)
                if self.status_change_callback:
                    self.status_change_callback(callsign, "STALE")

        return stale

    def get_client_info(self, callsign: str) -> dict:
        """Get the latest heartbeat info for a client.

        Args:
            callsign: The client's callsign.

        Returns:
            Dictionary with last_heartbeat, position, transport,
            or None if the client has never sent a heartbeat.
        """
        return self._clients.get(callsign)

# talon/client/notifications.py
# Client-side notification handler.
#
# Receives notifications from the server and decides how to alert
# the operator based on their settings.
#
# IMPORTANT — AUDIO ALERTS ARE OPT-IN:
# Audio is NEVER played automatically. The operator must explicitly
# enable audio alerts in their settings. This is a safety requirement:
# unexpected audio could compromise an operator's position in the field.
#
# Notification display options (all controlled by client settings):
#   - Visual banner (always shown for PRIORITY and above)
#   - Screen flash (for FLASH and FLASH_OVERRIDE, if enabled)
#   - Audio tone (ONLY if the operator has opted in)
#   - Lock screen notification (ONLY if enabled in settings)

import time


class NotificationHandler:
    """Processes incoming notifications from the server.

    Attributes:
        settings: The operator's notification preferences.
        pending: List of unread notifications.
        on_display: Callback to show a notification in the UI.
    """

    def __init__(self, settings: dict, on_display=None):
        # Settings example:
        # {
        #     "audio_enabled": False,    # DEFAULT: OFF (opt-in only)
        #     "audio_threshold": "FLASH",
        #     "lock_screen": False,       # DEFAULT: OFF
        #     "visual_threshold": "ROUTINE",
        # }
        self.settings = settings
        self.pending = []
        self.on_display = on_display

    def handle(self, notification: dict):
        """Process an incoming notification.

        Args:
            notification: Notification dict from the server containing
                          event type, importance, title, body, etc.
        """
        self.pending.append(notification)

        importance = notification.get("importance", "ROUTINE")

        # Always show visual notification if above threshold
        if self._meets_threshold(importance,
                                 self.settings.get("visual_threshold", "ROUTINE")):
            if self.on_display:
                self.on_display(notification)

        # Audio alert — ONLY if the operator has opted in
        if self.settings.get("audio_enabled", False):
            audio_threshold = self.settings.get("audio_threshold", "FLASH")
            if self._meets_threshold(importance, audio_threshold):
                self._play_audio(importance)

    def get_unread(self) -> list:
        """Get all unread notifications."""
        return list(self.pending)

    def mark_read(self, index: int = None):
        """Mark notification(s) as read.

        Args:
            index: If provided, mark only that notification. Otherwise mark all.
        """
        if index is not None and 0 <= index < len(self.pending):
            self.pending.pop(index)
        elif index is None:
            self.pending.clear()

    def _meets_threshold(self, importance: str, threshold: str) -> bool:
        """Check if an importance level meets or exceeds a threshold.

        Importance levels in order:
            ROUTINE < PRIORITY < IMMEDIATE < FLASH < FLASH_OVERRIDE
        """
        levels = ["ROUTINE", "PRIORITY", "IMMEDIATE", "FLASH", "FLASH_OVERRIDE"]
        try:
            return levels.index(importance) >= levels.index(threshold)
        except ValueError:
            # Unknown level — default to showing it
            return True

    def _play_audio(self, importance: str):
        """Play an audio alert tone.

        This method is ONLY called when audio_enabled is True.
        The actual audio playback will be implemented in the UI layer.

        Args:
            importance: Used to select the tone (higher = more urgent).
        """
        # Placeholder — Kivy audio playback will go here
        pass

"""Core persistence for the audio-alert opt-in setting."""
from __future__ import annotations

from talon_core.utils.logging import get_logger

_log = get_logger("audio_alerts")
_META_KEY = "audio_alerts_enabled"


def is_audio_enabled(conn) -> bool:
    """Return True iff the operator has opted in to audio alerts."""
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (_META_KEY,),
        ).fetchone()
        return row is not None and row[0] == "1"
    except Exception as exc:
        _log.debug("Could not read audio setting: %s", exc)
        return False


def set_audio_enabled(conn, enabled: bool) -> None:
    """Persist the audio alert opt-in choice to the DB meta table."""
    value = "1" if enabled else "0"
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        (_META_KEY, value),
    )
    conn.commit()
    _log.info("Audio alerts %s", "enabled" if enabled else "disabled")

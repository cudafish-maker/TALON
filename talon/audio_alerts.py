"""
Audio alert management.

HARD REQUIREMENT: audio alerts for FLASH/FLASH_OVERRIDE SITREPs are
OPT-IN ONLY.  Never call play_alert() without checking is_audio_enabled()
first.  See CLAUDE.md and talon/ui/screens/sitrep_screen.py for the full
safety contract.

The opt-in setting is stored in the encrypted DB meta table under the key
'audio_alerts_enabled'.  Default: disabled (0 / absent).

Audio playback uses Kivy's SoundLoader.  The alert WAV is generated once at
runtime from stdlib (wave + struct + math) and cached in the system temp
directory — no bundled audio files required.  All audio failures are logged
at DEBUG level and silently swallowed so a missing audio backend never
disrupts operations.
"""
import math
import pathlib
import struct
import tempfile
import typing
import wave

from talon.utils.logging import get_logger

_log = get_logger("audio_alerts")

_META_KEY = "audio_alerts_enabled"

# Module-level path cache so the WAV is generated at most once per process.
_ALERT_SOUND_PATH: typing.Optional[pathlib.Path] = None


# ---------------------------------------------------------------------------
# Setting persistence
# ---------------------------------------------------------------------------

def is_audio_enabled(conn) -> bool:
    """Return True iff the operator has opted in to audio alerts.

    Reads the 'audio_alerts_enabled' row from the DB meta table.
    Returns False (safe default) on any DB error or if the row is absent.
    """
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (_META_KEY,)
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


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

def play_alert() -> None:
    """Play the FLASH alert tone.

    Generates and caches the WAV on first call.  Silently does nothing if
    the Kivy audio backend is unavailable — never raises.
    """
    sound_path = _get_or_create_alert_sound()
    if sound_path is None:
        return
    try:
        from kivy.core.audio import SoundLoader  # noqa: PLC0415
        sound = SoundLoader.load(str(sound_path))
        if sound is not None:
            sound.play()
        else:
            _log.debug("SoundLoader returned None — audio backend unavailable")
    except Exception as exc:
        _log.debug("Audio playback failed: %s", exc)


def _get_or_create_alert_sound() -> typing.Optional[pathlib.Path]:
    """Return the cached WAV path, generating it if not yet created."""
    global _ALERT_SOUND_PATH
    if _ALERT_SOUND_PATH is not None and _ALERT_SOUND_PATH.exists():
        return _ALERT_SOUND_PATH
    try:
        path = pathlib.Path(tempfile.gettempdir()) / "talon_flash_alert.wav"
        _generate_alert_wav(path)
        _ALERT_SOUND_PATH = path
        _log.debug("Alert sound generated: %s", path)
        return path
    except Exception as exc:
        _log.warning("Could not generate alert sound: %s", exc)
        return None


def _generate_alert_wav(path: pathlib.Path) -> None:
    """Generate a two-burst 880 Hz (A5) alert tone as a 16-bit mono PCM WAV.

    A two-burst pattern (0.25 s on / 0.05 s gap / 0.25 s on) is distinctive
    and cuts through ambient noise.  10 ms linear fade-in/fade-out envelopes
    on each burst prevent audible clicks at the boundaries.

    Uses only stdlib — no external audio dependencies.
    """
    sample_rate = 22050
    frequency = 880      # Hz — A5, penetrating and distinct
    burst_s = 0.25       # seconds per tone burst
    gap_s = 0.05         # silent gap between bursts
    fade_s = 0.01        # 10 ms fade in / fade out

    def _tone_burst(duration: float) -> list[bytes]:
        n_frames = int(sample_rate * duration)
        frames = []
        for i in range(n_frames):
            t = i / sample_rate
            envelope = min(1.0, t / fade_s, (duration - t) / fade_s)
            value = int(32767 * envelope * math.sin(2 * math.pi * frequency * t))
            value = max(-32768, min(32767, value))
            frames.append(struct.pack("<h", value))
        return frames

    def _silence(duration: float) -> list[bytes]:
        return [struct.pack("<h", 0)] * int(sample_rate * duration)

    all_frames = (
        _tone_burst(burst_s)
        + _silence(gap_s)
        + _tone_burst(burst_s)
    )

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)   # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(all_frames))

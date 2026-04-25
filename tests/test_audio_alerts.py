"""Tests for talon.audio_alerts — setting persistence and WAV generation."""
import pathlib

import pytest

from talon.audio_alerts import (
    _generate_alert_wav,
    is_audio_enabled,
    set_audio_enabled,
)


class TestAudioSetting:
    def test_default_disabled(self, tmp_db):
        """No meta row → disabled by default."""
        conn, _ = tmp_db
        assert is_audio_enabled(conn) is False

    def test_set_enabled_persists(self, tmp_db):
        conn, _ = tmp_db
        set_audio_enabled(conn, True)
        assert is_audio_enabled(conn) is True

    def test_set_disabled_persists(self, tmp_db):
        conn, _ = tmp_db
        set_audio_enabled(conn, True)
        set_audio_enabled(conn, False)
        assert is_audio_enabled(conn) is False

    def test_toggle_round_trip(self, tmp_db):
        conn, _ = tmp_db
        set_audio_enabled(conn, True)
        set_audio_enabled(conn, False)
        set_audio_enabled(conn, True)
        assert is_audio_enabled(conn) is True

    def test_upsert_does_not_duplicate(self, tmp_db):
        """Calling set_audio_enabled multiple times must not create duplicate rows."""
        conn, _ = tmp_db
        set_audio_enabled(conn, True)
        set_audio_enabled(conn, False)
        rows = conn.execute(
            "SELECT count(*) FROM meta WHERE key = 'audio_alerts_enabled'"
        ).fetchone()
        assert rows[0] == 1

    def test_no_conn_returns_false(self):
        """Graceful handling when conn is missing (pre-login guard)."""

        class _BadConn:
            def execute(self, *a, **kw):
                raise RuntimeError("no connection")

        assert is_audio_enabled(_BadConn()) is False


class TestWavGeneration:
    def test_generates_valid_wav(self, tmp_path):
        import wave
        out = tmp_path / "alert.wav"
        _generate_alert_wav(out)
        assert out.exists()
        with wave.open(str(out)) as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 22050
            assert wf.getnframes() > 0

    def test_wav_has_expected_duration(self, tmp_path):
        """Two 0.25 s bursts + 0.05 s gap = 0.55 s total."""
        import wave
        out = tmp_path / "alert.wav"
        _generate_alert_wav(out)
        with wave.open(str(out)) as wf:
            duration = wf.getnframes() / wf.getframerate()
        assert abs(duration - 0.55) < 0.02  # within 20 ms tolerance

    def test_wav_is_silent_free_of_hard_clipping(self, tmp_path):
        """No sample should exceed 16-bit signed range."""
        import struct
        import wave
        out = tmp_path / "alert.wav"
        _generate_alert_wav(out)
        with wave.open(str(out)) as wf:
            raw = wf.readframes(wf.getnframes())
        samples = struct.unpack(f"<{len(raw) // 2}h", raw)
        assert all(-32768 <= s <= 32767 for s in samples)
        assert max(abs(s) for s in samples) > 10000  # not silent

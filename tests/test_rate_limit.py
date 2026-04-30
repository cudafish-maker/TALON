"""Tests for server-side in-memory abuse controls."""

from talon_core.server.rate_limit import RateLimiter


def test_rate_limiter_blocks_after_window_limit_and_recovers(monkeypatch):
    now = [100.0]
    events: list[dict] = []

    import talon_core.server.rate_limit as rate_limit_module

    def _audit(name: str, **kwargs) -> None:
        events.append({"name": name, **kwargs})

    monkeypatch.setattr(rate_limit_module, "audit", _audit)
    limiter = RateLimiter(
        limit=2,
        window_s=10,
        event_name="enrollment_failure",
        time_func=lambda: now[0],
    )

    assert limiter.allow("raw-secret-key", reason="bad_token") is True
    assert limiter.allow("raw-secret-key", reason="bad_token") is True
    assert limiter.allow("raw-secret-key", reason="bad_token") is False

    assert events[-1]["name"] == "rate_limit_exceeded"
    assert events[-1]["event"] == "enrollment_failure"
    assert events[-1]["reason"] == "bad_token"
    assert events[-1]["key_hash"] != "raw-secret-key"
    assert events[-1]["count"] == 3
    assert events[-1]["window_s"] == 10

    now[0] = 111.0
    assert limiter.allow("raw-secret-key", reason="bad_token") is True

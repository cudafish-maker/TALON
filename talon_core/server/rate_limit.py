"""Small in-memory rate limiters for server network abuse controls."""
from __future__ import annotations

import collections
import threading
import time
import typing

from talon_core.utils.logging import audit, get_logger

_log = get_logger("server.rate_limit")


class RateLimiter:
    """Sliding-window limiter keyed by an operator/network bucket."""

    def __init__(
        self,
        *,
        limit: int,
        window_s: int,
        event_name: str,
        time_func: typing.Callable[[], float] = time.time,
    ) -> None:
        self.limit = int(limit)
        self.window_s = int(window_s)
        self.event_name = event_name
        self._time = time_func
        self._hits: dict[str, collections.deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, *, reason: str = "") -> bool:
        now = self._time()
        cutoff = now - self.window_s
        with self._lock:
            bucket = self._hits.setdefault(key, collections.deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            bucket.append(now)
            count = len(bucket)
            allowed = count <= self.limit
        if allowed:
            return True
        _log.warning(
            "Rate limit exceeded: event=%s key=%s count=%d",
            self.event_name,
            key,
            count,
        )
        audit(
            "rate_limit_exceeded",
            event=self.event_name,
            key_hash=_hash_key(key),
            reason=reason,
            count=count,
            window_s=self.window_s,
        )
        return False


def _hash_key(key: str) -> str:
    import hashlib

    return hashlib.sha256(key.encode("utf-8")).hexdigest()

"""Desktop session logging buffer."""
from __future__ import annotations

import collections
import logging
import threading


class DesktopLogBuffer(logging.Handler):
    """Bounded in-memory logging handler for the current desktop session."""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__(level=logging.INFO)
        self._records: collections.deque[logging.LogRecord] = collections.deque(
            maxlen=capacity
        )
        self._lock = threading.Lock()
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self._records.append(record)

    def records(self) -> list[logging.LogRecord]:
        with self._lock:
            return list(self._records)

    def formatted_lines(self) -> list[str]:
        return [self.format(record) for record in self.records()]

    def warning_count(self) -> int:
        return sum(record.levelno >= logging.WARNING for record in self.records())


_BUFFER: DesktopLogBuffer | None = None


def install_desktop_log_buffer() -> DesktopLogBuffer:
    """Install and return the singleton desktop session log buffer."""
    global _BUFFER
    if _BUFFER is not None:
        return _BUFFER
    buffer = DesktopLogBuffer()
    logging.getLogger("talon").addHandler(buffer)
    _BUFFER = buffer
    return buffer


def desktop_log_buffer() -> DesktopLogBuffer:
    return install_desktop_log_buffer()

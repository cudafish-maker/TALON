"""
Structured logging wrapper. All log calls go through stdlib logging.
The audit hook (set via set_audit_hook) is called for AUDIT-level events —
used by talon/server/audit.py to persist records to the encrypted audit log.
"""
import logging
import typing

_audit_hook: typing.Optional[typing.Callable[[str, dict], None]] = None

# Library code: attach a NullHandler so callers that don't configure logging
# don't see "No handlers could be found for logger 'talon'" warnings.
# Application-level logging (format, level, StreamHandler) is configured by
# the entry point (main.py) via logging.basicConfig(), not here.
logging.getLogger("talon").addHandler(logging.NullHandler())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"talon.{name}")


def set_audit_hook(hook: typing.Callable[[str, dict], None]) -> None:
    """Register a callback invoked for every audit() call."""
    global _audit_hook
    _audit_hook = hook


def audit(event: str, **kwargs: object) -> None:
    """Log a security-relevant event and forward to the audit hook if set.

    Only the event name is written to the stdlib logger to avoid leaking
    sensitive fields (callsigns, token hashes, RNS hashes) to log files or
    aggregators in plaintext.  The encrypted audit log via _audit_hook is the
    canonical record and receives the full payload.
    """
    logger = get_logger("audit")
    logger.info("AUDIT %s", event)  # kwargs go only to the encrypted audit log
    if _audit_hook is not None:
        _audit_hook(event, dict(kwargs))

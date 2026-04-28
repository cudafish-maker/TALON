"""Passphrase policy helpers for local TALON secrets."""
from __future__ import annotations


class PassphrasePolicyError(ValueError):
    """Raised when a passphrase does not meet the TALON local policy."""


def validate_passphrase_policy(passphrase: str) -> None:
    """Require at least 12 characters and at least three character classes."""
    if len(passphrase) < 12:
        raise PassphrasePolicyError("Passphrase must be at least 12 characters.")
    classes = 0
    classes += any(ch.islower() for ch in passphrase)
    classes += any(ch.isupper() for ch in passphrase)
    classes += any(ch.isdigit() for ch in passphrase)
    classes += any(not ch.isalnum() for ch in passphrase)
    if classes < 3:
        raise PassphrasePolicyError(
            "Passphrase must include at least three character classes."
        )

"""Passphrase policy helpers for local TALON secrets."""
from __future__ import annotations

import dataclasses
import math


class PassphrasePolicyError(ValueError):
    """Raised when a passphrase does not meet the TALON local policy."""


@dataclasses.dataclass(frozen=True)
class PassphraseStrengthResult:
    score: int
    valid: bool
    reason: str


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
    strength = evaluate_passphrase_strength(passphrase)
    if not strength.valid:
        raise PassphrasePolicyError(strength.reason)


def evaluate_passphrase_strength(passphrase: str) -> PassphraseStrengthResult:
    """Return a dependency-free, zxcvbn-style local strength estimate."""
    lowered = passphrase.lower()
    if _has_common_pattern(lowered):
        return PassphraseStrengthResult(
            score=1,
            valid=False,
            reason="Passphrase contains a common or predictable pattern.",
        )

    charset = 0
    charset += 26 if any(ch.islower() for ch in passphrase) else 0
    charset += 26 if any(ch.isupper() for ch in passphrase) else 0
    charset += 10 if any(ch.isdigit() for ch in passphrase) else 0
    charset += 32 if any(not ch.isalnum() for ch in passphrase) else 0
    charset = max(charset, 1)
    entropy = len(passphrase) * math.log2(charset)

    unique_ratio = len(set(passphrase)) / max(1, len(passphrase))
    if unique_ratio < 0.35:
        entropy *= 0.55
    if _has_sequence(lowered):
        entropy *= 0.65

    if entropy >= 75:
        score = 4
    elif entropy >= 50:
        score = 3
    elif entropy >= 35:
        score = 2
    else:
        score = 1

    return PassphraseStrengthResult(
        score=score,
        valid=score >= 3,
        reason=(
            "Passphrase is strong enough."
            if score >= 3
            else "Passphrase is too predictable; use a longer phrase with less patterning."
        ),
    )


def _has_common_pattern(lowered: str) -> bool:
    common = (
        "password",
        "qwerty",
        "letmein",
        "admin123",
        "welcome1",
        "changeme",
        "correcthorsebatterystaple",
    )
    if any(value in lowered for value in common):
        return True
    if any(ch * 5 in lowered for ch in "abcdefghijklmnopqrstuvwxyz0123456789"):
        return True
    return False


def _has_sequence(lowered: str) -> bool:
    sequences = (
        "abcdefghijklmnopqrstuvwxyz",
        "zyxwvutsrqponmlkjihgfedcba",
        "0123456789",
        "9876543210",
        "qwertyuiop",
        "poiuytrewq",
    )
    return any(seq[i:i + 5] in lowered for seq in sequences for i in range(len(seq) - 4))

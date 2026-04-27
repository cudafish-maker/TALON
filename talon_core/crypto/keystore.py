"""
Argon2id key derivation and salt management.

The derived key is used to open the SQLCipher database via PRAGMA key.
The salt is stored plaintext next to the database file — losing the salt
is equivalent to losing the encrypted data. The threat model is file
exfiltration, not local brute force.
"""
import os
import pathlib

import argon2.low_level as _argon2

from talon_core.constants import (
    ARGON2_HASH_LEN,
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_SALT_LEN,
    ARGON2_TIME_COST,
)


def generate_salt() -> bytes:
    return os.urandom(ARGON2_SALT_LEN)


def load_or_create_salt(path: pathlib.Path) -> bytes:
    """Return existing salt or generate and persist a new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        data = path.read_bytes()
        if len(data) != ARGON2_SALT_LEN:
            raise ValueError(f"Salt file {path} has unexpected length {len(data)}")
        return data
    salt = generate_salt()
    # Create the file at 0o600 before writing so it is never world-readable —
    # the salt is a second factor for offline passphrase attacks against the DB.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(salt)
    return salt


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """
    Derive a 256-bit key from a passphrase using Argon2id.

    Parameters are tuned to keep KDF time under ~2 seconds on mid-range Android.
    Returns raw key bytes suitable for use as a SQLCipher PRAGMA key (as hex).
    """
    return _argon2.hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=_argon2.Type.ID,
    )


def key_to_hex(key: bytes) -> str:
    """Format key bytes as a hex string for SQLCipher's PRAGMA key = \"x'...'\"""."""
    return key.hex()

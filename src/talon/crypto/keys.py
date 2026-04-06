# talon/crypto/keys.py
# Key derivation and master key management.
#
# How it works:
# 1. The operator enters a passphrase when they log in.
# 2. That passphrase is run through Argon2id (a memory-hard hashing
#    algorithm that is very resistant to brute-force attacks).
# 3. The result is a "master key" that is used to derive other keys:
#    - Database key: unlocks the SQLCipher encrypted database
#    - Field key: encrypts sensitive fields before they go into the DB
#    - Identity key: ties to the operator's Reticulum identity
# 4. The master key is NEVER written to disk. It only exists in memory
#    while the app is running. When the app closes, the key is gone.

import os

from argon2.low_level import Type, hash_secret_raw

# Salt length in bytes — a random value mixed with the passphrase
# to ensure two identical passphrases produce different keys.
SALT_LENGTH = 32

# Master key length in bytes (256 bits — standard for strong encryption)
KEY_LENGTH = 32

# Argon2id parameters — these control how much CPU and memory are
# used when deriving the key. Higher values = slower brute force attacks
# but also slower login for the operator. These are tuned for a balance.
ARGON2_TIME_COST = 3  # Number of iterations
ARGON2_MEMORY_COST = 65536  # Memory usage in KB (64MB)
ARGON2_PARALLELISM = 4  # Number of parallel threads


def generate_salt() -> bytes:
    """Create a random salt value.

    The salt is stored alongside the encrypted database so it can
    be used again when the operator logs in. The salt itself is not
    secret — its purpose is to make each key unique even if two
    operators use the same passphrase.
    """
    return os.urandom(SALT_LENGTH)


def derive_master_key(passphrase: str, salt: bytes) -> bytes:
    """Turn a passphrase into a master encryption key using Argon2id.

    Args:
        passphrase: The operator's login passphrase (plaintext string).
        salt: The random salt value (created once during enrollment).

    Returns:
        A 32-byte (256-bit) master key.

    This is intentionally slow (~0.5-1 second) to make brute-force
    attacks impractical. An attacker trying millions of passphrases
    would need millions of seconds.
    """
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=KEY_LENGTH,
        type=Type.ID,  # Argon2id — hybrid of Argon2i and Argon2d
    )


def derive_subkey(master_key: bytes, purpose: str) -> bytes:
    """Derive a purpose-specific key from the master key.

    Different parts of the system need different keys (database,
    field encryption, etc). This creates a unique key for each
    purpose from the single master key.

    Args:
        master_key: The 32-byte master key from derive_master_key().
        purpose: A string like "database", "field", or "identity".

    Returns:
        A 32-byte key unique to the given purpose.
    """
    # Use the purpose string as a salt to derive a unique subkey
    purpose_salt = purpose.encode("utf-8").ljust(SALT_LENGTH, b"\x00")
    return hash_secret_raw(
        secret=master_key,
        salt=purpose_salt,
        time_cost=1,  # Fast — the master key is already strong
        memory_cost=1024,
        parallelism=1,
        hash_len=KEY_LENGTH,
        type=Type.ID,
    )

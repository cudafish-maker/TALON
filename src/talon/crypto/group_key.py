# talon/crypto/group_key.py
# Group key management for T.A.L.O.N.
#
# The "group key" is a shared encryption key that all trusted clients
# and the server use to encrypt operational data. This is what allows
# the server operator to read group chat and shared data.
#
# Key lifecycle:
# 1. Server generates the group key when first set up.
# 2. Each new client receives the group key during enrollment.
# 3. When a client is REVOKED (compromised/lost), the group key
#    is rotated — a brand new key is generated and pushed to all
#    remaining trusted clients. The revoked client's copy of the
#    old key becomes useless for future communications.
#
# This does NOT apply to DMs — those use per-pair keys that the
# server cannot read.

import nacl.secret
import nacl.utils
import os
import time


# Group key is 32 bytes (256 bits)
GROUP_KEY_LENGTH = 32


def generate_group_key() -> bytes:
    """Generate a new random group key.

    Called when the server is first set up, and again each time
    the group key is rotated (after a client revocation).

    Returns:
        A 32-byte random key.
    """
    return os.urandom(GROUP_KEY_LENGTH)


def rotate_group_key() -> dict:
    """Generate a new group key for rotation after a revocation.

    Returns a dictionary containing the new key and metadata
    about the rotation event.

    Returns:
        Dictionary with:
        - "key": the new 32-byte group key
        - "rotated_at": timestamp of when rotation occurred
        - "version": should be incremented by the caller
    """
    return {
        "key": generate_group_key(),
        "rotated_at": time.time(),
    }


def encrypt_for_group(group_key: bytes, plaintext: bytes) -> bytes:
    """Encrypt data with the group key so all trusted members can read it.

    Used for: group chat messages, shared operational data in transit.

    Args:
        group_key: The current 32-byte group key.
        plaintext: The data to encrypt.

    Returns:
        Encrypted bytes that any holder of the group key can decrypt.
    """
    box = nacl.secret.SecretBox(group_key)
    return box.encrypt(plaintext)


def decrypt_from_group(group_key: bytes, ciphertext: bytes) -> bytes:
    """Decrypt data that was encrypted with the group key.

    Args:
        group_key: The 32-byte group key (must be the same version
                   used to encrypt).
        ciphertext: The encrypted bytes.

    Returns:
        The original plaintext bytes.

    Raises:
        nacl.exceptions.CryptoError: If the key is wrong (e.g., the
        data was encrypted with an older group key version).
    """
    box = nacl.secret.SecretBox(group_key)
    return box.decrypt(ciphertext)

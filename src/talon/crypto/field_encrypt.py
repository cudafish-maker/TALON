# talon/crypto/field_encrypt.py
# Field-level encryption using PyNaCl (libsodium).
#
# This encrypts individual sensitive data fields BEFORE they are
# stored in the database. Even if someone gets access to the
# SQLCipher database file AND its key, these fields remain encrypted
# with a separate key.
#
# Used for highly sensitive data like:
# - Exact coordinates of safe houses and caches
# - Operator real identities (if stored)
# - Sensitive SITREP content
#
# Uses NaCl's SecretBox (XSalsa20-Poly1305):
# - XSalsa20 stream cipher for encryption
# - Poly1305 MAC for authentication (detects tampering)

import nacl.secret
import nacl.utils


def create_secret_box(field_key: bytes) -> nacl.secret.SecretBox:
    """Create an encryption box using a 32-byte field key.

    The SecretBox is the main tool for encrypting and decrypting.
    Think of it like a lockbox — you create it with a key, then
    use it to lock (encrypt) and unlock (decrypt) data.

    Args:
        field_key: A 32-byte key (from keys.derive_subkey with
                   purpose="field").

    Returns:
        A SecretBox object you can use to encrypt/decrypt.
    """
    return nacl.secret.SecretBox(field_key)


def encrypt_field(box: nacl.secret.SecretBox, plaintext: str) -> bytes:
    """Encrypt a text field.

    Args:
        box: The SecretBox created with create_secret_box().
        plaintext: The text to encrypt (e.g., a GPS coordinate string).

    Returns:
        Encrypted bytes. These are safe to store in the database.
        They include a random nonce (one-time number) so encrypting
        the same text twice produces different output.
    """
    return box.encrypt(plaintext.encode("utf-8"))


def decrypt_field(box: nacl.secret.SecretBox, ciphertext: bytes) -> str:
    """Decrypt a previously encrypted field.

    Args:
        box: The same SecretBox (same key) used to encrypt.
        ciphertext: The encrypted bytes from encrypt_field().

    Returns:
        The original plaintext string.

    Raises:
        nacl.exceptions.CryptoError: If the key is wrong or data
        has been tampered with.
    """
    return box.decrypt(ciphertext).decode("utf-8")

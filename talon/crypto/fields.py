"""
Per-field encryption using PyNaCl SecretBox (XSalsa20-Poly1305).

Used for fields requiring additional protection within the already-encrypted
SQLCipher database (e.g. DM message bodies, audit log entries).
The nonce is prepended to the ciphertext; both are stored together.
"""
import nacl.secret
import nacl.utils


def encrypt_field(data: bytes, key: bytes) -> bytes:
    """Encrypt data with a 32-byte key. Returns nonce + ciphertext."""
    box = nacl.secret.SecretBox(key)
    return bytes(box.encrypt(data))


def decrypt_field(ciphertext: bytes, key: bytes) -> bytes:
    """Decrypt data produced by encrypt_field."""
    box = nacl.secret.SecretBox(key)
    return bytes(box.decrypt(ciphertext))

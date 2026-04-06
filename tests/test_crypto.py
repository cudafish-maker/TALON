# tests/test_crypto.py
# Tests for the cryptography layer (keys, field encryption, group keys, leases).

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from talon.crypto.field_encrypt import create_secret_box, decrypt_field, encrypt_field
from talon.crypto.group_key import (
    decrypt_from_group,
    encrypt_for_group,
    generate_group_key,
    rotate_group_key,
)
from talon.crypto.keys import derive_master_key, derive_subkey, generate_salt
from talon.crypto.lease import (
    generate_lease_token,
    is_lease_valid,
    sign_lease,
    time_remaining,
    verify_lease_signature,
)

# ---------- Key derivation ----------


def test_salt_generation():
    """Salt should be 32 bytes and unique each time."""
    salt1 = generate_salt()
    salt2 = generate_salt()
    assert len(salt1) == 32
    assert salt1 != salt2


def test_key_derivation():
    """Same passphrase + salt should produce the same key."""
    salt = generate_salt()
    key1 = derive_master_key("test-passphrase", salt)
    key2 = derive_master_key("test-passphrase", salt)
    assert key1 == key2
    assert len(key1) == 32  # 256-bit key


def test_different_passphrase_different_key():
    """Different passphrases should produce different keys."""
    salt = generate_salt()
    key1 = derive_master_key("passphrase-one", salt)
    key2 = derive_master_key("passphrase-two", salt)
    assert key1 != key2


def test_subkey_derivation():
    """Subkeys for different purposes should be different."""
    salt = generate_salt()
    master = derive_master_key("test", salt)
    db_key = derive_subkey(master, "database")
    field_key = derive_subkey(master, "field")
    assert db_key != field_key
    assert len(db_key) == 32


# ---------- Field encryption ----------


def test_field_encrypt_decrypt():
    """Encrypting then decrypting should return the original text."""
    salt = generate_salt()
    master = derive_master_key("test", salt)
    field_key = derive_subkey(master, "field")
    box = create_secret_box(field_key)

    original = "Top secret mission data"
    encrypted = encrypt_field(box, original)
    decrypted = decrypt_field(box, encrypted)

    assert decrypted == original
    assert encrypted != original  # Should actually be encrypted


def test_field_encrypt_different_each_time():
    """Same plaintext should produce different ciphertext (random nonce)."""
    salt = generate_salt()
    master = derive_master_key("test", salt)
    field_key = derive_subkey(master, "field")
    box = create_secret_box(field_key)

    encrypted1 = encrypt_field(box, "same text")
    encrypted2 = encrypt_field(box, "same text")
    assert encrypted1 != encrypted2


# ---------- Group key ----------


def test_group_key_generation():
    """Group key should be 32 bytes."""
    key = generate_group_key()
    assert len(key) == 32


def test_group_key_rotation():
    """Rotated key should be different from the original."""
    original = generate_group_key()
    result = rotate_group_key()
    assert result["key"] != original
    assert len(result["key"]) == 32
    assert "rotated_at" in result


def test_group_encrypt_decrypt():
    """Group encryption round-trip should work."""
    key = generate_group_key()
    plaintext = b"Broadcast message to all operators"

    encrypted = encrypt_for_group(key, plaintext)
    decrypted = decrypt_from_group(key, encrypted)

    assert decrypted == plaintext


def test_rotated_key_cannot_decrypt_old():
    """After key rotation, the new key should NOT decrypt old messages."""
    old_key = generate_group_key()
    encrypted = encrypt_for_group(old_key, b"old message")

    result = rotate_group_key()
    new_key = result["key"]

    try:
        decrypt_from_group(new_key, encrypted)
        assert False, "Should have raised an exception"
    except Exception:
        pass  # Expected — new key can't decrypt old data


# ---------- Lease tokens ----------


def test_lease_generation():
    """Lease should have a token and expires_at."""
    lease = generate_lease_token()
    assert "token" in lease
    assert "expires_at" in lease
    assert lease["expires_at"] > 0


def test_lease_validity():
    """A freshly generated lease should be valid."""
    lease = generate_lease_token()
    assert is_lease_valid(lease)
    assert time_remaining(lease) > 0


def test_lease_signing():
    """A signed lease should verify correctly."""
    lease = generate_lease_token()
    secret = b"server-secret-key-for-testing-00"  # 32 bytes

    signature = sign_lease(lease["token"], secret)
    assert verify_lease_signature(lease["token"], signature, secret)


def test_lease_tamper_detection():
    """Modifying a signed lease should fail verification."""
    lease = generate_lease_token()
    secret = b"server-secret-key-for-testing-00"

    signature = sign_lease(lease["token"], secret)

    # Tamper: use a different token
    tampered_token = os.urandom(32)

    assert not verify_lease_signature(tampered_token, signature, secret)

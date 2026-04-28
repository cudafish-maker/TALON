"""Tests for talon.crypto.keystore and talon.crypto.fields."""
import pathlib
import stat

import pytest

from talon.crypto.keystore import derive_key, generate_salt, key_to_hex, load_or_create_salt
from talon.crypto.fields import decrypt_field, encrypt_field
from talon_core.crypto.identity import (
    load_or_create_identity,
    load_or_create_protected_identity,
    protected_identity_path,
)
from talon_core.crypto.passphrase import (
    PassphrasePolicyError,
    validate_passphrase_policy,
)


class TestKeystore:
    def test_generate_salt_length(self):
        from talon.constants import ARGON2_SALT_LEN
        salt = generate_salt()
        assert len(salt) == ARGON2_SALT_LEN

    def test_generate_salt_unique(self):
        assert generate_salt() != generate_salt()

    def test_derive_key_deterministic(self):
        salt = generate_salt()
        k1 = derive_key("passphrase", salt)
        k2 = derive_key("passphrase", salt)
        assert k1 == k2

    def test_derive_key_different_passphrases(self):
        salt = generate_salt()
        assert derive_key("abc", salt) != derive_key("xyz", salt)

    def test_derive_key_different_salts(self):
        assert derive_key("abc", generate_salt()) != derive_key("abc", generate_salt())

    def test_derive_key_length(self):
        from talon.constants import ARGON2_HASH_LEN
        key = derive_key("test", generate_salt())
        assert len(key) == ARGON2_HASH_LEN

    def test_key_to_hex(self):
        key = bytes(range(32))
        assert key_to_hex(key) == key.hex()

    def test_load_or_create_salt_creates(self, tmp_path):
        from talon.constants import ARGON2_SALT_LEN
        salt_path = tmp_path / "test.salt"
        salt = load_or_create_salt(salt_path)
        assert salt_path.exists()
        assert len(salt) == ARGON2_SALT_LEN

    def test_load_or_create_salt_stable(self, tmp_path):
        salt_path = tmp_path / "test.salt"
        s1 = load_or_create_salt(salt_path)
        s2 = load_or_create_salt(salt_path)
        assert s1 == s2

    def test_load_or_create_salt_bad_length(self, tmp_path):
        salt_path = tmp_path / "bad.salt"
        salt_path.write_bytes(b"\x00" * 10)
        with pytest.raises(ValueError):
            load_or_create_salt(salt_path)


class TestFields:
    @pytest.fixture
    def key(self):
        return bytes(range(32))  # 32-byte test key

    def test_round_trip(self, key):
        plaintext = b"sensitive operator data"
        ct = encrypt_field(plaintext, key)
        assert decrypt_field(ct, key) == plaintext

    def test_ciphertext_differs_from_plaintext(self, key):
        plaintext = b"test"
        ct = encrypt_field(plaintext, key)
        assert ct != plaintext

    def test_different_encryptions_produce_different_ciphertext(self, key):
        plaintext = b"same plaintext"
        # SecretBox uses a random nonce each time
        ct1 = encrypt_field(plaintext, key)
        ct2 = encrypt_field(plaintext, key)
        assert ct1 != ct2

    def test_wrong_key_raises(self, key):
        import nacl.exceptions
        ct = encrypt_field(b"secret", key)
        wrong_key = bytes([k ^ 0xFF for k in key])
        with pytest.raises(nacl.exceptions.CryptoError):
            decrypt_field(ct, wrong_key)


class TestProtectedIdentity:
    def test_creates_encrypted_identity_without_plaintext(self, tmp_path, test_key):
        identity_path = tmp_path / "client.identity"

        identity = load_or_create_protected_identity(identity_path, test_key)
        encrypted_path = protected_identity_path(identity_path)
        loaded = load_or_create_protected_identity(identity_path, test_key)

        assert encrypted_path.exists()
        assert not identity_path.exists()
        assert loaded.hash == identity.hash
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
        assert stat.S_IMODE(encrypted_path.stat().st_mode) == 0o600
        assert identity.get_private_key() not in encrypted_path.read_bytes()

    def test_migrates_private_legacy_plaintext_identity(self, tmp_path, test_key):
        identity_path = tmp_path / "client.identity"
        legacy = load_or_create_identity(identity_path)

        migrated = load_or_create_protected_identity(identity_path, test_key)

        assert migrated.hash == legacy.hash
        assert not identity_path.exists()
        assert protected_identity_path(identity_path).exists()

    def test_rejects_group_readable_legacy_plaintext_identity(self, tmp_path, test_key):
        identity_path = tmp_path / "client.identity"
        load_or_create_identity(identity_path)
        identity_path.chmod(0o644)

        with pytest.raises(RuntimeError, match="group/world-accessible"):
            load_or_create_protected_identity(identity_path, test_key)


class TestPassphrasePolicy:
    def test_accepts_twelve_chars_with_three_classes(self):
        validate_passphrase_policy("ValidPass-12")

    @pytest.mark.parametrize("passphrase", ["Short-1", "lowercase-only-pass"])
    def test_rejects_policy_failures(self, passphrase):
        with pytest.raises(PassphrasePolicyError):
            validate_passphrase_policy(passphrase)

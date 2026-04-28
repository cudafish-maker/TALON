"""
Reticulum Identity lifecycle management.

RNS identities are private network credentials. New TALON identities are stored
as encrypted ``*.identity.enc`` files using a domain-separated key derived from
the unlocked SQLCipher key. Legacy plaintext identity files are migrated only
when their permissions are already private.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import stat
import typing

import RNS

from talon_core.crypto.fields import decrypt_field, encrypt_field

_IDENTITY_HEADER = b"TALON-RNS-IDENTITY-v1\n"
_IDENTITY_KEY_DOMAIN = b"talon:rns-identity:v1"


def protected_identity_path(identity_path: pathlib.Path) -> pathlib.Path:
    """Return the encrypted identity path for a legacy plaintext path."""
    return pathlib.Path(f"{identity_path}.enc")


def load_or_create_protected_identity(
    identity_path: pathlib.Path,
    db_key: bytes,
) -> RNS.Identity:
    """Load, migrate, or create an encrypted RNS identity."""
    encrypted_path = protected_identity_path(identity_path)
    _ensure_private_dir(identity_path.parent)

    if encrypted_path.exists():
        _require_private_file(encrypted_path)
        identity = _load_encrypted_identity(encrypted_path, db_key)
        if identity is None:
            raise RuntimeError(f"Failed to load identity from {encrypted_path}")
        return identity

    if identity_path.exists():
        _require_private_file(identity_path)
        identity = RNS.Identity.from_file(str(identity_path))
        if identity is None:
            raise RuntimeError(f"Failed to load identity from {identity_path}")
        _write_encrypted_identity(encrypted_path, identity, db_key)
        _destroy_one(identity_path)
        return identity

    identity = RNS.Identity()
    _write_encrypted_identity(encrypted_path, identity, db_key)
    return identity


def reencrypt_protected_identity(
    identity_path: pathlib.Path,
    old_db_key: bytes,
    new_db_key: bytes,
) -> None:
    """Re-encrypt an existing protected identity after a passphrase change."""
    encrypted_path = protected_identity_path(identity_path)
    if not encrypted_path.exists() and not identity_path.exists():
        return
    identity = load_or_create_protected_identity(identity_path, old_db_key)
    _write_encrypted_identity(encrypted_path, identity, new_db_key)


def load_or_create_identity(identity_path: pathlib.Path) -> RNS.Identity:
    """Load or create a legacy plaintext RNS identity with private permissions."""
    path_str = str(identity_path)
    _ensure_private_dir(identity_path.parent)
    if identity_path.exists():
        _require_private_file(identity_path)
        identity = RNS.Identity.from_file(path_str)
        if identity is None:
            raise RuntimeError(f"Failed to load identity from {identity_path}")
        return identity
    identity = RNS.Identity()
    _write_private_file(identity_path, identity.get_private_key())
    return identity


def destroy_identity(identity_path: pathlib.Path) -> None:
    """
    Destroy legacy and encrypted identity files for *identity_path*.

    A single-pass overwrite is attempted before unlinking regular files. This
    impedes trivial recovery on conventional storage, but does not guarantee
    physical erasure on SSDs or copy-on-write filesystems.
    """
    for candidate in (identity_path, protected_identity_path(identity_path)):
        _destroy_one(candidate)


def identity_hex(identity: RNS.Identity) -> str:
    """Return the hex representation of an identity's public key hash."""
    return RNS.prettyhexrep(identity.hash)


def _identity_key(db_key: bytes) -> bytes:
    return hashlib.blake2b(
        db_key,
        digest_size=32,
        person=b"TALONRNSIDv1",
        salt=hashlib.sha256(_IDENTITY_KEY_DOMAIN).digest()[:16],
    ).digest()


def _load_encrypted_identity(
    encrypted_path: pathlib.Path,
    db_key: bytes,
) -> typing.Optional[RNS.Identity]:
    data = encrypted_path.read_bytes()
    if not data.startswith(_IDENTITY_HEADER):
        raise RuntimeError(f"Unsupported identity file format: {encrypted_path}")
    plaintext = decrypt_field(data[len(_IDENTITY_HEADER):], _identity_key(db_key))
    return RNS.Identity.from_bytes(plaintext)


def _write_encrypted_identity(
    encrypted_path: pathlib.Path,
    identity: RNS.Identity,
    db_key: bytes,
) -> None:
    payload = _IDENTITY_HEADER + encrypt_field(
        identity.get_private_key(),
        _identity_key(db_key),
    )
    _write_private_file(encrypted_path, payload)


def _ensure_private_dir(path: pathlib.Path) -> None:
    if path.exists() and path.is_symlink():
        raise RuntimeError(f"Refusing to use symlinked identity directory: {path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except PermissionError as exc:
        raise RuntimeError(f"Could not secure identity directory {path}") from exc


def _require_private_file(path: pathlib.Path) -> None:
    if path.is_symlink():
        raise RuntimeError(f"Refusing to load symlinked identity file: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise RuntimeError(
            f"Identity file {path} is group/world-accessible; expected 0o600"
        )


def _write_private_file(path: pathlib.Path, data: bytes) -> None:
    _ensure_private_dir(path.parent)
    if path.is_symlink():
        raise RuntimeError(f"Refusing to write symlinked identity file: {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    finally:
        try:
            os.chmod(path, 0o600)
        except FileNotFoundError:
            pass


def _destroy_one(path: pathlib.Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        path.unlink()
        return
    try:
        size = path.stat().st_size
        with open(path, "r+b", buffering=0) as f:
            f.write(os.urandom(size))
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

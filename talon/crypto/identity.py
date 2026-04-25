"""
Reticulum Identity lifecycle management.

Identities are created once per node, persisted to disk by RNS itself,
and destroyed only during operator revocation (hard shred).
"""
import pathlib
import typing
import os
import RNS


def load_or_create_identity(identity_path: pathlib.Path) -> RNS.Identity:
    """Load a persisted RNS Identity or create and save a new one."""
    path_str = str(identity_path)
    if identity_path.exists():
        identity = RNS.Identity.from_file(path_str)
        if identity is None:
            raise RuntimeError(f"Failed to load identity from {identity_path}")
        return identity
    identity = RNS.Identity()
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity.to_file(path_str)
    return identity


def destroy_identity(identity_path: pathlib.Path) -> None:
    """
    Permanently destroy an identity file (hard revocation step).

    A single-pass overwrite is performed before unlinking to impede trivial
    file-recovery tools on conventional magnetic media.

    Limitation: on SSDs (wear levelling) and copy-on-write filesystems
    (Btrfs, ZFS, APFS) the overwrite does NOT guarantee physical erasure —
    the original block may persist in flash until the device garbage-collects
    it.  The primary defence against recovery on these storage types is
    full-disk encryption (SQLCipher for the DB; OS-level FDE for everything
    else).  When the disk is encrypted, the overwrite provides no meaningful
    additional protection, and its absence also causes no meaningful exposure.
    """
    if identity_path.exists():
        # Overwrite with random bytes before unlinking to resist trivial recovery
        # on conventional storage.  See docstring for SSD/CoW limitations.
        size = identity_path.stat().st_size
        identity_path.write_bytes(os.urandom(size))
        identity_path.unlink()


def identity_hex(identity: RNS.Identity) -> str:
    """Return the hex representation of an identity's public key hash."""
    return RNS.prettyhexrep(identity.hash)

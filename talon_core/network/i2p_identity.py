"""Helpers for TALON Reticulum I2P server destinations."""
from __future__ import annotations

import asyncio
import dataclasses
import pathlib

from talon_core.network.rns_config import ReticulumConfigError


DEFAULT_I2PD_SERVER_INTERFACE_NAME = "TALON i2pd Server"


@dataclasses.dataclass(frozen=True)
class I2PServerAddress:
    address: str
    key_path: pathlib.Path
    generated: bool = False


def get_i2pd_server_b32(
    config_dir: pathlib.Path,
    *,
    interface_name: str = DEFAULT_I2PD_SERVER_INTERFACE_NAME,
) -> I2PServerAddress | None:
    """Return the existing TALON i2pd server B32 address, if one exists."""
    config_dir = pathlib.Path(config_dir)
    i2p_dir = _i2p_storage_dir(config_dir)

    old_key_path = _old_i2p_key_path(i2p_dir, interface_name)
    if old_key_path.is_file():
        return I2PServerAddress(
            address=_address_from_key_file(old_key_path),
            key_path=old_key_path,
        )

    identity = _load_transport_identity(config_dir)
    if identity is None:
        return None

    key_path = _new_i2p_key_path(i2p_dir, interface_name, identity.hash)
    if not key_path.is_file():
        return None
    return I2PServerAddress(address=_address_from_key_file(key_path), key_path=key_path)


def ensure_i2pd_server_b32(
    config_dir: pathlib.Path,
    *,
    interface_name: str = DEFAULT_I2PD_SERVER_INTERFACE_NAME,
) -> I2PServerAddress:
    """Return or create the TALON i2pd server B32 address.

    Reticulum creates the I2P destination lazily on first startup. This helper
    mirrors Reticulum's current filename scheme so the Network Setup dialog can
    show the operator the address before restarting TALON, provided i2pd's SAM
    bridge is available.
    """
    existing = get_i2pd_server_b32(config_dir, interface_name=interface_name)
    if existing is not None:
        return existing

    config_dir = pathlib.Path(config_dir)
    storage_dir = config_dir / "storage"
    i2p_dir = _i2p_storage_dir(config_dir)
    i2p_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod_private(i2p_dir, 0o700)

    identity = _load_transport_identity(config_dir)
    if identity is None:
        identity = _create_transport_identity(storage_dir)

    key_path = _new_i2p_key_path(i2p_dir, interface_name, identity.hash)
    if key_path.is_file():
        return I2PServerAddress(address=_address_from_key_file(key_path), key_path=key_path)

    private_key = _generate_i2p_destination_private_key()
    key_path.write_text(private_key, encoding="utf-8")
    _chmod_private(key_path, 0o600)
    return I2PServerAddress(
        address=_address_from_key_file(key_path),
        key_path=key_path,
        generated=True,
    )


def _i2p_storage_dir(config_dir: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(config_dir) / "storage" / "i2p"


def _transport_identity_path(config_dir: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(config_dir) / "storage" / "transport_identity"


def _old_i2p_key_path(i2p_dir: pathlib.Path, interface_name: str) -> pathlib.Path:
    from RNS import Identity

    destination_hash = Identity.full_hash(
        Identity.full_hash(interface_name.encode("utf-8"))
    )
    return i2p_dir / f"{destination_hash.hex()}.i2p"


def _new_i2p_key_path(
    i2p_dir: pathlib.Path,
    interface_name: str,
    transport_identity_hash: bytes,
) -> pathlib.Path:
    from RNS import Identity

    destination_hash = Identity.full_hash(
        Identity.full_hash(interface_name.encode("utf-8"))
        + Identity.full_hash(transport_identity_hash)
    )
    return i2p_dir / f"{destination_hash.hex()}.i2p"


def _load_transport_identity(config_dir: pathlib.Path):
    identity_path = _transport_identity_path(config_dir)
    if not identity_path.is_file():
        return None
    from RNS import Identity

    identity = Identity.from_file(str(identity_path))
    if identity is None:
        raise ReticulumConfigError(
            f"Could not load Reticulum transport identity: {identity_path}"
        )
    return identity


def _create_transport_identity(storage_dir: pathlib.Path):
    storage_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod_private(storage_dir, 0o700)
    identity_path = storage_dir / "transport_identity"
    from RNS import Identity

    identity = Identity()
    if not identity.to_file(str(identity_path)):
        raise ReticulumConfigError(
            f"Could not create Reticulum transport identity: {identity_path}"
        )
    _chmod_private(identity_path, 0o600)
    return identity


def _address_from_key_file(key_path: pathlib.Path) -> str:
    try:
        private_key = key_path.read_text(encoding="utf-8").strip()
        from RNS.vendor.i2plib import Destination

        destination = Destination(data=private_key, has_private_key=True)
    except Exception as exc:
        raise ReticulumConfigError(
            f"Could not read i2pd server destination key: {key_path}"
        ) from exc
    return f"{destination.base32}.b32.i2p"


def _generate_i2p_destination_private_key() -> str:
    try:
        from RNS.vendor import i2plib

        destination = asyncio.run(i2plib.new_destination())
    except Exception as exc:
        raise ReticulumConfigError(
            "Could not generate an i2pd server address. Confirm i2pd is running "
            "and SAM is enabled on 127.0.0.1:7656."
        ) from exc
    return destination.private_key.base64


def _chmod_private(path: pathlib.Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass

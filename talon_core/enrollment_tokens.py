"""Enrollment token formatting and parsing helpers."""
from __future__ import annotations

import base64
import collections.abc
import dataclasses
import json
import re
import typing


ENROLLMENT_TOKEN_V2_PREFIX = "TALON2:"
_MAX_ENROLLMENT_STRING_LENGTH = 8192
_I2P_B32_RE = re.compile(r"^[a-z2-7]+\.b32\.i2p$", re.IGNORECASE)
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


@dataclasses.dataclass(frozen=True)
class EnrollmentTransportHint:
    type: str
    peer: str = ""
    address: str = ""
    port: int | None = None


@dataclasses.dataclass(frozen=True)
class ParsedEnrollmentToken:
    token: str
    server_hash: str
    transports: tuple[EnrollmentTransportHint, ...] = ()
    version: int = 1
    raw: str = ""


def format_enrollment_token(
    token: str,
    server_hash: str,
    *,
    transports: typing.Iterable[object] = (),
) -> str:
    """Return a legacy or v2 enrollment string for operator delivery."""
    token = _required_string(token, "Enrollment token")
    hints = normalise_enrollment_transports(transports)
    server_hash = _normalise_server_hash(server_hash, required=bool(hints))
    if not hints:
        return f"{token}:{server_hash}" if server_hash else token

    payload = {
        "v": 2,
        "token": token,
        "server_hash": server_hash,
        "transports": [_transport_to_wire(hint) for hint in hints],
    }
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")
    return f"{ENROLLMENT_TOKEN_V2_PREFIX}{encoded}"


def parse_enrollment_token(value: str) -> ParsedEnrollmentToken:
    """Parse either ``TOKEN:SERVER_HASH`` or ``TALON2:<base64url-json>``."""
    raw = _required_string(value, "Enrollment string")
    if len(raw) > _MAX_ENROLLMENT_STRING_LENGTH:
        raise ValueError("Enrollment string is too large.")

    if raw.startswith(ENROLLMENT_TOKEN_V2_PREFIX):
        return _parse_v2(raw)
    return _parse_legacy(raw)


def normalise_enrollment_transports(
    transports: typing.Iterable[object] | None,
) -> tuple[EnrollmentTransportHint, ...]:
    """Validate and canonicalise v2 transport hints."""
    if transports is None:
        return ()
    if isinstance(transports, (str, bytes, collections.abc.Mapping)):
        raise ValueError("Enrollment transports must be a list of objects.")

    hints: list[EnrollmentTransportHint] = []
    seen: set[tuple[object, ...]] = set()
    for item in transports:
        kind = _hint_value(item, "type") or _hint_value(item, "kind")
        kind = str(kind).strip().lower()
        if kind in {"i2p", "i2pd"}:
            peer = str(_hint_value(item, "peer") or _hint_value(item, "address") or "")
            peer = _normalise_i2p_peer(peer)
            hint = EnrollmentTransportHint(type="i2p", peer=peer)
            key = ("i2p", peer)
        elif kind in {"ygg", "yggdrasil"}:
            address = _normalise_yggdrasil_address(str(_hint_value(item, "address") or ""))
            port = _normalise_port(_hint_value(item, "port"), default=4343)
            hint = EnrollmentTransportHint(type="yggdrasil", address=address, port=port)
            key = ("yggdrasil", address, port)
        elif not kind:
            raise ValueError("Enrollment transport is missing a type.")
        else:
            raise ValueError(f"Unsupported enrollment transport type: {kind!r}")

        if key not in seen:
            seen.add(key)
            hints.append(hint)
    return tuple(hints)


def _parse_v2(raw: str) -> ParsedEnrollmentToken:
    encoded = raw[len(ENROLLMENT_TOKEN_V2_PREFIX):].strip()
    if not encoded:
        raise ValueError("Enrollment token payload is empty.")
    if not _BASE64URL_RE.match(encoded):
        raise ValueError("Enrollment token payload is not valid base64url.")
    encoded += "=" * (-len(encoded) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Enrollment token payload could not be decoded: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Enrollment token payload must be an object.")
    if payload.get("v") != 2:
        raise ValueError("Unsupported enrollment token version.")

    token = _required_string(payload.get("token"), "Enrollment token")
    server_hash = _normalise_server_hash(payload.get("server_hash"), required=True)
    transports = normalise_enrollment_transports(payload.get("transports") or ())
    return ParsedEnrollmentToken(
        token=token,
        server_hash=server_hash,
        transports=transports,
        version=2,
        raw=raw,
    )


def _parse_legacy(raw: str) -> ParsedEnrollmentToken:
    if ":" not in raw:
        raise ValueError(
            "Invalid enrollment string - expected TOKEN:SERVER_HASH or TALON2:<payload> format"
        )
    token, server_hash = raw.split(":", 1)
    token = _required_string(token, "Token part")
    server_hash = _normalise_server_hash(server_hash, required=True)
    return ParsedEnrollmentToken(
        token=token,
        server_hash=server_hash,
        raw=raw,
    )


def _transport_to_wire(hint: EnrollmentTransportHint) -> dict[str, object]:
    if hint.type == "i2p":
        return {"type": "i2p", "peer": hint.peer}
    if hint.type == "yggdrasil":
        return {"type": "yggdrasil", "address": hint.address, "port": int(hint.port or 4343)}
    raise ValueError(f"Unsupported enrollment transport type: {hint.type!r}")


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string.")
    value = value.strip()
    if not value:
        raise ValueError(f"{label} is empty.")
    return value


def _normalise_server_hash(value: object, *, required: bool) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("Server hash must be a string.")
    value = value.strip().lower()
    if not value:
        if required:
            raise ValueError("Server hash is required.")
        return ""
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("Server hash must be hexadecimal.") from exc
    return value


def _normalise_i2p_peer(value: str) -> str:
    value = value.strip().lower()
    if not _I2P_B32_RE.match(value):
        raise ValueError("I2P peer must be a server .b32.i2p address.")
    return value


def _normalise_yggdrasil_address(value: str) -> str:
    value = value.strip().lower()
    if not value:
        raise ValueError("Yggdrasil address is required.")
    if any(char.isspace() for char in value):
        raise ValueError("Yggdrasil address must not contain whitespace.")
    try:
        import ipaddress

        address = ipaddress.ip_address(value.split("%", 1)[0])
        if address not in ipaddress.ip_network("200::/7"):
            raise ValueError
    except ValueError as exc:
        raise ValueError("Yggdrasil address must be an IPv6 address in 200::/7.") from exc
    return value


def _normalise_port(value: object, *, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("Transport port must be an integer.") from exc
    if port < 1 or port > 65535:
        raise ValueError("Transport port must be between 1 and 65535.")
    return port


def _hint_value(item: object, key: str) -> object:
    if isinstance(item, collections.abc.Mapping):
        return item.get(key)
    return getattr(item, key, None)

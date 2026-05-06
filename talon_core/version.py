"""Application version and wire metadata helpers."""
from __future__ import annotations

import importlib.metadata
import typing

DEFAULT_APP_VERSION = "0.1.1"

APP_CAPABILITIES: tuple[str, ...] = (
    "protocol-v1",
    "peer-metadata-v1",
    "app-update-v1",
)


def current_app_version() -> str:
    """Return the installed TALON package version with a source fallback."""
    try:
        return importlib.metadata.version("talon")
    except importlib.metadata.PackageNotFoundError:
        return DEFAULT_APP_VERSION


def peer_metadata(role: typing.Literal["client", "server"]) -> dict[str, object]:
    """Return optional wire metadata that older peers can safely ignore."""
    return {
        "app_version": current_app_version(),
        "role": role,
        "capabilities": list(APP_CAPABILITIES),
    }

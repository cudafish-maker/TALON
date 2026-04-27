"""
Core configuration loader and path helpers.

This module intentionally avoids UI toolkit imports. Platform layers that need
app-specific sandbox paths should pass explicit values in ``talon.ini`` or
construct a ConfigParser before creating ``TalonCoreSession``.
"""
from __future__ import annotations

import configparser
import os
import pathlib
import typing

from talon_core.constants import TRANSPORT_PRIORITY


def _default_data_dir() -> pathlib.Path:
    return pathlib.Path.home() / ".talon"


def load_config(
    config_path: typing.Optional[pathlib.Path] = None,
) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()

    explicit: typing.Optional[pathlib.Path] = config_path
    if explicit is None:
        env_path = os.environ.get("TALON_CONFIG", "").strip()
        if env_path:
            explicit = pathlib.Path(env_path)

    if explicit is not None:
        cfg.read([str(explicit)])
        return cfg

    for candidate in (
        pathlib.Path.home() / ".talon" / "talon.ini",
        pathlib.Path("talon.ini"),
    ):
        if candidate.exists():
            cfg.read([str(candidate)])
            break

    return cfg


def get_mode(cfg: configparser.ConfigParser) -> typing.Literal["server", "client"]:
    mode = cfg.get("talon", "mode", fallback=os.environ.get("TALON_MODE", "client")).lower()
    if mode not in ("server", "client"):
        raise ValueError(f"Invalid TALON_MODE: {mode!r} - must be 'server' or 'client'")
    return typing.cast(typing.Literal["server", "client"], mode)


def _get_data_dir(cfg: configparser.ConfigParser) -> pathlib.Path:
    raw = cfg.get("paths", "data_dir", fallback="").strip()
    return pathlib.Path(raw) if raw else _default_data_dir()


def get_data_dir(cfg: configparser.ConfigParser) -> pathlib.Path:
    return _get_data_dir(cfg)


def get_db_path(cfg: configparser.ConfigParser) -> pathlib.Path:
    return _get_data_dir(cfg) / "talon.db"


def get_salt_path(cfg: configparser.ConfigParser) -> pathlib.Path:
    return _get_data_dir(cfg) / "talon.salt"


def get_rns_config_dir(cfg: configparser.ConfigParser) -> pathlib.Path:
    raw = cfg.get("paths", "rns_config_dir", fallback="").strip()
    if raw:
        return pathlib.Path(raw)
    return _default_data_dir() / "reticulum"


def get_document_storage_path(cfg: configparser.ConfigParser) -> pathlib.Path:
    raw = cfg.get("documents", "storage_path", fallback="").strip()
    return pathlib.Path(raw) if raw else _get_data_dir(cfg) / "documents"


def get_transport_priority(cfg: configparser.ConfigParser) -> tuple[str, ...]:
    raw = cfg.get("network", "transport_priority", fallback="").strip()
    if not raw:
        return TRANSPORT_PRIORITY
    return tuple(x.strip() for x in raw.split(",") if x.strip())

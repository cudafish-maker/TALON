"""
Configuration loader for TALON.

Search order for talon.ini:
  1. Path passed explicitly to load_config()
  2. ~/.talon/talon.ini
  3. ./talon.ini (working directory)

On Android, data_dir and rns_config_dir default to the Kivy app's
user_data_dir (resolved at call time, not module load, to avoid
importing Kivy before Kivy is initialised).
"""
import configparser
import os
import pathlib
import typing

from talon.utils.logging import get_logger

_log = get_logger("config")


def _default_data_dir() -> pathlib.Path:
    try:
        from kivy.app import App  # type: ignore
        app = App.get_running_app()
        if app is not None:
            return pathlib.Path(app.user_data_dir)
    except Exception as exc:
        _log.debug("Kivy app not available for data dir: %s", exc)
    return pathlib.Path.home() / ".talon"


def load_config(config_path: typing.Optional[pathlib.Path] = None) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()

    # Resolve an explicit path (argument takes priority over env var).
    explicit: typing.Optional[pathlib.Path] = config_path
    if explicit is None:
        env_path = os.environ.get("TALON_CONFIG", "").strip()
        if env_path:
            explicit = pathlib.Path(env_path)

    if explicit is not None:
        # Explicit path specified — read that file only.  Do NOT fall through to
        # the default search paths; merging configs from different instances
        # (server + client) would silently corrupt settings like ``mode``.
        cfg.read([str(explicit)])
    else:
        # No explicit path — search defaults, stopping at the first file found.
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
        raise ValueError(f"Invalid TALON_MODE: {mode!r} — must be 'server' or 'client'")
    return mode  # type: ignore[return-value]


def _get_data_dir(cfg: configparser.ConfigParser) -> pathlib.Path:
    raw = cfg.get("paths", "data_dir", fallback="").strip()
    return pathlib.Path(raw) if raw else _default_data_dir()

def get_data_dir(cfg: configparser.ConfigParser) -> pathlib.Path:
    return _get_data_dir(cfg)

def get_db_path(cfg): return _get_data_dir(cfg) / "talon.db"

def get_salt_path(cfg): return _get_data_dir(cfg) / "talon.salt"


def get_rns_config_dir(cfg: configparser.ConfigParser) -> pathlib.Path:
    raw = cfg.get("paths", "rns_config_dir", fallback="").strip()
    if raw:
        return pathlib.Path(raw)
    try:
        from kivy.app import App  # type: ignore
        app = App.get_running_app()
        if app is not None:
            return pathlib.Path(app.user_data_dir) / "reticulum"
    except Exception:
        pass
    return pathlib.Path.home() / ".talon" / "reticulum"


def get_document_storage_path(cfg: configparser.ConfigParser) -> pathlib.Path:
    """Return the server's document storage directory.

    Reads ``[documents] storage_path`` from talon.ini.
    Falls back to ``<data_dir>/documents`` if not set.
    """
    raw = cfg.get("documents", "storage_path", fallback="").strip()
    return pathlib.Path(raw) if raw else _get_data_dir(cfg) / "documents"


def get_transport_priority(cfg: configparser.ConfigParser) -> tuple[str, ...]:
    from talon.constants import TRANSPORT_PRIORITY
    raw = cfg.get("network", "transport_priority", fallback="").strip()
    if not raw:
        return TRANSPORT_PRIORITY
    return tuple(x.strip() for x in raw.split(",") if x.strip())

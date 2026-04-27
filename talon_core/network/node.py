"""
Reticulum node initialisation.

Server mode: starts as both a Propagation Node and a Transport Node.
Client mode with RNode: starts as a Transport Node (enables LoRa mesh relay).
Client mode without RNode: peer-only, no transport duties.

Call init_reticulum() once at app startup (after DB is open).
Call shutdown_reticulum() on app exit.
"""
import pathlib
import typing
import importlib

import RNS

from talon_core.utils.logging import get_logger

_log = get_logger("network.node")

APP_NAME = "talon"
APP_ASPECT = "node"
_RNS_INTERFACE_MODULES = (
    "Interface",
    "LocalInterface",
    "AutoInterface",
    "BackboneInterface",
    "TCPInterface",
    "UDPInterface",
    "I2PInterface",
    "RNodeInterface",
    "SerialInterface",
    "KISSInterface",
    "AX25KISSInterface",
    "RNodeMultiInterface",
    "PipeInterface",
    "WeaveInterface",
)


def is_transport_started() -> bool:
    """Return whether the installed Reticulum transport stack is running."""
    is_started = getattr(RNS.Transport, "is_started", None)
    if callable(is_started):
        return bool(is_started())
    return getattr(RNS.Transport, "owner", None) is not None


def init_reticulum(
    config_dir: pathlib.Path,
    mode: typing.Literal["server", "client"],
    enable_transport: bool = False,
) -> RNS.Reticulum:
    """
    Initialise the Reticulum stack.

    Args:
        config_dir: Directory where Reticulum stores its configuration and keys.
        mode: "server" always enables transport + propagation.
              "client" enables transport only if enable_transport=True (RNode present).
        enable_transport: For client mode — set True when an RNode interface is available.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    _ensure_rns_interface_globals()
    reticulum = RNS.Reticulum(configdir=str(config_dir))

    if mode == "server" or enable_transport:
        is_started = getattr(RNS.Transport, "is_started", None)
        if callable(is_started) and not is_started():
            RNS.Transport.start(reticulum)
            _log.info("Transport node started (mode=%s)", mode)

    _log.info("Reticulum initialised (mode=%s, config=%s)", mode, config_dir)
    return reticulum


def _ensure_rns_interface_globals() -> None:
    """Load Reticulum interface modules explicitly for PyInstaller bundles."""
    reticulum_module = importlib.import_module("RNS.Reticulum")
    for module_name in _RNS_INTERFACE_MODULES:
        if hasattr(reticulum_module, module_name):
            continue
        try:
            module = importlib.import_module(f"RNS.Interfaces.{module_name}")
        except ModuleNotFoundError:
            continue
        setattr(reticulum_module, module_name, module)


def make_destination(
    identity: RNS.Identity,
    direction: int = RNS.Destination.IN,
    dest_type: int = RNS.Destination.SINGLE,
) -> RNS.Destination:
    """Create the primary TALON destination for this identity."""
    return RNS.Destination(identity, direction, dest_type, APP_NAME, APP_ASPECT)


def announce(destination: RNS.Destination, app_data: typing.Optional[bytes] = None) -> None:
    """Announce this node's presence on the network."""
    destination.announce(app_data=app_data)
    _log.info("Announced destination %s", RNS.prettyhexrep(destination.hash))


def shutdown_reticulum() -> None:
    """Gracefully stop the Reticulum transport stack."""
    try:
        RNS.Transport.exit_handler()
        _log.info("Reticulum transport stopped")
    except Exception as exc:
        _log.warning("Error during Reticulum shutdown: %s", exc)

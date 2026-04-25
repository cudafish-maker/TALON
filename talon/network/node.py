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

import RNS

from talon.utils.logging import get_logger

_log = get_logger("network.node")

APP_NAME = "talon"
APP_ASPECT = "node"


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
    reticulum = RNS.Reticulum(configdir=str(config_dir))

    if mode == "server" or enable_transport:
        if not RNS.Transport.is_started():
            RNS.Transport.start(reticulum)
            _log.info("Transport node started (mode=%s)", mode)

    _log.info("Reticulum initialised (mode=%s, config=%s)", mode, config_dir)
    return reticulum


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

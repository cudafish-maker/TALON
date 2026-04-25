"""
Reticulum Propagation Node setup — server exclusive.

The propagation node stores and forwards announces and link packets for
operators that are temporarily offline (e.g. RNode clients out of range).
This is a thin wrapper around RNS.Propagation that ties into the server's
already-running Reticulum instance.

Usage
-----
Call start_propagation_node() once at server startup, after init_reticulum().
Call stop_propagation_node() on shutdown before shutdown_reticulum().
"""
import pathlib
import typing

import RNS
import RNS.vendor.umsgpack as umsgpack  # bundled with RNS

from talon.utils.logging import audit, get_logger

_log = get_logger("server.propagation")

# Module-level reference so stop_propagation_node() can reach it.
_propagation_node: typing.Optional[RNS.Propagation] = None


def start_propagation_node(
    identity: RNS.Identity,
    storage_path: pathlib.Path,
    announce_delay: float = 2.0,
) -> RNS.Propagation:
    """
    Start the RNS Propagation Node on the already-running Reticulum instance.

    Parameters
    ----------
    identity:
        The server's RNS Identity (used to sign propagation announces).
    storage_path:
        Directory where the propagation node persists its message store.
        Created if it does not exist.
    announce_delay:
        Seconds to wait before the first announce after startup.
        Allows Transport to settle before broadcasting presence.

    Returns
    -------
    The active RNS.Propagation instance.

    Raises
    ------
    RuntimeError
        If a propagation node is already running, or if Transport has not
        been started (call init_reticulum() with mode="server" first).
    """
    global _propagation_node

    if _propagation_node is not None:
        raise RuntimeError("Propagation node is already running.")

    if not RNS.Transport.is_started():
        raise RuntimeError(
            "RNS Transport must be started before the propagation node. "
            "Call init_reticulum(mode='server') first."
        )

    storage_path.mkdir(parents=True, exist_ok=True)

    _propagation_node = RNS.Propagation(
        identity,
        storagepath=str(storage_path),
    )

    audit("propagation_node_started", storage_path=str(storage_path))
    _log.info("Propagation node started (storage=%s)", storage_path)
    return _propagation_node


def stop_propagation_node() -> None:
    """
    Gracefully shut down the propagation node.

    Safe to call even if the node was never started.
    """
    global _propagation_node

    if _propagation_node is None:
        return

    try:
        _propagation_node.exit_handler()
    except Exception as exc:
        _log.warning("Error stopping propagation node: %s", exc)
    finally:
        _propagation_node = None

    audit("propagation_node_stopped")
    _log.info("Propagation node stopped.")


def get_propagation_node() -> typing.Optional[RNS.Propagation]:
    """Return the active propagation node, or None if not started."""
    return _propagation_node

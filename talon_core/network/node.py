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
import os
import contextlib

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


class _ReticulumPanic(RuntimeError):
    """Raised when Reticulum tries to terminate the process during startup."""


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
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(config_dir, 0o700)
    except PermissionError as exc:
        raise RuntimeError(f"Could not secure Reticulum config directory {config_dir}") from exc
    _ensure_rns_interface_globals()
    rns_log_lines: list[str] = []
    try:
        with _rns_panic_as_exception():
            reticulum = RNS.Reticulum(
                configdir=str(config_dir),
                logdest=_rns_log_callback(rns_log_lines),
            )
    except _ReticulumPanic as exc:
        _reset_failed_reticulum_start()
        detail = _reticulum_startup_error_detail(rns_log_lines)
        raise RuntimeError(f"Reticulum startup failed: {detail}") from exc
    except Exception:
        _reset_failed_reticulum_start()
        raise

    if mode == "server" or enable_transport:
        is_started = getattr(RNS.Transport, "is_started", None)
        if callable(is_started) and not is_started():
            RNS.Transport.start(reticulum)
            _log.info("Transport node started (mode=%s)", mode)

    _log.info("Reticulum initialised (mode=%s, config=%s)", mode, config_dir)
    return reticulum


@contextlib.contextmanager
def _rns_panic_as_exception() -> typing.Iterator[None]:
    """Convert Reticulum's process-exiting panic into a catchable exception."""
    original_panic = RNS.panic

    def _panic() -> None:
        raise _ReticulumPanic("Reticulum panic during startup")

    RNS.panic = _panic
    try:
        yield
    finally:
        RNS.panic = original_panic


def _rns_log_callback(lines: list[str]) -> typing.Callable[[str], None]:
    def _callback(line: str) -> None:
        text = str(line)
        lines.append(text)
        if len(lines) > 50:
            del lines[:-50]
        if "[Error]" in text or "[Critical]" in text:
            _log.error("%s", text)
        elif "[Warning]" in text:
            _log.warning("%s", text)
        else:
            _log.info("%s", text)

    return _callback


def _reticulum_startup_error_detail(lines: list[str]) -> str:
    errors = [
        _clean_rns_log_line(line) for line in lines
        if "[Error]" in line or "[Critical]" in line
    ]
    errors = [
        line for line in errors
        if line
        and not line.startswith("Traceback ")
        and not line.startswith("An unhandled ")
    ]
    relevant = errors[-3:] if errors else lines[-3:]
    if relevant:
        return " ".join(relevant)
    return "Reticulum aborted startup without a diagnostic message."


def _clean_rns_log_line(line: str) -> str:
    text = str(line).splitlines()[0].strip()
    parts = text.split("] ", 2)
    if len(parts) == 3 and parts[0].startswith("[") and parts[1].startswith("["):
        return parts[2].strip()
    return text


def _reset_failed_reticulum_start() -> None:
    """Clear Reticulum singleton state after a failed constructor panic."""
    try:
        RNS.Transport.detach_interfaces()
    except Exception:
        pass
    try:
        RNS.Transport.interfaces = []
    except Exception:
        pass
    reticulum_cls = getattr(RNS, "Reticulum", None)
    if reticulum_cls is not None:
        for name, value in (
            ("_Reticulum__instance", None),
            ("_Reticulum__exit_handler_ran", False),
            ("_Reticulum__interface_detach_ran", False),
        ):
            try:
                setattr(reticulum_cls, name, value)
            except Exception:
                pass


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
    full_hash = destination.hash.hex()
    _log.info("Announced destination %s", full_hash[:12])
    _log.debug("Full announced destination hash: %s", RNS.prettyhexrep(destination.hash))


def shutdown_reticulum() -> None:
    """Gracefully stop the Reticulum transport stack."""
    try:
        RNS.Transport.exit_handler()
        _log.info("Reticulum transport stopped")
    except Exception as exc:
        _log.warning("Error during Reticulum shutdown: %s", exc)

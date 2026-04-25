"""
Transport interface detection and priority management.

Priority order: yggdrasil > i2p > tcp > rnode

WARNING: When TCP is active, the operator's IP address may be visible to other
network participants. The UI must display a warning and recommend using a VPN
whenever TCP is the active interface.
"""
import typing

from talon.constants import TRANSPORT_PRIORITY
from talon.utils.logging import get_logger

_log = get_logger("network.interfaces")

# Interface types that expose the operator's IP — trigger VPN warning in UI
IP_EXPOSING_INTERFACES: frozenset[str] = frozenset({"tcp"})


def detect_available_interfaces() -> list[str]:
    """
    Return a list of interface types believed to be available on this device,
    ordered by TRANSPORT_PRIORITY (highest first).

    This is a best-effort detection; actual reachability is confirmed by RNS.
    """
    available: list[str] = []
    for iface in TRANSPORT_PRIORITY:
        if _probe_interface(iface):
            available.append(iface)
    return available


def _probe_yggdrasil() -> bool:
    """Check for an interface address in the Yggdrasil range (200::/7)."""
    try:
        import ipaddress
        import socket
        yggdrasil_net = ipaddress.ip_network("200::/7")
        for *_, sockaddr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET6):
            addr_str = str(sockaddr[0]).split("%")[0]  # strip zone-ID suffix
            try:
                if ipaddress.ip_address(addr_str) in yggdrasil_net:
                    return True
            except ValueError:
                continue
        return False
    except Exception:
        return False


def _probe_i2p() -> bool:
    """Check if the I2P SAM bridge is reachable on localhost:7656."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 7656), timeout=1):
            return True
    except Exception:
        return False


# Default TCP probe endpoints.
# OPSEC note: these are public commercial DNS servers.  In high-OPSEC deployments
# override with LAN-local targets via configure_tcp_probe_endpoints() (called from
# app startup after reading [network] tcp_probe_hosts from talon.ini) to avoid
# revealing TALON activity to the internet.
_TCP_PROBE_ENDPOINTS: list[tuple[str, int]] = [
    ("8.8.8.8", 53),
    ("1.1.1.1", 53),
    ("8.8.4.4", 53),
]


def configure_tcp_probe_endpoints(hosts_str: str) -> None:
    """Parse '[network] tcp_probe_hosts' from talon.ini and replace the probe list.

    Format: comma-separated ``host:port`` pairs, e.g. ``192.168.1.1:53, 10.0.0.1:80``.
    Invalid entries are skipped with a warning.
    """
    global _TCP_PROBE_ENDPOINTS
    endpoints: list[tuple[str, int]] = []
    for entry in hosts_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            host, port_str = entry.rsplit(":", 1)
            endpoints.append((host.strip(), int(port_str.strip())))
        except (ValueError, AttributeError):
            _log.warning("Ignoring invalid tcp_probe_hosts entry: %r", entry)
    if endpoints:
        _TCP_PROBE_ENDPOINTS = endpoints
        _log.info("TCP probe endpoints updated: %s", _TCP_PROBE_ENDPOINTS)


def _probe_tcp() -> bool:
    """TCP is available if any probe endpoint is reachable.

    Multiple fallbacks so networks that block a single host do not falsely
    report TCP unavailable.  Configure endpoints via configure_tcp_probe_endpoints()
    to avoid contacting commercial DNS servers in high-OPSEC environments.
    """
    import socket
    for host, port in _TCP_PROBE_ENDPOINTS:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except Exception:
            continue
    return False


# Known RNode USB VID/PID pairs used for reliable device identification.
# Mark I uses the Silicon Labs CP2102; Mark II uses the QinHeng CH9102.
_RNODE_VID_PID: frozenset[tuple[int, int]] = frozenset({
    (0x10C4, 0xEA60),  # Silicon Labs CP2102 — Mark I RNode
    (0x1A86, 0x55D4),  # QinHeng CH9102 — Mark II RNode
})

# Device-name prefix patterns used as a fallback when VID/PID is unavailable.
_RNODE_NAME_PREFIXES: tuple[str, ...] = ("/dev/ttyUSB", "/dev/ttyACM", "COM")


def _probe_rnode() -> bool:
    """Check for a connected RNode serial device.

    Filters comports() by known RNode USB VID/PID pairs to avoid false
    positives from unrelated serial hardware (GPS receivers, Arduino boards,
    USB-to-serial adapters, etc.).  Falls back to device-name prefix matching
    when VID/PID information is not available from the OS.
    """
    try:
        import serial.tools.list_ports  # type: ignore
        for port in serial.tools.list_ports.comports():
            vid = getattr(port, "vid", None)
            pid = getattr(port, "pid", None)
            if vid is not None and pid is not None:
                if (vid, pid) in _RNODE_VID_PID:
                    return True
            else:
                # VID/PID unavailable — fall back to device name heuristic.
                if any(port.device.startswith(p) for p in _RNODE_NAME_PREFIXES):
                    return True
        return False
    except Exception:
        return False


_PROBERS: dict[str, typing.Callable[[], bool]] = {
    "yggdrasil": _probe_yggdrasil,
    "i2p":       _probe_i2p,
    "tcp":       _probe_tcp,
    "rnode":     _probe_rnode,
}


def _probe_interface(iface_type: str) -> bool:
    return _PROBERS.get(iface_type, lambda: False)()


def requires_vpn_warning(active_interfaces: list[str]) -> bool:
    """Return True if any active interface may expose the operator's IP."""
    return any(iface in IP_EXPOSING_INTERFACES for iface in active_interfaces)


def select_primary_interface(available: list[str]) -> typing.Optional[str]:
    """Return the highest-priority available interface, or None."""
    for iface in TRANSPORT_PRIORITY:
        if iface in available:
            return iface
    return None

# talon/net/reticulum.py
# Reticulum identity and link management.
#
# Reticulum is the networking layer that handles ALL communication
# in T.A.L.O.N. It provides:
# - End-to-end encryption between any two nodes
# - Automatic routing across different transport types
# - Identity-based addressing (no IP addresses needed)
# - Works over Internet (I2P, Yggdrasil, TCP) and radio (LoRa)
#
# Key concepts:
# - Identity: A cryptographic key pair that uniquely identifies a node.
#   Like a digital fingerprint — used instead of IP addresses.
# - Destination: An endpoint that can receive data. Identified by
#   the identity's public key hash.
# - Link: An encrypted connection between two destinations.
#   All data sent over a link is automatically encrypted.
# - Announce: A broadcast that tells the network "I exist at this
#   identity." Other nodes can then establish links to you.

import logging
import os

import RNS

from talon.net.interfaces import build_reticulum_config

log = logging.getLogger(__name__)

# The app name used in Reticulum destinations.
# All T.A.L.O.N. traffic is identified by this name.
APP_NAME = "talon"


def write_reticulum_config(
    talon_config: dict,
    is_server: bool,
    config_dir: str = None,
    rnode_override: dict = None,
) -> str:
    """Generate a Reticulum config file from T.A.L.O.N. YAML settings.

    Translates T.A.L.O.N.'s interface configuration into Reticulum's
    native config format and writes it to disk. Reticulum reads this
    file on startup to know which interfaces to activate.

    Args:
        talon_config: The merged T.A.L.O.N. config dict (default.yaml +
                      server.yaml or client.yaml).
        is_server: True for server, False for client.
        config_dir: Directory to write the config file. Defaults to
                    the platform data directory.
        rnode_override: Optional RNode interface config dict (from
                        RNodeManager.get_interface_config()) to override
                        the YAML-based RNode config with auto-detected
                        port and validated parameters.

    Returns:
        Path to the generated Reticulum config file.
    """
    if config_dir is None:
        from talon.platform import get_data_dir

        config_dir = os.path.join(get_data_dir(), "reticulum")

    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "config")

    # Build interface configs from T.A.L.O.N. YAML
    interfaces = build_reticulum_config(talon_config, is_server)

    # Apply RNode override from hardware detection
    if rnode_override and rnode_override.get("port"):
        interfaces["RNode"] = rnode_override

    # Reticulum general settings
    ret_config = talon_config.get("reticulum", {})
    enable_transport = ret_config.get("transport_node", False)

    # Write Reticulum config file format
    lines = ["[reticulum]\n"]
    lines.append(f"  enable_transport = {'Yes' if enable_transport else 'No'}\n")
    lines.append("  share_instance = Yes\n")
    lines.append("  shared_instance_port = 37428\n")
    lines.append("  instance_control_port = 37429\n")
    lines.append("\n")
    lines.append("[interfaces]\n")

    for name, iface in interfaces.items():
        iface_type = iface.get("type", "")
        lines.append(f"  [[{name}]]\n")
        lines.append(f"    type = {iface_type}\n")
        enabled = iface.get("interface_enabled", True)
        lines.append(f"    interface_enabled = {'True' if enabled else 'False'}\n")

        # Write interface-specific parameters
        for key, value in iface.items():
            if key in ("type", "interface_enabled"):
                continue
            if isinstance(value, bool):
                lines.append(f"    {key} = {'True' if value else 'False'}\n")
            else:
                lines.append(f"    {key} = {value}\n")
        lines.append("\n")

    with open(config_path, "w") as f:
        f.writelines(lines)

    log.info(
        "Wrote Reticulum config to %s with %d interface(s): %s",
        config_path,
        len(interfaces),
        ", ".join(interfaces.keys()),
    )
    return config_dir


def initialize_reticulum(
    config_path: str = None,
    talon_config: dict = None,
    is_server: bool = False,
    rnode_override: dict = None,
) -> RNS.Reticulum:
    """Start the Reticulum network stack.

    This must be called before any networking can happen.

    If talon_config is provided, generates a Reticulum config file
    from the T.A.L.O.N. YAML settings. Otherwise uses config_path
    directly (or the Reticulum default at ~/.reticulum/).

    Args:
        config_path: Path to an existing Reticulum config directory.
        talon_config: T.A.L.O.N. config dict — if provided, a
                      Reticulum config is generated from it.
        is_server: Whether this is a server instance.
        rnode_override: RNode interface config from RNodeManager.

    Returns:
        The Reticulum instance.
    """
    if talon_config is not None:
        config_path = write_reticulum_config(
            talon_config,
            is_server,
            config_dir=config_path,
            rnode_override=rnode_override,
        )
        log.info("Starting Reticulum with generated config at %s", config_path)
    else:
        log.info("Starting Reticulum with config at %s", config_path or "~/.reticulum/")

    # RNS keeps a process-wide singleton — calling RNS.Reticulum() a second
    # time raises OSError("Attempt to reinitialise Reticulum…"). That happens
    # when an earlier start() got past this point but failed later (e.g. in
    # setup_services()) and the user clicks login again. Reuse the running
    # instance instead so retries work cleanly.
    existing = RNS.Reticulum.get_instance()
    if existing is not None:
        log.warning("Reticulum already initialised in this process; reusing existing instance")
        return existing

    return RNS.Reticulum(config_path)


def create_identity(identity_path: str = None) -> RNS.Identity:
    """Create or load a Reticulum identity (key pair).

    If an identity file exists at the given path, it is loaded.
    If not, a new identity is created and saved there.

    Each operator has their own identity. The server has its own
    identity. These are used for encryption and authentication.

    Args:
        identity_path: File path to store/load the identity.
                       If None, creates a transient (temporary) identity.

    Returns:
        An RNS.Identity object containing the key pair.
    """
    if identity_path:
        # Try to load existing identity from file
        identity = RNS.Identity.from_file(identity_path)
        if identity is None:
            # No file found — create a new identity and save it
            identity = RNS.Identity()
            identity.to_file(identity_path)
        return identity
    else:
        return RNS.Identity()


def create_destination(
    identity: RNS.Identity,
    direction: str,
    app_name: str = APP_NAME,
    aspect: str = "default",
) -> RNS.Destination:
    """Create a Reticulum destination (a reachable endpoint).

    A destination is like a phone number — other nodes use it
    to establish encrypted links to this node.

    Args:
        identity: The identity that owns this destination.
        direction: "in" for receiving connections, "out" for initiating.
        app_name: The application name (always "talon").
        aspect: A sub-identifier (e.g., "sync", "chat", "heartbeat").

    Returns:
        An RNS.Destination object.
    """
    if direction == "in":
        return RNS.Destination(identity, RNS.Destination.IN, RNS.Destination.SINGLE, app_name, aspect)
    else:
        return RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, app_name, aspect)


def announce_destination(destination: RNS.Destination) -> None:
    """Announce this destination to the network.

    Broadcasts "I exist" so other nodes can find and connect to
    this destination. On LoRa, this propagates hop-by-hop through
    relay nodes.

    Args:
        destination: The destination to announce.
    """
    destination.announce()

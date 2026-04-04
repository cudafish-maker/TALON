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

import RNS


# The app name used in Reticulum destinations.
# All T.A.L.O.N. traffic is identified by this name.
APP_NAME = "talon"


def initialize_reticulum(config_path: str = None) -> RNS.Reticulum:
    """Start the Reticulum network stack.

    This must be called before any networking can happen.
    It reads the Reticulum config file and starts all configured
    network interfaces (Yggdrasil, I2P, TCP, RNode).

    Args:
        config_path: Optional path to a custom Reticulum config file.
                     If None, uses the default (~/.reticulum/).

    Returns:
        The Reticulum instance. Keep a reference to this — it runs
        in the background managing all network traffic.
    """
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
        return RNS.Destination(
            identity, RNS.Destination.IN, app_name, aspect
        )
    else:
        return RNS.Destination(
            identity, RNS.Destination.OUT, app_name, aspect
        )


def announce_destination(destination: RNS.Destination) -> None:
    """Announce this destination to the network.

    Broadcasts "I exist" so other nodes can find and connect to
    this destination. On LoRa, this propagates hop-by-hop through
    relay nodes.

    Args:
        destination: The destination to announce.
    """
    destination.announce()

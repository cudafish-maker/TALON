# talon/net/interfaces.py
# Network interface configuration for T.A.L.O.N.
#
# This module generates the Reticulum configuration needed to
# enable each transport interface (Yggdrasil, I2P, TCP, RNode).
#
# Reticulum uses its own config file format. This module reads
# the T.A.L.O.N. YAML config and produces the corresponding
# Reticulum interface configuration.
#
# Each interface type connects to the network differently:
# - Yggdrasil: TCP connection to the Yggdrasil IPv6 address
# - I2P: Tunneled connection through the local I2P router
# - TCP: Direct TCP connection (WARNING: exposes IP)
# - RNode: Serial connection to LoRa radio hardware


def build_reticulum_config(talon_config: dict, is_server: bool) -> dict:
    """Build Reticulum interface configuration from T.A.L.O.N. config.

    Reads the interfaces section of server.yaml or client.yaml
    and produces the configuration that Reticulum needs to set up
    each network interface.

    Args:
        talon_config: The loaded T.A.L.O.N. YAML configuration.
        is_server: True if building config for the server,
                   False for a client.

    Returns:
        Dictionary of Reticulum interface configurations.
    """
    interfaces = {}
    iface_config = talon_config.get("interfaces", {})

    # --- Yggdrasil Interface ---
    ygg = iface_config.get("yggdrasil", {})
    if ygg.get("enabled"):
        if is_server:
            # Server LISTENS for incoming connections on its
            # Yggdrasil IPv6 address.
            interfaces["Yggdrasil"] = {
                "type": "TCPServerInterface",
                "listen_ip": ygg.get("listen_address", ""),
                "listen_port": ygg.get("listen_port", 4243),
            }
        else:
            # Client CONNECTS to the server's Yggdrasil address.
            interfaces["Yggdrasil"] = {
                "type": "TCPClientInterface",
                "target_host": ygg.get("target_host", ""),
                "target_port": ygg.get("target_port", 4243),
            }

    # --- I2P Interface ---
    i2p = iface_config.get("i2p", {})
    if i2p.get("enabled"):
        if is_server:
            # Server creates an I2P tunnel for clients to connect to.
            interfaces["I2P"] = {
                "type": "I2PInterface",
                "peers": [],
                "listen_port": i2p.get("listen_port", 4244),
            }
        else:
            # Client connects through I2P to the server's address.
            interfaces["I2P"] = {
                "type": "I2PInterface",
                "peers": [i2p.get("i2p_address", "")],
                "target_port": i2p.get("target_port", 4244),
            }

    # --- TCP Interface ---
    tcp = iface_config.get("tcp", {})
    if tcp.get("enabled"):
        if is_server:
            # Server listens on a TCP port.
            # WARNING: Clients connecting via TCP expose their IP.
            interfaces["TCP"] = {
                "type": "TCPServerInterface",
                "listen_ip": tcp.get("bind_address", "0.0.0.0"),
                "listen_port": tcp.get("listen_port", 4242),
            }
        else:
            # Client connects directly to server's IP.
            # WARNING: This exposes the client's real IP address.
            interfaces["TCP"] = {
                "type": "TCPClientInterface",
                "target_host": tcp.get("target_host", ""),
                "target_port": tcp.get("target_port", 4242),
            }

    # --- RNode Interface (LoRa Radio) ---
    rnode = iface_config.get("rnode", {})
    if rnode.get("enabled"):
        # RNode config is the same for server and client.
        # Both transmit and receive on the same frequency.
        # Clients also act as transport nodes to enable mesh relay.
        interfaces["RNode"] = {
            "type": "RNodeInterface",
            "port": rnode.get("port", "/dev/ttyUSB0"),
            "frequency": rnode.get("frequency", 915000000),
            "bandwidth": rnode.get("bandwidth", 125000),
            "spreading_factor": rnode.get("spreading_factor", 10),
            "coding_rate": rnode.get("coding_rate", 5),
            "tx_power": rnode.get("tx_power", 17),
        }

    # --- Default fallback ---
    # If no transport is enabled in the config (e.g. fresh install,
    # operator hasn't picked one yet), enable AutoInterface so the
    # node can still discover and reach peers on the local subnet.
    # AutoInterface uses link-local discovery on the local network
    # only — it does not expose anything beyond the LAN.
    if not interfaces:
        interfaces["Default"] = {
            "type": "AutoInterface",
        }

    return interfaces

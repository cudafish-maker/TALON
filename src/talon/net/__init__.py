# talon/net/__init__.py
# Networking subsystem for T.A.L.O.N.
# Wraps the Reticulum Network Stack (RNS) to handle:
# - Identity management (cryptographic keys for each operator)
# - Link establishment (encrypted connections between nodes)
# - Transport detection and fallback (Yggdrasil → I2P → TCP → RNode)
# - Heartbeat monitoring
# - Interface configuration (I2P, Yggdrasil, TCP, RNode 915MHz)

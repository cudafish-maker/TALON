# Reticulum Ownership

Reticulum is non-negotiable and remains inside Python core on desktop and
mobile.

## Hard Rules

- Core owns RNS config, identity load/create, destination setup, link lifecycle,
  path recall, announces, packet/resource framing, and shutdown.
- TALON sync, enrollment, heartbeat, revocation, document transfer, and chat
  traffic must use Reticulum.
- Desktop and mobile clients must not open independent TALON sync sockets.
- A non-Python Reticulum implementation would require a separate audited
  compatibility project before TALON can depend on it.

## Interface Priority

Transport preference is:

1. Yggdrasil
2. I2P
3. TCP
4. RNode

TCP exposes an operator IP address and must surface a VPN warning in UI read
models. RNode/LoRa is bandwidth constrained and should avoid large document
transfers.

## Current Runtime Shape

- Server creates a dedicated `talon.server` destination.
- Client enrollment uses a combined `TOKEN:SERVER_HASH` string.
- Enrollment accepts the installed Reticulum identity hash length by deriving
  the expected hex length from `RNS.Identity.TRUNCATED_HASHLENGTH`.
- Reticulum startup supports installed RNS versions that start transport during
  `RNS.Reticulum(...)` and do not expose `RNS.Transport.is_started()`.
- Core explicitly loads Reticulum interface modules before startup so PyInstaller
  bundles do not lose RNS interface globals that are normally discovered through
  filesystem globbing.
- Broadband sync keeps a persistent RNS link per client.
- LoRa remains a polling fallback.
- Large payloads use shared framing or RNS Resource transfer where appropriate.

## Mobile Gate

The Android spike must prove that Chaquopy can import and initialize `RNS`, load
isolated mobile RNS config dirs, create/load Reticulum identity, and complete a
loopback or TCP Reticulum sync test.

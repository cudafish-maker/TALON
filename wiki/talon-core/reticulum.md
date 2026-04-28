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
- Client RNS links identify with the local Reticulum identity before TALON
  enrollment, sync, heartbeat, client push, or document request messages.
- Server link callbacks cache the identified remote RNS hash and resolve the
  matching active operator before dispatching privileged message families.
- Authorization ignores legacy JSON `operator_rns_hash` and enrollment
  `rns_hash` values; those fields are compatibility-only if present.
- Enrollment accepts the installed Reticulum identity hash length by deriving
  the expected hex length from `RNS.Identity.TRUNCATED_HASHLENGTH`.
- Client and server Reticulum identities are stored as encrypted
  `client.identity.enc` / `server.identity.enc` files after SQLCipher unlock.
- Reticulum startup supports installed RNS versions that start transport during
  `RNS.Reticulum(...)` and do not expose `RNS.Transport.is_started()`.
- Core explicitly loads Reticulum interface modules before startup so PyInstaller
  bundles do not lose RNS interface globals that are normally discovered through
  filesystem globbing.
- Broadband sync keeps a persistent RNS link per client.
- LoRa remains a polling fallback.
- Large payloads use shared framing or RNS Resource transfer where appropriate.
- Server resource callbacks reject unsolicited resources. Client resource
  callbacks accept only pending document responses, and both sides enforce
  encoded chunk, decoded chunk, and total reassembly byte budgets.
- When a server operator is revoked, active push links for that authenticated
  operator are notified, closed, and removed from the active-client registry.

## Mobile Gate

The Android spike must prove that Chaquopy can import and initialize `RNS`, load
isolated mobile RNS config dirs, create/load Reticulum identity, and complete a
loopback or TCP Reticulum sync test.

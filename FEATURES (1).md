# T.A.L.O.N.
**Tactical Awareness & Linked Operations Network**

A self-hosted, encrypted, mesh-capable coordination platform built for resilient team operations when conventional infrastructure fails. No internet dependency. No cloud. No telemetry — your network, your data.

---

## Connectivity

Runs over **Yggdrasil**, **I2P**, **direct TCP**, or **RNode LoRa (915 MHz)** radio — built on the [Reticulum](https://reticulum.network/) mesh networking stack. LoRa nodes act as automatic relay points. The fastest available path is selected automatically, and clients fall back gracefully to cached data when the server is unreachable. Can be configured to avoid all public DNS queries for high-OPSEC deployments.

---

## Security

- **Database**: AES-256 at rest (SQLCipher); passphrase-to-key via Argon2id
- **Sensitive fields** (SITREPs, audit log): additional field-level encryption via PyNaCl/libsodium
- **Direct messages**: end-to-end encrypted — server routes but cannot read
- **Transport**: encrypted at every hop by Reticulum
- **Operator leases**: each operator must be periodically re-approved (24 hr default); expired leases soft-lock the client
- **Hard revocation**: identity burned and wiped; group key rotation triggered automatically
- **Audit log**: fully encrypted, append-only record of all server operations

---

## Operator Management

Enrollment is invite-only via server-generated one-time tokens (24 hr expiry, single-use). No self-registration. The server operator manages skills, profile fields, and lease status per operator. Revocation is immediate and irreversible.

**Built-in skills:** medic · comms · logistics · intelligence · recon · navigation · engineering · security

---

## Situational Awareness

Interactive tactical map with switchable base layers (OpenStreetMap, Satellite, Topo). Tap any marker to open a detail panel without leaving the map.

- **Asset markers** — color-coded by category: personnel, safe houses, caches, rally points, vehicles
- **Zone overlays** — AO, DANGER, RESTRICTED, FRIENDLY, OBJECTIVE, and custom polygons
- **Waypoint routes** — ordered sequences plotted directly on the map
- Map tiles pre-cached for your area of operations

---

## Asset Tracking

Assets are tracked by category with GPS coordinates entered manually or picked on the map. A **two-party verification workflow** keeps assets flagged as unverified until physically confirmed by a second operator. Status is always visible: confirmed (green), unverified (grey), or mission-assigned (amber). Changes sync to all connected clients in real time.

---

## Mission Management

Full OPORD-style workflow built around a 5-step wizard: **Parameters → Timeline → Assets → Objectives → Review**. Covers mission type, priority, operational phases, asset assignment, AO polygon, and waypoint routes.

Approval flow: `pending → active → completed / aborted / rejected`

Each approved mission automatically gets a dedicated **#mission-\<name\>** chat channel.

---

## SITREPs

Five severity tiers with escalating notification behavior:

| Level | Behavior |
|---|---|
| ROUTINE | 3-second auto-dismiss |
| PRIORITY | 5-second auto-dismiss |
| IMMEDIATE | Half-screen modal (must dismiss) |
| FLASH | Full-screen takeover (must dismiss) |
| FLASH OVERRIDE | Full-screen takeover (must dismiss) |

SITREPs are append-only, field-encrypted, and can be linked to a mission or asset. Audio alerts are opt-in only.

---

## Communications

Channels organized by purpose: Emergency, All-Hands, Mission, Squad, and Direct Message. System defaults include `#flash`, `#general`, `#sitrep-feed`, and `#alerts`. Per-mission channels are auto-created on approval. Supports urgent message flagging, grid reference embedding, and custom channels. Direct messages are end-to-end encrypted.

---

## Document Repository

Server-hosted file storage for all enrolled operators. Uploads pass through a security pipeline: 50 MB cap, filename sanitization, extension/MIME blocklist, EXIF stripping via image re-encoding, and SHA-256 integrity verification. Files are stored with field encryption and opaque internal filenames. Office/ODF formats display a macro-risk warning on download.

---

## Offline Operation

All data is locally cached in an encrypted on-device database. Records created offline are queued and pushed on reconnect. Sync is delta-based (version numbers only). Server version wins on conflict; conflicts are saved as amendments for review. LoRa mode uses 2-minute sync intervals and automatic message chunking at the 380-byte MTU limit.

---

## Administration

The server operator has singular authority over all enrolled operators: lease management, revocation, enrollment token generation, and a searchable encrypted audit log. Server operator can read all group channels; DMs remain end-to-end encrypted.

---

## Interface & Platform

Dark tactical theme (near-black, tactical green, amber, red). Persistent collapsible nav rail with badge counters. Three-column desktop layout: nav rail + map + context panel. User-configurable font scaling.

**Runs on:** Linux · Windows · Android  
**Server:** Linux (Raspberry Pi-class hardware sufficient for small teams)  
**Config:** single `talon.ini` file · self-hosted · no accounts · no telemetry

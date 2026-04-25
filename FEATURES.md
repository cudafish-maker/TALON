# T.A.L.O.N. — Feature Overview

**Tactical Awareness & Linked Operations Network**
Civilian command-and-control / situational awareness platform designed for resilient coordination when conventional infrastructure fails.

---

## Core Value Proposition

TALON is a self-hosted, encrypted, mesh-capable coordination platform. It is not dependent on the internet, cloud services, or any third-party infrastructure. All data stays within your network. It is designed for teams that need reliable communication, awareness, and coordination under austere or contested conditions.

---

## Connectivity & Networking

**Works when the internet doesn't.**

- Built on [Reticulum](https://reticulum.network/) — a cryptography-based mesh networking stack
- Runs over **Yggdrasil**, **I2P**, **direct TCP**, or **RNode LoRa (915 MHz)** radios
- LoRa radio nodes act as mesh relay points, automatically extending range
- Priority-based transport selection: fastest/most reliable path chosen automatically
- Configurable to avoid public DNS queries entirely (high-OPSEC deployments)
- Clients fall back gracefully to cached data when the server is unreachable

---

## Security & Encryption

**End-to-end encrypted storage. No trust required.**

- Database encrypted at rest with **AES-256 (SQLCipher)**; passphrase never stored
- Passphrase-to-key derivation via **Argon2id** (resistant to GPU/ASIC brute-force)
- Sensitive fields (SITREPs, audit log) additionally encrypted at the field level with **PyNaCl / libsodium**
- Direct messages: end-to-end encrypted (server routes but cannot read)
- Transport encryption handled by Reticulum at every hop
- **Operator lease system**: each operator must be periodically re-approved by the server (24 hr default); expired leases soft-lock the client
- **Hard revocation**: operator identity burned and wiped; group key rotation triggered for remaining team
- Full encrypted **audit log** of all server operations: enrollments, revocations, data changes

---

## Enrollment & Operator Management

**Invite-only. No self-registration.**

- Enrollment is **server-generated one-time token only** — operators cannot self-register
- Tokens expire after 24 hours and are single-use
- Server operator manages skills, profile fields, and lease status per operator
- Predefined skills: medic, comms, logistics, intelligence, recon, navigation, engineering, security
- Custom profile fields supported
- Operator revocation is immediate and irreversible

---

## Situational Awareness — The Map

**Everything on one tactical map.**

- Interactive tile map with three switchable base layers: **OpenStreetMap, Satellite (ESRI), Topo**
- **Asset markers** color-coded by category (personnel, safe houses, caches, rally points, vehicles)
- **Zone polygon overlays**: AO, DANGER, RESTRICTED, FRIENDLY, OBJECTIVE, custom — translucent fills with type-specific colors
- **Waypoint routes** plotted as ordered sequences on the map
- Tap any marker to open a detail panel without leaving the map
- Polygon drawing and waypoint route creation tools built in
- Map tiles pre-cached for your area of operations

---

## Asset Tracking

**Know where your resources are and whether they've been confirmed.**

- Asset categories: **Personnel, Safe Houses, Caches, Rally Points, Vehicles, Custom**
- GPS coordinates entered manually or picked directly on the map
- **Two-party verification workflow**: asset stays "unverified" until physically confirmed by a second operator or the server
- Verification status always visible (green = confirmed, grey = unverified, amber = mission-assigned)
- Mission allocation tracking (which mission an asset is assigned to)
- Changes sync to all connected clients in real time

---

## Mission Management (OPORD-style)

**Full operational order workflow, not just a task list.**

5-step mission creation wizard covering:

1. **Parameters** — designation, type (Reconnaissance / Direct Action / Logistics / Medevac / Custom), priority, intent, lead coordinator, constraints
2. **Timeline** — activation time, operational phases, staging and demobilization locations
3. **Assets** — assign from available pool; support resources (medical, logistics, comms, equipment)
4. **Objectives** — primary/secondary objectives, AO polygon, waypoint routes, key locations
5. **Review** — full summary before submission

Mission approval workflow: `pending → active → completed / aborted / rejected` (server controls final state).  
Each approved mission automatically gets its own dedicated **#mission-\<name\>** chat channel.

---

## SITREP System (Situation Reports)

**Severity-tiered alerts that scale with urgency.**

Five severity levels with escalating notification behavior:

| Level | Behavior |
|-------|----------|
| ROUTINE | 3-second auto-dismissing notification |
| PRIORITY | 5-second auto-dismissing notification |
| IMMEDIATE | Half-screen modal (must be dismissed) |
| FLASH | Full-screen takeover (must be dismissed) |
| FLASH OVERRIDE | Full-screen takeover (must be dismissed) |

- Audio alerts for FLASH/FLASH OVERRIDE are **opt-in only** — never automatic
- SITREPs are **append-only**: no operator can edit or delete (server operator can delete)
- All SITREP bodies are field-encrypted
- Can be linked to a mission or asset

---

## Communications (Chat)

**Structured channels, not an open chatroom.**

- Organized by purpose: **Emergency, All-Hands, Mission, Squad, Direct Message**
- System default channels: `#flash`, `#general`, `#sitrep-feed`, `#alerts`
- Auto-created per-mission channels on mission approval
- Custom channels supported
- **Urgent message flag** for time-sensitive traffic
- **Grid reference embedding** in messages
- Direct messages: deterministically named, encrypted (server routes but cannot read)

---

## Document Repository

**Secure file storage accessible to the whole team.**

- Server-hosted file repository accessible to all enrolled operators
- Extensible security pipeline for uploads:
  - 50 MB size cap
  - Filename sanitization (strips paths, rejects dotfiles)
  - Extension and MIME type blocklist
  - Image re-encoding to strip **EXIF metadata** and prevent polyglot exploits
  - SHA-256 integrity verification
  - Field-encrypted storage (opaque internal filenames)
- Macro-risk warning displayed for Office/ODF formats on download
- File type icons for quick visual identification (PDF, image, video, audio, archive, spreadsheet, etc.)

---

## Offline-First Operation

**Disconnected is a normal state, not an error.**

- All data is locally cached in an encrypted on-device database
- Records created offline are queued and pushed to the server on reconnect
- Delta sync via version numbers — only changed records are transferred
- Conflict resolution: server version wins; conflicts saved as amendments for review
- Smart message fragmentation prevents silent data loss at LoRa MTU limits (380-byte threshold with automatic chunking)
- LoRa mode uses longer sync intervals (2 min) to avoid saturating low-bandwidth radio links

---

## Server-Exclusive Administration

**One operator. Full authority.**

- **Clients screen**: view all enrolled operators, lease status, revocation controls, skills/profile editing
- **Enrollment screen**: generate and manage one-time tokens; copy combined `TOKEN:SERVER_HASH` string for distribution
- **Audit log viewer**: searchable, color-coded encrypted log of all server operations
- **Keys screen**: key management
- Server operator can read all group channels (DMs are still end-to-end encrypted)
- No tiered permissions — server operator has singular authority

---

## Interface

**Dark tactical theme. Built for readability under stress.**

- Near-black background, tactical green primary, amber warning, red danger
- Persistent collapsible navigation rail (never covers the map)
- Badge counters on nav icons show unseen updates per section
- Three-column desktop layout: nav rail + map + context panel
- Context panel shows asset/zone/waypoint detail on tap, or situation summary by default
- User-configurable **font scaling** (global, persisted) for accessibility
- Cross-platform: **Linux, Windows, Android**

---

## Platform & Deployment

- Self-hosted: you run the server, you own the data
- No accounts, no cloud, no telemetry
- Server: Linux (Raspberry Pi-class hardware is sufficient for small teams)
- Clients: Linux, Windows, Android
- Configuration via a single `talon.ini` file
- Packaged binaries via PyInstaller (desktop) and Buildozer (Android)

---

*TALON is open-source and designed for teams that cannot afford to depend on infrastructure they do not control.*

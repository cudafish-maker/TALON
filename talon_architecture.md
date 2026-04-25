---
name: T.A.L.O.N. Architecture Plan
description: Full architecture plan for T.A.L.O.N. (Tactical Awareness & Linked Operations Network) — civilian command and awareness platform built on Reticulum
type: project
---

## T.A.L.O.N. — Tactical Awareness & Linked Operations Network

Personal project and team tool. Civilian command-and-control / situational awareness platform inspired by A.T.O.C. (atoc.io).

**Why:** Resilient tactical coordination over mesh networks, works when conventional infrastructure fails.

### Stack
- **Language:** Python (Reticulum is Python-native)
- **UI:** Kivy/KivyMD (cross-platform: Linux, Windows, Android)
- **Database:** SQLCipher (encrypted SQLite)
- **Crypto:** Argon2id (key derivation), PyNaCl/libsodium (field encryption)
- **Transport:** Reticulum network stack
- **Interfaces:** I2P, Yggdrasil, RNode 915MHz
- **Server:** User's local machine (running Claude Code)

### Reticulum Topology
- Server: Propagation Node + Transport Node
- Clients with RNode: also Transport Nodes (enables mesh relay over LoRa)
- Yggdrasil/I2P: direct client-to-server
- LoRa: mesh — clients relay for each other back to server

### Security Model
- Reticulum: transport encryption
- SQLCipher: data-at-rest
- Lease token system: 24hr soft lock (not data destruction)
  - Expired lease → app locks, server operator approves re-auth
- Revocation: hard shred + identity burn + group key rotation
- Client enrollment: server-generated one-time token only
- DMs: end-to-end encrypted (server routes but cannot read)
- Group chat: group key (server CAN read)
- Server operator has full authority, single permission level

### Data Model
- **Operators:** callsign, skills (predefined + custom), profile (self-edit only, server can edit any)
- **Assets:** people, safe houses, caches, rally points, vehicles, custom categories. Unverified until second operator or server confirms physically.
- **SITREPs:** predefined templates + freeform. Append-only (operators cannot delete/edit previous entries). Server-only deletion. Importance levels: ROUTINE, PRIORITY, IMMEDIATE, FLASH, FLASH OVERRIDE. Notifications on create/append to all other clients + server.
- **Missions:** objectives, assigned operators, linked assets/waypoints/zones/SITREPs. Any operator creates, server-only delete/abort.
- **Routes/Waypoints:** ordered waypoint sequences, linked to missions
- **Zones:** polygon boundaries (AO, DANGER, RESTRICTED, FRIENDLY, OBJECTIVE, custom)
- **Documents:** uploadable files/manuals stored on server. Any operator uploads, server-only delete. Large files broadband-only.
- **Chat:** group channels, custom channels, DMs, mission-auto-channels. Default channels: #general, #sitrep-feed, #alerts, #mission-[name]. Server operator can see all including DMs.
- **Audit Log:** all events timestamped and encrypted on server

### Sync Protocol
- Delta sync (version numbers per record)
- Transport priority: Yggdrasil > I2P > RNode
- RNode has FULL map/asset/SITREP/chat functionality on cached tiles
- Only documents and new tile downloads queued for broadband
- Heartbeat: 60s broadband, 2min LoRa
- Conflict resolution: server wins, conflicts saved as amendments
- Connection mode: online-first, detect uplink, fall back to cached data if no connection
- Map tiles pre-cached for AO (all 3 layers: OSM, Satellite, Topo)

### UI Layouts
- **Server (laptop):** three-column (nav + map + context panel) with server-exclusive sections (clients, audit, enroll, keys)
- **Client laptop:** three-column (nav + map + context panel)
- **Client Android (landscape):** nav rail + map + slideable context panel. Map never fully disappears.
- **Dark tactical theme:** near-black background, tactical green primary, amber warning, red danger
- Notification overlays scale with SITREP importance up to full-screen takeover for FLASH OVERRIDE

### Build/Release
- Git branches: dev (working), main (stable)
- GitHub Actions: tag on main → builds Linux (PyInstaller), Windows (PyInstaller), Android (Buildozer)
- Platform build configs in build/ directory, not separate source folders

### How to apply
This is the master reference for all T.A.L.O.N. development decisions. Verify against current code state before acting on specifics.

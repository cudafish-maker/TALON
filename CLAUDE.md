# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Wiki

**Always read [wiki/INDEX.md](wiki/INDEX.md) at the start of every session.** It contains the current build status, what's done, what's next, and any manual changes the operator has made between sessions. The wiki is the authoritative source of project state — more current than this file.

- [wiki/INDEX.md](wiki/INDEX.md) — session snapshot, done/TODO, manual changes
- [wiki/status.md](wiki/status.md) — per-module implementation status
- [wiki/decisions.md](wiki/decisions.md) — key technical decisions and rationale
- [wiki/bugs.md](wiki/bugs.md) — open bugs and issues
- [wiki/fixed_bugs.md](wiki/fixed_bugs.md) — resolved bugs archive
- [wiki/features.md](wiki/features.md) — feature planning and backlog

**Bug tracking workflow:** When a bug from `bugs.md` is fixed, move its full entry to `fixed_bugs.md` and update the summary counts in both files.

**Feature tracking workflow:** After implementing or editing any feature, update the relevant entry in `features.md` and `index.md`— adjust the `[x]`/`[~]`/`[ ]` status and description to match the current implementation state.

## Project

**T.A.L.O.N.** — Tactical Awareness & Linked Operations Network. Civilian command-and-control / situational awareness platform inspired by A.T.O.C. (atoc.io). Designed for resilient coordination over mesh networks when conventional infrastructure fails.

## Stack

- **Language:** Python (Reticulum is Python-native)
- **UI:** Kivy / KivyMD (cross-platform: Linux, Windows, Android)
- **Database:** SQLCipher (encrypted SQLite)
- **Crypto:** Argon2id (key derivation), PyNaCl / libsodium (field encryption)
- **Transport:** Reticulum network stack
- **Interfaces:** I2P, Yggdrasil, RNode 915 MHz LoRa

## Build & Run

Build configs live in [build/](build/) — not in separate source folders.

```bash
# Development
python main.py                 # run app (server or client mode, set in config)

# Packaging
# Linux / Windows: PyInstaller (triggered via GitHub Actions on tag → main)
# Android: Buildozer (triggered via GitHub Actions on tag → main)
```

Git branching: `dev` = active work, `main` = stable. Tag `main` to trigger CI builds.

## Architecture

### Network topology

- **Server:** Reticulum Propagation Node + Transport Node
- **Clients with RNode:** also act as Transport Nodes (LoRa mesh relay back to server)
- **Yggdrasil / I2P clients:** connect directly to server
- Transport priority for sync: Yggdrasil > I2P > RNode

### Security model

- Reticulum handles transport encryption
- SQLCipher handles data-at-rest
- Lease token system: 24 hr soft lock (no data destruction); expired lease locks app until server re-approves
- Revocation: hard shred + identity burn + group key rotation
- Enrollment: server-generated one-time token only — no self-registration
- DMs: end-to-end encrypted (server routes, cannot read)
- Group chat: group key (server CAN read)
- Server operator has singular authority; no tiered permissions

### Data model

| Entity | Key rules |
|--------|-----------|
| **Operators** | callsign, predefined + custom skills; self-edit profile; server edits any |
| **Assets** | people / safe houses / caches / rally points / vehicles / custom; unverified until 2nd operator or server physically confirms |
| **SITREPs** | predefined templates + freeform; append-only; server-only deletion; levels: ROUTINE → PRIORITY → IMMEDIATE → FLASH → FLASH OVERRIDE; notifies all on create/append |
| **Missions** | any operator creates; server-only delete/abort; linked to assets, waypoints, zones, SITREPs |
| **Routes/Waypoints** | ordered sequences, mission-linked |
| **Zones** | polygon boundaries: AO, DANGER, RESTRICTED, FRIENDLY, OBJECTIVE, custom |
| **Documents** | server-stored files; any operator uploads; server-only delete; large files broadband-only |
| **Chat** | #general, #sitrep-feed, #alerts, #mission-[name] defaults + custom + DMs; server operator sees all |
| **Audit Log** | all events timestamped, server-side encrypted |

### Sync protocol

- Delta sync via per-record version numbers
- Heartbeat: 60 s broadband / 2 min LoRa
- Conflict resolution: server wins; conflicts saved as amendments
- Map tiles pre-cached for AO (OSM, Satellite, Topo layers)
- Documents and new tile downloads queued for broadband only
- Mode: online-first → fall back to cached data on no connection

### UI

- **Dark tactical theme:** near-black background, tactical green primary, amber warning, red danger
- **Server layout:** three-column (nav + map + context panel) + server-exclusive sections (clients, audit, enroll, keys)
- **Client laptop:** three-column (nav + map + context panel)
- **Client Android (landscape):** nav rail + map + slideable context panel; map never fully disappears
- SITREP notification overlays scale with importance up to full-screen takeover for FLASH OVERRIDE

## Critical conventions

- **FLASH SITREP audio alerts must be opt-in only** — never automatic. This is a hard operator-safety requirement.
- Server operator has full authority — there is a single permission level, no role hierarchy to add.
- Unverified assets must stay unverified until physically confirmed by a second party.

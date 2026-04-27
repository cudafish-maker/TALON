# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this
repository.

## Wiki

Always read [wiki/INDEX.md](wiki/INDEX.md) at the start of every session. The
wiki is the authoritative project state.

The active source document is
[wiki/platform_split_plan.md](wiki/platform_split_plan.md). TALON is being split
into:

- [wiki/talon-core/INDEX.md](wiki/talon-core/INDEX.md) - shared Python core.
- [wiki/talon-desktop/INDEX.md](wiki/talon-desktop/INDEX.md) - Linux/Windows
  PySide6 desktop.
- [wiki/talon-mobile/INDEX.md](wiki/talon-mobile/INDEX.md) - Android native UI
  with Chaquopy.

Other active wiki files:

- [wiki/bugs.md](wiki/bugs.md) - current cross-project bug index.
- [wiki/archive/INDEX.md](wiki/archive/INDEX.md) - historical docs, fixed bugs,
  and completed checklists.

Legacy root docs such as `features.md`, `status.md`, `decisions.md`,
`Phase_2_Network_sync.md`, `document_management.md`, `map.md`, and
`linux_release_readiness.md` have been distilled into the project wikis and
archived under [wiki/archive/legacy/](wiki/archive/legacy/).

## Wiki Workflows

Bug tracking:

- Active cross-project issues live in [wiki/bugs.md](wiki/bugs.md).
- Platform-specific details also belong in the relevant project function doc.
- When a bug is fixed, move the full entry to
  [wiki/archive/fixed_bugs.md](wiki/archive/fixed_bugs.md), update counts, and
  update affected project docs.

Feature tracking:

- Update the relevant project function doc under `wiki/talon-core/`,
  `wiki/talon-desktop/`, or `wiki/talon-mobile/`.
- Update the project `INDEX.md` if status, blockers, or acceptance criteria
  changed.
- Update root [wiki/INDEX.md](wiki/INDEX.md) only for cross-project status.

Architecture changes:

- Read [wiki/platform_split_plan.md](wiki/platform_split_plan.md) first.
- Keep Reticulum, RNS identity, sync, enrollment, lease, revocation, document
  transfer, and chat traffic inside `talon-core`.
- Treat Kivy/KivyMD as legacy migration state, not the target architecture.

## Project

T.A.L.O.N. - Tactical Awareness & Linked Operations Network. Civilian
command-and-control / situational awareness platform designed for resilient
coordination over mesh networks when conventional infrastructure fails.

## Target Stack

- Shared core: Python.
- Desktop: Python plus PySide6/Qt, importing `talon-core` in-process.
- Mobile: Android native UI plus Chaquopy, embedding Python `talon-core`.
- Database: SQLCipher.
- Crypto: Argon2id, PyNaCl/libsodium, cryptography where needed.
- Transport: Reticulum network stack.
- Interfaces: Yggdrasil, I2P, TCP, RNode/LoRa.

Current implementation note: the repo still contains a Kivy/KivyMD monolith.
Kivy is legacy during migration and should only receive emergency release fixes.

## Build & Run

Build configs currently live in [build/](build/).

```bash
# Current monolith development
python main.py

# Current legacy packaging
# Linux/Windows: PyInstaller workflows
# Android legacy path: Buildozer workflow
```

Future packaging should follow the platform split:

- `talon-desktop`: Linux PySide6 first, then Windows.
- `talon-mobile`: Android native UI plus Chaquopy after the RNS spike passes.

## Architecture Rules

- Reticulum is non-negotiable and remains in Python core on desktop and mobile.
- No client may bypass RNS for TALON sync traffic.
- Preserve the current SQLCipher schema and wire protocol during extraction
  unless a migration is explicitly planned.
- Desktop and mobile consume core read models and dispatch core service
  commands; they do not implement business policy.
- Server/admin workflows are desktop-only until explicitly approved for mobile.

## Security Model

- Reticulum handles transport encryption.
- SQLCipher handles data at rest.
- Argon2id derives local DB keys.
- PyNaCl handles field encryption and future DM E2E work.
- Enrollment uses server-generated one-time tokens only.
- Lease expiry soft-locks the client until server re-approval.
- Revocation locks locally and burns identity material where policy requires.
- Current DMs are server-readable until Phase 2b E2E encryption lands.
- Group chat is server-readable by design.

## Critical Conventions

- FLASH and FLASH_OVERRIDE audio alerts must be opt-in only.
- Server operator has full authority; do not add role hierarchy without a
  deliberate product decision.
- Unverified assets stay unverified until confirmed by a second party or server
  authority.
- Client-authored records must resolve to the enrolled operator, not silently to
  the server sentinel.

# Technical Decisions

Key decisions made during design/implementation and the reasoning behind them.
Consult this before changing architectural choices.

---

## Platform Development Priority

**Order:** Linux Server → Linux Client → Windows → Android

Each phase must be working end-to-end before moving to the next. This keeps validation simple — one platform at a time. Android-specific work (nav rail, `_build_android_layout`) is deferred until Phase 4.

---

## Language & Stack

**Python** — required by Reticulum (Python-native).
**Kivy + KivyMD** — cross-platform (Linux, Windows, Android) without separate codebases.
**SQLCipher (`sqlcipher3`)** — `pysqlcipher3` is dead (Python 3.8 era); `sqlcipher3` is actively maintained and has a community p4a recipe for Android.
**hatchling** build backend — pure-Python, pip-compatible, no lockfile format that breaks Buildozer.

---

## Config Format

**`configparser` INI** (not TOML) — `tomllib` is stdlib only from Python 3.11+. Buildozer requires Python 3.10 for p4a compatibility, so `tomllib` is unavailable without an extra dependency. `configparser` is always present.

---

## Transport Priority

Order: `yggdrasil > i2p > tcp > rnode`

- Yggdrasil and I2P are privacy-preserving overlay networks.
- TCP has more bandwidth than LoRa but **exposes the operator's IP address**. The UI must display a VPN warning whenever TCP is the active interface.
- RNode (LoRa) has the least bandwidth but works without internet infrastructure.

---

## Server/Client Mode Separation

Single codebase, mode detected from `talon.ini` or `TALON_MODE` env var before Kivy initialises.

Server-exclusive code (`talon/server/`, `talon/ui/screens/server/`) is **never imported at module level** on clients. All server imports are deferred behind `if self.mode == "server":` in `talon/app.py`.

Buildozer additionally excludes these paths from client APKs via `source.exclude_patterns`.

---

## Entry Point

`main.py` at repo root (not inside a package). Buildozer hardcodes this path; moving it requires patching the spec. Kivy also expects the entry point at the root.

Environment must be configured **before the first Kivy import** — set `KIVY_NO_ENV_CONFIG=1` at the top of `main.py`.

---

## Argon2id Parameters

`time_cost=3, memory_cost=65536 (64MB), parallelism=1`

Keeps KDF time under ~2 seconds on mid-range Android. Salt is stored plaintext next to the DB — losing the salt = losing the data. Threat model is **file exfiltration**, not local brute force.

---

## SQL Migrations

Embedded as Python string literals in `talon/db/migrations.py` (not external `.sql` files). This ensures they survive Android APK packaging without requiring additional Buildozer `datas` configuration.

---

## PyInstaller vs Buildozer

`pyinstaller` is in `[project.optional-dependencies.desktop]` only — **never** in core `[project.dependencies]`. Adding it to core would cause the Buildozer Android build container to fail.

---

## Cython Pin (Android CI)

Buildozer/p4a requires `cython==0.29.x`. Cython 3.x breaks multiple p4a recipes. Pin is in the GitHub Actions workflow, not in `pyproject.toml` (it's a build tool, not a runtime dep).

---

## FLASH Audio Alert Rule

**Hard requirement (operator safety):** Audio alerts for FLASH and FLASH_OVERRIDE SITREPs must be opt-in only. The `sitrep_screen.py` file must contain a comment block at the top enforcing this. Never call audio playback automatically.

---

## Server Operator Sentinel (author_id = 1)

`sitreps.author_id` (and similar FK columns) is `NOT NULL REFERENCES operators(id)` with `PRAGMA foreign_keys = ON`. In Phase 1 the server operator authenticates by passphrase only — they have no row in the `operators` table.

**Decision:** Migration 0002 seeds a fixed row `(id=1, callsign='SERVER')` as a sentinel so server-originated SITREPs satisfy the FK constraint. Server-authored content displays as "SERVER" in the feed.

**Temporary — must be revisited when enrollment is implemented:**
- The server operator should enroll with their real callsign and RNS identity.
- At that point, either update the sentinel row in-place (simple, re-attributes history) or add a migration that sets `author_id` on existing rows to the real operator id.
- Do not add a second permanent "SERVER" callsign once real enrollment exists — the sentinel is a Phase 1 bridge only.

---

## DMs vs Group Chat Encryption

- **DMs:** end-to-end encrypted via PyNaCl — server routes but cannot read.
- **Group chat:** encrypted with group key — server CAN read.
- Message bodies are stored as field-encrypted BLOBs in the DB regardless.

# TALON Wiki — Quick Reference Index

Read this file at the start of every session to get oriented.
Then read the linked topic files for the areas you'll be working in.

## Current Phase
**Phase 2 core complete** — Linux client enrollment, bidirectional sync, offline outbox push, UI refresh/badges, and network revocation lock behavior are implemented and covered by tests. Remaining: DM E2E (Phase 2b, separate session).

## Development Phase Priority

**Phase 1 → Phase 2 → Phase 3 → Phase 4** (sequential — validate each before moving on)

| Phase | Target | Criteria |
|-------|--------|----------|
| **1** | Linux Server | Full feature set running on Linux in server mode |
| **2** | Linux Client | Full feature set running on Linux in client mode |
| **3** | Windows | Server + Client working via PyInstaller on Windows |
| **4** | Android | Client working via Buildozer on Android |

Android layout work (`_build_android_layout`, nav rail) is deferred until Phase 4.

---

## Phase 2 — Linux Client (core complete; Phase 2b pending)

**Done:**
- [x] Same-machine test setup, `TALON_CONFIG` env-var, RNS isolation fix
- [x] Wire protocol (`protocol.py`), `net_handler.py`, `client_sync.py`
- [x] Enrollment verified end-to-end over RNS loopback
- [x] Server→client push sync verified end-to-end
- [x] Client→server push (BUG-061 fixed): outbox, UUID identity, push coalescing, backoff, tombstone GC, UI badges
- [x] Shared map context/overlays: main map and map picker/drawing modals now render the same assets, zones, and mission routes
- [x] Main map mission overlays are selection-scoped: right-panel mission cards control visible mission routes / operating areas
- [x] Main map asset picker: asset panel controls visible asset markers; selected mission assets are always shown
- [x] Global UI theme selector: main dashboard can switch between Tactical Green and Readable Dark; selection persists in DB meta and alert/severity colors remain unchanged
- [x] Windowed desktop dashboard polish: main-screen summary/header labels now stay single-line and ellipsize instead of wrapping into clipped fixed-height rows
- [x] Mission create custom variants: operators can define custom mission types, operating constraints, support resources, and key locations during mission creation
- [x] SITREP tactical UI rework: feed and composer now use the shared phosphor/tactical theme; server delete and opt-in FLASH audio behavior preserved
- [x] Test suite verified with current migrations/protocol: `pytest -q` passed with 195 tests
- [x] Architecture Step 4: mission and asset write workflows now use service commands that return explicit domain events for network notification dispatch
- [x] Architecture Step 5: the shared SQLCipher connection now serializes writes through a transaction wrapper, supports nested savepoints, and blocks shutdown until in-flight writers drain
- [x] Architecture Step 6: local operator resolution is centralized; client-authored assets, SITREPs, missions, documents, and chat messages now resolve to the enrolled operator instead of falling back to the server sentinel
- [x] Architecture Step 7: domain events now cover linked-record deletes plus operator lease/revocation flows, and `TalonApp` consumes the same events for network push scheduling and UI badge/refresh routing
- [x] Architecture Step 8: `ClientSyncManager` and `ServerNetHandler` now delegate enrollment, link routing, outbox/push, record apply, tombstone, serialization, and active-client concerns to helper components while keeping the existing façade API stable
- [x] Architecture Step 9 (coverage expansion): integration tests now cover canonical client-push round trips, mission lifecycle event emission, asset verification/deletion-request sync, current-operator attribution entry points, and revocation-over-sync/client-lock paths
- [x] Push refresh fixes: SITREPs now refresh the main dashboard immediately, server UI refreshes after accepted client pushes, and client-authored chat messages push to the server via the outbox
- [x] Startup sync badge fix: initial client hydration refreshes visible screens quietly and no longer creates red unread badges for records from previous app sessions
- [x] Lock/revocation over network: server emits explicit operator revocation packets, inactive sync/heartbeat denials locally revoke the enrolled operator, and clients trigger the lease lock immediately after local revocation
- [x] Offline-create → reconnect → push flow covered by integration tests for pending client records being accepted by the server and replaced by canonical server records
- [x] Test suite verified after startup badge fix: `pytest -q` passed with 195 tests

**Remaining:**
- [ ] DM encryption: key exchange + E2E message flow (Phase 2b, separate session)

## Phase 3 — Windows
- [ ] Verify PyInstaller desktop build runs on Windows
- [ ] Test all Phase 1+2 features on Windows

## Phase 4 — Android (deferred)
- [ ] Implement Android nav rail layout (`_build_android_layout`)
- [ ] Verify Buildozer APK builds and runs on device

---

## Manual Changes (entered by operator)
<!-- Add entries below when you make code changes outside of Claude Code sessions.
     Format: YYYY-MM-DD HH:MM — file(s) changed — brief description -->

2026-04-14 09:00 - minor changes to server/login.kv to make login screen more visually appealing.

---

## Topic Files
- [features.md](features.md) — feature status by category + full phase checklists
- [status.md](status.md) — per-file implementation status (DONE / SCAFFOLD / TODO)
- [Phase_2_Network_sync.md](Phase_2_Network_sync.md) — Phase 2 protocol spec, architecture decisions, implementation order
- [sitrep_ui_rework.md](sitrep_ui_rework.md) — SITREP tactical UI rework checklist and verification notes
- [architecture_improvement.md](architecture_improvement.md) — architecture refactor TODOs from project review
- [decisions.md](decisions.md) — key technical decisions and rationale
- [bugs.md](bugs.md) — known bugs and issues
- [map.md](map.md) — map widget + context panel design notes, implementation plan, feature table
- [document_management.md](document_management.md) — document repository plan, security pipeline, implementation status
- [linux_release_readiness.md](linux_release_readiness.md) — tracked blockers and exit criteria before shipping Linux server/client builds

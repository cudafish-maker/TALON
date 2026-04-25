# Feature Planning & Backlog

## Legend
- `[x]` — implemented and working
- `[~]` — partially implemented (backend done, UI scaffold; or UI wired but not fully tested end-to-end)
- `[ ]` — not started

---

## Phase Progress

### Phase 1 — Linux Server
- [x] Core package: config, crypto, DB, migrations (schema v15)
- [x] Network: node, interfaces, links, sync engine, lease callbacks
- [x] Server layer: enrollment, revocation (hard shred), audit, propagation
- [x] All UI screens + KV layouts implemented (login, lock, main, sitrep, asset, mission, chat, server/*)
- [x] Main desktop dashboard windowed-mode text handling — asset/mission/SITREP summary labels stay single-line and ellipsize instead of wrapping into clipped fixed-height rows
- [x] Global UI theme selector — main dashboard switcher persists Tactical Green vs Readable Dark in encrypted DB meta; tactical alert/severity colors remain fixed
- [x] Login → Argon2id → SQLCipher → screen transition fully wired
- [x] SITREP: feed, compose, severity overlay, audio opt-in toggle (FLASH/FLASH_OVERRIDE only)
- [x] SITREP tactical UI rework: themed feed rows, severity summary, right-side composer, linked asset/mission controls, and server delete confirmation
- [x] Asset: create/edit/verify, category filter, map pin refresh
- [x] Mission: create, approval workflow, AO polygon, waypoints, linked SITREPs
- [x] Mission create custom variants: custom mission types, operating constraints, support resources, and arbitrary key locations persist with mission records
- [x] Chat: phosphor green redesign, URGENT flag, grid ref, default + custom channels, DMs
- [x] Document management: upload (12-step security pipeline), download, delete, list
- [x] Server screens: enrollment UI, clients/lease UI, audit log UI, key revocation UI
- [x] Operator skills/profile: predefined + custom skills, display_name + notes
- [x] Map: OSM/Satellite/Topo layers, zone overlays, asset markers, waypoint display
- [x] Build configs: buildozer.spec, pyinstaller-linux/windows.spec, CI workflows
- [x] Tests: conftest, test_crypto, test_db, test_sync, test_enrollment

### Phase 2 — Linux Client (core complete; Phase 2b pending)
- [x] Same-machine test setup: `~/.talon-client/talon.ini`, RNS loopback stanzas
- [x] `TALON_CONFIG` env-var support; RNS isolation fix (`~/.talon/reticulum`)
- [x] Wire protocol (`protocol.py`): message constants, encode/decode
- [x] `net_handler.py`: server RNS destination, enrollment/sync/heartbeat handler
- [x] `client_sync.py`: enrollment + delta sync manager, path-request retry
- [x] Enrollment UI: TOKEN:SERVER_HASH combined string + COPY TO CLIPBOARD
- [x] **Enrollment verified end-to-end** over RNS loopback (same-machine TCP)
- [x] Delta sync: persistent-link push; `push_update`/`push_delete` on every DB write; tombstone table (migration 0009); MSG_CHUNK fragmentation for >462-byte RNS.Packet limit; LoRa 120 s polling
- [x] Push UI refresh: `Clock.schedule_once` + `TalonApp.on_data_pushed()` refreshes active client/server screens immediately, including main-dashboard SITREP updates and server UI refresh after accepted client pushes; initial client startup sync refreshes quietly without unread badges
- [x] **Server→client push sync verified end-to-end** over RNS loopback
- [x] Client→server push (BUG-061 fixed): UUID-based record identity (migrations 0010/0015); offline outbox for assets, SITREPs, missions, zones, and chat messages; push coalescing (50 ms debounce); exponential backoff (5 s→5 min); tombstone GC (30 d); chunk buffer GC (60 s TTL); UI badge counters
- [x] Current operator resolution: client-authored assets, SITREPs, missions, documents, and chat messages now resolve from the enrolled operator id/meta; server sentinel use is explicit
- [x] Lock/revocation over network verified: server revocation emits explicit `operator_revoked` packets; reconnect-time inactive denials locally revoke the enrolled operator and trigger the lease lock path
- [x] Verify tests pass with current migrations and protocol (`pytest -q`: 195 passed)
- [x] Architecture Step 8: sync/network façade classes now delegate to helper components for enrollment, link lifecycle, outbox/push, record apply, tombstones, serialization, and active-client tracking while preserving the existing public API
- [x] Architecture Step 9: integration coverage now exercises canonical client-push round trips, mission lifecycle event emission, asset verification/deletion-request sync, current-operator attribution entry points, and revocation-over-sync/client-lock paths
- [x] Offline-create → reconnect → push flow covered by integration tests for pending client records being accepted by the server and replaced by canonical server records
- [ ] DM encryption: client key exchange + E2E message flow (Phase 2b, separate session)

### Phase 3 — Windows
- [ ] Verify PyInstaller desktop build runs on Windows
- [ ] Test all Phase 1+2 features on Windows

### Phase 4 — Android (deferred)
- [ ] Implement Android nav rail layout (`_build_android_layout`)
- [ ] Verify Buildozer APK builds and runs on device
- [ ] Test all features on Android in client mode

---

## In Scope (architecture-defined)

### Operators
- [~] Callsign registration (enrollment flow) — backend done (`enrollment.py`: token gen, `create_operator`, `renew_lease`); enrollment screen UI is scaffold
- [x] Skills: predefined (8 tactical skills, checkbox toggles) + custom (free-text, add/remove); profile fields: display_name + notes; server can edit any operator from Clients screen; self-edit deferred to Phase 2 (requires enrolled operator_id on client)
- [x] Lease soft-lock + server re-auth — sync engine checks lease on every heartbeat; `on_lease_expired` navigates to lock screen; `on_lease_renewed` calls `LockScreen.on_lease_renewed()` → back to main

### Assets
- [x] Create/view assets by category (person, safe house, cache, rally point, vehicle, custom)
- [x] GPS coordinate entry — manual text input or tap-to-place on interactive map picker
- [x] Two-party physical verification — verify/unverify toggle in edit dialog; `confirmed_by` stored on verify, cleared to NULL on unverify
- [x] Map pin display per asset type — category-coloured markers; dashed amber border for unverified
- [x] Server operator delete — with confirmation dialog; NULLs linked SITREP `asset_id` before delete
- [x] Asset list in context panel with tap-to-zoom on map

### SITREPs
- [x] Freeform body with importance level picker (ROUTINE → FLASH OVERRIDE)
- [x] Predefined level templates via picker in compose bar
- [x] Append-only for operators — no edit UI; operators cannot delete
- [x] Server-only deletion — trash icon gated on `app.mode == "server"`; confirmation dialog; `delete_sitrep()` server-enforced
- [x] Tactical desktop screen — phosphor themed topbar, feed summary, severity-colored rows, right-side compose panel, asset/mission link controls, and audio opt-in state
- [ ] Notifications on create/append to all clients + server (RNS push — Phase 2)
- [x] Notification overlay scaling with severity — ROUTINE/PRIORITY → auto-dismiss dialog; IMMEDIATE → half-screen modal; FLASH/FLASH OVERRIDE → full-screen modal with severity color
- [x] **Audio alerts OPT-IN ONLY** (hard requirement) — bell toggle in SITREP screen header; setting persisted in DB meta table; two-burst 880 Hz WAV generated at runtime; fires only on FLASH/FLASH_OVERRIDE when opted in
- [x] Asset link — SITREP can be linked to an asset at compose time; link icon in feed row

### Missions
- [x] Any operator creates (title + description + asset requests) — status: pending_approval
- [x] Server approval workflow — server reviews, modifies asset list, approves or rejects
- [x] Server-only abort, complete, delete (with confirmation dialogs)
- [x] Asset allocation — requested assets flagged immediately; confirmed on approval; released on reject/abort/complete
- [x] Auto-create #mission-[name] channel on approval (not on submission)
- [x] Mission AO polygon — operator draws boundary on map at create time; saved as AO zone; displayed as blue overlay on tactical map after approval
- [x] Link waypoints to mission — tap-to-place route via `WaypointRouteModal` at create time; saved as ordered waypoints linked to mission via `create_waypoints_for_mission()`
- [x] Link SITREPs to mission — checkbox selection at mission create time via `link_sitreps_to_mission()`; loaded filtered by `mission_id` in mission detail view
- [x] Custom mission variants — create wizard accepts custom mission type text, custom operating constraints, custom support-resource rows, and custom key-location rows; custom resources are stored in `missions.custom_resources` JSON

### Map
- [x] OSM, Satellite, Topo tile layers (layer switcher in map widget)
- [ ] Pre-cache AO tiles for offline use
- [x] Shared map context — `MapContext` loads assets, zones, missions, and waypoints once per refresh so main maps and picker/drawing maps show the same operational picture
- [x] Zone overlays — `ZoneLayer` renders filled + stroked polygons by zone type; shared by main map and picker/drawing maps
- [x] Asset markers — `AssetMarker` subclass; category-coloured; tap fires `on_asset_tap`
- [x] Main map asset picker — asset panel `MAP` button lets operators choose which asset markers are displayed
- [x] Selected mission asset union — when a mission is selected, assets associated with that mission are displayed even if they are not part of the asset-picker baseline
- [x] Waypoint / route display — persisted mission waypoints render as route overlays on map pickers; on the main map they appear only for the mission selected in the right-side mission panel
- [x] Mission operating-area selection — main-map mission-linked zones/routes are scoped to the selected mission; unselecting hides mission overlays

### Chat
- [x] Default channels: #general, #sitrep-feed, #alerts — seeded by `ensure_default_channels()` on first entry
- [x] Custom channels — operator creates via name dialog; normalised to `#name`
- [x] DMs — `dm:<a>:<b>` naming; operator picker to start; displayed as "DM: callsign_a / callsign_b"; server sees all
- [x] Mission auto-channels (#mission-[name]) — created by `approve_mission()` in missions.py; appear in channel list automatically
- [x] Server operator can delete any channel or message (confirmation dialog)
- [ ] DM E2E encryption — deferred to Phase 2b: `nacl.public.Box(sender_privkey, recipient_rns_pubkey)`; current DMs use SQLCipher + RNS transport and remain server-readable

### Documents
- [x] Upload/download files (any operator upload, server-only delete) — 12-step security pipeline; server stores encrypted `.bin` files; integrity check + macro warning on download
- [ ] Large files broadband-only (queue for non-LoRa connections) — Phase 2

### Server Admin
- [x] Client list + lease management — operator list with colour-coded status badges (green/amber/red); renew/revoke with confirmation; SERVER sentinel filtered from list
- [x] Encrypted audit log viewer — two-line rows; colour-coded event names (red/amber/green/grey by semantic); payload formatted as key=value pairs; exact-match event filter
- [x] Enrollment token generation UI — wired to `generate_enrollment_token()`; pending token list shown
- [~] Key revocation UI (hard shred) — revoke button wired to `revoke_operator()`; group key rotation UI is stub

---

## Backlog (not in architecture, potential future additions)

_Add ideas here for discussion before committing to implementation._

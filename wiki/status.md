# Module Status

## Legend
- `DONE` — implemented and tested
- `SCAFFOLD` — file exists, implementation is a stub/placeholder
- `TODO` — not started
- `BLOCKED` — waiting on something

---

## Core Package

| File | Status | Notes |
|------|--------|-------|
| `talon/__init__.py` | DONE | version only |
| `talon/constants.py` | DONE | all app-wide literals |
| `talon/config.py` | DONE | INI loader, mode detection, path resolution; explicit `TALON_CONFIG`/`config_path` now reads that file only — prevents silent merge with default server config |
| `talon/utils/platform.py` | DONE | IS_ANDROID, IS_DESKTOP |
| `talon/utils/logging.py` | DONE | structured logger, audit hook |

## Crypto Layer

| File | Status | Notes |
|------|--------|-------|
| `talon/crypto/keystore.py` | DONE | Argon2id KDF, salt management |
| `talon/crypto/fields.py` | DONE | PyNaCl SecretBox encrypt/decrypt |
| `talon/crypto/identity.py` | DONE | RNS Identity create/load/destroy |

## Database Layer

| File | Status | Notes |
|------|--------|-------|
| `talon/db/connection.py` | DONE | SQLCipher open/close, WAL, FK; `DbConnection` wrapper serializes shared writes with implicit `BEGIN IMMEDIATE`, exposes nested savepoint transactions, and blocks shutdown until in-flight writers finish |
| `talon/db/migrations.py` | DONE | schema v2 (migration 0002 adds SERVER operator sentinel); atomicity via BEGIN/COMMIT inside executescript() — savepoint approach from BUG-014 was incompatible with executescript() and fixed by BUG-027. TODO: update sentinel once enrollment wired — see decisions.md |
| `talon/db/models.py` | DONE | dataclasses for all entities |

## Feature Modules

| File | Status | Notes |
|------|--------|-------|
| `talon/audio_alerts.py` | DONE | `is_audio_enabled()`/`set_audio_enabled()` (DB meta table); `play_alert()` generates two-burst 880 Hz WAV via stdlib, caches in tmp dir, loads via Kivy SoundLoader; silently no-ops if audio backend unavailable |
| `talon/operators.py` | DONE | `get_operator()`, `list_operators()` (sentinel excluded by default), `update_operator_skills()` (normalises to lowercase), `update_operator_profile()`; shared `resolve_local_operator_id()` / `require_local_operator_id()` keep client authorship off the server sentinel unless server mode opts in explicitly |
| `talon/sitrep.py` | DONE | `create_sitrep()` (field-encrypts body, optional asset_id), `load_sitreps()` (decrypts, LEFT JOIN callsign + asset label, asset_id filter), `delete_sitrep()`. TODO: replace SERVER_AUTHOR_ID once enrollment wired |
| `talon/assets.py` | DONE | `create_asset()`, `load_assets()` (category + available_only filters), `get_asset()`, `update_asset()`, `delete_asset()`; all queries include `mission_id` column (migration 0005) |
| `talon/missions.py` | DONE | `create_mission()` (pending_approval + asset pre-allocation), `approve_mission()` (creates #mission-channel, finalises assets), `reject_mission()`, `abort_mission()`, `complete_mission()`, `delete_mission()` (cascades zones/waypoints/channels); `load_missions()`, `get_mission()`, `get_mission_assets()`, `get_channel_for_mission()` |
| `talon/zones.py` | DONE | `create_zone()`, `load_zones()` (mission_id filter), `get_zone()`, `delete_zone()`; polygon stored as JSON; used by mission AO drawing and main map overlay |

## Service Layer

| File | Status | Notes |
|------|--------|-------|
| `talon/services/events.py` | DONE | shared domain-event model: single-record change/delete, linked-record batches, lease-renewed, and operator-revoked events; exposes record-mutation expansion for app/network consumers |
| `talon/services/assets.py` | DONE | asset workflow commands return notification-ready domain events; hard delete now emits one linked-record event for the asset delete plus SITREP unlink updates |
| `talon/services/missions.py` | DONE | mission workflow commands return notification-ready domain events; mission delete now emits one linked-record event covering message/channel/zone/waypoint deletes plus SITREP/asset updates |
| `talon/services/operators.py` | DONE | operator update, lease-renewal, and revocation service commands now emit domain events for server UI/network routing |

## Network Layer

| File | Status | Notes |
|------|--------|-------|
| `talon/network/node.py` | DONE | RNS init, transport, announce, shutdown |
| `talon/network/interfaces.py` | DONE | detection, priority, VPN warning; Yggdrasil probe checks 200::/7 range (BUG-015); TCP probe tries 3 endpoints (BUG-010) |
| `talon/network/links.py` | DONE | RNS Link lifecycle |
| `talon/network/sync.py` | DONE | heartbeat; `_check_lease()` fires `on_lease_expired`/`on_lease_renewed` on state transitions; `apply_server_record()` upserts via `_upsert_record()` (PRAGMA table_info column validation); SQL allowlist + `_validated_table()` guard; started by LoginScreen, stopped by TalonApp.on_stop |
| `talon/network/protocol.py` | DONE | message type constants; `encode()`/`decode()` (UTF-8 JSON); includes explicit `operator_revoked` and coded `operator_inactive` errors for revocation lock handling |
| `talon/network/client_components.py` | DONE | helper components for `ClientSyncManager`: identity/enrollment, broadband/LoRa link lifecycle, outbox push/ack handling, record application, tombstone reconciliation, UI notification dispatch with startup badge suppression, and local revocation marking |
| `talon/network/client_sync.py` | DONE | `ClientSyncManager` now acts as the stable client sync façade; public API stays `start()`, `stop()`, `start_after_enroll()`, `enroll()`, and `push_pending_to_server()` while compatibility wrappers delegate to the extracted helper components; first sync after login is treated as quiet startup hydration |

## Server-Exclusive Layer

| File | Status | Notes |
|------|--------|-------|
| `talon/server/__init__.py` | DONE | import guard comment block |
| `talon/server/enrollment.py` | DONE | token gen, list_pending, create_operator, renew_lease; create_operator wrapped in atomic `BEGIN IMMEDIATE` transaction (BUG-006); token SHA-256 hash logged on generation (BUG-009) |
| `talon/server/revocation.py` | DONE | hard shred, identity burn, group key rotation callback; `rns_hash_was` in audit payload replaced with SHA-256 hash (BUG-012) |
| `talon/server/audit.py` | DONE | append/query field-encrypted audit log, install_hook |
| `talon/server/propagation.py` | DONE | RNS Propagation Node start/stop, singleton guard |
| `talon/server/net_components.py` | DONE | helper components for `ServerNetHandler`: RNS link routing, active-client tracking, record serialization, sync/tombstone reads, push dispatch, revocation packets, and validated message handling for enroll/sync/heartbeat/client-push flows |
| `talon/server/net_handler.py` | DONE | `ServerNetHandler` now acts as the stable server sync façade; destination lifecycle and notify API stay in place while the extracted helper components own routing, delta building, tombstones, serialization, and active-link concerns |

## UI Layer

| File | Status | Notes |
|------|--------|-------|
| `talon/ui/theme.py` | DONE | selectable Tactical Green / Readable Dark global theme tokens; persisted via `meta.global_theme`; SITREP alert/severity colours stay fixed; `apply_theme()` updates KivyMD palette/window background |
| `talon/app.py` | DONE | TalonApp(MDApp), deferred server screen registration; `on_data_pushed()` active-screen refresh/badge routing supports quiet refreshes for startup hydration; `dispatch_domain_events()` now drives both network notifications and local badge/refresh updates from the shared service event stream; global theme loading/selection notifies built screens; `resolve_local_operator_id()` / `require_local_operator_id()` wrap the shared operator resolver for UI flows; `net_handler` + `client_sync` refs, stopped on exit; DB shutdown now delegates to the shared connection wrapper |
| `main.py` | DONE | entry point, KIVY_NO_ENV_CONFIG guard, mode detection |
| `talon/ui/screens/login_screen.py` | DONE | passphrase entry; hardened: conn leak (BUG-003), key null-check (BUG-004), passphrase zeroed (BUG-008); RNS initialised on main thread before background KDF thread (signal handler fix); server starts `ServerNetHandler`; client starts `ClientSyncManager` (heartbeat if enrolled, enrollment dialog with PASTE button if first-run); post-login lease monitoring now resolves the local operator through the shared helper instead of picking the first synced operator row |
| `talon/ui/screens/lock_screen.py` | DONE | `on_lease_renewed()` transitions to main screen; sync engine calls this via `on_lease_renewed` callback |
| `talon/ui/screens/main_screen.py` | DONE | hamburger MDDropdownMenu replaces fixed sidebar; MapWidget + ContextPanel wired; map refresh uses shared `MapContext`; asset panel `MAP` picker filters visible asset markers; right-panel mission cards select mission route/operating-area overlays and force associated mission assets visible; topbar theme selector switches/persists Tactical Green vs Readable Dark; windowed desktop summary labels ellipsize instead of wrapping/clipping; Android deferred Phase 4 |
| `talon/ui/screens/map_screen.py` | SCAFFOLD | map placeholder; back button wired |
| `talon/ui/screens/asset_screen.py` | DONE | asset list with category filter; create/edit/verify via ModalView dialogs; uses shared `PointPickerModal` so asset location picking shows operational map context; refreshes map markers after changes; create/verify ownership checks now resolve the local operator via the shared helper |
| `talon/ui/screens/sitrep_screen.py` | DONE | Python-built tactical/phosphor layout with theme-rebuild hook, topbar, feed summary, severity-colored rows, right-side composer, asset/mission link pickers, server-only delete confirmation; on_new_sitrep wired; audio opt-in toggle persists to DB meta and gates play_alert on FLASH/FLASH_OVERRIDE; compose authorship now resolves through the shared local-operator helper instead of falling back implicitly to `SERVER_AUTHOR_ID` in client mode |
| `talon/ui/screens/mission_screen.py` | DONE | mission list with status filter and theme-rebuild hook; create dialog (title + description + asset request + AO polygon picker); server approval dialog (asset override); detail dialog (assets, channel, AO zone); abort/complete/delete with confirmation; `PolygonDrawLayer` / `PolygonDrawView` / `PolygonDrawModal` for tap-to-draw AO polygon |
| `talon/chat.py` | DONE | `ensure_default_channels()`, `create_channel()`, `get_or_create_dm_channel()`, `load_channels()`, `load_messages()`, `send_message()` with UUID/sync_status for client outbox, `delete_message()`, `delete_channel()`; no field-level encryption — SQLCipher + RNS transport sufficient; DM E2E (nacl.public.Box) deferred to Phase 2b |
| `talon/ui/screens/chat_screen.py` | DONE | channel list with selection and theme-rebuild hook; send/receive messages; new channel dialog; new DM picker; server-only delete channel/message with confirmation dialogs; footer/status and message send paths now share the same local-operator resolution helper |
| `talon/ui/screens/server/clients_screen.py` | DONE | operator list with colour-coded status; SERVER sentinel filtered; renew/revoke/profile-save now run through operator service commands so lease/profile/revocation changes emit shared domain events before UI refresh |
| `talon/ui/screens/server/audit_screen.py` | DONE | two-line rows (timestamp + colour-coded event / payload summary); `_fmt_payload()` formats dict as key=value pairs; `_event_color()` maps event semantics to green/amber/red/grey; exact-match filter; refresh clears filter |
| `talon/ui/screens/server/enroll_screen.py` | DONE | token gen wired to `generate_enrollment_token()`; reads `server_rns_hash` from meta to display combined `TOKEN:SERVER_HASH`; COPY TO CLIPBOARD button |
| `talon/ui/screens/server/keys_screen.py` | SCAFFOLD | rotation stub remains; revoke now routes through the operator service command so revocation shares the same domain-event notifications as the clients screen |
| `talon/ui/widgets/map_data.py` | DONE | shared `MapContext` loader for assets, zones, missions, and persisted mission waypoints; includes selected-mission overlay filtering and selected-mission asset union for main map |
| `talon/ui/widgets/map_layers.py` | DONE | reusable ZoneLayer, WaypointLayer, and OperationalOverlayController for consistent map overlays |
| `talon/ui/widgets/map_sources.py` | DONE | shared OSM/Satellite/Topo tile source definitions used by main map and picker maps |
| `talon/ui/widgets/map_widget.py` | DONE | MapWidget (MapView); tile sources OSM/Satellite/Topo; shared operational overlays; on_asset_tap event |
| `talon/ui/widgets/map_draw.py` | DONE | shared map drawing/picker modals for AO polygons, point selection, and routes; now renders operational assets/zones/routes by default |
| `talon/ui/widgets/asset_marker.py` | DONE | MapMarker subclass; category-coloured circles; dashed amber border for unverified |
| `talon/ui/widgets/context_panel.py` | DONE | situation summary + asset/zone/waypoint detail views; show_asset() accepts linked_sitreps list; update_summary() for sync engine |
| `talon/ui/widgets/sitrep_overlay.py` | DONE | ROUTINE/PRIORITY → auto-dismissing MDDialog; IMMEDIATE → half-screen modal; FLASH/FLASH_OVERRIDE → full-screen modal with severity color |
| `talon/ui/widgets/nav_rail.py` | SCAFFOLD | mode-aware nav rail stub (Phase 4); rebuilds colors when the global theme changes |
| `talon/ui/kv/login.kv` | SCAFFOLD | passphrase field + unlock button |
| `talon/ui/kv/lock.kv` | SCAFFOLD | lock icon + status message |
| `talon/ui/kv/main.kv` | DONE | two-column layout (map FloatLayout + context panel); nav sidebar removed, hamburger overlay injected at runtime |
| `talon/ui/kv/map.kv` | SCAFFOLD | back button header + placeholder label |
| `talon/ui/kv/asset.kv` | DONE | header with back/refresh/add buttons; category filter dropdown; scrollable asset list |
| `talon/ui/kv/sitrep.kv` | DONE | registration stub only; layout is built in `SitrepScreen._build_layout()` |
| `talon/ui/kv/mission.kv` | DONE | header (back/refresh/add); status filter dropdown; scrollable MDBoxLayout mission list |
| `talon/ui/kv/chat.kv` | DONE | sidebar header with new-channel + new-DM buttons; channel list; right panel with active channel label + scrollable message list + compose bar |
| `talon/ui/kv/server/clients.kv` | SCAFFOLD | back button + refresh + operator list with renew/revoke actions |
| `talon/ui/kv/server/audit.kv` | DONE | filter bar (text field + SEARCH); two-column header (Timestamp / Event+payload); scrollable log list |
| `talon/ui/kv/server/enroll.kv` | DONE | back button + token display + COPY TO CLIPBOARD button + copy status label + pending list |
| `talon/ui/kv/server/keys.kv` | SCAFFOLD | back button + group key rotation + operator identity list |

## Tests

| File | Status | Notes |
|------|--------|-------|
| `tests/conftest.py` | DONE | tmp_db fixture (SQLCipher + migrations), test_key |
| `tests/test_app_events.py` | DONE | app-level domain-event dispatch coverage for linked-record expansion, operator lease/revocation routing, and current-screen refresh deduplication |
| `tests/test_crypto.py` | DONE | keystore + fields |
| `tests/test_db.py` | DONE | connection + migrations |
| `tests/test_sync.py` | DONE | heartbeat, version logic, upsert (insert/replace/column filtering), lease expiry/renewal callbacks, client-push integration, and revocation-over-sync/client-lock coverage |
| `tests/test_enrollment.py` | DONE | token lifecycle, operator creation, lease renewal |
| `tests/test_services.py` | DONE | service-command event coverage for assets, missions, and operator update/lease/revocation flows |
| `tests/test_ui_theme.py` | DONE | global theme token switching, alert-colour stability, and `meta.global_theme` persistence |

## Build & CI

| File | Status | Notes |
|------|--------|-------|
| `build/buildozer.spec` | DONE | arm64-v8a, API 34, server/* excluded |
| `build/pyinstaller-linux.spec` | DONE | kv files bundled as datas |
| `build/pyinstaller-windows.spec` | DONE | kv files bundled as datas |
| `.github/workflows/build-desktop.yml` | DONE | Linux + Windows matrix on tag/main; `xclip` added to Linux system deps |
| `.github/workflows/build-android.yml` | DONE | Python 3.10, Cython 0.29.37 pin |

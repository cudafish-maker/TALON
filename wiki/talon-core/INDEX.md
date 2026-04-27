# talon-core Wiki

`talon-core` is the shared Python runtime for TALON. It owns the application
state, Reticulum integration, SQLCipher database, crypto, sync protocol, domain
services, read models, and event stream used by all clients.

## Current Status

Phase 1 core extraction and physical split hardening are complete for the
current source tree. Backend implementations now live under `talon_core`; the
legacy backend modules under `talon/` are compatibility shims for the Kivy
client and older tests. `talon_core.TalonCoreSession` provides the application
boundary for:

- config/path resolution, SQLCipher unlock/migration/close, and runtime dirs;
- Reticulum startup, server/client sync startup, lease monitoring, and client
  enrollment;
- service commands for operators, assets, SITREPs, missions, chat, documents,
  enrollment, and persisted settings;
- read models for session state, dashboard summary, sync status, operators,
  assets, SITREPs, missions, chat, documents, enrollment, audit, map context,
  and settings;
- event subscription/publication for UI refresh, badges, sync pushes, and
  linked-record workflows.

The legacy Kivy screens now route main domain behavior through the facade while
the app mirrors core-owned runtime references for compatibility. The PySide6
desktop client imports core modules directly rather than using legacy wrappers.
The next core work is supporting desktop feature build-out while keeping the
package boundary clean and avoiding new UI-to-backend bypasses.

## Function Docs

- [api_boundary.md](api_boundary.md) - public core facade for clients.
- [config_session.md](config_session.md) - config, paths, startup, shutdown.
- [security.md](security.md) - SQLCipher, Argon2id, PyNaCl, leases, revocation.
- [reticulum.md](reticulum.md) - RNS ownership and transport policy.
- [sync_protocol.md](sync_protocol.md) - enrollment, heartbeat, sync, outbox.
- [data_model.md](data_model.md) - core entities and ownership.
- [operators.md](operators.md) - enrollment, profile, lease, revocation.
- [assets.md](assets.md) - asset service rules and verification.
- [sitreps.md](sitreps.md) - SITREP rules, alerts, field encryption.
- [missions.md](missions.md) - mission lifecycle and linked records.
- [map.md](map.md) - map read models, zones, routes, asset overlays.
- [chat.md](chat.md) - channels, messages, DMs, encryption target.
- [documents.md](documents.md) - secure repository and client fetch/cache.
- [events_testing.md](events_testing.md) - domain events and test matrix.

## Extraction Acceptance

- Existing tests pass after each extraction slice.
- No UI framework imports are required by `talon_core`.
- Desktop and mobile call core through the public API, not through Reticulum,
  database, or crypto internals.
- Reticulum remains the only TALON sync transport path.
- Schema version and wire protocol remain compatible during migration.

## Latest Verification

- 2026-04-27: Fixed core command-boundary sync propagation for chat/network
  flows: server-side chat sends now notify the server push dispatcher, and
  client-side sends are marked pending and queued through the outbox. `pytest -q`
  passed, 265 passed and 1 skipped.
- 2026-04-26: Physical split hardening moved backend implementations for config,
  DB, crypto, Reticulum/protocol/sync/server handlers, services, domain models,
  documents, chat, assets, missions, SITREPs, map helpers, and settings into
  `talon_core`; legacy `talon/` backend modules remain as compatibility shims.
- 2026-04-26: `rg -n "from talon\.|import talon\." talon_desktop talon_core`
  returned only `talon.ini` comments in `talon_core/network/interfaces.py`.
- 2026-04-26: `rg -n "kivy|kivymd|PySide6|Qt" talon_core` returned no matches.
- 2026-04-26: Reticulum startup now supports the installed RNS 1.1.9 API by
  detecting transport ownership when `RNS.Transport.is_started()` is absent;
  enrollment hash validation derives the accepted hex length from
  `RNS.Identity.TRUNCATED_HASHLENGTH`.
- 2026-04-27: Core Reticulum startup explicitly loads RNS interface modules for
  PyInstaller bundles; the packaged Linux artifact passed Reticulum TCP loopback
  enrollment and server-to-client asset sync.
- 2026-04-27: `pytest -q` passed, 255 tests after Linux Breakpoint B package
  loopback completion.
- 2026-04-26: `pytest -q` passed, 254 tests after PySide6 Linux package smoke
  wiring.
- 2026-04-26: `pytest -q` passed, 252 tests after Linux Breakpoint A
  development-shell Reticulum loopback verification.
- 2026-04-26: `pytest -q` passed, 249 tests after Desktop Qt smoke test wiring.
- 2026-04-26: Added `dashboard.summary` and `sync.status` read models. Focused
  verification `pytest -q tests/test_core_session.py tests/test_sync.py
  tests/test_desktop_shell.py` passed, 65 tests.
- 2026-04-26: `python -m py_compile talon_core/__init__.py talon_core/session.py talon_core/map.py talon/app.py talon/ui/screens/asset_screen.py talon/ui/screens/sitrep_screen.py talon/ui/screens/mission_screen.py talon/ui/screens/mission_create_screen.py talon/ui/screens/chat_screen.py talon/ui/screens/main_screen.py talon/ui/screens/server/clients_screen.py talon/ui/screens/server/enroll_screen.py talon/ui/screens/server/audit_screen.py talon/ui/screens/server/keys_screen.py talon/ui/widgets/map_data.py talon/ui/widgets/font_scale.py` passed.
- 2026-04-26: `pytest -q tests/test_core_session.py tests/test_documents.py tests/test_app_events.py tests/test_db.py tests/test_operators.py tests/test_services.py tests/test_chat.py tests/test_missions.py tests/test_audio_alerts.py tests/test_map_data.py tests/test_enrollment.py tests/test_registry.py tests/test_ui_theme.py` passed, 118 tests.
- 2026-04-26: `pytest -q tests/test_core_session.py` passed, 4 tests.
- 2026-04-26: `pytest -q tests/test_core_session.py tests/test_db.py tests/test_operators.py tests/test_services.py` passed, 54 tests.
- 2026-04-26: `python -m py_compile talon/app.py talon/ui/screens/login_screen.py talon_core/session.py tests/test_core_session.py tests/test_app_events.py` passed.
- 2026-04-26: `pytest -q tests/test_core_session.py tests/test_app_events.py` passed, 10 tests.
- 2026-04-26: `pytest -q tests/test_core_session.py tests/test_app_events.py tests/test_db.py tests/test_operators.py tests/test_services.py` passed, 60 tests.
- 2026-04-26: `python -m py_compile talon_core/__init__.py talon_core/session.py talon/ui/screens/document_screen.py tests/test_core_session.py` passed.
- 2026-04-26: `pytest -q tests/test_core_session.py tests/test_documents.py` passed, 10 tests.
- 2026-04-26: `pytest -q tests/test_core_session.py tests/test_documents.py tests/test_app_events.py tests/test_db.py tests/test_operators.py tests/test_services.py` passed, 65 tests.

## Legacy Sources

- [../archive/legacy/Phase_2_Network_sync.md](../archive/legacy/Phase_2_Network_sync.md)
- [../archive/legacy/architecture_improvement.md](../archive/legacy/architecture_improvement.md)
- [../archive/legacy/decisions.md](../archive/legacy/decisions.md)
- [../archive/legacy/status.md](../archive/legacy/status.md)

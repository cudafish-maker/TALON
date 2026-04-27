# Events And Testing

Core domain events are the bridge between service commands, network sync, and UI
refresh adapters.

## Event Requirements

Core emits events for:

- Single-record create/update/delete.
- Linked-record batches.
- Operator lease renewal.
- Operator revocation.
- Sync status and pending outbox count.
- UI refresh and unread badge routing.
- SITREP alert overlays and opt-in audio eligibility.
- Network-applied table refreshes for clients and servers that subscribe to the
  core event stream directly.

Desktop should adapt events to Qt signals. Mobile should adapt events to
Android/Chaquopy callbacks. Neither client should reimplement event policy.

## Core Test Matrix

- Config/session startup and shutdown.
- SQLCipher open, migrations, transaction rollback, nested transactions.
- Argon2id and field encryption.
- RNS identity load/create and isolated config paths.
- Protocol validators and framing.
- Enrollment and lease lifecycle.
- Server-to-client sync and client outbox push.
- Revocation over sync and reconnect denial lock.
- Service commands for assets, SITREPs, missions, operators, chat, documents.
- Read models for dashboard, maps, documents, chat, and admin screens.
- Event emission for linked-record workflows.

## Current Verification

- `tests/test_core_session.py` covers the initial `TalonCoreSession` facade:
  config/path resolution, DB unlock/migration/close, passphrase-derived unlock,
  session/operator read models, event subscription, operator/asset/SITREP/mission/
  chat/document/enrollment/settings command dispatch, map/document/chat/mission
  read models, server-only command guards, and client self-verification policy.
- Focused regression run on 2026-04-26:
  `pytest -q tests/test_core_session.py tests/test_db.py tests/test_operators.py tests/test_services.py`
  passed with 54 tests.
- After migrating Kivy login/startup to the core facade, 2026-04-26 focused
  regression:
  `pytest -q tests/test_core_session.py tests/test_app_events.py tests/test_db.py tests/test_operators.py tests/test_services.py`
  passed with 60 tests.
- After moving Documents onto the core facade, 2026-04-26 focused regression:
  `pytest -q tests/test_core_session.py tests/test_documents.py tests/test_app_events.py tests/test_db.py tests/test_operators.py tests/test_services.py`
  passed with 65 tests.
- After completing the Phase 1 facade and migrating the remaining legacy Kivy
  domain screens, 2026-04-26 full regression:
  `pytest -q`
  passed with 212 tests.
- After physical split hardening and dashboard/sync-status read-model work,
  2026-04-26 focused regression:
  `pytest -q tests/test_core_session.py tests/test_sync.py tests/test_desktop_shell.py`
  passed with 65 tests.
- Latest full regression on 2026-04-27 after Linux Breakpoint B package
  loopback completion:
  `pytest -q`
  passed with 255 tests.
- 2026-04-27: Added `ui_refresh_requested` events for network-applied table
  notifications in PySide6 runtimes, while preserving the legacy Kivy
  `on_data_pushed` badge path. Focused verification
  `pytest -q tests/test_core_session.py tests/test_app_events.py
  tests/test_desktop_shell.py tests/test_registry.py tests/test_sync.py`
  passed, 112 tests and 1 skipped. Full `pytest -q` passed, 269 tests and
  1 skipped.

# Architecture Improvement TODO

Purpose: track architecture improvements identified during the project review in suggested implementation order. These are maintainability and reliability tasks, not immediate failing-test triage.

Current baseline: Phase 2 architecture refactors are complete. The last full local run recorded `pytest -q` with `199 passed in 613.84s`, and `pytest --collect-only -q` collected 199 tests on 2026-04-25 after the client document fetch/cache and Linux packaging updates.

## Guardrails

- [ ] Preserve the current Linux Server -> Linux Client -> Windows -> Android phase order.
- [ ] Keep server-only imports deferred behind server mode.
- [ ] Avoid a wholesale ORM rewrite unless the current SQL module pattern becomes a blocker.
- [ ] Keep each change incremental and testable so Phase 2 sync validation remains stable.

## Suggested Order

### 1. Add Shared Network Framing

Goal: remove duplicated packet/chunk handling before adding more protocol surface for revocation and DM E2E.

- [x] Move duplicated `_smart_send()` logic out of `talon/network/client_sync.py` and `talon/server/net_handler.py`.
- [x] Move duplicated chunk reassembly logic into a shared helper such as `talon/network/framing.py`.
- [x] Update both client and server network paths to use the shared framing helper.
- [x] Add focused tests for packet-size boundary behavior, chunk ordering, duplicate chunks, stale-buffer GC, and buffer caps.

### 2. Add Protocol Validators

Goal: keep network handlers from growing more ad hoc validation as Phase 2 lock/revocation and Phase 2b DM messages are added.

- [x] Add a protocol version field to wire messages.
- [x] Add per-message validation helpers for required fields and field types.
- [x] Keep `protocol.decode()` responsible for JSON decoding, then validate message shape before handler dispatch.
- [x] Add tests for malformed `enroll_request`, `sync_request`, `heartbeat`, `client_push_records`, `push_update`, and `push_delete` payloads.
- [x] Add a validator registry that can be extended as new revocation and DM E2E messages are introduced.

### 3. Create A Synced-Table Registry

Goal: make sync behavior table-driven instead of scattered across app, client, server, and sync modules.

- [x] Create one registry for synced table metadata.
- [x] Consolidate `_CLIENT_PUSH_TABLES`, `_OFFLINE_TABLES`, `_SYNC_TABLES`, `_SYNC_TABLE_ALLOWLIST`, tombstone order, document exclusions, and field transforms.
- [x] Include table properties: syncable, client-pushable, offline-creatable, tombstone order, redacted fields, encrypted fields, ownership fields, and UI refresh targets.
- [x] Update `SyncEngine`, `ClientSyncManager`, `ServerNetHandler`, and `TalonApp` badge routing to read from the registry.
- [x] Add tests proving unsupported tables remain blocked.

### 4. Introduce Service Commands For Missions And Assets

Goal: move persistence plus network-notification orchestration out of large UI screens, starting with the workflows that currently have the most linked-record side effects.

- [x] Add command/service modules for mission workflows.
- [x] Add command/service modules for asset workflows.
- [x] Have service commands return explicit domain events after successful commits.
- [x] Replace manual notification orchestration in mission approval, rejection, abort, completion, and deletion flows.
- [x] Replace manual notification orchestration in asset create, edit, verify, deletion-request, and hard-delete flows.
- [x] Keep UI screens responsible for validation presentation and rendering, not linked-row prequeries or sync notification fan-out.

### 5. Add Shared DB Transaction Handling

Goal: reduce concurrency risk from one SQLCipher connection used across UI, sync threads, timers, and RNS callbacks.

- [x] Add a small transaction helper or `DbSession` wrapper.
- [x] Route UI, sync, and server callback writes through one serialization path.
- [x] Use consistent `BEGIN IMMEDIATE`, commit, rollback, and lock behavior.
- [x] Make shutdown wait for or block new DB writes before closing the shared SQLCipher connection.
- [x] Add tests for rollback behavior and nested or concurrent write attempts where practical.

### 6. Clean Up Current-Operator Resolution

Goal: remove ad hoc fallbacks to the server sentinel and make authorship consistent across server and client mode.

- [x] Add one helper or service for resolving the local operator id.
- [x] Replace ad hoc fallbacks to `SERVER_AUTHOR_ID` in UI screens.
- [x] Keep server sentinel behavior explicit until real server-operator enrollment replaces it.
- [x] Verify client-created assets, SITREPs, missions, documents, and chat messages are attributed to the enrolled operator.
- [x] Add tests that catch client actions being accidentally attributed to the server sentinel.

### 7. Add Domain Event Notifications

Goal: let data/service commands emit one consistent set of events for network push, UI badge refresh, and future audit hooks.

- [x] Define event types such as record changed, record deleted, linked records changed, lease renewed, and operator revoked.
- [x] Emit events from data/service commands after commits.
- [x] Convert `TalonApp.net_notify_change()` and `net_notify_delete()` into event consumers where possible.
- [x] Use the same events for UI badge refresh and network push scheduling.
- [x] Add tests for event emission on multi-record workflows such as mission deletion and operator revocation.

### 8. Split Client And Server Sync Responsibilities

Goal: reduce the size and coupling of the two largest network classes after shared framing, validators, registry, services, and events have created better seams.

- [x] Break `ClientSyncManager` into smaller components for identity/enrollment, link lifecycle, outbox, tombstone reconciliation, record application, and UI notification dispatch.
- [x] Break `ServerNetHandler` into smaller components for RNS link callbacks, enrollment handling, delta building, client push handling, tombstones, serialization, and active-client tracking.
- [x] Keep the public app-facing API small: start, stop, enroll, push pending record, notify change, notify delete.
- [x] Keep compatibility tests around enrollment, heartbeat, sync, client push, tombstones, and chunked payloads green during the split.

### 9. Expand Integration Coverage

Goal: lock in behavior after architecture refactors and before larger Phase 2b/Phase 3 work.

- [x] Add integration-style tests for client push plus server canonical record return.
- [x] Add tests for mission approval, rejection, abort, completion, and deletion event emission.
- [x] Add tests for asset verification and deletion-request sync behavior.
- [x] Add tests for revocation over sync once lock/revocation networking is completed.
- [x] Add tests that verify screens or services do not bypass current-operator attribution.

## Notes

- The current architecture is functional and tested, so these tasks should be treated as controlled refactors.
- The largest complexity hotspots are `talon/network/client_sync.py`, `talon/server/net_handler.py`, and large UI screen modules.
- DM E2E encryption should benefit from the protocol validation, framing, table-registry, and service-layer work, but it should remain scoped to Phase 2b.

# Network Sync Rewrite — Session Progress

**Session started:** 2026-04-18
**Branch:** dev (Phase 2)

## Goal
Full bidirectional sync rewrite. Server→client push already works. This adds:
- Client→server push (BUG-061)
- Offline intel preservation (new records created while disconnected survive reconnect)
- UUID-based record identity
- Push coalescing (50ms debounce)
- Chunk buffer GC (60s TTL)
- Tombstone cleanup (30-day GC)
- Exponential backoff on reconnect
- UI badge system for off-screen data changes

## Offline Intel Design
New records created while offline: `sync_status='pending'` in local DB. On reconnect, pushed to server BEFORE sync_request. Server checks UUID — unknown = accept (new intel), known = server wins (edit conflict → amendments table + UI notification).

## File Change Summary
| File | Status | Notes |
|------|--------|-------|
| `talon/constants.py` | ✅ Done | DB_SCHEMA_VERSION 9 → 10 |
| `talon/db/migrations.py` | ✅ Done | Migration 0010: uuid + sync_status + amendments |
| `talon/network/protocol.py` | ✅ Done | MSG_CLIENT_PUSH_RECORDS, MSG_PUSH_ACK |
| `talon/assets.py` | ✅ Done | uuid + sync_status in create_asset() |
| `talon/sitrep.py` | ✅ Done | uuid + sync_status in create_sitrep() |
| `talon/missions.py` | ✅ Done | uuid in create_mission() |
| `talon/zones.py` | ✅ Done | uuid in create_zone() |
| `talon/waypoints.py` | ✅ Done | uuid in create_waypoints_for_mission() |
| `talon/server/net_handler.py` | ✅ Done | _handle_client_push, push coalescing (50ms), tombstone GC (30d), chunk GC (60s) |
| `talon/network/client_sync.py` | ✅ Done | outbox push, is_connected, push_ack, exponential backoff (5s→5min), chunk GC, LoRa outbox |
| `talon/app.py` | ✅ Done | Badge system in on_data_pushed + clear_badge + _refresh_badge_display |
| `talon/ui/screens/main_screen.py` | ✅ Done | set_nav_badges() + clear_badge on on_pre_enter |

## Steps Checklist
- [x] Step 1: Migration 0010 + DB_SCHEMA_VERSION bump
- [x] Step 2: UUID wiring in feature modules
- [x] Step 3: Protocol constants
- [x] Step 4: Server net_handler rewrite
- [x] Step 5: Client sync rewrite
- [x] Step 6: UI badge system
- [x] Step 7: Verify tests pass (`pytest tests/`)
- [x] Step 8: Offline-create → reconnect → push verification covered by integration tests
- [x] Step 9: Post-test bug fixes (2026-04-18, session 2)

## Post-Test Bug Fixes (session 2 — 2026-04-18)

Manual test revealed two bugs:

### BUG-A: Client-created records never reached the server
**Root cause**: `app.net_notify_change()` checked only `self.net_handler is not None`
(server mode).  In client mode `net_handler` is `None`, so every call was a no-op.
There was no path to push client-created records to the server.

**Fix**:
- `talon/app.py`: Added `_CLIENT_PUSH_TABLES` constant; updated `net_notify_change()`
  to call `client_sync.push_pending_to_server(table, record_id)` in client mode for
  tables in that set.
- `talon/network/client_sync.py`: Added `push_pending_to_server(table, record_id)`
  (non-blocking — spawns daemon thread) and `_push_record_pending()` worker.
  Worker marks the record `sync_status='pending'`, then flushes the outbox via the
  persistent link if `_initial_sync_done` is True.
- `talon/network/client_sync.py`: Added `self._initial_sync_done` flag — set True on
  MSG_SYNC_DONE, False on link close.  MSG_PUSH_ACK only sends a follow-up
  `sync_request` during the initial connection phase (when flag is False).

### BUG-B: Server hangs on exit ("program may be waiting" dialog)
**Root cause**: `threading.Timer` in `net_handler.notify_change()` creates non-daemon
threads by default.  Python's shutdown waits for all non-daemon threads to finish.
If `_flush_push_buffer` was blocked on `self._lock` at shutdown time, the process
could not exit.

**Fix**: `talon/server/net_handler.py` — set `_t.daemon = True` on the Timer thread.

## Key Design Notes
- `sync_status` only on tables clients field-create: assets, sitreps, missions, zones, messages
- Waypoints deferred: created for offline missions need mission UUID resolution (later)
- `amendments` table stores rejected offline edits so operators can review what was superseded
- LoRa outbox push added to `_do_lora_cycle` (runs before `_lora_sync`)
- Server push coalescing: 50ms debounce; `notify_change` enqueues, `_flush_push_buffer` sends
- Chunk buffers: added `created_at` timestamp, `_gc_chunk_buffers()` purges entries > 60s old

## Picking Up Mid-Session
If session ends before completion, check the checkboxes above and the File Change Summary table. 
The next session should continue from the first unchecked step.

Open bugs handled by this rewrite:
- BUG-061: client→server push — FIXED by outbox + _handle_client_push

## Phase 2 Closeout Update (2026-04-24)

- Network revocation now has explicit `operator_revoked` server packets and
  coded `operator_inactive` errors for clients denied during sync, heartbeat, or
  client-push.
- Clients locally mark the enrolled operator revoked and force the lease monitor
  to re-check immediately, so live revocation and offline-revoked reconnects both
  enter the lock path.
- `pytest -q` passed with 192 tests, including offline outbox round trips,
  startup sync badge suppression, and
  revocation-over-sync/client-lock coverage.

# Phase 2 — Network Sync & Enrollment

Architecture decisions, protocol specification, and implementation notes for the
TALON client↔server network layer.

---

## Context

Phase 2 core is implemented for Linux clients. Enrollment, server→client push,
client→server offline outbox push, heartbeat/lease checks, tombstones,
revocation lock behavior, startup hydration badge suppression, and on-demand
client document fetch/cache are all in-tree and covered by tests.

This document now describes the current Phase 2 network state:
- Protocol layer with versioned JSON messages, validators, and shared framing
- Server-side RNS destination, enrollment/sync/heartbeat/client-push handlers
- Client-side sync manager façade plus helper components
- Persistent broadband sync link, LoRa polling fallback, tombstones, and outbox
- On-demand document fetch over the persistent sync link

DM E2E encryption remains **out of scope** for Phase 2 core and is tracked as
Phase 2b.

---

## Architecture Decisions

### 1. Message Format: JSON over RNS Links
UTF-8 JSON with a `version` field injected by `protocol.encode()`. Message
shape is validated before handler dispatch. Small payloads send as one RNS
packet; larger payloads are split/reassembled by `talon/network/framing.py`
using `chunk` messages so callers do not duplicate packet-size logic.

### 2. Server Destination: `talon.server` aspect
A dedicated `RNS.Destination(identity, IN, SINGLE, "talon", "server")` — separate
from the existing `talon.node` destination used for routing/transport. The destination
hash is deterministic from the server's identity, stable across restarts.

The server creates/loads its identity from `<data_dir>/server.identity` via the
existing `load_or_create_identity()` in `talon/crypto/identity.py`.

### 3. Enrollment Token Format: `TOKEN:SERVER_HASH`
The enrollment screen displays a combined 129-char string:
`{64-char-token}:{64-char-server-rns-hash}`. The client pastes this single string
into one field. Split on `:` to extract both pieces. This avoids two separate
copy-paste operations and keeps the QR code payload simple.

### 4. Synced-Table Registry And Field Handling
Sync behavior is table-driven by `talon/network/registry.py`. The registry owns
sync order, client-push/offline flags, tombstone order, redacted fields,
encrypted fields, ownership fields, and UI refresh targets.

`sitreps.body` is field-encrypted among the synced tables. The server decrypts
it before including it in a wire record; the client re-encrypts it with its own
DB key before local storage. `messages.body` is transported as text bytes for
the current chat implementation; DM E2E encryption remains Phase 2b.

`documents.file_path` is redacted from normal metadata sync. Document plaintext
is transferred only by explicit `document_request` / `document_response`.

### 5. Tables Synced to Client

| Table               | Synced        | Notes |
|---------------------|---------------|-------|
| `operators`         | Yes           | Filter `id != 1` (SERVER sentinel seeded by migration 0002) |
| `assets`            | Yes           | |
| `sitreps`           | Yes           | `body` decrypted by server, re-encrypted by client |
| `missions`          | Yes           | |
| `waypoints`         | Yes           | |
| `zones`             | Yes           | |
| `channels`          | Yes           | Default + mission + DM channels |
| `messages`          | Yes           | `body` is plaintext currently |
| `documents`         | Metadata only | `file_path` redacted; first client open fetches plaintext over persistent sync link, then caches encrypted locally |
| `enrollment_tokens` | **Never**     | Server-only |
| `audit_log`         | **Never**     | Server-only |

### 6. Persistent Broadband Link And LoRa Polling
Broadband sync keeps one persistent RNS Link per client. Initial sync, heartbeat,
client outbox push, push acknowledgements, server push updates/deletes,
operator revocation packets, and document fetch requests all use that link.

LoRa remains a polling fallback at 120 seconds and avoids large document
transfers.

### 7. Client Response Buffering, Push, And Tombstones
The server sends `N × sync_response` messages followed by `sync_done`.
`sync_done` also carries tombstones newer than the client's last successful
sync so offline deletes are applied in registry-defined order.

Client-created offline records use UUID identity and `sync_status='pending'`.
The outbox coalesces push attempts, retries with exponential backoff, and
replaces accepted pending rows with canonical server records when a `push_ack`
arrives.

### 8. Migration 0007 — Seed Meta Keys
Seeds `server_rns_hash` and `my_operator_id` meta keys with empty-string defaults
so runtime code can always `SELECT value FROM meta WHERE key = ?` without
handling missing-row cases.

### 9. Client Identity
Stored at `<data_dir>/client.identity` (e.g. `~/.talon-client/client.identity`),
separate from the server identity. Loaded via `load_or_create_identity()` on first
login. The hex hash of this identity is the `rns_hash` sent in `enroll_request`.

---

## Wire Protocol

All messages are UTF-8 JSON exchanged over an established RNS Link.

### enroll_request  (client → server)
```json
{
  "type": "enroll_request",
  "token": "<64-char hex>",
  "callsign": "ALPHA-1",
  "rns_hash": "<client identity hash hex>"
}
```

### enroll_response  (server → client)
```json
{
  "type": "enroll_response",
  "ok": true,
  "operator_id": 5,
  "callsign": "ALPHA-1",
  "lease_expires_at": 1234567890,
  "error": null
}
```

### sync_request  (client → server)
```json
{
  "type": "sync_request",
  "operator_rns_hash": "<client identity hash hex>",
  "last_sync_at": 1234567890,
  "version_map": {
    "operators": {"1": 1, "5": 2},
    "sitreps":   {"1": 1},
    "assets":    {}
  }
}
```

### sync_response  (server → client, one changed record)
```json
{
  "type": "sync_response",
  "table": "sitreps",
  "record": {"id": 3, "level": "PRIORITY", "body": "<plaintext body>", "...": "..."}
}
```

### sync_done  (server → client)
```json
{
  "type": "sync_done",
  "tombstones": [{"table": "assets", "record_id": 10, "deleted_at": 1234567890}],
  "server_id_sets": {"assets": [1, 2, 3]}
}
```

### heartbeat  (client → server)
```json
{
  "type": "heartbeat",
  "operator_rns_hash": "<client identity hash hex>"
}
```

### heartbeat_ack  (server → client)
```json
{
  "type": "heartbeat_ack",
  "timestamp": 1234567890,
  "lease_expires_at": 1234567890
}
```

### client_push_records  (client → server)
```json
{
  "type": "client_push_records",
  "operator_rns_hash": "<client identity hash hex>",
  "records": {
    "assets": [{"uuid": "<uuid>", "...": "..."}],
    "sitreps": []
  }
}
```

The server validates that each table is client-pushable, strips client-supplied
identity fields where required, accepts or rejects each record, then returns
`push_ack`.

### push_ack  (server → client)
```json
{
  "type": "push_ack",
  "accepted": ["<client uuid>"],
  "rejected": [{"uuid": "<client uuid>", "reason": "server version newer"}]
}
```

### document_request / document_response
```json
{
  "type": "document_request",
  "operator_rns_hash": "<client identity hash hex>",
  "document_id": 7
}
```

Successful document fetches are returned as an `RNS.Resource` with
`document_response` metadata; error/availability replies use normal packets.

### operator_revoked  (server → client)
```json
{
  "type": "operator_revoked",
  "operator_id": 5,
  "lease_expires_at": 1234567890,
  "version": 4,
  "reason": "operator_revoked"
}
```

The client marks that operator row revoked locally. If it is the enrolled
operator, the lease monitor is forced to re-check immediately so the lock screen
is reached without waiting for the next heartbeat tick.

### error  (either direction)
```json
{
  "type": "error",
  "message": "human-readable description",
  "code": "operator_inactive"
}
```

`code` is optional. `operator_inactive` is used when the server denies sync,
heartbeat, or client-push because the identity is unknown or revoked; clients
treat it as local operator revocation so an offline-revoked client locks on
reconnect.

---

## New Files

| File | Purpose |
|------|---------|
| `talon/network/protocol.py` | Message type constants, `encode()`, `decode()` |
| `talon/server/net_handler.py` | Server RNS destination, link accept, message routing |
| `talon/network/client_sync.py` | Client enrollment + delta sync manager |
| `talon/network/framing.py` | Shared packet/chunk send and reassembly helpers |
| `talon/network/registry.py` | Shared synced-table behavior registry |
| `talon/network/client_components.py` | Client sync helper components |
| `talon/server/net_components.py` | Server sync helper components |

## Modified Files

| File | Change |
|------|--------|
| `talon/constants.py` | Current `DB_SCHEMA_VERSION = 15`; includes `RNS_SERVER_ASPECT` |
| `talon/db/migrations.py` | Meta keys, tombstones, UUIDs/outbox state, chat fields, mission custom fields, and message sync status are all represented by migrations through 0015 |
| `talon/app.py` | Owns `net_handler` + `client_sync`, dispatches domain events to network/UI, and stops network managers on exit |
| `talon/ui/screens/login_screen.py` | Server starts `ServerNetHandler`; client starts `ClientSyncManager` and shows enrollment dialog on first run |
| `talon/ui/screens/server/enroll_screen.py` | Displays combined `TOKEN:SERVER_HASH` string |

---

## Current Component Ownership

1. `talon/network/protocol.py` validates message shape and owns message constants.
2. `talon/network/framing.py` owns packet/chunk send and reassembly.
3. `talon/network/registry.py` owns synced-table policy.
4. `talon/server/net_handler.py` exposes the stable server façade; `talon/server/net_components.py` owns routing, deltas, tombstones, push ingest/dispatch, revocation packets, and document transfer.
5. `talon/network/client_sync.py` exposes the stable client façade; `talon/network/client_components.py` owns identity/enrollment, links, outbox, record apply, tombstones, UI notifications, revocation, and document fetch/cache.
6. `talon/app.py` consumes domain events and forwards them to network/UI refresh paths.

---

## Edge Cases & Risks

| Risk | Mitigation |
|------|-----------|
| Server destination not announced when client enrolls | client enrollment calls the Reticulum destination recall helper and surfaces a clear "server not reachable" error if no destination is found |
| Concurrent client syncs | Active links are tracked by server helper components; client push and document request state is protected by manager locks |
| `sitreps.body` decrypt fails on server | Wrap in try/except; skip record + log warning; don't abort full sync |
| Heartbeat fires before DB is open | client helpers check the app connection before DB operations |
| Sync sent before enrollment completes | client identity/enrollment helpers require `my_operator_id` and server hash metadata before opening the persistent sync path |
| SERVER sentinel (id=1) sent in operators sync | server delta helpers filter `operators` with `id != 1` |
| `enrollment_tokens` / `audit_log` queried by client | not in the registry sync allowlist; unsupported tables are rejected before query/dispatch |

---

## Verification Procedure

```bash
# Terminal 1 — server
python main.py
# Login → Enroll screen → Generate → copy TOKEN:HASH string

# Terminal 2 — client
TALON_CONFIG=~/.talon-client/talon.ini python main.py
# Login → enrollment dialog → paste TOKEN:HASH + callsign → Enroll
# Should transition to main screen

# Verify on server: Clients screen shows new operator row
# Create SITREP / asset / chat message on server
# Broadband client should receive pushes on the persistent link; LoRa fallback polls every 120 s
# Revoke operator on server — broadband client should lock on the revocation packet or inactive denial
```

---

## Out of Scope / Deferred

- DM E2E encryption (NaCl Box, key exchange via RNS identity public keys)
- Client document upload
- Large-file broadband-only queueing beyond the current first-open document fetch
- LoRa sync optimisations and delta compression

## Current Verification Notes

- Latest full local validation: `pytest -q` passed with 199 tests after client document fetch/cache work.
- `pytest --collect-only -q` collected 199 tests on 2026-04-25.
- Revocation coverage includes live server `operators` push plus explicit
  `operator_revoked` packet handling, and reconnect-time `operator_inactive`
  error handling for clients revoked while offline.
- Offline-create → reconnect → push behavior is covered by integration tests
  that push pending client records to the server and replace them with canonical
  server records.
- The first client sync after login is treated as quiet startup hydration:
  screens can refresh, but old records from a prior app session do not create
  unread badges.
- Client document cache coverage includes stale-cache invalidation when document
  metadata changes and cache-file cleanup when a document row is deleted.

# Phase 2 — Network Sync & Enrollment

Architecture decisions, protocol specification, and implementation notes for the
TALON client↔server network layer.

---

## Context

Phase 1 (Linux Server) is complete. Phase 2 targets the Linux Client. The codebase
already has scaffold network code (`node.py`, `links.py`, `sync.py`) and a complete
server-side data layer, but there is **no RNS message exchange** between client and
server yet — no enrollment flow, no delta sync protocol, no heartbeat acknowledgement.

This document covers:
- Network protocol layer (message format + encoding)
- Server-side RNS destination + message handler
- Client-side sync manager (enrollment + delta sync)
- DB migration to seed meta keys
- Login screen enrollment dialog (client first-run)
- Enrollment screen update (show combined token+hash string)

DM E2E encryption is **out of scope** — addressed in a separate Phase 2b document
after sync is validated end-to-end.

---

## Architecture Decisions

### 1. Message Format: JSON over RNS Links
UTF-8 JSON. No new dependencies. RNS Links handle reassembly for large payloads
so no manual chunking is needed. Readable for debugging. Each `send_packet()` call
is one message.

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

### 4. Field-Encrypted Column Handling in Sync
Only `sitreps.body` is field-encrypted among the synced tables (per `sitrep.py`).
`messages.body` is NOT field-encrypted currently (group chat relies on SQLCipher +
RNS transport; DM E2E is Phase 2b).

Protocol: the server **decrypts** `sitreps.body` before including it in a
`sync_response` packet. The client **re-encrypts** it with its own DB key before
writing to its local DB. The RNS Link provides transport encryption so plaintext
fields are not exposed on the wire.

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
| `documents`         | Metadata only | No file content; broadband download is separate |
| `enrollment_tokens` | **Never**     | Server-only |
| `audit_log`         | **Never**     | Server-only |

### 6. New Link Per Heartbeat (vs. Persistent Link)
Open a fresh RNS Link for each heartbeat sync cycle. Simpler state management,
no reconnection logic. Acceptable overhead for 60 s (broadband) and 120 s (LoRa).
Persistent-link optimisation is a candidate for a future session.

### 7. Client Response Buffering
The server sends `N × sync_response` (one per table with changes) followed by
`sync_done`. The client buffers `sync_response` messages using a list +
`threading.Event`. The event is set on `sync_done`. `wait(timeout=30)` prevents
infinite blocking if the server goes offline mid-sync.

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
  "version_map": {
    "operators": {"1": 1, "5": 2},
    "sitreps":   {"1": 1},
    "assets":    {}
  }
}
```

### sync_response  (server → client, one per table with new records)
```json
{
  "type": "sync_response",
  "table": "sitreps",
  "records": [
    {"id": 3, "level": "PRIORITY", "body": "<plaintext body>", "...": "..."}
  ]
}
```

### sync_done  (server → client)
```json
{ "type": "sync_done" }
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

## Modified Files

| File | Change |
|------|--------|
| `talon/constants.py` | `DB_SCHEMA_VERSION → 7`, add `RNS_SERVER_ASPECT` |
| `talon/db/migrations.py` | Migration 0007: seed `server_rns_hash` + `my_operator_id` meta keys |
| `talon/app.py` | Add `net_handler` + `client_sync` refs; stop them on exit |
| `talon/ui/screens/login_screen.py` | Server: start net_handler. Client: enrollment dialog on first run |
| `talon/ui/screens/server/enroll_screen.py` | Display combined `TOKEN:SERVER_HASH` string |

---

## Implementation Order

1. `talon/network/protocol.py` — standalone, no deps
2. `talon/constants.py` — bump version, add RNS constant
3. `talon/db/migrations.py` — migration 0007
4. `talon/server/net_handler.py` — depends on protocol.py + enrollment.py
5. `talon/network/client_sync.py` — depends on protocol.py + sync.py + links.py
6. `talon/app.py` — wire refs
7. `talon/ui/screens/login_screen.py` — enrollment dialog + manager startup
8. `talon/ui/screens/server/enroll_screen.py` — combined token display

---

## Edge Cases & Risks

| Risk | Mitigation |
|------|-----------|
| Server destination not announced when client enrolls | `_open_link_to_server` raises clear error if `Destination.recall()` returns None; surfaces in enrollment dialog |
| Concurrent client syncs | Each link gets its own callback closure in `_on_link_established` — no shared per-link state |
| `sitreps.body` decrypt fails on server | Wrap in try/except; skip record + log warning; don't abort full sync |
| Heartbeat fires before DB is open | `_heartbeat_loop` checks `conn is not None` before DB ops |
| Sync sent before enrollment completes | `_do_sync` checks `my_operator_id is not None`; skips if not enrolled |
| SERVER sentinel (id=1) sent in operators sync | `WHERE id != 1` filter in `_handle_sync` operators query |
| `enrollment_tokens` / `audit_log` queried by client | Not in `_SYNC_TABLE_ALLOWLIST` — already guarded in `sync.py` |

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
# Wait ~60 s — client should receive all three
# Revoke operator on server — client should lock within 60 s
```

---

## Out of Scope (Phase 2b)

- DM E2E encryption (NaCl Box, key exchange via RNS identity public keys)
- Document file-content sync (broadband download flow)
- LoRa sync optimisations (persistent links, delta compression)

## Current Verification Notes

- `pytest -q` passed with 192 tests after adding startup sync badge suppression.
- Revocation coverage includes live server `operators` push plus explicit
  `operator_revoked` packet handling, and reconnect-time `operator_inactive`
  error handling for clients revoked while offline.
- Offline-create → reconnect → push behavior is covered by integration tests
  that push pending client records to the server and replace them with canonical
  server records.
- The first client sync after login is treated as quiet startup hydration:
  screens can refresh, but old records from a prior app session do not create
  unread badges.

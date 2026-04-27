# Sync Protocol

Core owns the TALON sync protocol and must preserve compatibility during the
platform split.

## Implemented Phase 2 Behavior

- Versioned UTF-8 JSON messages over RNS links.
- Shared framing for packet-size limits and chunk reassembly.
- Server destination: `talon.server`.
- Enrollment token format: `TOKEN:SERVER_HASH`.
- Enrollment `rns_hash` validation is bounded to the installed Reticulum
  identity hash length rather than a hard-coded legacy width.
- Persistent broadband link for sync, heartbeat, push, revocation, and document
  requests.
- LoRa polling fallback at 120 seconds.
- Server-to-client delta sync by table/version.
- Client-to-server outbox push for offline-created records.
- Core service command events feed sync side effects through
  `TalonCoreSession`: server mutations call `notify_change`/`notify_delete`,
  and client primary outbox records are marked pending and queued for push.
- Network-applied records notify the core event stream with table refresh
  events when a client uses event subscriptions instead of the legacy Kivy
  `on_data_pushed` callback.
- `ClientSyncManager.push_record_pending()` is the public client outbox entry
  point used by the facade for immediate chat/SITREP/asset push attempts.
- Tombstone sync for deletes.
- Client document fetch via `document_request` and resource-backed response.

## Synced Tables

| Table | Sync | Notes |
|-------|------|-------|
| `operators` | Yes | Server sentinel excluded from normal client list |
| `assets` | Yes | Client-pushable with server-side ownership checks |
| `sitreps` | Yes | Body decrypted for wire, re-encrypted locally |
| `missions` | Yes | Linked records versioned with lifecycle changes |
| `waypoints` | Yes | Mission route data |
| `zones` | Yes | Mission AO and operational areas |
| `channels` | Yes | Default, mission, custom, DM channels |
| `messages` | Yes | Server-readable until DM E2E lands |
| `documents` | Metadata | Plaintext fetch requires explicit request |
| `enrollment_tokens` | No | Server-only |
| `audit_log` | No | Server-only |

## Message Families

- `enroll_request` / `enroll_response`
- `sync_request` / `sync_response` / `sync_done`
- `heartbeat` / `heartbeat_ack`
- `client_push_records` / `push_ack`
- `document_request` / `document_response`
- `operator_revoked`
- `error` with coded states such as `operator_inactive`

## Core Extraction Requirements

- Keep `protocol.py`, framing, registry, client sync, and server net behavior
  available behind core APIs.
- Preserve schema v15 behavior until an intentional migration is planned.
- Maintain tests for validators, framing, registry allowlists, client push,
  revocation lock, and document cache invalidation.

## Legacy Source

Distilled from
[../archive/legacy/Phase_2_Network_sync.md](../archive/legacy/Phase_2_Network_sync.md).

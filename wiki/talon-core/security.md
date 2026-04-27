# Security

Core owns all security-sensitive behavior. Client UIs present state and collect
operator input; they do not implement crypto or revocation policy.

## Data At Rest

- SQLCipher protects the database.
- Argon2id derives the DB key from the passphrase.
- Current Argon2id target parameters: `time_cost=3`,
  `memory_cost=65536`, `parallelism=1`.
- Field encryption uses PyNaCl `SecretBox` for protected fields such as SITREP
  bodies and audit payloads.
- Document blobs are encrypted before storage and verified with SHA-256 on read.

## Transport

- Reticulum provides transport encryption and routing.
- Core is the only owner of RNS identity, links, interface config, and sync
  packet/resource handling.
- No fallback sync path may bypass RNS.

## Lease And Revocation

- Enrollment creates an operator tied to an RNS identity hash.
- Heartbeat and sync denials with `operator_inactive` locally revoke the client.
- Explicit `operator_revoked` packets force immediate lease re-check.
- Revocation must lock the active enrolled operator without waiting for the next
  normal heartbeat interval.

## Operator Safety Rules

- FLASH and FLASH_OVERRIDE audio alerts are opt-in only.
- Asset verification requires a second party or server authority; clients must
  not verify their own assets by bypassing services.
- Server sentinel `operator_id=1` remains a bridge only until real server
  operator enrollment exists.

## Deferred Security Work

- DM end-to-end encryption is Phase 2b.
- Group chat remains server-readable by design.
- Group key rotation UI is currently a legacy stub and should be redesigned
  through core services.

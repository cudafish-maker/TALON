# Security

Core owns all security-sensitive behavior. Client UIs present state and collect
operator input; they do not implement crypto or revocation policy.

## Data At Rest

- SQLCipher protects the database.
- Argon2id derives the DB key from the passphrase.
- New passphrases and passphrase changes require at least 12 characters and at
  least three character classes.
- Current Argon2id target parameters: `time_cost=3`,
  `memory_cost=65536`, `parallelism=1`.
- Field encryption uses PyNaCl `SecretBox` for protected fields such as SITREP
  bodies and audit payloads.
- Document blobs are encrypted before storage and verified with SHA-256 on read.
- Reticulum identities are protected after DB unlock. Core stores encrypted
  `client.identity.enc` and `server.identity.enc` files using a
  domain-separated SecretBox key derived from the unlocked DB key.
- Legacy plaintext `client.identity` / `server.identity` files may migrate only
  when their path is private; migrated plaintext copies are destroyed.
- TALON data directories, Reticulum config directories, identity files, and DB
  files are created or repaired to private owner-only permissions where safe.

## Transport

- Reticulum provides transport encryption and routing.
- Core is the only owner of RNS identity, links, interface config, and sync
  packet/resource handling.
- No fallback sync path may bypass RNS.
- Clients must call `link.identify(identity)` before TALON enrollment, sync,
  heartbeat, client-push, or document-request payloads.
- The server derives authorization from the identified RNS link and the
  matching active operator record. Legacy payload identity fields are accepted
  only for compatibility and are ignored for authorization.
- Inbound server resources are rejected by default. Clients accept resources
  only for pending document requests, and chunk/resource byte budgets are
  enforced before payloads are read into memory.

## Dataset Visibility

- All active authenticated operators intentionally sync the shared operational
  dataset and may request server-hosted documents. This is an accepted release
  risk for the current product model, not a per-record ACL implementation.
- Any future need-to-know, mission, channel, role, or clearance model must be
  enforced in core before sync delta selection and document transfer.

## Lease And Revocation

- Enrollment creates an operator tied to an RNS identity hash.
- Heartbeat and sync denials with `operator_inactive` locally revoke the client.
- Explicit `operator_revoked` packets force immediate lease re-check.
- Revocation must lock the active enrolled operator without waiting for the next
  normal heartbeat interval.
- Confirmed self-revocation stops sync, closes active links, destroys encrypted
  and legacy client identity files, clears enrollment metadata, marks pending
  outbox rows revoked, and requires fresh enrollment before network sync can
  restart.

## Operator Safety Rules

- FLASH and FLASH_OVERRIDE audio alerts are opt-in only.
- Asset verification requires a second party or server authority; clients must
  not verify their own assets by bypassing services.
- Server sentinel `operator_id=1` remains a bridge only until real server
  operator enrollment exists.
- Full RNS identity and destination hashes are DEBUG-only diagnostics. INFO logs
  may include short prefixes for operational correlation.
- Generated FLASH alert audio uses an application-private temp/cache path rather
  than a fixed shared `/tmp` filename.

## Deferred Security Work

- DM end-to-end encryption is Phase 2b.
- Group chat remains server-readable by design.
- Group key rotation UI is currently a legacy stub and should be redesigned
  through core services.

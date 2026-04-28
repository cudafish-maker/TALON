# Security Review: T.A.L.O.N.

## Executive Summary

T.A.L.O.N. uses appropriate cryptographic building blocks in several places: Reticulum `SINGLE` destinations for transport, SQLCipher for the database, Argon2id for key derivation, and PyNaCl `SecretBox` for selected fields. The most serious findings are above those primitives: server-side authorization trusts client-supplied JSON identity fields instead of the authenticated Reticulum link, and the client RNS private identity is stored outside the passphrase-protected database. Under the requested physical-access model, an attacker who can copy a client machine has a direct path to impersonation and offline data attack, with the passphrase only protecting SQLCipher content, not the Reticulum identity file.

## Remediation Status

Completed on 2026-04-28. This review remains as the original finding record;
the checklist below records the implemented remediation state for follow-on
sessions.

- [x] C-1: Privileged server requests require an authenticated Reticulum link
  identity. The server derives operator context from `link.identify(...)`
  rather than JSON `operator_rns_hash` / enrollment `rns_hash` fields.
- [x] H-1 / L-3: Client and server RNS identity files are encrypted as
  `client.identity.enc` / `server.identity.enc` after SQLCipher unlock, with
  private runtime directory and file-mode checks.
- [x] H-2: Client push uses explicit per-table server validators for assets,
  SITREPs, missions, zones, and messages instead of generic upsert.
- [x] H-3: All-active operator dataset visibility is documented as an accepted
  release risk; sync and document download still require authenticated active
  operator context.
- [x] M-1: Resource acceptance and chunk reassembly enforce state and size
  budgets, and budget violations close links.
- [x] M-2: Confirmed client self-revocation stops sync, destroys identity
  files, clears enrollment metadata, and marks pending outbox rows revoked.
- [x] M-3 / L-1 / L-2: New/change passphrases require at least 12 characters
  and three character classes, full RNS hashes are DEBUG-only, and audio alert
  files use a private temp/cache path.

Verification:

- [x] `pytest -q tests/test_protocol.py tests/test_sync.py tests/test_registry.py tests/test_revocation.py tests/test_audio_alerts.py tests/test_crypto.py`
  passed, 116 tests.
- [x] `pytest -q` passed, 298 passed and 1 skipped.
- [x] `python -m talon_desktop.main --loopback-smoke` passed with same-machine
  Reticulum enrollment/sync smoke output `TALON_PACKAGE_LOOPBACK_OK`.

## Scope And Threat Model

Reviewed application source, tests, build/config helpers, and the requested Reticulum security-review skill references. Project documentation was not used as an authority for findings.

Assumed attacker capabilities:

- A remote attacker can operate a Reticulum node on the same reachable mesh or transport.
- A stronger attacker can obtain physical access to a client machine and copy local files.
- The client machine is protected only by the TALON passphrase, unless the deployment adds OS full-disk encryption or equivalent controls.
- A compromised or malicious enrolled client is in scope.

Reticulum topology observed:

- Server destination: `RNS.Destination(..., RNS.Destination.IN, RNS.Destination.SINGLE, "talon", "server")` in `talon_core/server/net_handler.py:195`.
- Client sessions: `RNS.Link(dest)` to the server destination in `talon_core/network/client_components.py:1166`, `talon_core/network/client_components.py:1273`, `talon_core/network/client_components.py:1365`, and `talon_core/network/client_components.py:1446`.
- Custom application protocol: UTF-8 JSON plus `MSG_CHUNK` framing and Reticulum resources in `talon_core/network/protocol.py:97`.
- Interface exposure is configuration-driven. The code loads Reticulum interface classes including TCP, UDP, I2P, RNode, Serial/KISS, Auto, Pipe, and Weave in `talon_core/network/node.py:23`.
- No `Destination.PLAIN`, `Destination.GROUP`, LXMF, `pickle.loads`, `marshal.loads`, `eval`, `exec`, AES-ECB, MD5, or SHA-1 use was found in the reviewed application code.

## Critical Findings

### [C-1] Server Authorizes Requests By A Client-Supplied RNS Hash

**File:** `talon_core/server/net_components.py:563`

**Impact:** Any node that knows an active operator RNS hash can claim that operator and receive sync data, request documents, renew leases, register a push link, and submit client-pushed records without proving possession of the corresponding RNS private key.

**Detail:** The server registers an incoming link and immediately dispatches packets with no remote identity challenge or `set_remote_identified_callback` gate at `talon_core/server/net_components.py:225`. Authorization decisions then use `operator_rns_hash = msg.get("operator_rns_hash", "").strip()` from the JSON payload at `talon_core/server/net_components.py:563`, `talon_core/server/net_components.py:624`, `talon_core/server/net_components.py:671`, and `talon_core/server/net_components.py:758`. The active check only queries `operators.rns_hash` for the attacker-provided value at `talon_core/server/net_components.py:575`.

The client constructs this field from its local identity hash at `talon_core/network/client_components.py:1079` and sends it in sync requests at `talon_core/network/client_components.py:1096`. That hash is a public identifier, not a secret, and the server syncs operator rows including `rns_hash` to clients through `talon_core/server/net_components.py:117`. Under the physical-access model, an attacker can also copy or inspect a client DB after unlocking or passphrase recovery.

This is the Reticulum architectural fallacy pattern: Reticulum secures the link to the server destination, but TALON does not bind privileged application actions to a cryptographic proof that the peer owns the claimed operator identity.

**Recommended Fix:** Require proof of possession for every privileged session. Either use Reticulum link identity (`link.identify(...)` on the client plus server-side remote identified callback, if available for this RNS version) or implement a server nonce challenge where the client signs with its RNS identity private key and the server verifies that the public key hash matches `operators.rns_hash`. Reject messages until the link has an authenticated operator context, and remove `operator_rns_hash` from client-authoritative request bodies.

## High Findings

### [H-1] Client RNS Private Identity Is Stored Outside Passphrase Protection

**File:** `talon_core/crypto/identity.py:22`

**Impact:** A physical attacker can copy `client.identity` and impersonate the client identity without knowing the TALON passphrase.

**Detail:** Client identity loading stores the Reticulum identity at `<data_dir>/client.identity` in `talon_core/network/client_components.py:862`. The helper creates the parent directory and calls `identity.to_file(path_str)` at `talon_core/crypto/identity.py:22`. There is no application-enforced file mode, directory mode, encryption with the TALON passphrase, or OS keystore binding. By contrast, the salt file is created with `0o600` at `talon_core/crypto/keystore.py:38`.

This matters because the local database is passphrase-derived SQLCipher, but the Reticulum private identity is not. In the requested physical-access model, the RNS identity becomes the weakest local secret. Combined with [C-1], an attacker does not even need this private key to claim a hash; once [C-1] is fixed, this plaintext identity file would still be sufficient for network impersonation.

**Recommended Fix:** Store RNS identities with the same or stronger protection as the DB key. At minimum, create the data directory at `0o700`, create identity files with `os.open(..., 0o600)`, verify permissions on load, and fail closed on world/group-readable files. Prefer encrypting identity material with a passphrase-derived or OS-keystore key and decrypting only after unlock.

### [H-2] Client Push Accepts Server-Controlled Columns Without Domain Validation

**File:** `talon_core/network/registry.py:271`

**Impact:** A malicious or compromised client can create records with server-controlled or workflow-sensitive values, such as an already-active mission, instead of being constrained to the normal client workflow.

**Detail:** `client_push_records` validation only checks that table names are strings and records are JSON objects at `talon_core/network/protocol.py:297`. The server then copies all provided fields except `id` and `sync_status` at `talon_core/network/registry.py:282`, forces only ownership fields and a few table-specific values at `talon_core/network/registry.py:290`, and passes the result to `_upsert_record` at `talon_core/server/net_components.py:825`. `_upsert_record` filters to live schema columns but does not enforce domain rules or server-only columns at `talon_core/network/sync.py:216`.

`missions` is marked `client_pushable=True` at `talon_core/network/registry.py:60`, but no forced `status = 'pending_approval'` exists. The database schema default for `missions.status` is `'active'` at `talon_core/db/migrations.py:64`. A malicious client can therefore push an active mission or other invalid workflow state. Similar validation gaps exist for ranges, lengths, foreign keys, enum values, timestamps, and mission/asset relationships.

**Recommended Fix:** Do not insert client-pushed records through generic upsert. Define explicit server-side DTOs per pushable table, drop all server-controlled fields, validate all values with the same domain functions used by local commands, and force workflow values such as `missions.status = 'pending_approval'`.

### [H-3] Any Active Operator Can Sync All Records And Request Any Document

**File:** `talon_core/server/net_components.py:584`

**Impact:** A single compromised or physically captured client can retrieve the shared operational dataset and any server-hosted document, including data not already cached locally.

**Detail:** Once `_operator_active()` succeeds, `handle_sync()` iterates every syncable table and sends all deltas at `talon_core/server/net_components.py:584`. `handle_document_request()` checks only that the claimed operator is active at `talon_core/server/net_components.py:675`, then downloads the requested document by integer ID at `talon_core/server/net_components.py:702` and sends plaintext over an RNS resource at `talon_core/server/net_components.py:724`. There is no per-record, per-channel, mission, role, clearance, or need-to-know authorization.

If the intended product model is "all active operators see everything," severity drops to an accepted design risk. Under the requested physical-access model, this still means one captured passphrase or one unlocked client exposes the full shared data plane.

**Recommended Fix:** Add server-side ACLs before sync and document transfer. At minimum, authorize document IDs against operator membership or mission/channel scope, and filter sync deltas by the authenticated operator context established in [C-1].

## Medium Findings

### [M-1] Incoming RNS Resources Are Accepted And Read Into Memory Without Size Or State Limits

**File:** `talon_core/server/net_components.py:229`

**Impact:** A malicious peer can consume server or client memory and CPU by establishing links and sending oversized resources or excessive incomplete transfers.

**Detail:** The server accepts all resources with `link.set_resource_callback(lambda _resource: True)` at `talon_core/server/net_components.py:229`. Completed resources are read fully into memory with `resource.data.read()` and handed to packet dispatch at `talon_core/server/net_components.py:237`. The client uses the same accept-all pattern at `talon_core/network/client_components.py:1169` and reads resource payloads at `talon_core/network/client_components.py:1130`. LoRa sync does likewise at `talon_core/network/client_components.py:1368` and `talon_core/network/client_components.py:1370`.

The chunk reassembler caps fragment count and buffer count, but it base64-decodes `msg["data"]` without checking encoded or decoded chunk length at `talon_core/network/framing.py:132`. There is also no visible per-source link rate limit before callbacks are installed at `talon_core/server/net_components.py:225`.

**Recommended Fix:** Accept resources only when a state machine expects them, enforce maximum resource byte counts before reading into memory, add per-link and per-source rate limits, cap chunk encoded/decoded size, and close links that exceed protocol budgets.

### [M-2] Revocation Does Not Burn The Client Identity On The Client

**File:** `talon_core/network/client_components.py:429`

**Impact:** After a local revocation lock, the RNS private identity remains on disk and can still be copied from a physically captured machine.

**Detail:** When the client receives an inactive error or `operator_revoked`, it marks the operator row revoked and clears `rns_hash` in the local DB at `talon_core/network/client_components.py:429`. It then triggers the local lock check at `talon_core/network/client_components.py:458`. It does not call `destroy_identity()` for `<data_dir>/client.identity`, clear `server_rns_hash`, or remove queued local identity material.

This is partly mitigated if the server continues rejecting the revoked operator. It remains a material physical-access issue because the private identity file survives the lock event and [C-1] currently weakens server rejection semantics.

**Recommended Fix:** On confirmed self-revocation, stop sync, destroy or encrypt-retire `client.identity`, clear enrollment metadata, purge pending outbox state as policy requires, and require fresh enrollment for reactivation.

### [M-3] Passphrase Is The Sole Offline DB Control But Only Non-Empty Input Is Enforced

**File:** `talon_core/session.py:240`

**Impact:** A physical attacker who copies `talon.db` and `talon.salt` can run offline passphrase guessing with no server-side rate limit; weak passphrases become the practical security boundary.

**Detail:** The UI accepts any non-empty passphrase in `talon_desktop/app.py:123` and `talon/ui/screens/login_screen.py:44`. The core derives SQLCipher keys with Argon2id at `talon_core/session.py:240`, using parameters `time_cost=3`, `memory_cost=65536`, and `parallelism=1` from `talon_core/constants.py:109`. These parameters are reasonable for mobile usability, but there is no minimum length, entropy check, breached-password check, or hardware-backed key wrap.

This is a conditional finding: if deployments mandate strong passphrases and OS full-disk encryption, severity drops. Under the stated "passphrase only" client protection model, it is an important risk.

**Recommended Fix:** Enforce a high-entropy passphrase policy, add a passphrase change/migration path, consider stronger desktop KDF profiles, and prefer wrapping the DB key with OS keystore, TPM, Secure Enclave, or platform credential APIs where available.

## Low Findings

### [L-1] RNS Identity And Destination Hashes Are Logged At INFO

**File:** `talon_core/network/client_components.py:864`

**Impact:** Plaintext logs can persist operator identity hashes and server destination hashes, weakening pseudonymity and making later traffic correlation easier.

**Detail:** Client identity hashes are logged at INFO in `talon_core/network/client_components.py:864`. The server destination hash is logged at INFO in `talon_core/server/net_handler.py:207`, and generic announcements log destination hashes in `talon_core/network/node.py:102`. These hashes are not secret, but they are durable identifiers. Logs often have broader retention and access than encrypted application data.

**Recommended Fix:** Move full hashes to DEBUG-only diagnostics, redact to short prefixes in INFO logs, and document production log retention expectations.

### [L-2] Fixed Audio Temp File Can Be Symlinked On Shared Systems

**File:** `talon/audio_alerts.py:96`

**Impact:** If the legacy Kivy app runs with elevated privileges on a shared machine, a local attacker could pre-create `/tmp/talon_flash_alert.wav` as a symlink and cause overwrite of an unintended file.

**Detail:** The alert generator uses a predictable path under `tempfile.gettempdir()` at `talon/audio_alerts.py:96`, then writes it through `wave.open(str(path), "w")` at `talon/audio_alerts.py:141`. In normal non-root desktop use this is low impact, but fixed names in shared temp directories are avoidable.

**Recommended Fix:** Use an application-private cache directory or create temp files with `os.open(..., O_CREAT | O_EXCL, 0o600)` / `NamedTemporaryFile(delete=False)` and verify the path is not a symlink.

### [L-3] Runtime Directories And SQLCipher DB File Rely On Process Umask

**File:** `talon_core/db/connection.py:322`

**Impact:** On multi-user systems with permissive umask values, local users may be able to copy encrypted DB files, Reticulum config, or identity directories for offline attack.

**Detail:** The SQLCipher database parent directory is created with default permissions at `talon_core/db/connection.py:322`. The Reticulum config directory is similarly created with default permissions at `talon_core/network/node.py:63`. The salt file is correctly created as `0o600` at `talon_core/crypto/keystore.py:38`, and document storage is created as `0o700` at `talon_core/documents.py:160`, but the broader runtime storage hardening is inconsistent.

**Recommended Fix:** Create all TALON data and Reticulum directories with `0o700`, verify mode on startup, chmod existing directories where safe, and warn or refuse to start if identity or DB material is group/world-readable.

## Recommendations

1. Fix [C-1] first. Establish an authenticated operator context per RNS link and remove all trust in client-supplied `operator_rns_hash` values.
2. Fix [H-1] next. Treat `client.identity` and `server.identity` as passphrase-protected secrets, enforce private file permissions, and protect them at least as strongly as the SQLCipher DB.
3. Replace generic client-push upsert with per-table domain validators for [H-2].
4. Decide whether [H-3] is intentional. If not, add server-side ACLs before sync and document transfer.
5. Add resource and link budget enforcement for [M-1].
6. Make revocation destructive on the client where policy requires, addressing [M-2].
7. Strengthen local physical-access controls for [M-3], [L-1], and [L-3].

## Positive Security Notes

- Network payloads use JSON validation rather than unsafe `pickle`, `marshal`, `eval`, or `exec`.
- Dynamic table names used by sync paths are routed through allowlists in `talon_core/network/registry.py` and `talon_core/network/sync.py`.
- Enrollment tokens are generated with `os.urandom(32)` in `talon_core/server/enrollment.py:32`.
- Salt files are created with `0o600` in `talon_core/crypto/keystore.py:38`.
- Document upload has meaningful filename sanitization, extension/MIME blocking, path traversal checks, encryption, and SHA-256 integrity verification.

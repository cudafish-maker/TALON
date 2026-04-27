# Fixed Bugs & Closed Issues

_Archive of resolved issues. When a bug in [../bugs.md](../bugs.md) is fixed, move its full entry here and update the summary counts in both files._

_Severity: CRITICAL > HIGH > MEDIUM > LOW > NOTE._

---

## Summary

| Status | Count |
|--------|-------|
| FIXED  | 108   |
| CLOSED (non-issue) | 1 |

---

## Fixed Issues

### [BUG-090] PySide6 desktop misses network-applied refresh events
- **File:** `talon_core/session.py`, `talon_core/services/events.py`, `talon_desktop/qt_events.py`
- **Severity:** HIGH
- **Category:** Bug / Sync / UI Refresh
- **Status:** FIXED 2026-04-27
- **Description:** Network-applied records could update the local database
  without refreshing the PySide6 desktop. The client and server sync managers
  notified `TalonCoreSession._notify_client_ui()` /
  `_notify_server_ui()`, but the PySide6 runtime does not install the legacy
  `on_data_pushed` callback used by Kivy. As a result, server-to-client changes
  and server UI refreshes after client pushes could require manual refresh even
  though sync traffic arrived.
- **Fix:** Core now emits a `ui_refresh_requested` event for network table
  notifications when no legacy callback is installed, preserving the Kivy badge
  callback path when it is present. Operator sync notifications now map to
  operator/client/chat refresh targets. The Qt event bridge now queues
  cross-thread core callbacks onto the Qt object thread before emitting refresh
  signals. Regression tests cover core network refresh event publication,
  legacy callback precedence, desktop event mapping, and sync notification
  behavior.

---

### [BUG-089] Linux installer archive auto-discovery can select unrelated downloads
- **File:** `build/install-talon.sh`, `.github/workflows/build-desktop.yml`
- **Severity:** HIGH
- **Category:** Release / Installer
- **Status:** FIXED 2026-04-26
- **Description:** Running the standalone installer from a directory such as `~/Downloads` could select an unrelated archive, for example `pycharm-2025.3.3-aarch64.tar.gz`, because archive auto-discovery inspected generic `.tar.gz` files and treated nested archive-like entries as possible TALON payloads.
- **Fix:** The Linux release now embeds the installer inside the tarball as `talon-linux/install.sh`. Users extract `talon-linux.tar.gz`, `cd talon-linux`, and run `bash ./install.sh`; the installer uses its own extracted bundle directory as the source and no longer scans nearby archives or accepts archive inputs. The GitHub workflow now copies `build/install-talon.sh` into `dist/talon-linux/install.sh`, packages that directory, smoke-installs from the extracted bundle, and publishes only the tarball plus checksum for Linux.

---

### [BUG-088] Linux reinstall can select the current install as its source
- **File:** `build/install-talon.sh`
- **Severity:** HIGH
- **Category:** Release / Installer
- **Status:** FIXED 2026-04-25
- **Description:** Running `./install-talon.sh` from a home directory containing both the downloaded release assets and an existing `~/.local/share/talon/talon-linux` install could fail during reinstall. No-argument discovery returned the whole search directory, then bundle resolution found the existing installed bundle before the downloaded archive. The installer moved that installed bundle to a backup and then attempted to copy from the now-moved source path, producing `cp: cannot stat ... talon-linux` and `ERROR: Failed to stage TALON bundle.`
- **Fix:** Archive auto-discovery has been removed from the installer. The Linux release now embeds `install.sh` inside the extracted `talon-linux/` bundle, and the installer uses that bundle directory as its default source. `install_bundle` also refuses to use the current install target as the source bundle before moving the old install aside. The dependency checker now finds `ldconfig` under `/sbin` or `/usr/sbin` so normal-user installs on Debian/Mint do not falsely report installed libraries as missing. Local repro validation covered installing from an extracted release bundle with an existing install already present.

---

### [BUG-087] Fresh Linux client can fail Kivy startup with no matching FB config
- **File:** `main.py`, `build/install-talon.sh`
- **Severity:** MEDIUM
- **Category:** Release / Installer / Graphics
- **Status:** FIXED 2026-04-26
- **Description:** On a fresh Linux client machine, the packaged app could fail during Kivy/SDL/OpenGL startup with a graphics stack error such as `No matching FB config found`. The first mitigation added missing Mesa/GLX/DRI packages and disabled multisampling, but a Linux Mint test host still showed SDL2 failing and Kivy falling back to the X11/GLX window provider. A follow-up forced SDL EGL, which avoided the fallback but failed on the same Mint host with `Could not get EGL display`.
- **Fix:** `main.py` now sets Kivy environment defaults before any Kivy import: `KIVY_WINDOW=sdl2` keeps Kivy from falling back to the X11 provider, `LIBGL_ALWAYS_SOFTWARE=1` defaults Linux to Mesa software GL, and Kivy `graphics.multisamples` is still set to `0` on desktop platforms before any window/app import. The installed `talon` launcher and Linux smoke-test environment also export the same Kivy/SDL defaults from process start. The Linux installer checks for `libGLX.so.0`, uses common library-path fallback checks when `ldconfig` is incomplete, and installs the relevant Mesa/GLX/DRI runtime packages across supported package managers (`libglx-mesa0`/`libegl-mesa0`/`mesa-utils` on apt-family systems, `mesa-dri-drivers`/`glx-utils` on dnf/yum, `Mesa-dri` on zypper, and `mesa` on pacman). Users should still run TALON as their normal desktop user, not via `sudo`, because root sessions can lack the display and X authority needed by Kivy.

---

### [BUG-086] Linux installer cannot locate bundle inside release artifact wrapper
- **File:** `build/install-talon.sh`
- **Severity:** MEDIUM
- **Category:** Release / Installer
- **Status:** FIXED 2026-04-25
- **Description:** Installing on another machine could fail with `No TALON PyInstaller bundle found in tarball` when the provided input was not the raw PyInstaller bundle directory but a wrapper archive or extracted artifact containing `talon-linux.tar.gz`. The installer only searched extracted trees for a `talon` executable next to `_internal/base_library.zip`.
- **Fix:** The installer now accepts direct `.tar.gz` bundles with arbitrary GitHub/tag filenames, `.zip` artifacts, extracted bundle directories, directories containing release archives, and nested release archives. With no path argument, it searches next to the installer first and then the current directory for a compatible release archive. It inspects archive contents instead of depending on `talon-linux*` naming, safely extracts zip entries, adds `unzip` to dependency checks/package lists, and resolves the inner PyInstaller bundle before installation. Local smoke validation covered direct `talon-linux.tar.gz`, no-arg install beside a versioned/space-containing tarball name, a GitHub-style zip containing the tarball, and an extracted artifact directory containing the tarball.

---

### [BUG-084] Client chat push and active-screen refresh gaps
- **File:** `talon/network/registry.py`, `talon/db/migrations.py`, `talon/chat.py`, `talon/server/net_handler.py`, `talon/app.py`
- **Severity:** HIGH
- **Category:** Bug / Sync / UI Refresh
- **Status:** FIXED 2026-04-22
- **Description:** Client-authored chat messages were written locally but never pushed to the server because `messages` was syncable but not client-pushable and lacked `sync_status`, so `app.net_notify_change("messages", id)` was skipped in client mode. Incoming SITREPs updated the peer database but did not refresh the main dashboard because `sitreps` only targeted the SITREP screen. Server-side acceptance of client-pushed SITREPs/missions/messages updated the server DB and rebroadcast to clients but did not notify the server UI thread, so active server screens stayed stale until navigation.
- **Fix:** Added migration 0015 for `messages.sync_status`, made `messages` client-pushable/offline-creatable with `sender_id` derived from the authenticated operator, and encoded pushed message bodies back to bytes on server insert. Added `main` as a SITREP refresh target and scheduled server UI refreshes after accepted client pushes. Added regressions for chat message push, message sync metadata, registry transforms, and server UI notification.

---

### [BUG-083] Image upload sanitization fails open when Pillow re-encoding fails
- **File:** `talon/documents.py` lines 134–156
- **Severity:** MEDIUM
- **Category:** Security / File Upload Sanitization
- **Status:** FIXED 2026-04-22
- **Description:** `_sanitize_image()` logs a warning and returns the original bytes if Pillow cannot re-encode an image. The upload pipeline treats image re-encoding as the step that strips EXIF and prevents image polyglots, so a malformed image or parser edge case can bypass that hardening while still being accepted as an image by MIME detection.
- **Fix:** `_sanitize_image()` now raises `DocumentBlockedExtension` when Pillow is installed but image re-encoding fails. Pillow absence remains an explicit logged fallback, but parser/re-encode failures no longer store the original bytes. Added a regression test that simulates Pillow failing during image open and asserts the upload path fails closed.

---

### [BUG-082] First-run enrollment leaves `app.operator_id` and lease monitoring unset until restart
- **File:** `talon/ui/screens/login_screen.py` lines 344–351
- **Severity:** HIGH
- **Category:** Bug / Enrollment / Lease Enforcement
- **Status:** FIXED 2026-04-22
- **Description:** During first-run client enrollment, `_do_login()` starts `SyncEngine` with `operator_id=None` before enrollment. After `ClientSyncManager.enroll()` succeeds, the UI callback starts client sync and navigates to `main`, but it never assigns `app.operator_id = operator_id` and never restarts or updates `app.sync_engine` with the enrolled operator id. Until the app is restarted, ownership checks that depend on `app.operator_id` are wrong and the local lease/revocation heartbeat cannot lock the client.
- **Fix:** The enrollment success callback now assigns `app.operator_id` immediately and updates the running lease monitor via `SyncEngine.set_operator_id()`. The client sync loop is started after that state is set, so ownership checks and lease/revocation monitoring use the enrolled operator without requiring an app restart.

---

### [BUG-081] Delete tombstones are pushed before the local delete succeeds
- **File:** `talon/ui/screens/asset_screen.py` lines 511–513, `talon/ui/screens/sitrep_screen.py` lines 300–301, `talon/ui/screens/mission_screen.py` lines 798–805, `talon/ui/screens/document_screen.py` lines 631–632, `talon/ui/screens/chat_screen.py` lines 1362–1364
- **Severity:** HIGH
- **Category:** Bug / Sync / Data Integrity
- **Status:** FIXED 2026-04-22
- **Description:** Several server UI delete flows call `app.net_notify_delete()` before executing the actual local delete. `notify_delete()` writes a tombstone and pushes `push_delete` immediately. If the subsequent DB/filesystem delete fails, connected clients and future reconnecting clients can delete records that still exist on the server, permanently diverging from the authoritative state.
- **Fix:** Asset, SITREP, mission, document, and chat-message delete flows now perform the local delete first and only write tombstones/push deletes after the delete commits. Multi-row mission deletes still pre-collect affected ids before the transaction, but tombstones are emitted only after `delete_mission()` succeeds. Comments on `net_notify_delete()` / `notify_delete()` were updated to reflect the post-commit contract.

---

### [BUG-080] Malformed `MSG_CHUNK` sequence metadata can crash packet callbacks
- **File:** `talon/server/net_handler.py` lines 645–662, `talon/network/client_sync.py` lines 933–950
- **Severity:** HIGH
- **Category:** Security / Denial of Service / Input Validation
- **Status:** FIXED 2026-04-22
- **Description:** `_handle_chunk_data()` accepts arbitrary `seq` and `total` values. A packet such as `seq=99,total=1` makes `len(buf) == total` true, then `b"".join(buf[i] for i in range(total))` raises `KeyError` because fragment `0` is missing. On the server, chunk reassembly happens before the main handler try/except in `_on_packet()`, so malformed chunk metadata can escape the protocol error path and disrupt the RNS callback/session.
- **Fix:** Server and client chunk handlers now validate `msg_id`, integer `seq`, integer `total`, sane total bounds, `0 <= seq < total`, duplicate fragments, and mid-stream total changes before buffering. Reassembly is wrapped so missing fragments are logged and dropped instead of raising. Added regression tests for out-of-range chunk metadata on both server and client handlers.

---

### [BUG-079] Mission relationship updates do not bump child record versions
- **File:** `talon/missions.py` lines 125–128, 201–220, 391–395; `talon/sitrep.py` lines 80–85
- **Severity:** MEDIUM
- **Category:** Bug / Sync / Data Integrity
- **Status:** FIXED 2026-04-22
- **Description:** Mission workflows update related rows without incrementing those rows' `version` counters. `create_mission()` and `approve_mission()` set `assets.mission_id`, `_transition()` releases assets, and `link_sitreps_to_mission()` changes `sitreps.mission_id`, but none of those statements include `version = version + 1`. Active clients may receive explicit pushes from some UI paths, but offline clients rely on version-map delta sync and will not receive these changed relationships if their local version already matches the server's unchanged version.
- **Fix:** Mission asset allocation, release, approval replacement, mission deletion unlinking, SITREP mission linking, and asset-delete SITREP unlinking now bump child `version` counters. Mission-create and mission-approval UI paths now notify all affected child assets, including released assets. Added regression tests covering mission create, approve replacement, transition release, mission delete unlinking, and SITREP link updates.

---

### [BUG-078] Operator revocation, lease, and profile changes do not bump `operators.version`
- **File:** `talon/server/revocation.py` lines 75–79, `talon/server/enrollment.py` lines 142–144, `talon/operators.py` lines 65–67 and 85–87
- **Severity:** HIGH
- **Category:** Bug / Sync / Revocation
- **Status:** FIXED 2026-04-22
- **Description:** The operators table is synced by version, but several operator updates do not increment `operators.version`: revocation, lease renewal, skill updates, and profile updates. Server UI paths call `net_notify_change("operators", operator_id)`, but the client discards a pushed record when its local version is greater than or equal to the server version. This can prevent revoked/renewed operator state from reaching clients and directly blocks the Phase 2 lock/revocation-over-network requirement.
- **Fix:** Revocation, lease renewal, skill updates, and profile updates now increment `operators.version`. UI lease renewals notify connected clients, and heartbeat-triggered lease renewals enqueue an operators push as well. Added regression tests for lease renewal, revocation, skills, and profile version bumps.

---

### [BUG-077] `SyncEngine._upsert_record()` uses `INSERT OR REPLACE`, which can delete existing rows
- **File:** `talon/network/sync.py` lines 190–220
- **Severity:** HIGH
- **Category:** Bug / Sync / Data Integrity
- **Status:** FIXED 2026-04-22
- **Description:** SQLite's `INSERT OR REPLACE` resolves conflicts by deleting the existing row and inserting a new one. For synced parent rows that already have local children (for example missions with waypoints/channels, assets with SITREPs, or channels with messages), this can fail with FK constraints or trigger delete semantics instead of an update. It also amplifies client-push id collision risk because a conflicting primary key can replace an unrelated row.
- **Fix:** `_upsert_record()` now uses `INSERT ... ON CONFLICT(id) DO UPDATE SET ...` when an id is present, preserving existing rows in place. Records without an id are inserted normally so the local database allocates the primary key. Added regression tests that upsert an asset with a dependent SITREP and assert the child reference survives.

---

### [BUG-076] Client push trusts author and verification fields supplied by the client
- **File:** `talon/server/net_handler.py` lines 430–455
- **Severity:** HIGH
- **Category:** Security / Authorization / Data Integrity
- **Status:** FIXED 2026-04-22
- **Description:** For new client-pushed records, the server accepts `created_by`, `author_id`, `verified`, and `confirmed_by` values from the untrusted record payload. The current asset self-verification guard only strips verification when `created_by == pushing_operator_id`; a crafted client can claim another `created_by` value and submit `verified=1` or spoof mission/zone/SITREP authorship. The server already knows the pushing operator from `operator_rns_hash` and should not trust identity-bearing fields from the client.
- **Fix:** Server client-push ingest now derives the pushing operator from `operator_rns_hash` and overwrites identity fields for client-created assets, missions, zones, and SITREPs. New client-pushed assets are forced to `verified=0` and `confirmed_by=NULL` regardless of inbound payload. Added a regression test that spoofs creator/verification fields and asserts the stored server row uses the authenticated operator and remains unverified.

---

### [BUG-075] Client-pushed records preserve local `id`, allowing replacement of unrelated server rows
- **File:** `talon/server/net_handler.py` lines 430–455, `talon/network/client_sync.py` lines 765–799, `talon/network/sync.py` lines 190–220
- **Severity:** CRITICAL
- **Category:** Security / Data Integrity / Sync
- **Status:** FIXED 2026-04-22
- **Description:** `_collect_outbox()` serializes `SELECT *` pending rows, including the client's local primary key `id`. `_handle_client_push()` removes only `sync_status` and passes the rest to `SyncEngine._upsert_record()`. If the incoming UUID is unknown but the local `id` collides with an existing server row, `INSERT OR REPLACE` can replace the server's unrelated canonical record with the client's offline record. This is likely for first offline records because SQLite ids commonly start at `1`, and a malicious enrolled client can intentionally choose colliding ids.
- **Fix:** Server client-push ingest strips `id` from unknown-UUID records before insertion, so the server allocates the canonical row id. `_upsert_record()` no longer uses `INSERT OR REPLACE`, removing the replacement path as a second layer of protection. Added regression tests where a client pushes an unknown UUID with `id=1` while server row `id=1` already exists; the original row remains unchanged and the pushed row receives a different id.

---

### [BUG-073] Silent `except Exception: pass` in `config.py` hides init errors
- **File:** `talon/config.py` line 25
- **Severity:** LOW
- **Category:** Code Quality / Error Handling
- **Status:** FIXED 2026-04-22
- **Description:** `_default_data_dir()` catches all exceptions with no logging when probing the running Kivy app for `user_data_dir`. A Kivy import error, unexpected API change, or attribute error is silently swallowed, making startup failures in the data-directory resolution path invisible. The fallback to `~/.talon` is correct, but the failure itself should at least emit a `_log.debug()` so it shows up in debug traces.
- **Fix:** Added a config logger and replaced the silent catch with `except Exception as exc: _log.debug("Kivy app not available for data dir: %s", exc)`.

---

### [BUG-072] Chunk reassembly buffer has no per-source limit — DoS vector
- **File:** `talon/server/net_handler.py` lines 607–633, `talon/network/client_sync.py` lines 895–913
- **Severity:** MEDIUM
- **Category:** Security / Denial of Service
- **Status:** FIXED 2026-04-22
- **Description:** `_handle_chunk_data` buffers incomplete fragment reassemblies keyed by `msg_id`. There is no cap on how many concurrent incomplete reassembly buffers one client may create. An enrolled client can flood the server (or a peer client) with partial chunks using unique `msg_id` values, consuming unbounded memory until the 60 s TTL GC runs. In a constrained LoRa/mesh environment this can bring down the server process.
- **Fix:** Server and client chunk handlers now cap incomplete reassembly buffers at 50 entries and drop the oldest buffer when the cap is reached. They also cap fragment totals at 4096 per message. Added a regression test that creates 51 server chunk buffers and verifies the oldest is evicted.

---

### [BUG-071] No maximum-length validation on callsign or `rns_hash` at enrollment
- **File:** `talon/server/net_handler.py` lines 256–270
- **Severity:** MEDIUM
- **Category:** Security / Input Validation
- **Status:** FIXED 2026-04-22
- **Description:** `_handle_enroll()` checks that `callsign`, `rns_hash`, and `token` are non-empty but imposes no upper-length limit. An attacker in possession of a valid enrollment token could create a callsign of arbitrary length (megabytes), which would be stored in the DB and echoed in UI widgets, audit logs, and protocol messages.
- **Fix:** Network enrollment now rejects callsigns longer than 32 characters and rejects client RNS hashes unless they are exactly 64 hex characters before calling `create_operator()`.

---

### [BUG-070] UUID values from client push not validated for format
- **File:** `talon/server/net_handler.py` lines 410–411
- **Severity:** MEDIUM
- **Category:** Security / Input Validation
- **Status:** FIXED 2026-04-22
- **Description:** `_handle_push_records()` checks only truthiness of the `uuid` field (`if not uuid_val: continue`). A malformed value (wrong length, non-hex chars, empty string with spaces) is not rejected and gets stored directly in the database and echoed back to all clients via sync. `SyncEngine._upsert_record` does no additional UUID validation.
- **Fix:** Server client-push ingest now parses UUIDs with `uuid.UUID(...)`, normalizes accepted values to 32-character hex, and skips malformed UUIDs. Added a regression test that pushes `not-a-uuid` and asserts no row is stored and no UUID is accepted.

---

### [BUG-069] `int(msg.get("last_sync_at", 0))` raises unhandled `ValueError` on bad client input
- **File:** `talon/server/net_handler.py` line 307
- **Severity:** HIGH
- **Category:** Bug / Input Validation
- **Status:** FIXED 2026-04-22
- **Description:** `_handle_sync()` casts the client-supplied `last_sync_at` field directly with `int(...)`. If the client sends a non-numeric string (e.g. `"now"` or `""`), Python raises `ValueError`, which is not caught. This propagates up to the RNS packet callback, causing an unhandled exception in the server's sync handler for that link. An authenticated client can exploit this to crash a sync session.
- **Fix:** `_handle_sync()` now catches `TypeError` and `ValueError`, logs the bad value, and falls back to `last_sync_at = 0`.

---

### [BUG-058] `app.operator_id` never set — missions, SITREPs, and chat silently use SERVER sentinel
- **File:** `talon/ui/screens/mission_screen.py` line 998, `talon/ui/screens/sitrep_screen.py` line 107, `talon/chat.py` line 33
- **Severity:** MEDIUM
- **Category:** Bug / Incomplete Feature / Data Integrity
- **Status:** FIXED 2026-04-22
- **Description:** `_do_create_mission()` uses `author_id = getattr(app, "operator_id", 1)`. `operator_id` is never set on `TalonApp`, so every mission is attributed to the SERVER sentinel regardless of which client actually submitted it. Similarly, all SITREPs created via `SitrepScreen` use `SERVER_AUTHOR_ID = 1` and all chat messages use `SERVER_AUTHOR_ID`. In Phase 1 (server-only, before enrollment is wired), this is acceptable, but it creates historically incorrect audit data that will be difficult to correct retroactively once real enrollment is in place.
- **Fix:** Successful first-run enrollment now sets `app.operator_id` immediately. SITREP creation now uses `app.operator_id` when available, and chat sender resolution prefers `app.operator_id` before falling back to `meta.my_operator_id` or the SERVER sentinel. Mission creation already used `app.operator_id`, so it now receives the correct value after enrollment.

---

### [BUG-074] Client could verify its own asset — UI guard bypassed when `operator_id` is None
- **File:** `talon/ui/screens/asset_screen.py` lines 541, 602–617; `talon/server/net_handler.py` lines 425–432
- **Severity:** HIGH
- **Category:** Security / Data Integrity
- **Status:** FIXED 2026-04-20
- **Description:** Two separate enforcement failures allowed a client to mark its own asset verified. (1) The UI gate (`if is_server or not is_own_asset`) evaluates `is_own_asset = False` whenever `app.operator_id is None` (see BUG-058), so the VERIFY button always appeared for own assets on a client. (2) Even if the UI was bypassed, `_handle_client_push` accepted `verified=1` from the pushing creator with no server-side strip. Additionally, `_do_verify` always set `confirmed_by=SERVER_AUTHOR_ID` regardless of who was confirming.
- **Fix:** (1) Added a back-end guard in `_do_verify`: looks up the asset's `created_by` and refuses if it matches `app.operator_id` (effective once BUG-058 is resolved). (2) Fixed `confirmed_by` to use `app.operator_id` for client confirmations and `SERVER_AUTHOR_ID` only for server. (3) In `_handle_client_push` on the server, added a lookup of `pushing_operator_id` and strips `verified`/`confirmed_by` from any inbound asset record where `created_by == pushing_operator_id` — this is the authoritative enforcement regardless of client state.

---

### [BUG-061] Client→server record push not implemented — client writes were local-only
- **File:** `talon/network/protocol.py`, `talon/server/net_handler.py`, `talon/network/client_sync.py`
- **Severity:** HIGH
- **Category:** Missing Feature / Protocol Gap
- **Status:** FIXED 2026-04-17
- **Fix:** Implemented full client→server push protocol. Added `MSG_PUSH_RECORDS` / `MSG_PUSH_ACK` message types. Client-side: offline outbox buffers records with `sync_status='pending'`; on reconnect `client_sync.py` coalesces pending records and sends a push batch. Server-side: `_handle_push_records()` in `net_handler.py` validates table allowlist, re-encrypts sitrep bodies, upserts via `SyncEngine._upsert_record`, and broadcasts `notify_change` to other connected clients. Push uses UUID-based identity so records created offline don't duplicate. Includes exponential backoff on failure, tombstone GC, and UI outbox badges.

---

### [BUG-068] Push-applied records not reflected in UI until screen navigation
- **File:** `talon/network/client_sync.py`, `talon/app.py`
- **Severity:** HIGH
- **Category:** Bug / UI / Threading
- **Status:** FIXED 2026-04-17
- **Fix:** `_apply_record` and `_apply_delete` run on the sync background thread and updated the DB correctly, but Kivy widgets must only be updated on the main thread. After each successful DB apply, both methods now call `_notify_ui(table)` which does `Clock.schedule_once(dispatch, 0)` — posting a callback onto Kivy's main-thread event loop. The callback calls `app.on_data_pushed(table)` (added to `TalonApp`), which checks `_TABLE_SCREENS` to see if the currently visible screen displays data from that table, and if so calls `screen.on_pre_enter()` to refresh it. Changes pushed from the server now appear on screen immediately.

---

### [BUG-067] RNS.Packet silently drops payloads > ~462 bytes — sync_request never delivered
- **File:** `talon/server/net_handler.py`, `talon/network/client_sync.py`, `talon/network/protocol.py`
- **Severity:** CRITICAL
- **Category:** Bug / Protocol / Transport
- **Status:** FIXED 2026-04-17
- **Fix:** `RNS.Packet` has a hard ~462-byte encrypted payload limit regardless of transport. A `sync_request` with a populated version map was 568 bytes and was silently discarded — the server never received it, never sent `sync_done`, and the client timed out every 30 s. `RNS.Resource` was ruled out (see BUG-066). Fixed by application-level chunking: `_smart_send` now splits any payload > 380 bytes into 200-byte raw pieces, base64-encodes each, and sends them as individual `MSG_CHUNK` JSON packets (~329 bytes each). `_handle_chunk_data` on both sides buffers by `msg_id` and reassembles when all fragments arrive, then dispatches the message normally. Handles arbitrarily large payloads.

---

### [BUG-066] RNS.Resource unusable for protocol messages — causes auth failures
- **File:** `talon/server/net_handler.py`, `talon/network/client_sync.py`
- **Severity:** HIGH
- **Category:** Bug / Protocol / Transport
- **Status:** FIXED 2026-04-17
- **Fix:** Two consecutive attempts to use `RNS.Resource` for large payload delivery both failed. First attempt: `RNS.Resource(io.BytesIO(data), link)` — RNS treats the BytesIO `.name` attribute as a literal file path, raising `[Errno 2] No such file or directory`. Second attempt: `RNS.Resource(data, link)` with raw bytes — RNS.Resource uses its own multi-packet advertisement/segmentation protocol that conflicts with our packet callbacks on the same persistent link, producing "digest received was wrong" authentication errors on every connection attempt. Resolution: dropped `RNS.Resource` entirely in favour of application-level MSG_CHUNK fragmentation (BUG-067 fix).

---

### [BUG-065] Server-created records delayed ~60 s on clients — poll-only architecture
- **File:** `talon/server/net_handler.py`, `talon/network/client_sync.py`, `talon/app.py`
- **Severity:** HIGH
- **Category:** Bug / Protocol / UX
- **Status:** FIXED 2026-04-17
- **Fix:** Replaced poll-only sync with a persistent-link push architecture. The server now calls `net_handler.notify_change(table, record_id)` (via `app.net_notify_change()`) immediately after every DB write, which pushes a `push_update` message to all active client links. Clients receive and apply it within milliseconds. All write paths (assets, sitreps, missions, chat, operators, documents) wired with `net_notify_change` calls. LoRa clients retain 120 s polling via `lora_mode = true` in talon.ini.

---

### [BUG-064] Deleted records never propagated to clients
- **File:** `talon/server/net_handler.py`, `talon/network/client_sync.py`, `talon/db/migrations.py`, `talon/network/protocol.py`
- **Severity:** HIGH
- **Category:** Bug / Protocol / Data Integrity
- **Status:** FIXED 2026-04-17
- **Fix:** Added tombstone table (`deleted_records`) via migration 0009. Server calls `notify_delete(table, record_id)` which inserts a tombstone then pushes `push_delete` to all active links. Clients handle `push_delete` with `_apply_delete()` (`DELETE FROM {table} WHERE id = ?`). Offline clients catch up via tombstones included in the `sync_done` response (filtered by `last_sync_at`). All delete paths (assets, sitreps, missions, chat messages/channels, documents, operators) wired with `net_notify_delete` calls, with cascade-delete IDs pre-queried before the model-layer delete.

---

### [BUG-063] RNS Packet MTU overflow silently drops sync payloads
- **File:** `talon/server/net_handler.py`, `talon/network/client_sync.py`
- **Severity:** HIGH
- **Category:** Bug / Protocol / Reliability
- **Status:** FIXED 2026-04-17
- **Fix:** `RNS.Packet` is capped at ~462 bytes; multi-record `sync_response` payloads frequently exceeded this and were silently discarded. Fixed by: (a) sending one record per message instead of batching, (b) introducing `_smart_send(link, data)` in both handler and client — uses `RNS.Packet` when `len(data) <= 380`, otherwise `RNS.Resource(io.BytesIO(data), link)` which has no size limit. Resource completion is tracked via a concluded callback that routes through the same `_on_packet` dispatcher.

---

### [BUG-062] "digest received was wrong" — two links per cycle caused auth failures
- **File:** `talon/network/client_sync.py`, `talon/server/net_handler.py`
- **Severity:** HIGH
- **Category:** Bug / Protocol / Reliability
- **Status:** FIXED 2026-04-17
- **Fix:** The old client opened a sync link, then immediately opened a separate heartbeat link. Opening two links back-to-back to the same destination in rapid succession confused RNS's per-link key state, producing `digest received was wrong` errors and dropped packets. Fixed by collapsing both flows onto a single persistent link: after the initial sync exchange the link stays open; heartbeats are sent over the same link every `HEARTBEAT_BROADBAND_S` seconds. The link-closed callback triggers automatic reconnect after `_RECONNECT_DELAY_S = 5 s`.

---

### [BUG-059] `operators` table missing `version` column — all delta sync fails
- **File:** `talon/db/migrations.py`, `talon/server/net_handler.py`
- **Severity:** CRITICAL
- **Category:** Bug / Schema / Sync
- **Status:** FIXED 2026-04-17
- **Fix:** Added migration 0008: `ALTER TABLE operators ADD COLUMN version INTEGER NOT NULL DEFAULT 1`. Bumped `DB_SCHEMA_VERSION` to 8 in `talon/constants.py`. `ServerNetHandler._build_delta` explicitly selects `version`; without the column the query threw `OperationalError` which aborted the entire sync exchange before any table's records were transmitted.

---

### [BUG-060] Enrolled client reopens to enrollment screen after restart
- **File:** `talon/ui/screens/login_screen.py`
- **Severity:** HIGH
- **Category:** Bug / Enrollment / UX
- **Status:** FIXED 2026-04-17
- **Fix:** Login now checks `meta.my_operator_id` as a fallback when the `operators` table has no matching row (lines 122-133). This covers the window between enrollment and the first successful sync where the operator row only exists on the server.

---

### [BUG-001] SQL injection vulnerability in sync.py table enumeration
- **File:** `talon/network/sync.py`
- **Severity:** CRITICAL
- **Category:** Security
- **Status:** FIXED 2026-04-13
- **Fix:** Added module-level `_SYNC_TABLE_ALLOWLIST` frozenset and `_validated_table()` helper. The helper raises `ValueError` if any name is not in the allowlist. `build_version_map()` now iterates the allowlist constant and calls `_validated_table()` at the query site, making it impossible to accidentally pass an external name without being caught.

---

### [BUG-003] Database connection leaked if migration fails after `open_db()`
- **File:** `talon/ui/screens/login_screen.py`
- **Severity:** HIGH
- **Category:** Reliability / Resource Leak
- **Status:** FIXED 2026-04-13
- **Fix:** `_do_login()` now tracks `conn` separately from `app.conn`. A `try/finally` block closes `conn` if it was never transferred to `app` (error path). The happy path sets `conn = None` after assigning to `app.conn` so the `finally` skips cleanup.

---

### [BUG-004] No null-check on `key` before passing to audit `install_hook()`
- **File:** `talon/ui/screens/login_screen.py`
- **Severity:** HIGH
- **Category:** Reliability
- **Status:** FIXED 2026-04-13
- **Fix:** Added `if key is None: raise ValueError("DB key derivation returned None")` immediately after `derive_key()` returns and before `install_hook()` is called.

---

### [BUG-005] Sync engine `stop()` silently ignores thread join timeout
- **File:** `talon/network/sync.py`
- **Severity:** HIGH
- **Category:** Reliability
- **Status:** FIXED 2026-04-13
- **Fix:** Reduced join timeout from 5 s to 2 s. After `join()`, checks `self._thread.is_alive()` and logs a `WARNING` if the thread did not exit.

---

### [BUG-006] Multi-step enrollment not wrapped in a single atomic transaction
- **File:** `talon/server/enrollment.py`
- **Severity:** MEDIUM
- **Category:** Data Consistency
- **Status:** FIXED 2026-04-13
- **Fix:** `create_operator()` now wraps both the `INSERT INTO operators` and `UPDATE enrollment_tokens` in an explicit `BEGIN IMMEDIATE … COMMIT` block. Any exception triggers a `rollback()` so neither statement is committed in isolation.

---

### [BUG-008] Plaintext passphrase lingers in memory after key derivation
- **File:** `talon/ui/screens/login_screen.py`
- **Severity:** MEDIUM
- **Category:** Security
- **Status:** FIXED 2026-04-13 (best-effort)
- **Fix:** After `derive_key()` returns, the passphrase variable is overwritten with `"\x00" * len(passphrase)` and deleted. This is best-effort in CPython (immutable strings mean the original object may linger until GC), but it reduces the exposure window. The `bytearray` approach for stronger guarantees is tracked as a future improvement.

---

### [BUG-009] Enrollment token audit entry omits token identity
- **File:** `talon/server/enrollment.py`
- **Severity:** MEDIUM
- **Category:** Auditability
- **Status:** FIXED 2026-04-13
- **Fix:** `generate_enrollment_token()` now computes `sha256(token)` and includes `token_hash` in the `audit()` call, enabling correlation with later enrollment events without exposing the raw token.

---

### [BUG-010] Internet connectivity probe hardcoded to `8.8.8.8:53` — fails in restricted networks
- **File:** `talon/network/interfaces.py`
- **Severity:** MEDIUM
- **Category:** Reliability
- **Status:** FIXED 2026-04-13
- **Fix:** `_probe_tcp()` now tries three endpoints in sequence (`8.8.8.8:53`, `1.1.1.1:53`, `8.8.4.4:53`); returns `True` on the first successful connection. All three must fail before TCP is declared unavailable.

---

### [BUG-011] Lease display truncates rather than rounds, showing 23h for ~24h leases
- **File:** `talon/ui/screens/server/clients_screen.py`
- **Severity:** LOW
- **Category:** Logic
- **Status:** FIXED 2026-04-13
- **Fix:** Changed `(lease_expires - now) // 3600` to `math.ceil((lease_expires - now) / 3600)`.

---

### [BUG-012] Revocation audit log records plaintext RNS hash
- **File:** `talon/server/revocation.py`
- **Severity:** LOW
- **Category:** Auditability
- **Status:** FIXED 2026-04-13
- **Fix:** `rns_hash_was` in the `operator_revoked` audit payload is now `sha256(rns_hash)` rather than the raw hash.

---

### [BUG-013] `LockScreen.on_lease_renewed()` is an unimplemented stub
- **File:** `talon/ui/screens/lock_screen.py`
- **Severity:** NOTE
- **Category:** Incomplete Feature
- **Status:** FIXED 2026-04-13
- **Fix:** Implemented as `self.manager.current = "main"`. Note: the sync engine still needs to call this callback when a lease-renewal message arrives from the server — that wiring is part of the sync feature implementation work.

---

### [BUG-014] Migration version is incremented even if `executescript()` fails mid-script
- **File:** `talon/db/migrations.py`
- **Severity:** NOTE
- **Category:** Data Consistency
- **Status:** FIXED 2026-04-13
- **Fix:** Each migration now runs inside a named `SAVEPOINT`. On success, the savepoint is released (committed). On any exception, the savepoint is rolled back and released before re-raising, leaving the schema version unchanged and the DB in a consistent state.

---

### [BUG-015] Yggdrasil probe detects any IPv6, not specifically Yggdrasil addresses
- **File:** `talon/network/interfaces.py`
- **Severity:** NOTE
- **Category:** Incomplete Feature
- **Status:** FIXED 2026-04-13
- **Fix:** `_probe_yggdrasil()` now iterates the host's IPv6 addresses via `getaddrinfo` and checks each against `ipaddress.ip_network("200::/7")`. Returns `True` only if at least one address falls within Yggdrasil's allocation. Zone-ID suffixes are stripped before parsing.

---

### [BUG-016] `NameError` on login failure — `exc` deleted before `Clock` fires
- **File:** `talon/ui/screens/login_screen.py` line 85
- **Severity:** HIGH
- **Category:** Bug / Python Scoping
- **Status:** FIXED 2026-04-14
- **Description:** Python 3 (PEP 3110) deletes the `except`-clause name from the local namespace at the end of the `except` block. The lambda `lambda dt: self._on_error(str(exc))` captures `exc` by cell reference. By the time `Clock.schedule_once` fires it (next frame, after the block has exited), the cell is empty and raises `NameError: free variable 'exc' referenced before assignment`. Every failed login attempt silently crashed without displaying the error message.
- **Fix:** Capture the string before the lambda:
  ```python
  except Exception as exc:
      _log.warning("Login failed: %s", exc)
      err_msg = str(exc)
      Clock.schedule_once(lambda dt: self._on_error(err_msg))
  ```

---

### [BUG-017] `TypeError` when tapping the create-mission button
- **File:** `talon/ui/kv/mission.kv` line 25 / `talon/ui/screens/mission_screen.py` line 19
- **Severity:** HIGH
- **Category:** Bug / Signature Mismatch
- **Status:** FIXED 2026-04-14
- **Description:** `mission.kv` calls `root.on_create_pressed()` with no arguments. `MissionScreen.on_create_pressed(self, title: str)` requires `title`. Tapping the + button raised `TypeError: on_create_pressed() missing 1 required positional argument: 'title'`.
- **Fix:** Either change the KV binding to pass an empty string `root.on_create_pressed("")` as a scaffold placeholder, or — better — remove the `title` parameter from the method signature and have the method read from a title field via `self.ids`.

---

### [BUG-018] `TypeError` in `ContextPanel.show_waypoint()` when coordinates are `None`
- **File:** `talon/ui/widgets/context_panel.py` line 306
- **Severity:** MEDIUM
- **Category:** Bug / Missing Guard
- **Status:** FIXED 2026-04-14
- **Description:** `show_asset()` guards `if asset.lat is not None and asset.lon is not None` before formatting coordinates. `show_waypoint()` called `abs(waypoint.lat)` and `abs(waypoint.lon)` unconditionally. If a waypoint had no coordinates, this raised `TypeError: bad operand type for abs(): 'NoneType'`.
- **Fix:** Wrap coordinate display in the same None-guard used by `show_asset`:
  ```python
  if waypoint.lat is not None and waypoint.lon is not None:
      lat_str = f"{abs(waypoint.lat):.5f}° {'N' if waypoint.lat >= 0 else 'S'}"
      lon_str = f"{abs(waypoint.lon):.5f}° {'E' if waypoint.lon >= 0 else 'W'}"
      self._add_row("Lat", lat_str)
      self._add_row("Lon", lon_str)
  else:
      self._add_row("Location", "No coordinates")
  ```

---

### [BUG-019] SITREP severity colours in `ContextPanel` diverge from `theme.py`
- **File:** `talon/ui/widgets/context_panel.py` lines 33–38
- **Severity:** MEDIUM
- **Category:** Consistency / Visual Regression
- **Status:** FIXED 2026-04-14
- **Description:** `context_panel.py` defined its own `_SITREP_COLOUR` dict instead of importing `SITREP_COLORS` from `theme.py`. The values differed in several cases (`ROUTINE` grey vs. tactical green; `FLASH_OVERRIDE` red vs. purple). `sitrep_overlay.py` already correctly imported from `theme.py`.
- **Fix:** Removed `_SITREP_COLOUR` from `context_panel.py` and replaced with:
  ```python
  from talon.ui.theme import SITREP_COLORS as _SITREP_COLOUR
  ```

---

### [BUG-020] Login screen title hardcoded as "T.A.L.O.N. Server"
- **File:** `talon/ui/kv/login.kv` line 14
- **Severity:** LOW
- **Category:** Consistency
- **Status:** FIXED 2026-04-14
- **Description:** The display label always read "T.A.L.O.N. Server" regardless of `app.mode`. Client instances displayed the wrong title.
- **Fix:** Added `id: title_label` to the `MDLabel` in `login.kv`. `LoginScreen.on_kv_post()` sets `self.ids.title_label.text` to `"T.A.L.O.N. Server"` or `"T.A.L.O.N. Client"` based on `app.mode`.

---

### [BUG-021] Inconsistent use of `MDScrollView` vs plain `ScrollView` across KV files
- **File:** `talon/ui/kv/sitrep.kv` vs. `talon/ui/kv/server/audit.kv`, `clients.kv`, `keys.kv`, `enroll.kv`
- **Severity:** NOTE
- **Category:** Consistency / UI
- **Status:** FIXED 2026-04-14
- **Description:** `sitrep.kv` used KivyMD's `MDScrollView`; all four server KV files used plain Kivy `ScrollView`. This produced inconsistent scroll behaviour and theming across screens.
- **Fix:** Replaced `ScrollView` with `MDScrollView` in the four server KV files.

---

### [BUG-022] Refresh buttons in `audit.kv` and `clients.kv` call `on_pre_enter()` directly
- **File:** `talon/ui/kv/server/audit.kv` line 26, `talon/ui/kv/server/clients.kv` line 26
- **Severity:** NOTE
- **Category:** Code Quality / Design
- **Status:** FIXED 2026-04-14
- **Description:** Both KV files bound their refresh `MDIconButton` to `root.on_pre_enter()`. Lifecycle hooks should not be invoked directly from UI events.
- **Fix:** Added a dedicated `on_refresh_pressed()` method to each screen that calls the internal `_load` / `_refresh` helper; `on_pre_enter` calls the same helper independently.

---

### [BUG-023] `_AuditRow.timestamp` `StringProperty` is declared but never used
- **File:** `talon/ui/screens/server/audit_screen.py` line 79
- **Severity:** NOTE
- **Category:** Code Quality / Dead Code
- **Status:** FIXED 2026-04-14
- **Description:** `_AuditRow` declared `timestamp = StringProperty("")` but the property was never assigned. The timestamp text was set directly on a child `MDLabel` in `__init__`.
- **Fix:** Removed the `timestamp = StringProperty("")` declaration.

---

### [BUG-024] `ContextPanel.update_summary()` detects active view via header string comparison
- **File:** `talon/ui/widgets/context_panel.py` line 240
- **Severity:** LOW
- **Category:** Maintainability
- **Status:** FIXED 2026-04-14
- **Description:** `update_summary()` checked `if self._header_label.text == "SITUATION"` to determine whether the summary was on screen. Display text is a fragile state signal — a typo, whitespace change, or i18n pass silently breaks live updates.
- **Fix:** Added `self._current_view: str = "summary"` as an instance variable. Set in each `show_*` method. Checked in `update_summary` instead of the header text.

---

### [BUG-025] `navigate_to()` allocates a throw-away list on every call
- **File:** `talon/ui/screens/main_screen.py` line 129
- **Severity:** NOTE
- **Category:** Performance (trivial)
- **Status:** FIXED 2026-04-14
- **Description:** `if screen_name in [s.name for s in sm.screens]` built and immediately discarded a list on every navigation call.
- **Fix:** Replaced with a generator so iteration short-circuits on match:
  ```python
  if any(s.name == screen_name for s in sm.screens):
  ```

---

### [BUG-026] `_OperatorRow` / `_KeyOperatorRow` define Kivy properties that are never used in bindings
- **File:** `talon/ui/screens/server/clients_screen.py` lines 127–131, `talon/ui/screens/server/keys_screen.py` lines 123–128
- **Severity:** NOTE
- **Category:** Code Quality / Dead Code
- **Status:** FIXED 2026-04-14
- **Description:** Both row classes declared `StringProperty` / `NumericProperty` fields (`operator_id`, `callsign`, `rns_hash`, `status`) and assigned them in `__init__`, but button callbacks closed directly over constructor parameters and never referenced the Kivy properties.
- **Fix:** Removed unused Kivy properties; rely on constructor-captured closure variables.

---

### [BUG-027] `executescript()` destroys savepoint — `NameError: no such savepoint: migration_N`
- **File:** `talon/db/migrations.py`
- **Severity:** HIGH
- **Category:** Bug / Incompatible API Usage
- **Status:** FIXED 2026-04-14
- **Description:** `apply_migrations()` (BUG-014 fix) wrapped each migration in a `SAVEPOINT`. Python's `sqlite3.executescript()` **always issues an implicit `COMMIT` before running**, which destroys any active savepoint. The subsequent `RELEASE SAVEPOINT migration_N` then failed with `OperationalError: no such savepoint`. Users who had a v1 DB and upgraded to schema v2 hit this on first login after the update.
- **Fix:** Removed the SAVEPOINT mechanism entirely. Each migration's SQL and the schema-version `UPDATE` are wrapped in an explicit `BEGIN; ... COMMIT;` block embedded in the `executescript()` call. If `executescript()` raises before `COMMIT`, `conn.rollback()` clears the open transaction and the schema version is left unchanged.

---

### [BUG-028] `SQLite objects created in a thread can only be used in that same thread`
- **File:** `talon/db/connection.py`
- **Severity:** HIGH
- **Category:** Bug / Threading
- **Status:** FIXED 2026-04-14
- **Description:** `open_db()` was called from the login background thread. `app.conn` was then used from the Kivy UI (main) thread. Python's `sqlite3`/`sqlcipher3` wrapper enforces thread affinity by default and raised `ProgrammingError` when a connection was used from a different thread than the one that created it.
- **Fix:** Pass `check_same_thread=False` to `sqlcipher.connect()`. SQLite itself runs in serialized mode (thread-safe internally); this only disables Python's redundant extra check. Safe for our usage pattern of a single connection accessed sequentially from one thread at a time.

---

### [BUG-029] `channels` table missing `version` column — channel sync silently broken
- **File:** `talon/db/migrations.py` (migration 0001) + `talon/network/sync.py` line 84
- **Severity:** HIGH
- **Category:** Bug / Schema / Data Sync
- **Status:** FIXED 2026-04-14
- **Description:** `_SYNC_TABLE_ALLOWLIST` includes `"channels"`. `build_version_map()` ran `SELECT id, version FROM channels` for every table in the allowlist. The `channels` table was created without a `version` column. The query raised `OperationalError: table channels has no column named version`, which was caught by the bare `except Exception` block and silently replaced with `version_map["channels"] = {}`. Result: channels always appeared to have no records and were never delta-synced — new mission channels created on the server never propagated to clients.
- **Fix (two-part):**
  1. Add a migration (0004) to add `version INTEGER NOT NULL DEFAULT 1` to `channels`.
  2. Bump `DB_SCHEMA_VERSION` in `constants.py` to 4.

---

### [BUG-030] TOCTOU race in `create_operator()` — token validated outside transaction
- **File:** `talon/server/enrollment.py` lines 82–92
- **Severity:** MEDIUM
- **Category:** Bug / Race Condition / Security
- **Status:** FIXED 2026-04-14
- **Description:** `create_operator()` read and validated the enrollment token with a bare `SELECT` before issuing `BEGIN IMMEDIATE`. Two simultaneous enrollment requests for the same token would both pass validation, then race to insert the operator row. More critically, if two different callsigns both submitted the same token concurrently, both could succeed.
- **Fix:** Moved `BEGIN IMMEDIATE` to before the token `SELECT`, so the lock is held for the entire read-validate-write sequence:
  ```python
  conn.execute("BEGIN IMMEDIATE")
  try:
      row = conn.execute("SELECT ...").fetchone()
      # validate...
      cursor = conn.execute("INSERT INTO operators ...")
      conn.execute("UPDATE enrollment_tokens ...")
      conn.commit()
  except Exception as exc:
      conn.rollback()
      raise ValueError(...) from exc
  ```

---

### [BUG-031] `get_schema_version()` swallows wrong-passphrase error — confusing migration failures
- **File:** `talon/db/migrations.py` lines 161–165
- **Severity:** MEDIUM
- **Category:** Bug / Error Masking
- **Status:** FIXED 2026-04-14
- **Description:** `get_schema_version()` wrapped its query in a bare `except Exception: return 0`. If the database was opened with a wrong passphrase, every query raised `DatabaseError: file is not a database`. The except block caught this and returned 0, causing `apply_migrations()` to attempt all migrations against an undecryptable connection, with the root cause (wrong key) completely obscured.
- **Fix:** Narrowed the except to `except sqlcipher.OperationalError` (the expected error when the `meta` table does not yet exist on a brand-new DB), and let `DatabaseError` propagate:
  ```python
  def get_schema_version(conn: Connection) -> int:
      try:
          row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
          return int(row[0]) if row else 0
      except sqlcipher.OperationalError:
          return 0  # meta table does not exist yet — fresh DB
  ```

---

### [BUG-032] Raw `rns_hash` logged in plaintext in `revoke_operator()` warning
- **File:** `talon/server/revocation.py` lines 99–103
- **Severity:** MEDIUM
- **Category:** Security / Information Leakage
- **Status:** FIXED 2026-04-14
- **Description:** The encrypted audit log correctly stored `sha256(rns_hash)` (BUG-012 fix). However, `_log.warning()` on the same lines logged the raw `rns_hash` in plaintext to the standard logger, exposing the operator's Reticulum identity hash in log files.
- **Fix:** Replaced `rns_hash=rns_hash` with `rns_hash=hashlib.sha256(rns_hash.encode()).hexdigest()[:12] + "..."` in the `_log.warning()` call.

---

### [BUG-033] Missing database indexes for common query patterns
- **File:** `talon/db/migrations.py` (migration 0001)
- **Severity:** MEDIUM
- **Category:** Performance / Schema
- **Status:** FIXED 2026-04-14
- **Description:** The schema created no secondary indexes. Common query patterns (`sitreps` filtered by `level`, `assets` filtered by `category`/`verified`, `messages` ordered by `channel_id + sent_at`, etc.) degraded to full table scans as the dataset grew.
- **Fix:** Added a migration (combined with BUG-029's migration 0004) that creates:
  ```sql
  CREATE INDEX idx_sitreps_level        ON sitreps(level);
  CREATE INDEX idx_sitreps_created_at   ON sitreps(created_at);
  CREATE INDEX idx_assets_category      ON assets(category);
  CREATE INDEX idx_assets_verified      ON assets(verified);
  CREATE INDEX idx_operators_revoked    ON operators(revoked);
  CREATE INDEX idx_messages_channel_ts  ON messages(channel_id, sent_at);
  CREATE INDEX idx_audit_occurred_at    ON audit_log(occurred_at);
  CREATE INDEX idx_tokens_pending       ON enrollment_tokens(used_at, expires_at);
  ```

---

### [BUG-034] `DB_SCHEMA_VERSION` constant not validated against `len(MIGRATIONS)`
- **File:** `talon/constants.py` line 28, `talon/db/migrations.py`
- **Severity:** NOTE
- **Category:** Code Quality / Maintenance Hazard
- **Status:** FIXED 2026-04-14
- **Description:** Nothing enforced that `len(MIGRATIONS) == DB_SCHEMA_VERSION`. A developer could add a migration entry without bumping the constant, or vice versa, with no immediate error.
- **Fix:** Added an assertion at module level in `migrations.py`:
  ```python
  from talon.constants import DB_SCHEMA_VERSION
  assert len(MIGRATIONS) == DB_SCHEMA_VERSION, (
      f"MIGRATIONS has {len(MIGRATIONS)} entries but DB_SCHEMA_VERSION={DB_SCHEMA_VERSION}. "
      "Update constants.py when adding a migration."
  )
  ```

---

### [BUG-035] `audit.append_entry()` commits on every write — no burst batching
- **File:** `talon/server/audit.py` line 54
- **Severity:** NOTE
- **Category:** Performance
- **Status:** FIXED 2026-04-14
- **Description:** Every call to `append_entry()` issued a `conn.commit()`. In high-activity scenarios (bulk enrollment, rapid SITREP filing), each event triggered a separate fsync-level commit, adding measurable latency especially on Android flash storage.
- **Fix:** Removed the `conn.commit()` from `append_entry()` and committed instead in the `_hook` closure inside `install_hook()`. Keeps commit granularity at one audit event per commit without changing behaviour.

---

### [BUG-036] WAL journal mode not verified after `PRAGMA journal_mode = WAL`
- **File:** `talon/db/connection.py` line 31
- **Severity:** LOW
- **Category:** Reliability
- **Status:** FIXED 2026-04-14
- **Description:** `PRAGMA journal_mode = WAL` returns the mode actually set. On network filesystems and some Android storage configurations, WAL mode cannot be enabled and SQLite silently falls back to DELETE mode. `open_db()` ignored the return value, losing crash-recovery and concurrent-reader benefits with no warning.
- **Fix:** Check the returned mode and warn if it is not `"wal"`:
  ```python
  actual_mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
  if actual_mode != "wal":
      import logging
      logging.getLogger("db.connection").warning(
          "WAL journal mode unavailable (got %r) — using %s mode. "
          "Crash recovery guarantees are reduced.", actual_mode, actual_mode.upper()
      )
  ```

---

### [BUG-037] `_AuditRow` has two more dead `StringProperty` declarations (BUG-023 partial fix)
- **File:** `talon/ui/screens/server/audit_screen.py`
- **Severity:** NOTE
- **Category:** Code Quality / Dead Code
- **Status:** FIXED 2026-04-15
- **Description:** BUG-023 removed `timestamp = StringProperty("")` from `_AuditRow`, but two more dead Kivy properties remained: `event = StringProperty("")` and `payload_text = StringProperty("")`. Neither was ever assigned (the constructor parameters `event: str` and `payload: str` were consumed directly and used to set child `MDLabel` text). The unused `from kivy.properties import StringProperty` import was also left behind.
- **Fix:** Removed both dead `StringProperty` declarations and the now-orphaned import.

---

### [BUG-038] `delete_mission()` does not purge messages before deleting their channel — FK violation
- **File:** `talon/missions.py` lines 213–224
- **Severity:** HIGH
- **Category:** Bug / Data Integrity / FK Constraint
- **Status:** FIXED 2026-04-15
- **Description:** `delete_mission()` deleted the mission's channel row without first deleting the messages that referenced it via `messages.channel_id NOT NULL REFERENCES channels(id)`. With `PRAGMA foreign_keys = ON`, the channel delete raised `IntegrityError: FOREIGN KEY constraint failed` once any message had been posted in the mission channel.
- **Fix:** Added a `DELETE FROM messages WHERE channel_id IN (SELECT id FROM channels WHERE mission_id = ?)` statement immediately before the `DELETE FROM channels` statement in `delete_mission()`.

---

### [BUG-039] `create_mission()` TOCTOU — asset contention check runs outside transaction
- **File:** `talon/missions.py` lines 63–94
- **Severity:** MEDIUM
- **Category:** Bug / Race Condition
- **Status:** FIXED 2026-04-15
- **Description:** The asset contention check (bare `SELECT`) ran before `BEGIN IMMEDIATE`, so two concurrent `create_mission()` calls could both pass the check and double-allocate the same asset.
- **Fix:** Moved `BEGIN IMMEDIATE` to before the mission `INSERT`. The contention check, insert, and asset updates now all occur inside the same transaction. Added an `except ValueError: conn.rollback(); raise` clause so contention errors roll back cleanly.

---

### [BUG-040] `renew_lease()` silently succeeds for a non-existent `operator_id`
- **File:** `talon/server/enrollment.py` lines 137–150
- **Severity:** MEDIUM
- **Category:** Bug / Correctness
- **Status:** FIXED 2026-04-15
- **Description:** The UPDATE silently affected zero rows if `operator_id` did not exist. The function returned a plausible future timestamp and logged a "lease_renewed" audit event, all incorrectly.
- **Fix:** Captured the cursor from `conn.execute(...)` and raised `ValueError(f"Operator {operator_id} not found.")` when `cursor.rowcount == 0`, before calling `conn.commit()`.

---

### [BUG-041] SITREP delete button shown to all operators, not server-only
- **File:** `talon/ui/screens/sitrep_screen.py` lines 304–308
- **Severity:** MEDIUM
- **Category:** Bug / Access Control
- **Status:** FIXED 2026-04-15
- **Description:** `_load_feed()` unconditionally passed `screen=self` to `_SitrepRow`, rendering a delete button for every operator regardless of mode.
- **Fix:** Added `screen_ref = self if app.mode == "server" else None` before the loop; `screen=screen_ref` is now passed instead of `screen=self`.

---

### [BUG-042] `update_asset()` cannot clear `lat`/`lon` or `confirmed_by` back to NULL
- **File:** `talon/assets.py` lines 90–138
- **Severity:** MEDIUM
- **Category:** Bug / API Semantics
- **Status:** FIXED 2026-04-15
- **Description:** `None` was overloaded to mean both "not supplied" and "set to NULL", making it impossible to clear coordinates or the `confirmed_by` field. The unverify path in `asset_screen.py` silently left stale `confirmed_by` data in the DB.
- **Fix:** Added a module-level sentinel `_CLEAR = object()` in `talon/assets.py`. `update_asset()` now checks `is _CLEAR` before `is not None` for `lat`, `lon`, and `confirmed_by`. Updated `_do_verify()` in `asset_screen.py` to pass `confirmed_by=_CLEAR` when unverifying.

---

### [BUG-043] `approve_mission()` double rollback when asset contention detected
- **File:** `talon/missions.py` lines 148–153
- **Severity:** LOW
- **Category:** Bug / Reliability
- **Status:** FIXED 2026-04-15
- **Description:** The explicit `conn.rollback()` inside the `if taken:` guard ran before raising `ValueError`, which was immediately caught by `except ValueError: conn.rollback(); raise` — rolling back an already-rolled-back (or no-longer-active) transaction.
- **Fix:** Removed the explicit `conn.rollback()` inside the `if taken:` block. The outer `except ValueError` clause handles the rollback.

---

### [BUG-044] Dead mode validation in `main.py`
- **File:** `main.py` lines 24–26
- **Severity:** NOTE
- **Category:** Code Quality / Dead Code
- **Status:** FIXED 2026-04-15
- **Description:** `get_mode()` already raises `ValueError` for invalid mode strings before returning, so the subsequent `if mode not in ("server", "client"):` guard was unreachable dead code.
- **Fix:** Removed the unreachable guard and `sys.exit(1)` call.

---

### [BUG-045] `_do_create()` and `_do_edit()` in `asset_screen.py` duplicate `_parse_float()` inline
- **File:** `talon/ui/screens/asset_screen.py` lines 429–443, 570–585
- **Severity:** NOTE
- **Category:** Code Quality / Spaghetti / Duplication
- **Status:** FIXED 2026-04-15
- **Description:** Both methods duplicated the `try: float(...) except ValueError:` block four times total instead of calling the existing `_parse_float()` helper at the top of the file.
- **Fix:** Replaced all four inline blocks with `_parse_float()` calls followed by an explicit `if lat/lon is None: status_label.text = ...; return` check.

---

### [BUG-046] `_CATEGORY_LABEL` and `_CATEGORY_COLOR` dicts duplicated across two files
- **File:** `talon/ui/screens/asset_screen.py` lines 31–47, `talon/ui/widgets/context_panel.py` lines 34–50
- **Severity:** NOTE
- **Category:** Code Quality / Duplication
- **Status:** FIXED 2026-04-15
- **Description:** Both files defined identical dicts. Adding a new asset category required editing both files independently.
- **Fix:** Moved both dicts to `talon/assets.py` as `CATEGORY_LABEL` and `CATEGORY_COLOR` (public names). Both `asset_screen.py` and `context_panel.py` now import them as `_CATEGORY_LABEL` / `_CATEGORY_COLOR` via `from talon.assets import CATEGORY_COLOR as _CATEGORY_COLOR, CATEGORY_LABEL as _CATEGORY_LABEL`.

---

### [BUG-047] `_show_dialog()` in `sitrep_overlay.py` uses an unnecessary mutable-list closure hack
- **File:** `talon/ui/widgets/sitrep_overlay.py` lines 56–69
- **Severity:** NOTE
- **Category:** Code Quality / Spaghetti
- **Status:** FIXED 2026-04-15
- **Description:** `_ref: list = []; _ref.append(dialog)` was used to pass `dialog` into a `Clock.schedule_once` lambda, even though `dialog` is a plain local variable not subject to PEP 3110 scoping.
- **Fix:** Replaced with a default-argument capture: `lambda dt, d=dialog: d.dismiss()`. The `_ref` list removed entirely.

---

### [BUG-048] `enrollment.py` splits `talon.constants` import across two lines
- **File:** `talon/server/enrollment.py` lines 19, 23
- **Severity:** NOTE
- **Category:** Code Quality / Style
- **Status:** FIXED 2026-04-15
- **Description:** Two separate `from talon.constants import ...` statements imported from the same module.
- **Fix:** Combined into one: `from talon.constants import ENROLLMENT_TOKEN_EXPIRY_S, LEASE_DURATION_S`.

---

### [BUG-049] `_TokenRow` in `enroll_screen.py` has unused Kivy `StringProperty` declarations
- **File:** `talon/ui/screens/server/enroll_screen.py` lines 77–78
- **Severity:** NOTE
- **Category:** Code Quality / Dead Code
- **Status:** FIXED 2026-04-15
- **Description:** `_TokenRow` declared `token = StringProperty("")` and `info = StringProperty("")` but never used them in bindings; child labels were populated directly from constructor arguments.
- **Fix:** Removed both `StringProperty` declarations, the dead `self.token = token` / `self.info = info` assignments, and the now-unused `from kivy.properties import StringProperty` import.

---

### [BUG-050] `MissionScreen` uses `MDApp.get_running_app()` inconsistently with all other screens
- **File:** `talon/ui/screens/mission_screen.py` lines 657, 691, 703 (and 8 additional call sites)
- **Severity:** NOTE
- **Category:** Code Quality / Inconsistency
- **Status:** FIXED 2026-04-15
- **Description:** `mission_screen.py` imported `MDApp` from `kivymd.app` and called `MDApp.get_running_app()` in 11 places. Every other screen uses `App.get_running_app()` from `kivy.app`.
- **Fix:** Replaced `from kivymd.app import MDApp` with `from kivy.app import App`. Replaced all 11 `MDApp.get_running_app()` calls with `App.get_running_app()`.

---

### [BUG-051] `_row_to_asset()` defensive `len(row) > 11` check is fragile
- **File:** `talon/assets.py` line 171
- **Severity:** NOTE
- **Category:** Code Quality / Code Smell
- **Status:** FIXED 2026-04-15
- **Description:** The guard `row[11] if len(row) > 11 else None` silently masked queries that accidentally omitted `mission_id`. Both callers always select exactly 12 columns.
- **Fix:** Removed the guard; replaced with direct `mission_id=row[11]`.

---

## Closed / Non-Issues

### [BUG-007] Dynamic WHERE clause construction in `audit.query_entries()` is fragile
- **File:** `talon/server/audit.py` lines 101–107
- **Severity:** MEDIUM
- **Category:** Reliability
- **Status:** CLOSED AS NON-ISSUE
- **Assessment:** The WHERE clause is already correctly built: `("WHERE " + " AND ".join(clauses)) if clauses else ""`. The LIMIT param is always the last positional argument, matching the always-present `LIMIT ?` at the end of the query. The original bug report misidentified a non-issue. No fix required.

---

### [BUG-002] Race condition on `app.conn` between UI threads and shutdown
- **File:** `talon/app.py`
- **Severity:** HIGH
- **Category:** Reliability / Race Condition
- **Status:** FIXED 2026-04-15
- **Fix:** Added `self.db_lock = threading.RLock()` to `TalonApp.__init__()`. `on_stop()` now acquires the lock before closing `app.conn` and sets `conn = None` after closing to prevent double-close. A TODO comment marks the remaining work: acquire `db_lock` in all DB-touching UI callbacks once they are wired to real DB operations in Phase 1 feature implementation.

---

### [BUG-052] TOCTOU in `_transition()` and `approve_mission()` — status check outside transaction
- **File:** `talon/missions.py`
- **Severity:** HIGH
- **Category:** Bug / Race Condition / Data Integrity
- **Status:** FIXED 2026-04-15
- **Fix:** In both `_transition()` and `approve_mission()`, moved `BEGIN IMMEDIATE` to before the status `SELECT`, wrapping the full status-check-plus-write sequence in a single atomic transaction. The ValueError/Exception `except` blocks now also call `conn.rollback()` on the now-always-open transaction, matching the pattern established in `create_mission()`.

---

### [BUG-053] `get_or_create_dm_channel()` TOCTOU — SELECT-then-INSERT without transaction lock
- **File:** `talon/chat.py`
- **Severity:** HIGH
- **Category:** Bug / Race Condition
- **Status:** FIXED 2026-04-15
- **Fix:** Wrapped the SELECT-then-INSERT block in `BEGIN IMMEDIATE` / `COMMIT`. If the row already exists when the lock is acquired, the function calls `conn.rollback()` and returns the existing channel. A `ValueError` / generic `except` handler rolls back and re-raises, preventing the unhandled UNIQUE constraint exception from escaping to the caller.

---

### [BUG-054] SERVER sentinel (id=1) revocable via Keys screen — no sentinel guard
- **File:** `talon/ui/screens/server/keys_screen.py`
- **Severity:** HIGH
- **Category:** Bug / Data Integrity
- **Status:** FIXED 2026-04-15
- **Fix:** Added `if op_id == 1: continue` in `_refresh_operator_list()`, mirroring the existing guard in `clients_screen.py`. The SERVER sentinel is now skipped unconditionally before a `_KeyOperatorRow` widget is created, so no REVOKE button is ever rendered for it.

---

### [BUG-055] `shutdown_reticulum()` and `stop_propagation_node()` never called on app exit
- **File:** `talon/app.py`
- **Severity:** HIGH
- **Category:** Reliability / Resource Leak
- **Status:** FIXED 2026-04-15
- **Fix:** `TalonApp.on_stop()` now calls `stop_propagation_node()` (no-op if never started) and `shutdown_reticulum()` (no-op / swallowed exception if never started) via deferred imports, both wrapped in `try/except` so a Reticulum error during shutdown cannot prevent the database from being closed. The DB close is now also guarded by `db_lock` (see BUG-002).

---

### [BUG-056] Salt file written with default OS permissions — readable by other users
- **File:** `talon/crypto/keystore.py`
- **Severity:** MEDIUM
- **Category:** Security / File Permissions
- **Status:** FIXED 2026-04-15
- **Fix:** Replaced `path.write_bytes(salt)` with `os.open(..., O_WRONLY | O_CREAT | O_EXCL, 0o600)` + `os.fdopen(fd, "wb").write(salt)`. The file is now created at `0o600` atomically before any data is written, preventing a window where the file exists but is world-readable.

---

### [BUG-057] Audit field encryption uses the DB key — separate audit key claimed but not implemented
- **File:** `talon/ui/screens/login_screen.py`, `talon/server/audit.py`
- **Severity:** MEDIUM
- **Category:** Security / Design Mismatch
- **Status:** FIXED 2026-04-15
- **Fix:** In `_do_login()`, a separate `audit_key` is now derived via `derive_key(passphrase + ":audit", salt)` before the passphrase is zeroed out. This key is passed to `install_hook()` instead of the DB key. The DB key and audit key are derived from cryptographically independent inputs, providing genuine defence-in-depth. `audit.py`'s module docstring was updated to accurately describe the implementation.

---

### [BUG-059] Audit events logged in plaintext to stdlib logger — sensitive fields in log files
- **File:** `talon/utils/logging.py`
- **Severity:** MEDIUM
- **Category:** Security / Information Leakage
- **Status:** FIXED 2026-04-15
- **Fix:** Changed `logger.info("AUDIT %s %s", event, kwargs)` to `logger.info("AUDIT %s", event)`. The `kwargs` payload (which may contain callsigns, token hashes, RNS hashes) now goes only to the encrypted audit log via `_audit_hook`, not to any plaintext log handler.

---

### [BUG-060] `_probe_tcp()` contacts external DNS servers — OPSEC leak in restricted environments
- **File:** `talon/network/interfaces.py`
- **Severity:** MEDIUM
- **Category:** Security / OPSEC
- **Status:** FIXED 2026-04-15
- **Fix:** Extracted the hardcoded endpoint list into a module-level `_TCP_PROBE_ENDPOINTS` variable (defaulting to the three original public DNS hosts). Added `configure_tcp_probe_endpoints(hosts_str)` which parses a `[network] tcp_probe_hosts = host:port, ...` talon.ini value and replaces the module-level list. The OPSEC implication is documented in comments and the function docstring. `_probe_tcp()` now iterates `_TCP_PROBE_ENDPOINTS` instead of a hardcoded local list.

---

### [BUG-061] SERVER sentinel appears in DM picker — `ValueError` silently swallowed if selected
- **File:** `talon/ui/screens/chat_screen.py`
- **Severity:** MEDIUM
- **Category:** Bug / UX / Error Handling
- **Status:** FIXED 2026-04-15
- **Fix (two parts):** 1) Added `AND id != 1` to the operator query in `on_new_dm_pressed()` so the SERVER sentinel is never shown in the dropdown. 2) Added `_show_error(message)` helper to `ChatScreen` that opens a small modal with the error text; called when `_do_create_dm()` raises.

---

### [BUG-062] `destroy_identity()` single-pass overwrite insufficient on SSDs and CoW filesystems
- **File:** `talon/crypto/identity.py`
- **Severity:** LOW
- **Category:** Security / Incomplete Hardening
- **Status:** FIXED 2026-04-15
- **Fix:** Updated docstring to accurately document the limitation (SSD wear levelling, CoW filesystems), clarify that full-disk encryption is the primary defence, and explain that the single-pass overwrite is a best-effort measure for conventional magnetic media only. No runtime behaviour change — the limitation cannot be perfectly resolved in portable Python code.

---

### [BUG-063] Zone polygon fill not rendered — `ZoneLayer` draws outline only
- **File:** `talon/ui/widgets/map_widget.py`
- **Severity:** LOW
- **Category:** Bug / Visual
- **Status:** FIXED 2026-04-15
- **Fix:** Added `Mesh` to the Kivy graphics imports. `ZoneLayer.reposition()` now draws each zone in two passes: (1) a filled `Mesh` using the translucent RGBA value from `_ZONE_COLOUR` via a triangle-fan triangulation, then (2) a `Line` outline using the same hue at full opacity. Works correctly for convex polygons (the common AO/zone case); non-convex polygons may have minor fill artifacts on very concave bends.

---

### [BUG-064] No lat/lon range validation in asset, zone, and waypoint creation
- **File:** `talon/assets.py`, `talon/zones.py`, `talon/waypoints.py`
- **Severity:** LOW
- **Category:** Bug / Input Validation
- **Status:** FIXED 2026-04-15
- **Fix:** Added `ValueError` guards before each INSERT: `create_asset()` checks that `lat` (if not None) is in [−90, +90] and `lon` (if not None) is in [−180, +180]. `create_zone()` validates every polygon vertex. `create_waypoints_for_mission()` validates each waypoint inside the existing `BEGIN IMMEDIATE` loop before the INSERT.

---

### [BUG-065] Partial coordinates storable — lat set with lon NULL (or vice versa) in asset dialogs
- **File:** `talon/ui/screens/asset_screen.py`
- **Severity:** LOW
- **Category:** Bug / Data Consistency
- **Status:** FIXED 2026-04-15
- **Fix:** Added `if (lat is None) != (lon is None): status_label.text = "Both latitude and longitude are required together."; return` after individual coordinate parsing in both `_do_create()` and `_do_edit()`.

---

### [BUG-066] Custom channel names not validated — DM format (`dm:X:Y`) pattern accepted
- **File:** `talon/chat.py`
- **Severity:** LOW
- **Category:** Bug / Input Validation
- **Status:** FIXED 2026-04-15
- **Fix:** Added `import re` and three validation checks to `create_channel()` after name normalisation: (1) reject names starting with `#dm:` (reserved DM prefix); (2) reject names longer than 65 characters (`#` + 64 content chars); (3) reject names containing control characters (`\x00`–`\x1f`, `\x7f`).

---

### [BUG-067] `_format_ts()` duplicated identically in `sitrep_screen.py` and `chat_screen.py`
- **File:** `talon/ui/screens/sitrep_screen.py`, `talon/ui/screens/chat_screen.py`
- **Severity:** NOTE
- **Category:** Code Quality / Duplication
- **Status:** FIXED 2026-04-15
- **Fix:** Created `talon/utils/formatting.py` with a single `format_ts(ts: int) -> str` function. Both screens now import `from talon.utils.formatting import format_ts as _format_ts` and the local duplicate definitions have been removed. The unused `import datetime` was also removed from each screen.

---

### [BUG-068] `_InfoRow` defined in two places with inconsistent KivyMD color-setting API
- **File:** `talon/ui/screens/mission_screen.py`, `talon/ui/widgets/context_panel.py`
- **Severity:** NOTE
- **Category:** Code Quality / Duplication / Potential Visual Bug
- **Status:** FIXED 2026-04-15
- **Fix:** Created `talon/ui/widgets/info_row.py` with a single `InfoRow` class using the correct KivyMD colour API (`val.theme_text_color = "Custom"; val.text_color = value_color`). Both `mission_screen.py` and `context_panel.py` now import `from talon.ui.widgets.info_row import InfoRow as _InfoRow`; their local class definitions have been removed. The `context_panel.py` bug of using `val.color = value_color` (overrideable by the theme manager) is eliminated.

---

### [BUG-069] `_probe_rnode()` reports True for any serial port, not specifically RNode devices
- **File:** `talon/network/interfaces.py`
- **Severity:** NOTE
- **Category:** Reliability / Incorrect Detection
- **Status:** FIXED 2026-04-15
- **Fix:** Replaced the `len(comports()) > 0` check with a per-port loop. Each port is checked against `_RNODE_VID_PID` (a frozenset of `(vid, pid)` tuples for Mark I CP2102 and Mark II CH9102). If VID/PID is unavailable from the OS, falls back to checking `port.device` against `_RNODE_NAME_PREFIXES` (`/dev/ttyUSB`, `/dev/ttyACM`, `COM`). Returns `True` only when a matching device is found.

---

### [BUG-070] Pending enrollment token display truncated to 16 chars — indistinguishable when multiple tokens exist
- **File:** `talon/ui/screens/server/enroll_screen.py`
- **Severity:** NOTE
- **Category:** UX / Usability
- **Status:** FIXED 2026-04-15
- **Fix:** Changed `token[:16]` to `token[:32]` in `_TokenRow`. 32 of 64 hex characters provides sufficient visual discrimination between concurrent tokens while keeping the row width reasonable.

---

### [BUG-059] `app.config` (Kivy) used instead of `app.cfg` (TALON) in `document_screen.py`
- **File:** `talon/ui/screens/document_screen.py` lines 335, 463, 622
- **Severity:** HIGH
- **Category:** Bug / Data Integrity / Potential Crash
- **Status:** FIXED 2026-04-16
- **Fix:** Changed all three `get_document_storage_path(app.config)` calls to `get_document_storage_path(app.cfg)`. `app.config` is Kivy's internal ConfigParser; `app.cfg` is TALON's config object. Using the wrong one caused an `AttributeError` crash (if Kivy had no app config) or silently ignored any custom `[documents] storage_path` in `talon.ini`.

---

### [BUG-060] `_transition()` in `missions.py` swallows `ValueError` inside another `ValueError`
- **File:** `talon/missions.py` lines 333–336
- **Severity:** MEDIUM
- **Category:** Bug / Error Handling
- **Status:** FIXED 2026-04-16
- **Fix:** Split the single `except Exception` clause into `except ValueError: conn.rollback(); raise` followed by `except Exception as exc: conn.rollback(); raise ValueError(...) from exc`. This matches the pattern used in `create_mission`, `approve_mission`, etc., and prevents double-wrapping of intentional state-transition errors.

---

### [BUG-061] `chat.py` `load_messages` bytes fallback encodes string repr, not content
- **File:** `talon/chat.py` line 217
- **Severity:** MEDIUM
- **Category:** Bug / Data Corruption
- **Status:** FIXED 2026-04-16
- **Fix:** Replaced `row[3] if isinstance(row[3], bytes) else str(row[3]).encode()` with `bytes(row[3])`. `bytes()` correctly handles `bytes`, `bytearray`, and `memoryview` without encoding a Python object repr.

---

### [BUG-062] `document_screen.py` reads entire file into memory before size check
- **File:** `talon/ui/screens/document_screen.py` line 329
- **Severity:** MEDIUM
- **Category:** Bug / Resource Exhaustion
- **Status:** FIXED 2026-04-16
- **Fix:** Added a pre-check using `pathlib.Path(file_path).stat().st_size` against `MAX_DOCUMENT_SIZE_BYTES` before calling `read_bytes()`. If the file exceeds the limit the function returns early with an error message, preventing multi-GB files from exhausting memory before `upload_document()` can enforce the cap.

---

### [BUG-063] `delete_mission` docstring says "NULL zone.mission_id" but code deletes zones
- **File:** `talon/missions.py` lines 218–222
- **Severity:** LOW
- **Category:** Documentation Bug
- **Status:** FIXED 2026-04-16
- **Fix:** Updated docstring step 2 from `"NULL zone.mission_id  (nullable FK)"` to `"DELETE zones  (zones are deleted with the mission, not unlinked)"`, matching the actual `DELETE FROM zones WHERE mission_id = ?` implementation.

---

### [BUG-064] `logging.basicConfig()` called unconditionally at module import time
- **File:** `talon/utils/logging.py` lines 11–14
- **Severity:** LOW
- **Category:** Code Quality / Anti-pattern
- **Status:** FIXED 2026-04-16
- **Fix:** Replaced `logging.basicConfig(...)` in `logging.py` with `logging.getLogger("talon").addHandler(logging.NullHandler())` (the standard library pattern for library code). Moved `logging.basicConfig(format=..., level=logging.INFO)` to `main.py`, before any talon module is imported, so the application entry point owns root-logger configuration.

---

### [BUG-065] Mission slug collision — two similarly-named missions silently share a channel
- **File:** `talon/missions.py` lines 30–34, 139, 165–169
- **Severity:** MEDIUM
- **Category:** Bug / Data Integrity
- **Status:** FIXED 2026-04-16
- **Fix:** Changed `channel_name = f"#mission-{_slugify(row[0])}"` to `channel_name = f"#mission-{_slugify(row[0])}-{mission_id}"` in `approve_mission()`. Appending the mission primary key makes every channel name globally unique regardless of title similarity.

---

### [BUG-066] `configure_tcp_probe_endpoints()` is defined but never called — public DNS always used
- **File:** `talon/network/interfaces.py` lines 63–94
- **Severity:** NOTE / OPSEC
- **Category:** Incomplete Feature / OPSEC
- **Status:** FIXED 2026-04-16
- **Fix:** Added a call to `configure_tcp_probe_endpoints()` in `main()` (in `main.py`) immediately after `load_config()`, conditioned on `[network] tcp_probe_hosts` being set in `talon.ini`. High-OPSEC deployments can now override the default public DNS probe targets without code changes.

---

### [BUG-067] `delete_asset()` performs two writes without an explicit transaction
- **File:** `talon/assets.py` lines 173–182
- **Severity:** LOW
- **Category:** Code Quality / Inconsistency
- **Status:** FIXED 2026-04-16
- **Fix:** Wrapped the two `conn.execute()` calls in an explicit `try: conn.execute("BEGIN IMMEDIATE") … conn.commit() except: conn.rollback(); raise ValueError(...)` block, matching the pattern used by every other multi-step write in the codebase.

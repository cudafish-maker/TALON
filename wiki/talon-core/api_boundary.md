# Core API Boundary

`talon-core` exposes a UI-safe application boundary. Desktop and mobile clients
must not call low-level Reticulum, SQLCipher, migration, crypto, or sync modules
directly.

## Current Slice

Phase 1 adds `talon_core.TalonCoreSession`. Backend implementations now live
under `talon_core`; legacy `talon/` backend modules remain as compatibility
shims while client-facing behavior goes through the core facade.

Implemented now:

- Config load and runtime path resolution.
- SQLCipher unlock/open/migration/close.
- Optional lease monitor startup.
- Optional server/client network sync startup through existing managers.
- Client enrollment wrapper.
- Event subscription and publication.
- `session`, `dashboard.summary`, `sync.status`, operator, asset, SITREP,
  mission, chat, document, enrollment, audit, map, and settings read models.
- Command dispatcher for operator, asset, SITREP, mission, chat, document,
  enrollment, and settings service commands.
- Kivy login/startup now uses `TalonCoreSession` instead of opening DB and
  starting sync managers directly.
- Kivy feature screens now delegate main domain behavior to `TalonCoreSession`
  instead of direct backend imports.

Recently completed:

- Physical backend implementation moves into `talon_core`.
- Dedicated dashboard and sync-status read models for desktop/mobile clients.
- Initial `talon_desktop` adapter package.

## Target Facade

The stable facade now begins with:

```python
class TalonCoreSession:
    def start(self, config_path: str | None = None, mode: str | None = None) -> None: ...
    def unlock(self, passphrase: str) -> None: ...
    def close(self) -> None: ...
    def enroll_client(self, token_and_hash: str, callsign: str) -> None: ...
    def start_sync(self) -> None: ...
    def stop_sync(self) -> None: ...
    def command(self, command_name: str, payload: dict | None = None, **kwargs) -> object: ...
    def read_model(self, name: str, filters: dict | None = None) -> object: ...
    def subscribe(self, handler) -> object: ...
```

The exact module layout can change during extraction, but the behavioral groups
below are required.

## Required API Groups

- Config and session startup: config load, data/RNS/document path resolution,
  logging, DB open/close, mode setup.
- Authentication and enrollment: passphrase unlock, server bootstrap, client
  enrollment, lease state, revocation/lock state.
- Sync lifecycle: start/stop server net handler or client sync manager, expose
  connection status, heartbeat status, pending outbox count, last sync time.
- Domain commands: operators, assets, SITREPs, missions, map-linked records,
  chat, documents, audit, lease, revocation.
- Read models: dashboard, operators, assets, SITREPs, missions, map overlays,
  chat, documents, server admin, audit.
- Event stream: UI refresh, unread badges, sync status, lease lock, revocation
  lock, FLASH overlays, opt-in audio triggers.

## Client Rules

- `talon-desktop` imports `talon-core` directly in-process.
- `talon-mobile` reaches `talon-core` through Chaquopy.
- No client may bypass core for TALON sync, enrollment, revocation, document
  transfer, or chat traffic.

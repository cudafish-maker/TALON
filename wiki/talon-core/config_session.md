# Config And Session

Core owns runtime setup for every client.

## Current Slice

`talon_core.TalonCoreSession` now owns the first UI-independent session path:

- `start()` loads config, resolves mode, and calculates data, DB, salt, RNS, and
  document paths.
- `unlock()` derives the DB key, opens SQLCipher, verifies the key, applies
  migrations, and resolves the local operator.
- `unlock_with_key()` supports tests and future platform-secret integrations.
- `read_model("dashboard.summary")` returns a UI-ready operational count and
  runtime summary.
- `read_model("sync.status")` returns connection state, heartbeat state,
  pending outbox counts, last sync time, and active server client count.
- `close()` stops core-owned runtime managers and closes the DB.
- The legacy Kivy `LoginScreen` now delegates unlock, migration, lease monitor
  startup, and network sync startup to `TalonCoreSession`.

## Config Format

- Use `configparser` INI.
- Honor explicit `TALON_CONFIG` or supplied `config_path`; do not merge silently
  with default server config.
- Resolve mode from explicit session input, config, or `TALON_MODE`.

## Runtime Paths

Core resolves and owns:

- TALON data dir.
- SQLCipher database path.
- Salt path.
- Reticulum config dir.
- Server and client identity paths.
- Document storage path.
- Client document cache path.
- State/log dirs needed by launchers.

Desktop and mobile may supply platform-specific base dirs, but final path
ownership stays in core.

## Startup Sequence

1. Load config and mode.
2. Configure logging.
3. Derive/open SQLCipher only after passphrase unlock.
4. Run migrations.
5. Load/create local RNS identity after DB/config are ready.
6. Start server or client sync lifecycle as requested by the UI.

## Legacy Compatibility

`TalonApp` mirrors core-owned `conn`, `db_key`, `operator_id`, `sync_engine`,
`net_handler`, and `client_sync` references back onto the app object so existing
Kivy screens continue to work during incremental extraction.

## Shutdown

- Stop sync managers and RNS handlers.
- Block new DB writes.
- Wait for in-flight transaction wrapper writes to drain.
- Close the SQLCipher connection.
- Release event subscribers.

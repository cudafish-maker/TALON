# Assets

Core owns asset persistence, verification policy, mission allocation links, and
sync events.

## Asset Types

- Person
- Safe house
- Cache
- Rally point
- Vehicle
- Custom

## Rules

- Asset coordinates may be absent, but partial lat/lon pairs are invalid.
- Unverified assets remain visibly unverified until confirmed by a second party
  or server authority.
- Client push must ignore untrusted author, verification, and server-owned
  fields supplied by the client.
- Delete operations unlink related SITREPs and emit linked-record events.

## Read Models

Implemented through `TalonCoreSession`:

- `assets.list`
- `assets.detail`
- `map.context` asset overlays
- `sitreps.list` filtered by `asset_id`

Implemented commands:

- `assets.create`
- `assets.update`
- `assets.verify`
- `assets.request_delete`
- `assets.hard_delete`

Verification policy now lives in core: clients cannot verify their own assets,
and server-only hard deletes emit linked-record events for affected SITREPs.

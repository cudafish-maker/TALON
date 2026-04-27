# Missions

Core owns mission lifecycle, asset allocation, routes, zones, and linked SITREPs.

## Lifecycle

1. Operator creates a pending mission.
2. Server approves or rejects.
3. Approved missions may be active, completed, aborted, or deleted by server
   authority.

## Linked Records

- Assets requested at create time and finalized on approval.
- Mission channel created on approval.
- Waypoints define ordered routes.
- Zones define AO and other operating areas.
- SITREPs may be linked at create time or through service commands.

## Rules

- Mission lifecycle commands return domain events for all changed linked records.
- Asset allocation conflicts are handled transactionally.
- Deleting a mission cleans up or unlinks related channels, messages, zones,
  waypoints, assets, and SITREPs according to current service behavior.

## Read Models

Implemented through `TalonCoreSession`:

- `missions.list`
- `missions.detail`
- `missions.approval_context`
- `map.context` for route, zone, asset, and mission overlays

Implemented commands:

- `missions.create`
- `missions.approve`
- `missions.reject`
- `missions.complete`
- `missions.abort`
- `missions.delete`

Legacy Kivy mission browse/detail/approval and mission creation now route
through core. Server-only lifecycle guards live in the facade.

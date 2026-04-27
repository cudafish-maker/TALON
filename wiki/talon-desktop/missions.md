# Desktop Missions

Desktop owns mission presentation and dialogs. Core owns lifecycle rules.

## Views

- Mission list with status filter. Implemented.
- Mission detail with assets, waypoints, zones, linked SITREPs, and channel.
  Implemented.
- Compact create wizard/dialog. Implemented.
- Asset request controls. Implemented.
- AO polygon coordinate input. Implemented.
- Route/waypoint coordinate input. Implemented.
- Server approval, rejection, abort, completion, and delete controls.
  Implemented.
- Map drawing tools remain open.

## Behavior

- Mission overlays are visible on the map when selected.
- Asset allocations update when missions move through lifecycle states.
- Server actions use confirmation.
- Custom mission types, constraints, resources, and key locations remain
  supported.

## Current Implementation

- `talon_desktop.missions` provides Qt-free mission normalization, create
  payload validation, coordinate parsing, and server action policy helpers.
- `talon_desktop.mission_page.MissionPage` renders mission list/detail, create
  workflow, and server lifecycle controls.
- Mission create calls `TalonCoreSession.command("missions.create")` with
  requested assets, optional AO polygon, and optional route.
- Server lifecycle controls call `missions.approve`, `missions.reject`,
  `missions.abort`, `missions.complete`, and `missions.delete`.
- Mission-linked events refresh Missions, Assets, Map, SITREPs, and Chat through
  core event mapping.

## Acceptance

- Mission lifecycle events refresh mission, map, asset, SITREP, and chat views.
- Offline client-created missions push and reconcile when reconnected.

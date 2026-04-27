# Desktop Map

Desktop renders maps using a Qt-appropriate implementation while consuming core
map read models. The current PySide6 implementation is a local operational
overlay surface, not an online tile client.

## Required Layers

- Asset markers. Implemented.
- Zone polygons. Implemented.
- Mission routes and waypoints. Implemented.
- Asset-linked SITREP markers. Implemented.
- Selected mission operating areas. Implemented through mission filter.
- OSM. Deferred.
- Satellite. Deferred.
- Topo. Deferred.

## Interaction

- Mission filter scopes route and AO overlays.
- Selecting assets, mission routes, zones, waypoints, or asset-linked SITREPs
  opens context detail.
- Asset list/map picker controls remain open.
- Drawing tools for AO polygons, waypoint routes, and asset placement remain
  open.

## Current Implementation

- `talon_desktop.map_data` provides Qt-free projection and overlay helpers.
- `talon_desktop.map_page.MapPage` renders a Qt `QGraphicsScene` operational
  surface from `TalonCoreSession.read_model("map.context")`.
- The page renders asset markers, zone polygons, mission route lines, waypoint
  markers, and asset-linked SITREP markers.
- The page refreshes from core events for assets, missions, zones, waypoints,
  and SITREPs.
- No map tile/provider code exists yet, so no tile path bypasses core sync
  policy.

## Deferred

- OSM/Satellite/Topo tile layers and AO tile pre-cache remain deferred until
  sync and storage policy are designed in core.

## Legacy Source

Distilled from [../archive/legacy/map.md](../archive/legacy/map.md).

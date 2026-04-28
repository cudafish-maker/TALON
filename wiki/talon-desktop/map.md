# Desktop Map

Desktop renders maps using a Qt-appropriate implementation while consuming core
map read models. The current PySide6 implementation renders live raster base
map tiles underneath local operational overlays.

## Required Layers

- Asset markers. Implemented.
- Zone polygons. Implemented.
- Mission routes and waypoints. Implemented.
- Asset-linked SITREP markers. Implemented.
- Selected mission operating areas. Implemented through mission filter.
- OSM. Implemented as a live raster tile layer.
- Satellite. Implemented as a live raster tile layer.
- Topo. Implemented as a live raster tile layer.

## Interaction

- Mission filter scopes route and AO overlays.
- OSM, TOPO, and Satellite radio buttons switch the visible base layer.
- Mouse-wheel scrolling zooms the map in and out around the cursor.
- Selecting assets, mission routes, zones, waypoints, or asset-linked SITREPs
  uses item tooltips/details without a persistent side panel.
- Asset creation/editing includes an OSM map picker for click-to-place asset
  coordinates.
- Drawing tools for AO polygons and waypoint routes remain open.

## Current Implementation

- `talon_desktop.map_data` provides Qt-free projection and overlay helpers.
- `talon_desktop.map_tiles` provides Qt-free raster tile layer definitions,
  Web Mercator projection helpers, reverse click-to-coordinate projection, and
  visible-tile planning.
- `talon_desktop.map_page.MapPage` renders a Qt `QGraphicsScene` operational
  surface from `TalonCoreSession.read_model("map.context")`.
- The page uses Qt network loading for visible OSM, TOPO, and Satellite tiles,
  displays attribution in-scene, and keeps tile traffic outside TALON sync
  traffic.
- The page renders asset markers, zone polygons, mission route lines, waypoint
  markers, and asset-linked SITREP markers.
- The page refreshes from core events for assets, missions, zones, waypoints,
  and SITREPs.
## Deferred

- Offline tile packages, operator-managed tile cache controls, and AO tile
  pre-cache remain deferred until storage/privacy policy is designed.

## Legacy Source

Distilled from [../archive/legacy/map.md](../archive/legacy/map.md).

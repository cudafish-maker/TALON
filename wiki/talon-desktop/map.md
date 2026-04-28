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
- Mouse-wheel scrolling zooms the map viewport in and out around the cursor,
  then requests fresh raster tiles for the updated geographic bounds so zoomed
  views resolve to higher tile resolution instead of scaling the old image.
- Selecting assets, mission routes, zones, waypoints, or asset-linked SITREPs
  writes full overlay details into the persistent side panel.
- Asset visibility can be scoped through an all/none/apply picker.
- Asset creation/editing and mission workflows use the shared map picker with
  operational overlays and OSM/TOPO/Satellite base-layer selection.
- Drawing tools for AO polygons and waypoint routes are implemented.

## Current Implementation

- `talon_desktop.map_data` provides Qt-free projection and overlay helpers.
- `talon_desktop.map_tiles` provides Qt-free raster tile layer definitions,
  Web Mercator projection helpers, reverse click-to-coordinate projection, and
  visible-tile planning for both base and zoomed view bounds.
- `talon_desktop.map_page.MapPage` renders a Qt `QGraphicsScene` operational
  surface from `TalonCoreSession.read_model("map.context")`.
- The page uses Qt network loading for visible OSM, TOPO, and Satellite tiles,
  displays attribution in-scene, and keeps tile traffic outside TALON sync
  traffic.
- The page renders asset markers, zone polygons, mission route lines, waypoint
  markers, and asset-linked SITREP markers.
- `talon_desktop.map_picker` provides reusable point, polygon, and route
  dialogs for asset placement and mission geometry.
- The page refreshes from core events for assets, missions, zones, waypoints,
  and SITREPs.
## Deferred

- Offline tile packages, operator-managed tile cache controls, and AO tile
  pre-cache remain deferred until storage/privacy policy is designed.

## Legacy Source

Distilled from [../archive/legacy/map.md](../archive/legacy/map.md).

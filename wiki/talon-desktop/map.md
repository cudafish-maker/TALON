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
- Click-drag panning moves the active geographic bounds for the main map and
  shared map pickers, then refreshes raster tiles and operational overlays for
  the new view.
- Selecting assets, mission routes, zones, waypoints, or asset-linked SITREPs
  updates the map context panel while preserving item tooltip/debug metadata.
- The main map includes a left assets panel and a right context panel for both
  client and server modes; each panel can collapse toward its nearest screen
  edge.
- The right context panel uses a vertical splitter so the Selection, Missions,
  and SITREPs box heights can be adjusted by the operator; splitter positions
  are persisted with desktop view settings.
- Selecting an asset in the left assets panel recenters and zooms the map to
  that asset, then selects the asset marker when it is visible.
- The displayed map scene tracks the current `QGraphicsView` viewport size and
  uses zero internal scene margin, so the raster map fills the available map
  boundary instead of fitting a fixed 1000x700 scene inside it.
- Asset visibility can be scoped through an all/none/apply picker.
- Asset creation/editing and mission workflows use the shared map picker with
  operational overlays and OSM/TOPO/Satellite base-layer selection.
- Shared map pickers use the same viewport-sized scene geometry as the main
  map, keeping tile coverage and coordinate projection consistent across
  resize, pan, and zoom.
- Shared map pickers update geographic bounds and request a fresh tile plan on
  wheel zoom or click-drag pan, matching the main map instead of scaling the
  initially loaded pixmaps.
- Wheel and drag input is coalesced into short GUI-thread render batches so
  repeated gestures do not trigger a full tile request wave for every raw event.
- Drawing tools for AO polygons and waypoint routes are implemented.

## Current Implementation

- `talon_desktop.map_data` provides Qt-free projection and overlay helpers.
- `talon_desktop.map_tiles` provides Qt-free raster tile layer definitions,
  Web Mercator projection helpers, reverse click-to-coordinate projection, and
  viewport-aware visible-tile planning for both base and zoomed view bounds.
- `talon_desktop.map_page.MapPage` renders a Qt `QGraphicsScene` operational
  surface from `TalonCoreSession.read_model("map.context")`.
- The page uses Qt network loading for visible OSM, TOPO, and Satellite tiles,
  displays attribution in-scene, and keeps tile traffic outside TALON sync
  traffic.
- `talon_desktop.map_scene_tiles` preserves prior tile layers as stale
  backdrops until replacement tiles load, aborts superseded tile requests, and
  keeps a small decoded-pixmap LRU cache above the Qt disk cache. Incomplete or
  failed replacement frames leave stale coverage in place rather than blanking
  the map.
- The page renders asset markers, zone polygons, mission route lines, waypoint
  markers, and asset-linked SITREP markers.
- The page keeps mode-independent side panels for assets, selected overlay
  details, missions, and recent linked SITREPs; panel collapse controls remain
  visible while collapsed.
- `talon_desktop.map_picker` provides reusable point, polygon, and route
  dialogs for asset placement and mission geometry.
- The page refreshes from core events for assets, missions, zones, waypoints,
  and SITREPs.

## Deferred

- Offline tile packages, operator-managed tile cache controls, and AO tile
  pre-cache remain deferred until storage/privacy policy is designed.

## Legacy Source

Distilled from [../archive/legacy/map.md](../archive/legacy/map.md).

# Map Core

Core does not own UI widgets. It owns map read models and operational context.

## Current Shared Context

The monolith uses a shared `MapContext` to load:

- Assets
- Zones
- Missions
- Waypoints/routes

This behavior is now exposed as `TalonCoreSession.read_model("map.context")`
using the UI-independent `talon_core.map.MapContext` module. The legacy Kivy
`talon.ui.widgets.map_data` module is a compatibility import only.

## Overlay Rules

- Asset markers include category, coordinates, verification state, and mission
  association.
- Mission routes and operating areas are selection-scoped in desktop UI.
- Selected mission assets are always included when a mission is selected.
- Zone polygons include type, label, mission link, and vertices.
- AO tile pre-cache remains deferred.

## Client Responsibilities

Desktop and mobile render the map using their own UI frameworks. They consume
core read models for overlays and call core commands for asset placement,
waypoints, and zone creation.

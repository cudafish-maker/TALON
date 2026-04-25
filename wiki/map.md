# Map Widget & Context Panel — Design Notes

## Key Decisions Made

### Shared Operational Map Context (`map_data.py` + `map_layers.py`)
- Map screens and picker modals now load the same `MapContext` instead of each screen hand-selecting records.
- `MapContext` contains assets, zones, waypoints, and missions so route colouring can use mission status.
- `OperationalOverlayController` attaches shared asset markers, zone overlays, and waypoint/route overlays to any `MapView`.
- The app still creates separate `MapView` instances per screen/modal (Kivy widgets cannot be safely reused across parents), but the displayed operational picture is shared.
- Mission AO, route, staging/demob point, and asset-location pickers now show existing operational assets/zones/routes by default.
- Main screen mission overlays are selection-scoped: mission-linked routes and operating areas are hidden until the operator selects that mission in the right-side mission panel. Selecting the same mission again clears the overlay selection.
- Main screen asset markers are operator-filterable via the asset panel `MAP` picker. Assets linked to the selected mission are always included on the map even when they are outside the operator-selected baseline set.

### Tile Library: kivy_garden.mapview (`mapview` on PyPI)
- Rejected image-based approach (no static files needed).
- `MapView` is the standard Kivy tile map widget, works on Linux/Windows and Android.
- Install: `pip install mapview`. Import: `from kivy_garden.mapview import MapView`.
- Handles tile caching internally in `~/.kivy/cache/`. AO pre-cache is a future TODO.
- Android (Phase 4) needs a p4a recipe — deferred.
- Tile source definitions live in `talon/ui/widgets/map_sources.py`; picker/drawing modals inherit the active main-map layer when available.

### Zone Overlays: custom `MapLayer` subclass (`ZoneLayer`)
- Moved to `talon/ui/widgets/map_layers.py` so browse maps and picker maps render zones identically.
- `MapLayer.reposition()` is called by `MapView` after every pan/zoom — this is where we redraw polygons.
- Coordinate conversion: `mapview.get_window_xy_from(lat, lon, mapview.zoom)` → screen (x, y).
- Canvas draws `Line(points=...)` with translucent `Color` fill per zone type.
- Zone tap detection (touch-to-polygon hit test) deferred — not in MapLayer by default.

### Route / Waypoint Overlays: custom `MapLayer` subclass (`WaypointLayer`)
- Existing mission waypoints are grouped by `mission_id` and drawn as route lines with start/end/intermediate dots.
- Route line colour follows mission status when available: active green, pending amber, completed grey, aborted/rejected red.
- Used by the main tactical map and all picker/drawing modals so operators can see existing routes while planning new ones.

### Asset Markers: `MapMarker` subclass (`AssetMarker`)
- `MapMarker` is a `ButtonBehavior + Image` widget from mapview.
- Set `source=""` to suppress the default pin image; draw category circle on `canvas.before`.
- Bind `on_pos` / `on_size` → `_redraw()` so the circle repaints when the map pans.
- Verified assets: solid dark border. Unverified: dashed amber border (`Line(dash_offset=3)`).
- Category color coding (no text abbrev needed for Phase 1):
  - `person` → green `(0.2, 0.8, 0.2)`
  - `safe_house` → blue `(0.2, 0.6, 1.0)`
  - `cache` → amber `(1.0, 0.7, 0.0)`
  - `rally_point` → cyan `(0.0, 0.9, 0.9)`
  - `vehicle` → orange `(0.8, 0.4, 0.0)`
  - `custom` → grey `(0.7, 0.7, 0.7)`
- `on_release` dispatches `on_asset_tap(asset)` up to `MapWidget`.

### Context Panel: new `ContextPanel` widget (`context_panel.py`)
- **What it is**: The right-column (280dp) of the three-column layout. Dynamic detail / status pane.
- **Two modes**:
  - *Summary* (default): operators online, active mission name, latest SITREP level/preview.
  - *Detail*: pushed when something is tapped on map. Shows full item info + action buttons.
- **Implementation**: `MDBoxLayout` (vertical). Header label + `MDDivider` + `MDScrollView` > inner `MDBoxLayout`.
  - `_clear_content()` clears the inner box.
  - `_add_row(icon, label, value)` adds a two-column info row.
  - Public API: `show_summary()`, `show_asset(asset)`, `show_zone(zone)`, `show_waypoint(waypoint)`.
  - `update_summary(operators_online, active_mission, latest_sitrep)` for live data updates from sync.
  - Back button in detail views calls `show_summary()`.
- No separate `.kv` file — fully programmatic (dynamic content makes Python cleaner).

### Wiring (main_screen.py / main.kv)
- `MapWidget` and `ContextPanel` are instantiated in Python in `MainScreen.on_kv_post()`.
- `MapWidget` is added to `ids.map_container` (removing the placeholder label).
- `ContextPanel` is added to `ids.context_panel` (replacing placeholder label).
- `map_widget.bind(on_asset_tap=context_panel.show_asset)` — single binding wires the flow.
- `main.kv` `map_container` and `context_panel` boxes are emptied of placeholder labels.

---

## Features — Map Widget

| Feature | Status | Notes |
|---------|--------|-------|
| OSM tile layer (default) | DONE | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` |
| Satellite tile layer | DONE | ESRI World Imagery |
| Topo tile layer | DONE | OpenTopoMap |
| Tile layer switching | DONE | header toggle buttons (OSM / SAT / TOPO); `map_widget.set_layer()` |
| Asset marker display | DONE | colored circle per category; dashed amber border = unverified |
| Main map asset picker | DONE | asset panel `MAP` button filters displayed asset markers |
| Selected mission asset union | DONE | selected mission assets remain visible regardless of asset-picker baseline |
| Asset marker tap → context panel | DEFERRED | `on_asset_tap` logged; full detail view Phase 2 |
| Zone polygon overlays | DONE | translucent fill + colored border per zone type |
| Zone tap → context panel | DEFERRED | no hit-test in MapLayer by default |
| Waypoint / route display | DONE | shared route overlay on main map and picker/drawing maps |
| Shared map context | DONE | `MapContext` loads assets/zones/waypoints/missions for all map views |
| Main map mission overlay selection | DONE | right-panel mission cards filter visible mission routes and operating areas |
| AO tile pre-cache | DEFERRED | broadband-only, needs sync integration |

## Features — Context Panel

| Feature | Status | Notes |
|---------|--------|-------|
| Situation summary (default) | DONE | operators / mission / SITREP + asset list rows |
| Asset detail view | DONE | category, verified status, coords, description, linked SITREPs |
| Zone detail view | DONE | type, label, linked mission, vertex count |
| Waypoint detail view | DONE | sequence, label, mission, coords |
| Edit asset action | DEFERRED | navigates to Asset screen |
| Verify asset action | DEFERRED | navigates to Asset screen |
| Live summary updates | DEFERRED | `update_summary()` ready; called by sync engine |

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `pyproject.toml` | add `mapview>=2023.1.0` |
| `talon/ui/widgets/map_data.py` | shared `MapContext` loader for assets, zones, waypoints, missions |
| `talon/ui/widgets/map_layers.py` | shared `ZoneLayer`, `WaypointLayer`, `OperationalOverlayController` |
| `talon/ui/widgets/map_sources.py` | shared OSM/Satellite/Topo tile sources |
| `talon/ui/widgets/map_widget.py` | full implementation (`MapWidget`) using shared operational overlays |
| `talon/ui/widgets/asset_marker.py` | full implementation (`AssetMarker`) |
| `talon/ui/widgets/context_panel.py` | **new file** (`ContextPanel`) |
| `talon/ui/screens/main_screen.py` | wire `MapWidget` + `ContextPanel` in `on_kv_post` |
| `talon/ui/kv/main.kv` | remove placeholder labels from `map_container` and `context_panel` |

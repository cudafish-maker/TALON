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

### Context Panel: reusable `ContextPanel` widget (`context_panel.py`)
- **What it is**: A reusable dynamic detail/status pane. The current main dashboard uses custom left/right summary panels, and asset marker/list taps open a ContextPanel-styled detail modal.
- **Two modes**:
  - *Summary* (default): operators online, active mission name, latest SITREP level/preview.
  - *Detail*: pushed when something is tapped on map. Shows full item info + action buttons.
- **Implementation**: `MDBoxLayout` (vertical). Header label + `MDDivider` + `MDScrollView` > inner `MDBoxLayout`.
  - `_clear_content()` clears the inner box.
  - `_add_row(label, value)` adds a two-column info row.
  - Public API: `show_summary()`, `show_asset(asset)`, `show_zone(zone)`, `show_waypoint(waypoint)`.
  - `update_summary(operators_online, active_mission, latest_sitrep)` remains available for embedded summary uses.
  - Back button in detail views calls `show_summary()`.
- No separate `.kv` file — fully programmatic (dynamic content makes Python cleaner).

### Wiring (main_screen.py / main.kv)
- `MainScreen._build_desktop_layout()` builds the dashboard programmatically: topbar, icon rail, asset panel, full map, and mission/SITREP panel.
- `MapWidget` is instantiated in Python, placed inside the dashboard `FloatLayout`, and refreshed from shared `MapContext`.
- `MapWidget.on_asset_tap` is wired by `MainScreen`; tapping a marker opens the ContextPanel-styled asset detail modal with linked SITREPs.
- `main.kv` is now a minimal registration stub so the screen rule exists; it does not own the dashboard layout.

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
| Asset marker tap → detail | DONE | `on_asset_tap` opens a ContextPanel-styled asset detail modal with linked SITREPs; asset-list taps also center/zoom the map before opening detail |
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
| Live summary updates | DONE | main dashboard refreshes summary panels on data push/startup hydration; `ContextPanel.update_summary()` remains available for embedded summary uses |

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `pyproject.toml` | includes `mapview>=1.0.6` |
| `talon/ui/widgets/map_data.py` | shared `MapContext` loader for assets, zones, waypoints, missions |
| `talon/ui/widgets/map_layers.py` | shared `ZoneLayer`, `WaypointLayer`, `OperationalOverlayController` |
| `talon/ui/widgets/map_sources.py` | shared OSM/Satellite/Topo tile sources |
| `talon/ui/widgets/map_widget.py` | full implementation (`MapWidget`) using shared operational overlays |
| `talon/ui/widgets/asset_marker.py` | full implementation (`AssetMarker`) |
| `talon/ui/widgets/context_panel.py` | **new file** (`ContextPanel`) |
| `talon/ui/screens/main_screen.py` | programmatically wires `MapWidget`, shared map context, asset filter picker, mission overlay selection, and asset detail modal |
| `talon/ui/kv/main.kv` | minimal registration stub; dashboard layout is built in Python |

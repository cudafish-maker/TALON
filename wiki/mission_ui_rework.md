# Mission UI Rework — Implementation Checklist

Full redesign of the mission create flow: replacing the single-modal approach with a five-step OPORD-style wizard screen (`MissionCreateScreen`), with mutual-aid terminology throughout. Military ROE → Operating Constraints.

---

## Phase 1 — DB Migration

- [x] `talon/db/migrations.py` — append migration 0013 (18 `ALTER TABLE missions ADD COLUMN` statements for `mission_type`, `priority`, `lead_coordinator`, `organization`, `activation_time`, `operation_window`, `max_duration`, `staging_area`, `demob_point`, `standdown_criteria`, `phases` JSON, `constraints` JSON, `support_medical`, `support_logistics`, `support_comms`, `support_equipment`, `objectives` JSON, `key_locations` JSON)
- [x] `talon/constants.py` — bump `DB_SCHEMA_VERSION` from 12 → 13
- [x] Verify `len(MIGRATIONS) == DB_SCHEMA_VERSION` assertion passes (13 == 13)
- [x] `talon/db/migrations.py` — append migration 0014 (`missions.custom_resources` JSON for custom support-resource rows); `DB_SCHEMA_VERSION` is now 14

---

## Phase 2 — Data Model & Backend

- [x] `talon/db/models.py` — expand `Mission` dataclass with all 18 new fields (all have defaults so existing code still works); JSON fields typed as `list` / `dict`
- [x] `talon/missions.py` — `create_mission()`: add all new kwargs, include them in the INSERT
- [x] `talon/missions.py` — `get_mission()`: SELECT new columns, deserialize JSON fields with `json.loads()`
- [x] `talon/missions.py` — `load_missions()`: include new columns in SELECT (for list display: at minimum `mission_type` and `priority`)

---

## Phase 3 — Extract Shared Map Drawing Widgets

- [x] Create `talon/ui/widgets/map_draw.py`
- [x] Move `PolygonDrawLayer` from `mission_screen.py` → `map_draw.py`
- [x] Move `PolygonDrawView` from `mission_screen.py` → `map_draw.py`
- [x] Move `PolygonDrawModal` from `mission_screen.py` → `map_draw.py`
- [x] Move `WaypointDrawLayer` from `mission_screen.py` → `map_draw.py`
- [x] Move `WaypointDrawView` from `mission_screen.py` → `map_draw.py`
- [x] Move `WaypointRouteModal` from `mission_screen.py` → `map_draw.py`
- [x] Update `mission_screen.py` imports to use `talon.ui.widgets.map_draw`

---

## Phase 4 — New Mission Create Screen

- [x] Create `talon/ui/kv/mission_create.kv` — outer shell only (topbar + sidebar column + content ScrollView + footer bar)
- [x] Create `talon/ui/screens/mission_create_screen.py` — `MissionCreateScreen(MDScreen)`

### Step wiring
- [x] Sidebar: 5 step items (number badge, name, description, connector lines); active = green highlight, done = ✓
- [x] Sidebar bottom: live summary (designation, type, activation time, element count, objective count)
- [x] Footer: 5 progress segments + STEP X OF 5 label + BACK / NEXT / SUBMIT buttons
- [x] Step navigation: `on_next_step` / `on_back_step`, validates required fields on NEXT

### Step 1 — Parameters
- [x] Mission designation MDTextField (required)
- [x] Mission type picker (3-column button group): SEARCH & RESCUE, DEBRIS CLEARANCE, MEDICAL AID, SUPPLY DISTRIBUTION, ROUTE SURVEY, SHELTER SETUP, WELFARE CHECK, HAZMAT RESPONSE, EVACUATION SUPPORT; custom type entry
- [x] Priority pill toggle: ROUTINE (green) / PRIORITY (amber) / FLASH (red)
- [x] Description / mission intent MDTextField (multiline)
- [x] Lead coordinator MDTextField
- [x] Organization MDTextField
- [x] Operating Constraints toggle grid (2 cols, 6 options): STRUCTURAL ENTRY AUTHORIZED, HAZMAT CERTIFIED ONLY, MEDIA BLACKOUT, ANIMAL RESCUE PROTOCOL, WATER RESCUE PROTOCOL, HEAVY EQUIPMENT REQUIRED; custom constraint entry

### Step 2 — Timeline
- [x] Activation time MDTextField
- [x] Operation window MDTextField
- [x] Max duration MDTextField
- [x] Staging area MDTextField
- [x] Demob point MDTextField
- [x] Stand-down criteria MDTextField
- [x] Phases builder: ADD PHASE button → dynamic rows (badge + name + end-state + duration + ✕)

### Step 3 — Assets
- [x] Load available assets from DB at step entry (`load_assets(conn)`)
- [x] Checkbox grid grouped by category (PEOPLE / SAFE HOUSES / CACHES / RALLY POINTS / VEHICLES / CUSTOM)
- [x] Supporting resources (4 MDTextField): Medical support, Logistics/supply, Communications, Heavy equipment; custom resource label/detail rows

### Step 4 — Objectives & Location
- [x] Primary objective card (always present): label + criteria + phase link
- [x] ADD OBJECTIVE button → adds secondary objective cards (removable)
- [x] DRAW MISSION AREA button → opens PolygonDrawModal; shows vertex count when set + clear button
- [x] SET ROUTE / WAYPOINTS button → opens WaypointRouteModal; shows waypoint count + clear button
- [x] Key locations section: medical station, alt route, demob location (MDTextField fields); custom key-location label/detail rows

### Step 5 — Review & Submit
- [x] Review blocks for each section (Parameters, Timeline, Elements, Objectives)
- [x] Submit info banner ("Mission will be submitted for server approval")
- [x] SUBMIT MISSION button → `_do_submit()`

### Submit logic (`_do_submit`)
- [x] Call `create_mission(conn, ...)` with all new fields
- [x] If AO polygon set: call `create_zone(conn, ...)`
- [x] If route set: call `create_waypoints_for_mission(conn, mission_id, route)`
- [x] Call `app.net_notify_change("missions", mission_id)`
- [x] Navigate to "mission" screen

---

## Phase 5 — Update MissionScreen (List View)

- [x] `mission_screen.py` — remove `_show_create_dialog()` and all its closures/helpers (~370 lines removed)
- [x] `mission_screen.py` — `on_create_pressed()` → navigate to "mission_create" instead of showing modal
- [x] `mission_screen.py` — update `_show_detail_dialog()` to display new fields: mission_type, priority, lead_coordinator, constraints list, phases list, objectives list
- [x] Update `_MissionRow` to show type/priority sub-line (amber for PRIORITY, red for FLASH)

---

## Phase 6 — App Registration

- [x] `talon/app.py` — add `MissionCreateScreen` import in `_register_shared_screens()`
- [x] `talon/app.py` — `sm.add_widget(MissionCreateScreen(name="mission_create"))`
- [x] `mission_create.kv` auto-loaded by existing `glob("*.kv")` pattern — no extra registration needed

---

## Verification Checklist

- [ ] `python main.py` — server mode — Missions → + → wizard opens
- [ ] Step 1: fill designation + type + priority; sidebar summary updates live
- [ ] Step 2: add 2 phases; timing fields fill
- [ ] Step 3: select 2 assets; counter shows "2 SELECTED"
- [ ] Step 4: draw AO polygon (≥3 vertices); draw route (≥1 waypoint); add 1 objective
- [ ] Step 5: all fields appear in review blocks → Submit → success
- [ ] Mission appears in list with new type/priority visible
- [ ] Detail dialog shows new fields (type, priority, constraints, phases, objectives)
- [ ] Server approval flow still works on existing missions (no regression)
- [ ] `pytest tests/` — migration 0013 applies cleanly; existing tests pass

---

## Notes

- The KV file for `mission_create` only covers the outer shell. All step content is built procedurally in Python (consistent with existing TALON modal pattern).
- `PolygonDrawModal` and `WaypointRouteModal` are reused without modification from `map_draw.py`.
- Existing `approve_mission()`, `reject_mission()`, `abort_mission()`, `complete_mission()`, `delete_mission()` in `missions.py` are untouched — new columns are ignored by those flows.
- The back-navigation from `MissionCreateScreen` should clear `_data` to avoid stale form state on re-entry.

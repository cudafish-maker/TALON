# Desktop App Shell

The desktop shell is a PySide6 application that imports `talon-core`
in-process.

## Required Windows

- Unlock/login window.
- Lease/revocation lock window.
- Main operator dashboard.
- Modal/dialog framework for create/edit/detail flows.
- Server admin windows available only in server mode.

## Main Layout

The desktop target should keep the current operational density:

- Persistent navigation surface with all major functions.
- Large map area.
- Asset/mission/SITREP context panels.
- Status area for sync, lease, mode, and pending outbox.
- Alert overlay layer for SITREP severity events.

## Core Integration

- Start core from supplied config/mode.
- Unlock DB through core.
- Subscribe to core events and adapt them to Qt signals.
- Render read models from core.
- Dispatch all writes through core commands.

## Current Implementation

- `talon_desktop.main` provides the `talon-desktop` entry point and
  `python -m talon_desktop` launcher.
- `talon_desktop.app` creates the PySide6 login/enrollment/lock windows and
  main navigation shell.
- `talon_desktop.theme` applies the centralized dark operational Qt palette,
  stylesheet, left navigation rail styling, dialog/form polish, and dense table
  behavior.
- `talon_desktop.settings` persists desktop-local UI preferences with
  `QSettings`, including main window geometry/state, root and page splitter
  state, table column/header state, and the last selected navigation section.
- `talon_desktop.logs` and `talon_desktop.log_view` provide a bounded
  current-session log buffer, a status-bar Logs button with warning/error count,
  and a copyable log dialog for desktop/core runtime diagnostics.
- Unlock uses `TalonCoreSession.unlock()` and starts Reticulum/sync by default;
  `--no-sync` is available for local UI smoke tests.
- Offscreen desktop runtime smoke tests cover server unlock to the main window
  and client unlock to the enrollment prompt.
- The main window exposes Dashboard, Map, SITREPs, Assets, Missions, Chat,
  Documents, Operators, and server-only Enrollment/Clients/Audit/Keys sections.
- The Dashboard section renders the core `dashboard.summary` and `sync.status`
  read models instead of calculating counts in desktop code.
- `talon_desktop.qt_events.CoreEventBridge` adapts core domain events into Qt
  refresh, mutation, and lock signals.
- `talon_desktop.sitrep_page.SitrepPage` is the first non-placeholder feature
  page. It uses core read models and commands for the feed, composer, linked
  asset/mission selectors, server-only delete, composer templates, and audio
  opt-in state.
- High-severity SITREPs render through a non-modal dashboard overlay layer on
  the main content area. FLASH and FLASH_OVERRIDE audio remains gated by the
  persisted core audio opt-in setting.
- `talon_desktop.asset_page.AssetPage` replaces the generic Assets placeholder
  with a table, detail panel, create/edit dialog, verification controls, and
  deletion-request/server-delete command wiring.
- `talon_desktop.map_page.MapPage` replaces the generic Map placeholder with a
  Qt rendered operational overlay surface for assets, zones, routes, waypoints,
  and asset-linked SITREPs.
- `talon_desktop.mission_page.MissionPage` replaces the generic Missions
  placeholder with a list/detail page, create workflow, AO/route input,
  requested asset selection, and server lifecycle command controls.
- `talon_desktop.chat_page.ChatPage` replaces the generic Chat placeholder with
  channel and message navigation, composer, channel creation, DM creation,
  server-only delete controls, urgent rendering, and the DM security notice.
- `talon_desktop.document_page.DocumentPage` replaces the generic Documents
  placeholder with a list/detail page, server upload dialog, download/save flow,
  server delete flow, macro-risk warning, and document error surfacing.
- `talon_desktop.operator_page` replaces generic Operators, Enrollment,
  Clients, Audit, and Keys placeholders with operator profile/skills editing,
  enrollment token generation, pending token list, server hash display, lease
  renewal, revocation, audit log viewing, and key/identity status.

## Open Gaps

- Major function pages have initial command-backed workflows and offscreen smoke
  coverage; remaining gaps are parity refinements and packaging validation.
- Map has a rendered operational overlay surface; OSM/Satellite/Topo tile
  layers and drawing tools remain open.
- Linux package validation and Windows package validation are still pending.

## Migration Rule

Do not port Kivy widget structure directly. Preserve workflows and behavior, but
build native Qt screens around core read models and commands.

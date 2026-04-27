# TALON Wiki Index

Read this file at the start of every session. The wiki is organized around the
platform split, with `wiki/platform_split_plan.md` as the authoritative source
document.

## Primary Source

- [platform_split_plan.md](platform_split_plan.md) - migration plan for splitting
  TALON into `talon-core`, `talon-desktop`, and `talon-mobile`.
- [platform_split_checklist.md](platform_split_checklist.md) - master checkbox
  tracker for the platform split plan, including Linux and Windows breakpoints.

## Current State

As of 2026-04-26, Phase 1 core extraction and physical split hardening are
complete for the current source tree. `talon_core.TalonCoreSession` owns
config/session startup, SQLCipher unlock/migration/close, Reticulum/sync
startup, enrollment, lease monitoring, service command dispatch, read models,
and event publication. Backend implementations now live under `talon_core`;
legacy backend modules under `talon/` are compatibility shims for the Kivy
client and older import paths. Phase 2 desktop work has started:
`talon_desktop` provides a PySide6 entry point, login/enrollment/lock shell,
navigation, read-model pages, a core-event-to-Qt adapter, and a SITREP
feed/composer with templates, opt-in audio state, and a non-modal dashboard
alert overlay. The Assets page now has table/detail, create/edit,
verification, deletion-request, and server-delete workflows. The
Map page now renders selectable live OSM, TOPO, and Satellite raster base
layers plus local operational overlays for assets, zones, routes, waypoints,
and asset-linked SITREPs. The Missions page now covers list/detail,
create, requested assets, AO/route input, and server lifecycle controls. The
Chat page now covers channels, messages, composer, channel creation, DM
creation, server-only delete controls, urgent rendering, and the Phase 2b DM
security notice. The Documents page now covers list/detail, server upload,
download/save, server delete, macro-risk warnings, and document error surfacing.
Operators/server admin pages now cover operator list/detail, profile/skills
editing, enrollment tokens, pending tokens, server hash, lease renewal,
revocation, audit log viewing, and key/identity status. Kivy/KivyMD is retired
from active desktop CI, dependency extras, and publishing. The `desktop` Python
extra installs the PySide6 path only. Desktop smoke tests now construct the
main window offscreen, navigate every section, and cover client/server unlock
paths. Linux Breakpoint A development-shell validation passed locally, including
same-machine Reticulum TCP loopback for enrollment and server-to-client asset
sync. Linux Breakpoint B is complete: a PySide6 Linux PyInstaller spec,
installer script, and manual GitHub Actions workflow now build role-specific
`talon-desktop-client-linux.tar.gz` and `talon-desktop-server-linux.tar.gz`
packages from one PyInstaller output. The installer reads the artifact role,
creates explicit client/server launchers, and requires `DELETE TALON DATA`
confirmation before destructive local role switches. Target Linux Mint package
install/launch validation passed without the old Kivy/SDL/GLX startup failure,
and package-level Reticulum loopback enrollment/sync validation passed from the
packaged artifact and an extracted installed package before the role split. The
next development direction is a polished Linux server/client PySide6 release
candidate, including release-readiness polish and operator acceptance, before
Windows packaging. Windows packaging follows the accepted Linux release, then
the Android/Chaquopy Reticulum spike.

| Project | State | Next Work |
|---------|-------|-----------|
| `talon-core` | Phase 1 facade, dashboard/sync read models, physical split hardening, and Reticulum loopback verification complete for current source tree | Keep package boundary clean during desktop packaging and mobile spike work |
| `talon-desktop` | PySide6 shell plus SITREP, Assets, Map, Missions, Chat, Documents, Operators/server admin workflows, offscreen Qt smoke tests, Linux Breakpoint A dev-shell validation, Linux Breakpoint B package validation, and role-specific Linux client/server artifacts exist; Kivy is retired from active desktop release paths | Polish Linux server/client release candidate before Windows packaging |
| `talon-mobile` | Planned only | Run Android/Chaquopy/Reticulum feasibility spike before full UI work |

## Current Cross-Project Blockers

- BUG-085: the Documents screen is registered, but the current desktop dashboard
  lacks visible navigation to it. See [bugs.md](bugs.md) and
  [talon-desktop/documents.md](talon-desktop/documents.md).
- DM end-to-end encryption remains Phase 2b and belongs in `talon-core`, not in
  client-specific UI code.
- Archived Kivy UI code still exists as reference material and should be moved
  or deleted in a cleanup branch.
- Android work is blocked on proving `RNS`, SQLCipher, PyNaCl/cryptography, and
  document cache dependencies under Chaquopy.

## Project Wikis

| Wiki | Purpose |
|------|---------|
| [talon-core/INDEX.md](talon-core/INDEX.md) | Shared Python runtime, Reticulum, protocol, DB, crypto, services, read models, events |
| [talon-desktop/INDEX.md](talon-desktop/INDEX.md) | Linux/Windows PySide6 desktop app and legacy Kivy migration state |
| [talon-mobile/INDEX.md](talon-mobile/INDEX.md) | Android native UI, Chaquopy bridge, mobile lifecycle, mobile feature plan |

## Root Files

- [platform_split_plan.md](platform_split_plan.md) - source document for the split.
- [platform_split_checklist.md](platform_split_checklist.md) - master migration
  checklist.
- [bugs.md](bugs.md) - active cross-project bug index.
- [archive/INDEX.md](archive/INDEX.md) - historical docs, fixed bugs, and completed
  implementation checklists.

## Development Rules

- Start with [platform_split_plan.md](platform_split_plan.md), then read the
  relevant project `INDEX.md`.
- Keep Reticulum, RNS identity, sync, enrollment, lease, revocation, document
  transfer, and chat traffic inside `talon-core`.
- Do not add Kivy/KivyMD/mapview dependencies, tests, CI jobs, or release
  artifacts back to active desktop work.
- Update the project-specific function doc when changing behavior, and update
  this index only for cross-project status changes.

## Manual Changes

Manual operator changes should be recorded here when they affect project state.

- 2026-04-14 09:00 - minor changes to `server/login.kv` to make the login screen
  more visually appealing.

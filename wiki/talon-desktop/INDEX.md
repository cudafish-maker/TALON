# talon-desktop Wiki

`talon-desktop` is the Linux/Windows operator UI. The target stack is Python
plus PySide6/Qt importing `talon-core` directly.

## Current Status

The active desktop release path is now PySide6. The repo contains a
`talon_desktop` PySide6 shell with login/unlock, client enrollment prompt,
lease/revocation lock dialog, main navigation, read-model pages, and a Qt event
adapter around `talon-core`. The SITREP page now has a Qt feed, composer
templates, asset/mission link selectors,
server-only delete control, opt-in audio state, and a non-modal dashboard alert
overlay for high-severity reports. The Assets page now has a Qt table, detail
panel, create/edit dialog, map placement picker, verification controls, client
deletion requests, and server hard-delete command wiring. The Map page now
renders live OSM, TOPO, and Satellite raster base layers with radio-button
selection plus local operational overlays for assets, zones, mission
routes/waypoints, and asset-linked SITREPs.
The Missions page now has list/detail, create, requested asset, AO/route input,
and server lifecycle controls. The Chat page now has channel/message navigation,
composer, channel creation, direct-message creation, server delete controls,
urgent rendering, and the Phase 2b DM security notice. The Documents page now
has list/detail, server upload, download/save, server delete, macro-risk
warning, and document error surfacing. Operators/server admin pages now cover
operator list/detail, profile/skills editing, enrollment token generation,
pending tokens, server hash, lease renewal, revocation, audit log viewing, and
key/identity status. After physical split hardening, desktop code imports
`talon_core` directly instead of legacy `talon/` backend shims. Kivy is retired
from active desktop CI, dependency extras, and publishing. The new desktop
client now has a centralized PySide6 dark operational theme for the
main shell, collapsible icon navigation rail, dialogs, forms, tables, text
panels, and status surfaces, plus durable local desktop settings for window
geometry, splitter positions, table layouts, rail expanded/collapsed state, and
the last selected section. A session log buffer,
status-bar Logs affordance, and copyable log dialog now surface current-session
desktop/core warnings and errors. It has passed Linux Breakpoint A
development-shell validation:
editable desktop install, local `talon-desktop --no-sync` launch, offscreen
server/client unlock smoke tests, and same-machine Reticulum TCP loopback for
enrollment plus server-to-client asset sync. Linux Breakpoint B is complete:
the PySide6 Linux PyInstaller spec, installer, and manual GitHub Actions
workflow exist, and a local tarball package smoke passed for server and client.
Target Linux Mint package install/launch validation passed without the old
Kivy/SDL/GLX startup failure. Package-level Reticulum loopback sync passed from
the packaged artifact and an extracted installed package. Linux packaging now
produces separate client and server artifacts with role-specific launchers and
a destructive confirmation gate before switching local roles. The Linux package
breakpoint is complete. The current priority is a polished Linux server/client
release candidate before Windows packaging starts.

## Roadmap

1. Create PySide6 shell: login, lock, main window, navigation, event adapter. Initial slice complete.
2. Wire `talon-core` startup, read models, commands, and events. Startup, read models, events, and SITREP/Assets/Missions/Chat/Documents/Operators/server-admin commands are wired.
3. Rebuild major function screens. SITREPs, Assets, Map, Missions, Chat, Documents, and Operators/server admin initial workflows are complete.
4. Package Linux desktop and validate on the target Linux Mint environment. Complete.
5. Polish and accept the Linux server/client release candidate.
6. Validate Windows packaging after the accepted Linux release.
7. Move or delete archived Kivy UI code after it is no longer useful as a
   reference.

## Function Docs

- [app_shell.md](app_shell.md) - PySide6 shell and navigation.
- [operators.md](operators.md) - desktop operator/profile/admin views.
- [assets.md](assets.md) - asset list, edit, verification UI.
- [sitreps.md](sitreps.md) - feed, composer, alert overlays, audio opt-in.
- [missions.md](missions.md) - mission list, create wizard, approval workflow.
- [map.md](map.md) - desktop map rendering and panels.
- [chat.md](chat.md) - channels, DMs, message UI.
- [documents.md](documents.md) - document repository UI and BUG-085.
- [server_admin.md](server_admin.md) - clients, enroll, audit, keys.
- [packaging.md](packaging.md) - Linux/Windows packaging.
- [linux_role_artifact_split_checklist.md](linux_role_artifact_split_checklist.md) - Linux client/server artifact split and destructive role-switch checklist.
- [legacy_kivy.md](legacy_kivy.md) - retired Kivy state.
- [testing.md](testing.md) - desktop acceptance matrix.

## Active Desktop Blockers

- BUG-085: legacy desktop dashboard lacks visible Documents navigation.
- PySide6 major function pages now have initial workflows, offscreen smoke
  tests, and development-shell Reticulum loopback validation; remaining UI gaps
  are parity refinements and packaging validation.
- Linux package validation passed; release polish and operator acceptance remain
  before the Linux PySide6 server/client release candidate.
- Windows packaging follows after the Linux server/client release candidate is
  accepted.

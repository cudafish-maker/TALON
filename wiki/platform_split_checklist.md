# TALON Platform Split Master Checklist

_Created: 2026-04-26._
_Companion tracker for [platform_split_plan.md](platform_split_plan.md)._

Use this file as the operational checklist for the platform split. Check boxes
should only be marked when the repo, tests, and wiki state all reflect the work.
OS/package breakpoints should only be marked after validation on the named
platform.

## Completion Rules

- [x] Keep all Reticulum, RNS identity, sync, enrollment, lease, revocation,
  document transfer, and chat traffic inside `talon-core`.
- [ ] Do not mark desktop feature parity complete until the PySide6 desktop can
  cover current Kivy Phase 2 workflows.
- [ ] Do not mark Linux packaging complete until the package installs and
  launches on the target Linux Mint environment.
- [ ] Do not start Windows packaging work until the Linux server/client release
  candidate is polished and accepted.
- [ ] Do not mark Windows packaging complete until it is validated on Windows.
- [ ] Do not start full mobile UI work until the Android/Chaquopy Reticulum
  spike passes.

## Phase 0: Split Governance

- [x] Create project wikis for `talon-core`, `talon-desktop`, and
  `talon-mobile`.
- [x] Archive legacy root docs under `wiki/archive/legacy/`.
- [x] Make `wiki/platform_split_plan.md` the authoritative migration plan.
- [x] Record that Kivy/KivyMD is legacy migration state.
- [x] Record that Reticulum remains non-negotiable and core-owned.
- [x] Record that desktop and mobile clients must use core read models and
  service commands.
- [x] Keep this checklist current after each completed migration slice.

## Phase 1: `talon-core` Extraction

Goal: make backend behavior UI-independent while the legacy Kivy client still
runs.

### Core Package Boundary

- [x] Create `talon_core` package.
- [x] Add `TalonCoreSession` facade.
- [x] Expose config/session startup through core.
- [x] Expose SQLCipher unlock/open/migration/close through core.
- [x] Expose runtime paths for data, DB, salt, RNS config, and document storage.
- [x] Expose Reticulum startup through core.
- [x] Expose server sync startup/stop through core.
- [x] Expose client sync startup/stop through core.
- [x] Expose lease monitor startup/stop through core.
- [x] Expose client enrollment through core.
- [x] Expose event subscription and publication through core.
- [x] Ensure `talon_core` requires no UI framework imports.

### Core Commands

- [x] Operators: update profile.
- [x] Operators: renew lease.
- [x] Operators: revoke.
- [x] Assets: create.
- [x] Assets: update.
- [x] Assets: verify/unverify.
- [x] Assets: request deletion.
- [x] Assets: server hard delete.
- [x] SITREPs: create.
- [x] SITREPs: server delete.
- [x] Missions: create.
- [x] Missions: approve.
- [x] Missions: reject.
- [x] Missions: abort.
- [x] Missions: complete.
- [x] Missions: delete.
- [x] Chat: ensure default channels.
- [x] Chat: create channel.
- [x] Chat: delete channel.
- [x] Chat: create/get DM.
- [x] Chat: send message.
- [x] Chat: delete message.
- [x] Documents: upload.
- [x] Documents: download/fetch.
- [x] Documents: delete.
- [x] Enrollment: generate server token.
- [x] Settings: set meta.
- [x] Settings: set audio opt-in.

### Core Read Models

- [x] Session state.
- [x] Operators list/detail.
- [x] Assets list/detail.
- [x] SITREPs list.
- [x] Missions list/detail/approval context.
- [x] Chat channels/messages/operators/alerts/current operator.
- [x] Documents list/detail.
- [x] Enrollment pending tokens/server hash.
- [x] Audit list.
- [x] Map context.
- [x] Settings meta/audio/font scale.
- [x] Add dedicated dashboard summary/status read model.
- [x] Add dedicated sync status read model with connection state, heartbeat,
  pending outbox count, and last sync time.

### Legacy Client Routing

- [x] Kivy login/startup uses `TalonCoreSession`.
- [x] Kivy assets screen routes through core.
- [x] Kivy SITREP screen routes through core.
- [x] Kivy mission screens route through core.
- [x] Kivy chat screen routes through core.
- [x] Kivy documents screen routes through core.
- [x] Kivy operators/admin screens route through core.
- [x] Kivy map context routes through core.
- [x] Kivy persisted UI settings route through core.

### Core Physical Split Hardening

- [x] Move or repackage backend modules that still physically live under
  `talon/` into the final core package layout.
- [x] Keep compatibility imports or migrations where needed during package move.
- [x] Confirm no new desktop/mobile code imports DB, crypto, sync, or Reticulum
  internals directly.
- [x] Update package metadata for eventual standalone `talon-core` distribution.
- [x] Re-run full test suite after each package-move slice.

## Phase 2: `talon-desktop` PySide6

Goal: replace Kivy on Linux desktop first, polish an accepted Linux
server/client release, then validate Windows.

### Desktop Foundation

- [x] Create `talon_desktop` package.
- [x] Add `python -m talon_desktop` launcher.
- [x] Add `talon-desktop` console script.
- [x] Split desktop dependencies away from legacy Kivy/KivyMD.
- [x] Keep legacy Kivy dependencies under a separate `legacy-kivy` extra.
- [x] Add PySide6 login/unlock window.
- [x] Add client enrollment prompt.
- [x] Add lease/revocation lock dialog.
- [x] Add main window and persistent navigation.
- [x] Add Qt event bridge for core domain events.
- [x] Add generic read-model pages for major sections.
- [x] Confirm local dev shell launches from a virtual environment.
- [x] Add centralized PySide6 dark desktop theme and visual polish.
- [x] Add durable desktop settings for window geometry and operator UI choices.
- [x] Add global desktop error reporting/log-view affordance.

### Desktop Navigation Coverage

- [x] Dashboard section.
- [x] Map section.
- [x] SITREPs section.
- [x] Assets section.
- [x] Missions section.
- [x] Chat section.
- [x] Documents section.
- [x] Operators section.
- [x] Server-only Enrollment section.
- [x] Server-only Clients section.
- [x] Server-only Audit section.
- [x] Server-only Keys section.

### Desktop SITREPs

- [x] Build Qt SITREP feed.
- [x] Build Qt SITREP composer.
- [x] Populate severity picker from core constants.
- [x] Populate asset link selector from core read model.
- [x] Populate mission link selector from core read model.
- [x] Create SITREPs through `TalonCoreSession.command("sitreps.create")`.
- [x] Add server-only delete control.
- [x] Persist audio opt-in through core settings command.
- [x] Keep FLASH/FLASH_OVERRIDE audio opt-in only.
- [x] Refresh on core SITREP events.
- [x] Add high-severity alert dialog.
- [x] Add SITREP templates in Qt composer.
- [x] Replace alert dialog with full dashboard overlay layer.

### Desktop Assets

- [x] Build Qt asset table/list.
- [x] Build asset detail panel.
- [x] Build asset create dialog.
- [x] Build asset edit dialog.
- [x] Validate asset category, label, optional description, lat, and lon.
- [x] Create assets through `TalonCoreSession.command("assets.create")`.
- [x] Update assets through `TalonCoreSession.command("assets.update")`.
- [x] Verify/unverify assets through `TalonCoreSession.command("assets.verify")`.
- [x] Support client deletion request through
  `TalonCoreSession.command("assets.request_delete")`.
- [x] Support server hard delete through
  `TalonCoreSession.command("assets.hard_delete")`.
- [x] Prevent client self-verification behavior from being bypassed.
- [x] Refresh Assets, Dashboard, and Map on asset events.

### Desktop Map

- [x] Replace map placeholder with rendered operational map surface.
- [x] Load map data through `TalonCoreSession.read_model("map.context")`.
- [x] Render asset overlays.
- [x] Render mission zones.
- [x] Render mission routes/waypoints.
- [x] Add map selection behavior for assets/missions/SITREPs.
- [x] Add context panel for selected asset.
- [x] Add context panel for selected mission.
- [x] Add context panel for selected SITREP.
- [x] Refresh Map on assets, missions, zones, waypoints, and SITREP events.
- [x] Confirm no map tile/provider code bypasses core sync policy.

### Desktop Missions

- [x] Build mission list.
- [x] Build mission detail panel.
- [x] Build mission create dialog/wizard.
- [x] Support requested assets.
- [x] Support AO polygon input.
- [x] Support route/waypoint input.
- [x] Create missions through `TalonCoreSession.command("missions.create")`.
- [x] Server approve through `TalonCoreSession.command("missions.approve")`.
- [x] Server reject through `TalonCoreSession.command("missions.reject")`.
- [x] Server abort through `TalonCoreSession.command("missions.abort")`.
- [x] Server complete through `TalonCoreSession.command("missions.complete")`.
- [x] Server delete through `TalonCoreSession.command("missions.delete")`.
- [x] Refresh Missions, Assets, Map, SITREPs, and Chat on linked mission events.

### Desktop Chat

- [x] Build channel list.
- [x] Build message feed.
- [x] Build message composer.
- [x] Ensure default channels through core.
- [x] Create channel through `TalonCoreSession.command("chat.create_channel")`.
- [x] Delete channel through `TalonCoreSession.command("chat.delete_channel")`
  where allowed.
- [x] Create/get DM through `TalonCoreSession.command("chat.get_or_create_dm")`.
- [x] Send message through `TalonCoreSession.command("chat.send_message")`.
- [x] Delete message through `TalonCoreSession.command("chat.delete_message")`
  where allowed.
- [x] Render urgent messages distinctly.
- [x] Refresh Chat on channel/message events.
- [x] Preserve current DM security note: server-readable until Phase 2b E2E.

### Desktop Documents

- [x] Build document list.
- [x] Build document detail panel.
- [x] Build upload dialog.
- [x] Build download/save flow.
- [x] Build server delete flow.
- [x] Upload through `TalonCoreSession.command("documents.upload")`.
- [x] Download/fetch through `TalonCoreSession.command("documents.download")`.
- [x] Delete through `TalonCoreSession.command("documents.delete")`.
- [x] Surface blocked extension/MIME/size/integrity errors.
- [x] Warn on macro-capable document extensions before opening/saving.
- [x] Refresh Documents on document events.

### Desktop Operators And Server Admin

- [x] Build operator list/profile view.
- [x] Build operator profile edit dialog.
- [x] Update operator through `TalonCoreSession.command("operators.update")`.
- [x] Build enrollment token generator.
- [x] Show pending enrollment tokens.
- [x] Show server RNS hash.
- [x] Renew leases through `TalonCoreSession.command("operators.renew_lease")`.
- [x] Revoke operators through `TalonCoreSession.command("operators.revoke")`.
- [x] Build audit log view.
- [x] Build keys/identity status view.
- [x] Gate server/admin screens to server mode only.

### Desktop Testing

- [x] Add desktop navigation/event mapping tests.
- [x] Add desktop dependency metadata tests.
- [x] Add desktop SITREP helper tests.
- [x] Add Qt smoke test that constructs the main window offscreen.
- [x] Add UI smoke test that navigates to every desktop section.
- [x] Add desktop asset workflow tests.
- [x] Add desktop mission workflow tests.
- [x] Add desktop chat workflow tests.
- [x] Add desktop document workflow tests.
- [x] Add server admin workflow tests.
- [x] Run full `pytest -q` before each desktop milestone is marked complete.

### Linux Breakpoint A: Development Shell

- [x] `pip install -e ".[desktop]"` resolves without Kivy/KivyMD.
- [x] `talon-desktop --no-sync` launches locally from the venv.
- [x] Client mode unlock/enrollment path smoke-tested locally.
- [x] Server mode unlock path smoke-tested locally.
- [x] Local server/client sync smoke-tested through Reticulum loopback.

### Linux Breakpoint B: Linux Package

- [x] Create PySide6 Linux packaging config.
- [x] Build Linux package artifact.
- [x] Install Linux package on target Linux Mint environment.
- [x] Launch package on target Linux Mint environment.
- [x] Confirm no SDL/GLX/Kivy startup dependency remains in PySide6 package.
- [x] Run server mode from Linux package.
- [x] Run client mode from Linux package.
- [x] Complete unlock/enrollment smoke from Linux package.
- [x] Complete basic sync smoke from Linux package.
- [x] Document Linux package install and troubleshooting steps.

### Linux Release Polish

- [ ] Define Linux server/client release candidate scope and deferred items.
- [x] Add durable desktop settings for window geometry and operator UI choices.
- [x] Add global desktop error reporting/log-view affordance.
- [ ] Run manual server acceptance pass from the packaged Linux artifact.
- [ ] Run manual client acceptance pass from the packaged Linux artifact.
- [ ] Complete paired server/client enrollment and sync acceptance on target
  Linux systems.
- [ ] Verify package install, upgrade/reinstall, launcher, and uninstall or
  removal notes.
- [ ] Write Linux release notes with known limitations and troubleshooting.
- [ ] Mark Linux PySide6 server/client release candidate accepted.

### Windows Breakpoint

- [ ] Create Windows PySide6 packaging config after the Linux release candidate
  is accepted.
- [ ] Build Windows package artifact.
- [ ] Install Windows package on target Windows environment.
- [ ] Launch Windows package.
- [ ] Run server mode on Windows package.
- [ ] Run client mode on Windows package.
- [ ] Complete unlock/enrollment smoke on Windows package.
- [ ] Complete basic sync smoke on Windows package.
- [ ] Document Windows package install and troubleshooting steps.

### Desktop Exit Criteria

- [x] Linux PySide6 app can run server and client modes.
- [x] Linux package installs and launches on target Linux Mint without SDL/GLX
  failure.
- [ ] Linux server/client release candidate is polished and accepted.
- [ ] Desktop feature coverage reaches current Kivy Phase 2 core behavior.
- [ ] Windows packaging is validated after the accepted Linux release.
- [ ] Kivy release path is no longer needed for supported desktop releases.

## Phase 3: `talon-mobile` Android/Chaquopy Spike

Goal: prove Reticulum and core dependencies can run safely inside Android before
full mobile UI work starts.

### Android Project Foundation

- [ ] Create minimal native Android project.
- [ ] Add Chaquopy integration.
- [ ] Add app-private data directory strategy.
- [ ] Add app-private RNS config directory strategy.
- [ ] Add app-private document cache directory strategy.
- [ ] Bundle/import `talon-core`.
- [ ] Define narrow Android-to-core bridge API.
- [ ] Confirm mobile client does not import DB, sync, crypto, or Reticulum
  internals directly.

### Python Dependency Spike

- [ ] Import `RNS` under Chaquopy.
- [ ] Import SQLCipher binding under Chaquopy.
- [ ] Import PyNaCl under Chaquopy.
- [ ] Import cryptography under Chaquopy.
- [ ] Import Argon2 dependency under Chaquopy.
- [ ] Import document cache/security dependencies under Chaquopy.
- [ ] Document dependency build blockers and workarounds.
- [ ] Confirm dependencies package reproducibly in Android debug build.

### Reticulum Spike

- [ ] Initialize Reticulum with mobile-isolated config path.
- [ ] Create/load mobile RNS identity.
- [ ] Initialize TALON core in client mode.
- [ ] Start foreground service for long-running sync.
- [ ] Perform loopback or TCP Reticulum sync.
- [ ] Verify no TALON sync traffic bypasses RNS.
- [ ] Validate lifecycle pause/resume behavior.
- [ ] Validate permissions for network.
- [ ] Identify notification permission requirements.
- [ ] Identify USB/Bluetooth/RNode follow-up requirements.

### Mobile Spike Exit Criteria

- [ ] Android debug build initializes `talon-core`.
- [ ] Android debug build initializes Reticulum.
- [ ] Android debug build completes loopback or TCP sync.
- [ ] Core dependencies package reproducibly.
- [ ] Known blockers documented before full mobile UI starts.

## Phase 4: Full `talon-mobile` Android App

Goal: build a field-first Android client using the proven embedded Python core.

### Mobile Scope Controls

- [ ] Keep mobile client-only at first.
- [ ] Keep server/admin workflows desktop-only unless explicitly approved.
- [ ] Keep Reticulum and sync inside embedded Python core.
- [ ] Keep Android UI behind the narrow core bridge.
- [ ] Add Android event adapter from core events to UI state.
- [ ] Use foreground service for active/field-mode sync.

### Mobile Operator Lifecycle

- [ ] Unlock local DB from Android UI.
- [ ] Enroll with `TOKEN:SERVER_HASH`.
- [ ] Show lease state.
- [ ] Lock on lease expiry.
- [ ] Lock on revocation.
- [ ] Resume cleanly after Android lifecycle pause/resume.

### Mobile Map-First Dashboard

- [ ] Build map-first dashboard.
- [ ] Render assets.
- [ ] Render missions.
- [ ] Render zones.
- [ ] Render routes/waypoints.
- [ ] Show sync/lease/offline status.
- [ ] Support offline operation with pending records.

### Mobile Feature Workflows

- [ ] SITREP feed.
- [ ] SITREP composer.
- [ ] FLASH/FLASH_OVERRIDE overlay.
- [ ] Audio/notification alert behavior remains opt-in.
- [ ] Mission view and status.
- [ ] Asset view/create/update.
- [ ] Chat channels/messages.
- [ ] Document fetch/cache.
- [ ] Document warning/error display.

### Mobile Acceptance

- [ ] Android client can enroll.
- [ ] Android client can sync.
- [ ] Android client can operate offline.
- [ ] Android client can push pending records.
- [ ] Android client can fetch/cache documents.
- [ ] Android client locks on revocation.
- [ ] Android client locks on lease failure.
- [ ] Mobile UI does not access SQLCipher or Reticulum internals directly.
- [ ] Reticulum remains the only TALON sync transport path.

## Phase 5: Kivy Retirement

Goal: remove Kivy from release paths after replacement clients are accepted.

- [ ] Confirm PySide6 desktop has reached feature parity.
- [ ] Confirm Android client has reached accepted field-client baseline.
- [ ] Stop publishing Kivy Linux artifacts.
- [ ] Stop publishing Kivy Windows artifacts, if any remain.
- [ ] Remove Kivy from active desktop packaging.
- [ ] Remove KivyMD from active desktop packaging.
- [ ] Archive Kivy UI code or move it to a legacy branch.
- [ ] Keep rollback notes until at least one desktop and one mobile release are
  proven.
- [ ] Update root wiki to identify active release artifacts as PySide6 desktop
  and Android/Chaquopy mobile.

## Ongoing Cross-Project Work

### Security And Protocol

- [ ] Preserve SQLCipher schema compatibility unless a migration is explicitly
  planned.
- [ ] Preserve wire protocol compatibility during split.
- [ ] Keep server operator authority model unchanged unless a deliberate product
  decision changes it.
- [ ] Keep unverified assets unverified until confirmed by a second party or
  server authority.
- [ ] Ensure client-authored records resolve to enrolled operator, not silently
  to server sentinel.
- [ ] Implement DM end-to-end encryption in core when Phase 2b is scheduled.

### Documentation

- [ ] Update relevant project function doc after each behavior change.
- [ ] Update project `INDEX.md` after status/blocker/acceptance changes.
- [ ] Update root `wiki/INDEX.md` only for cross-project status changes.
- [ ] Move fixed bugs to `wiki/archive/fixed_bugs.md`.
- [ ] Keep Linux and Windows package validation notes current.
- [ ] Keep Android spike blockers current.

### Release Gates

- [ ] Full test suite passes before release candidate.
- [ ] Linux desktop package accepted.
- [ ] Linux PySide6 server/client release candidate accepted.
- [ ] Windows desktop package accepted.
- [ ] Android debug spike accepted.
- [ ] Android field-client release accepted.
- [ ] Kivy retired from supported release paths.

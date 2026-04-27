# Linux Role Artifact Split Checklist

_Created: 2026-04-27._
_Scope: PySide6 Linux desktop server/client release packaging._

This checklist tracks the work to replace the single ambiguous
`talon-desktop-linux.tar.gz` package with separate role-specific Linux
artifacts. Keep this file current while implementing the installer and workflow
changes.

## Goal

- [x] Replace the single ambiguous `talon-desktop-linux.tar.gz` package with two
  role-specific Linux PySide6 artifacts.
- [x] Ensure a machine cannot have client and server installed side by side.
- [x] Require explicit destructive confirmation before switching roles.
- [x] Preserve one shared codebase/build logic, but produce separate installable
  outputs.

## Artifact Split

- [x] Produce `talon-desktop-client-linux.tar.gz`.
- [x] Produce `talon-desktop-server-linux.tar.gz`.
- [x] Add a role marker inside each bundle, such as `.talon-artifact-role`.
- [x] Set client bundle marker content to `client`.
- [x] Set server bundle marker content to `server`.
- [x] Keep the internal PyInstaller executable name as `talon-desktop`.
- [x] Ensure installer reads the artifact role from the bundle marker.
- [x] Remove or reject installer `--mode`; role must come from the artifact, not
  user input.

## Client Install Behavior

- [x] Client artifact installs launcher `talon-desktop-client`.
- [x] Client artifact installs desktop entry `talon-desktop-client.desktop`.
- [x] Client desktop display name is `T.A.L.O.N. Client`.
- [x] Client default profile root is `~/.talon`.
- [x] Client wrapper sets `TALON_CONFIG` to the client config path.
- [x] Client install must not create `talon-desktop` or
  `talon-desktop-server`.

## Server Install Behavior

- [x] Server artifact installs launcher `talon-desktop-server`.
- [x] Server artifact installs desktop entry `talon-desktop-server.desktop`.
- [x] Server desktop display name is `T.A.L.O.N. Server`.
- [x] Server default profile root is `~/.talon-server`.
- [x] Server wrapper sets `TALON_CONFIG` to the server config path.
- [x] Server install must not create `talon-desktop` or
  `talon-desktop-client`.

## Role-Switch Guard

- [x] Before install, detect existing TALON footprint for the current user.
- [x] Detection includes `~/.talon`.
- [x] Detection includes `~/.talon-server`.
- [x] Detection includes TALON desktop bundles under the configured install
  root.
- [x] Detection includes launchers:
  - `talon-desktop`
  - `talon-desktop-client`
  - `talon-desktop-server`
- [x] Detection includes desktop entries:
  - `talon-desktop.desktop`
  - `talon-desktop-client.desktop`
  - `talon-desktop-server.desktop`
- [x] Detection includes TALON state/log directories under
  `~/.local/state/talon`.
- [x] Same-role reinstall may proceed without destructive confirmation.
- [x] Opposite-role install must stop before deletion.
- [x] Opposite-role install must warn that all previous local TALON files,
  databases, RNS identities, documents, launchers, desktop entries, bundles,
  and logs will be deleted.
- [x] `--yes` must not approve destructive deletion.
- [x] Require exact typed phrase: `DELETE TALON DATA`.
- [x] Support noninteractive `--confirm-delete "DELETE TALON DATA"` for
  controlled tests/automation.
- [x] Reject any other `--confirm-delete` value.
- [x] After valid confirmation, delete all detected local TALON footprint before
  installing the selected role.

## Permissions

- [x] Ensure profile/data directories are `0700`.
- [x] Ensure RNS directory is `0700`.
- [x] Ensure documents directory is `0700`.
- [x] Ensure config file is `0600`.
- [x] Preserve existing same-role config when reinstalling, but still enforce
  permissions.

## Build And Workflow

- [x] Update PySide6 Linux packaging workflow to create both artifacts.
- [x] Upload both tarballs.
- [x] Upload SHA-256 files for both tarballs.
- [x] Run server smoke against the server artifact.
- [x] Run client smoke against the client artifact.
- [x] Keep Reticulum loopback/package smoke coverage where feasible.
- [x] Keep legacy Kivy installer behavior unchanged unless fixture updates are
  required.

## Docs And Wiki

- [x] Update `wiki/talon-desktop/packaging.md` to document separate
  client/server artifacts.
- [x] Document launcher names and desktop entry names.
- [x] Document destructive role-switch behavior and exact confirmation phrase.
- [x] Document that server installs should be on dedicated or hardened operator
  machines.
- [x] Update `wiki/platform_split_checklist.md` release polish/package items to
  include split artifacts and role-switch validation.
- [x] Update testing notes after validation commands pass.

## Tests

- [x] Add fake PySide6 client/server bundle installer tests.
- [x] Test client artifact creates only client launcher and client desktop
  entry.
- [x] Test server artifact creates only server launcher and server desktop
  entry.
- [x] Test `--mode` is rejected.
- [x] Test same-role reinstall does not require destructive confirmation.
- [x] Test opposite-role install fails without confirmation.
- [x] Test opposite-role install fails with invalid confirmation.
- [x] Test opposite-role install succeeds with exact `DELETE TALON DATA`
  confirmation.
- [x] Test `--yes` alone does not authorize deletion.
- [x] Test destructive role switch deletes prior configs, DB/data, RNS,
  documents, bundles, launchers, desktop entries, and logs.
- [x] Test profile/config permissions are `0700` and `0600`.
- [x] Run `bash -n build/install-talon-desktop.sh`.
- [x] Run focused installer tests.
- [x] Run full `pytest -q`.

## Assumptions

- [x] There will be no generic `talon-desktop` installed launcher after this
  change.
- [x] A user may switch roles only by accepting deletion of all local TALON
  state.
- [x] Destructive confirmation requires the exact typed phrase
  `DELETE TALON DATA`.
- [x] Remote publishing remains deferred until valid Linux server/client
  artifacts are ready.

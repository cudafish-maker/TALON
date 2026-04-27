# Desktop Assets

Desktop asset UI consumes core asset read models and sends core asset commands.

## Views

- Asset table with category filter.
- Detail panel with verification, deletion-request, mission, and coordinate
  state.
- Create/edit dialog for category, label, description, latitude, and longitude.
- Verification/unverification controls.
- Client deletion request and server hard-delete controls.
- Map placement picker remains open.
- Linked SITREPs remain open.

## Behavior

- Unverified assets use a clear visual state.
- Verification requires valid operator authority from core.
- Asset delete uses confirmation and refreshes linked SITREPs/map state.
- Map pin filters should match the desktop map doc.

## Current Implementation

- `talon_desktop.assets` provides Qt-free normalization, payload validation,
  coordinate parsing, and client self-verification policy helpers.
- `talon_desktop.asset_page.AssetPage` renders the Qt asset table and detail
  panel.
- `AssetDialog` creates and edits assets through core command payloads.
- Asset create, update, verify/unverify, client deletion request, and server
  hard delete all call `TalonCoreSession.command(...)`.
- Asset domain events refresh Assets, Dashboard, and Map through the desktop
  event adapter.

## Acceptance

- Create, edit, verify/unverify, deletion request, and server hard delete work
  through core commands.
- Map placement remains open.
- Client-created assets push through the outbox and reconcile to canonical server
  records.

# Desktop Documents

Desktop provides the document repository UI. Core owns the document security
pipeline and transfer behavior.

## Current Core Boundary

Documents are the first legacy Kivy feature area moved onto
`TalonCoreSession`. The current Kivy `DocumentScreen` calls core read models and
commands for list, upload, download, and delete while keeping the existing UI
layout.

## Current PySide6 Implementation

- `talon_desktop.documents` provides Qt-free document view models, upload
  payload construction, macro-risk detection, server-only policy helpers, and
  user-facing document error messages.
- `talon_desktop.document_page.DocumentPage` renders the document list, detail
  panel, server-only upload dialog, download/save flow, server delete flow, and
  document event refresh.
- Client mode shows an explanatory upload-unavailable note instead of leaving
  the server-only upload workflow implicit.
- Uploads call `TalonCoreSession.command("documents.upload")`; downloads call
  `TalonCoreSession.command("documents.download")`; server deletes call
  `TalonCoreSession.command("documents.delete")`.
- Blocked extension/MIME, size, filename, integrity, and generic document
  errors are surfaced in the desktop UI.
- Macro-capable document extensions trigger a warning before save.

## Current Legacy Blocker

BUG-085: `DocumentScreen` is registered in the Kivy app and backed by document
code, but the current desktop dashboard has no visible navigation control for
`documents`.

Near-term Kivy release fix: add a visible Documents control or shared navigation
surface entry.

PySide6 requirement: Documents must be included in the first complete desktop
navigation shell.

## Views

- Document list with filename, type/size, uploader, uploaded time.
- Detail dialog with hash preview and description.
- Server upload and delete controls.
- Client/server download/open flow.
- Macro-risk warning before saving risky office formats.

## Behavior

- Server upload/delete only.
- Client download uses core fetch/cache behavior.
- Missing active broadband link should surface a clear unavailable state.

## Acceptance

- Server can upload, list, download, and delete documents.
- Client can list synced metadata and open/download documents after on-demand
  fetch.
- Stale cache invalidation is visible through refreshed metadata.

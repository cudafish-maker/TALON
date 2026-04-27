# Documents

Core owns the document repository, security pipeline, metadata sync, and client
fetch/cache behavior.

## Current Behavior

- Server upload/delete/list backend is implemented.
- Clients sync document metadata.
- Client open/download fetches plaintext on demand over the persistent sync link
  and stores a local encrypted cache.
- Stale client cache entries are evicted when document hash/version changes or
  the row is deleted.
- Client upload remains deferred.
- `TalonCoreSession` now owns document list/detail read models and upload,
  download, and delete commands.
- The legacy Kivy DocumentScreen now calls the core document boundary instead of
  calling `talon.documents`, config path helpers, or `app.client_sync` directly.

## Security Pipeline

- Enforce max size.
- Sanitize filenames.
- Block executable/script extensions.
- Use MIME magic where available, with extension fallback.
- Re-encode images with Pillow when available.
- Hash plaintext with SHA-256.
- Encrypt blob before storage.
- Write atomically under the resolved document storage path.
- Verify integrity on download.
- Audit upload, download, and delete actions.

## Sync Rules

- Normal table sync sends metadata only.
- `file_path` is redacted from normal document metadata sync.
- Plaintext transfer requires explicit `document_request`.
- LoRa should not be used for large document transfer.

## Core API

- Read models:
  - `documents.list`
  - `documents.detail`
- Commands:
  - `documents.upload`
  - `documents.download`
  - `documents.delete`

Command results publish domain events so the existing app event bridge can route
document changes to network notification and UI refresh paths.

## Legacy Source

Distilled from
[../archive/legacy/document_management.md](../archive/legacy/document_management.md).

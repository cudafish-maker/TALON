# Desktop Chat

Desktop presents channel and message workflows backed by core chat services.

## Current Implementation

- `talon_desktop.chat` provides Qt-free channel/message/operator view models,
  map-position grid-reference view models, and command payload helpers.
- `talon_desktop.chat_page.ChatPage` renders searchable/grouped channels,
  message feed, composer, channel creation, DM creation, server-only delete
  controls, urgent message styling/blink, operator presence, map-position grid
  attachment, and alert feed.
- The page calls `TalonCoreSession.command("chat.ensure_defaults")` before
  loading channels.
- Channel/message mutations refresh the Chat page through the desktop event
  adapter.
- DM UI keeps the current Phase 2b warning visible: direct messages remain
  server-readable until end-to-end encryption is implemented in core.

## Views

- Channel list.
- Channel search and group headers.
- Message timeline.
- Compose bar.
- Top-row Grid button that opens a map-position picker for assets, waypoints,
  zone centroids, and linked SITREP locations with latitude/longitude.
- Operator/alert side panel.
- New channel dialog.
- New DM dialog.
- Server-only delete channel/message actions.

## Behavior

- Default, custom, mission, and DM channels appear in one navigation surface.
- Default, custom, mission, and DM channels are grouped for scanability.
- Client-authored messages use the outbox and update after server ack.
- Attached grid references are stored on the outgoing chat message as the
  existing `messages.grid_ref` value.
- DM UI must clearly follow core's current security state: server-readable until
  Phase 2b E2E encryption lands.

## Acceptance

- Chat refreshes on server push and client push ack.
- Network-applied message/channel updates reach the PySide6 event bridge without
  requiring the legacy Kivy data-pushed callback.
- Urgent/FLASH-related channel behavior remains visible.
- Grid attachment uses the current core `map.context` and linked SITREP read
  models without bypassing core.
- Server-only delete controls are hidden from clients.

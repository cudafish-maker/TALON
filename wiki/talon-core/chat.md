# Chat

Core owns chat channels, messages, sync policy, and the Phase 2b DM encryption
target.

## Current Behavior

- Default channels: `#flash`, `#general`, `#sitrep-feed`, `#alerts`.
- Custom channels normalize to `#name`.
- Mission approval creates `#mission-[name]`.
- DMs use `dm:<a>:<b>` channel naming.
- Server can currently read DMs; SQLCipher and RNS protect at rest/in transit.
- `TalonCoreSession` now bridges chat command events into core sync: server
  sends notify the server push dispatcher, and client sends are marked pending
  for the outbox before being pushed over the active client sync link.

## Rules

- Client-authored messages push through the offline outbox.
- Desktop/mobile callers do not need to pass `sync_status` for normal client
  sends; the core facade queues the primary message record.
- Server can delete channels and messages.
- Channel names must reject reserved DM formats for custom channels.
- Message author must resolve to the enrolled operator.

## Phase 2b

DM end-to-end encryption belongs in core. Desktop and mobile should only present
DM state and errors returned by core.

## Facade Coverage

Implemented through `TalonCoreSession`:

- `chat.ensure_defaults`
- `chat.channels`
- `chat.messages`
- `chat.operators`
- `chat.alerts`
- `chat.current_operator`
- `chat.create_channel`
- `chat.delete_channel` server-only guard
- `chat.get_or_create_dm`
- `chat.send_message`
- `chat.delete_message` server-only guard

Legacy Kivy chat channel loading, message loading, message send, alert feed,
operator roster, channel creation, and message deletion now route through core.

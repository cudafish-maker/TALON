# SITREPs

Core owns SITREP creation, deletion policy, field encryption, links, and alert
events.

## Levels

- ROUTINE
- PRIORITY
- IMMEDIATE
- FLASH
- FLASH_OVERRIDE

## Rules

- Operators can create append-only SITREPs.
- Server controls deletion.
- SITREPs can link to assets and missions.
- SITREP bodies are field-encrypted at rest.
- Server decrypts body for wire sync; clients re-encrypt with their local DB key.
- FLASH audio is opt-in only and must be triggered through event policy, never
  automatic playback in core.

## Events

Core emits events for create, delete, linked record changes, UI refresh, badge
updates, alert overlays, and opt-in audio trigger eligibility.

## Facade Coverage

Implemented through `TalonCoreSession`:

- `sitreps.create`
- `sitreps.delete` server-only guard
- `sitreps.list` with optional `mission_id` and `asset_id` filters
- `settings.audio_enabled` and `settings.set_audio_enabled` for the opt-in
  audio toggle

Legacy Kivy SITREP creation, deletion, feed loading, asset link picking, mission
link picking, and audio opt-in persistence now route through core.

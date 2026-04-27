# Desktop SITREPs

Desktop provides the operator feed, composer, alert overlays, and audio opt-in
control.

## Views

- Feed with severity coloring.
- Composer with level picker and templates.
- Asset and mission link selectors.
- Server-only delete controls.
- Alert overlay layer for incoming SITREPs.

## Audio Rule

FLASH and FLASH_OVERRIDE audio remains opt-in only. The desktop UI may expose a
toggle, but playback eligibility comes from core event policy.

## Current Implementation

- `talon_desktop.sitrep_page.SitrepPage` replaces the generic placeholder page
  for the SITREPs section.
- Feed data comes from `TalonCoreSession.read_model("sitreps.list")`.
- Composer writes through `TalonCoreSession.command("sitreps.create", ...)`.
- The composer exposes Free Text, Contact, Medical, Logistics,
  Infrastructure, and Weather templates. Applying a template sets the suggested
  severity and inserts the template body; submitted reports persist the selected
  template key through the core command payload.
- Asset and mission link selectors are populated from core read models.
- Server mode exposes delete through `TalonCoreSession.command("sitreps.delete", ...)`;
  client mode does not show the delete control.
- Audio opt-in state is read from `settings.audio_enabled` and persisted through
  `settings.set_audio_enabled`.
- FLASH and FLASH_OVERRIDE can trigger a Qt beep only when audio is already
  enabled; no audio is played by default.
- Incoming IMMEDIATE/FLASH/FLASH_OVERRIDE SITREPs render through a non-modal
  dashboard overlay attached to the main desktop content area instead of modal
  alert dialogs.

## Open Gaps

- Incoming event handling currently resolves changed records from the visible
  feed window rather than a dedicated SITREP detail read model.

## Acceptance

- Incoming SITREPs refresh the active dashboard immediately.
- Alert overlay scale follows severity.
- Server-only delete is not available to client operators.
- Startup hydration does not create unread badges for old records.

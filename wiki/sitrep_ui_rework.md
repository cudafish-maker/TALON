# SITREP UI Rework — Implementation Checklist

Desktop SITREP screen redesign to match the current TALON tactical/phosphor theme used by Main, Chat, and Mission.

---

## Phase 1 — Layout Rebuild

- [x] Replace the old KV-built vertical layout with a Python-built screen shell in `talon/ui/screens/sitrep_screen.py`.
- [x] Convert `talon/ui/kv/sitrep.kv` to a minimal registration stub, matching the Mission/Chat pattern.
- [x] Add shared topbar styling with `CHAT_*` theme colors, TALON back navigation, refresh action, latest FLASH indicator, and audio opt-in state.
- [x] Add a feed header with total count and severity summary.
- [x] Add a right-side compose panel for severity, asset link, mission link, report body, clear, and send actions.

## Phase 2 — Feed Rows

- [x] Replace KivyMD feed rows with custom tactical rows using severity color bars.
- [x] Preserve append-only display behavior for operators.
- [x] Preserve server-only delete affordance and themed confirmation modal.
- [x] Show callsign, linked asset label, mission id, formatted timestamp, level, and report body preview.

## Phase 3 — Behavior Preservation

- [x] Preserve `create_sitrep()` submit path and `app.net_notify_change("sitreps", sitrep_id)`.
- [x] Preserve asset and mission link pickers.
- [x] Preserve sync callback refresh and severity overlay.
- [x] Preserve the hard safety rule: FLASH / FLASH_OVERRIDE audio remains opt-in only.

## Verification

- [x] `python -m compileall talon/ui/screens/sitrep_screen.py`
- [x] `python -m compileall talon/ui/kv`
- [x] `python -c "import os; os.environ['KIVY_NO_FILELOG']='1'; from talon.ui.screens.sitrep_screen import SitrepScreen; print(SitrepScreen.__name__)"`
- [x] `python -c "import os; os.environ['KIVY_NO_FILELOG']='1'; from kivy.lang import Builder; Builder.load_file('talon/ui/kv/sitrep.kv'); print('kv ok')"`
- [ ] Run `python main.py` and manually verify the SITREP screen loads in server mode.
- [ ] Create ROUTINE, IMMEDIATE, and FLASH SITREPs and verify row styling.
- [ ] Toggle audio opt-in and verify only the persisted button state changes.
- [ ] Link an asset and mission before sending and verify the feed shows the linked context.
- [ ] Server mode: delete confirmation opens and deletes the selected SITREP.

## Notes

- The redesign is UI-only. The SITREP database model and sync paths were not changed.
- Android layout work remains deferred to Phase 4 per `wiki/INDEX.md`.

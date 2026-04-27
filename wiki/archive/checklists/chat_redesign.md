# Chat Screen Redesign — Implementation Plan

**Status:** In progress  
**Started:** 2026-04-18  
**Design source:** Claude Design export — TALON Chat.html (phosphor green 4-pane tactical UI)

---

## Overview

Replacing the basic 2-pane KivyMD chat screen with a high-fidelity 4-pane tactical UI matching the Claude Design export. Phosphor green night-vision palette, channel grouping (EMERGENCY / ALL-HANDS / MISSION / SQUAD / DIRECT), URGENT message flagging, grid coordinate attachment, operators panel, and alert feed.

Fonts: RobotoMono (bundled KivyMD) + standard Roboto as condensed label fallback — custom font download deferred.

---

## Step-by-Step Checklist

### Phase 1 — Foundation

- [x] **1.1** Add `CHAT_*` color constants to `talon/ui/theme.py`
- [x] **1.2** Add `#flash` to `DEFAULT_CHANNELS` in `talon/constants.py`
- [x] **1.3** Bump `DB_SCHEMA_VERSION` to `11` in `talon/constants.py`

### Phase 2 — Database Migration

- [x] **2.1** Add migration 0011 to `talon/db/migrations.py`:
  - `messages.is_urgent` INTEGER NOT NULL DEFAULT 0
  - `messages.grid_ref` TEXT (nullable)
  - `channels.group_type` TEXT NOT NULL DEFAULT 'squad'
  - Backfill `group_type` for existing channels
- [x] **2.2** Update `Message` dataclass in `talon/db/models.py` — add `is_urgent`, `grid_ref`
- [x] **2.3** Update `Channel` dataclass in `talon/db/models.py` — add `group_type`

### Phase 3 — Chat Logic Updates

- [x] **3.1** Update `load_channels()` in `talon/chat.py` — SELECT and return `group_type`
- [x] **3.2** Update `load_messages()` in `talon/chat.py` — SELECT and return `is_urgent`, `grid_ref`
- [x] **3.3** Update `send_message()` in `talon/chat.py` — accept `is_urgent`, `grid_ref` kwargs
- [x] **3.4** Update `ensure_default_channels()` in `talon/chat.py` — seed `#flash` with `group_type='emergency'`

### Phase 4 — UI Widget Classes

- [x] **4.1** Write `_IconRail` class — 52dp vertical strip, back nav, icon buttons
- [x] **4.2** Write `_ChannelPanel` class — 220dp, search bar, grouped channel list, user footer
- [x] **4.3** Write `_ChannelItem` class — left border, icon glyph, name, unread badge, active/hover states
- [x] **4.4** Write `_ChatArea` class — flash banner, top bar, message scroll, input area
- [x] **4.5** Write `_MessageRow` class — header (ts + callsign + role + urgent tag), body, grid pill; URGENT styling
- [x] **4.6** Write `_RightPanel` class — operators section + alert feed section
- [x] **4.7** Write `_OperatorRow` class — online dot, callsign, role
- [x] **4.8** Write `_AlertRow` class — type/time label, alert text
- [x] **4.9** Wire blink animation helper (`_start_blink`) for URGENT tag + FLASH label

### Phase 5 — Screen Wiring

- [x] **5.1** Rewrite `ChatScreen` class in `chat_screen.py` — compose all 4 panes
- [x] **5.2** Wire `on_send_pressed()` — read urgent/grid flags, call updated `send_message()`
- [x] **5.3** Wire `select_channel()` — update chat area, scroll to bottom, clear badge
- [x] **5.4** Wire `refresh_operators()` — query DB and populate right panel
- [x] **5.5** Wire alert feed — query recent urgent messages for right panel
- [x] **5.6** Retain server-mode delete logic (long-press message → delete option; channel delete icon)

### Phase 6 — KV Layout

- [x] **6.1** Rewrite `talon/ui/kv/chat.kv` — minimal KV scaffold for 4-pane root layout; all styling via Python canvas

### Phase 7 — Verification

- [ ] **7.1** Run `python main.py` — chat screen loads with phosphor green 4-pane layout
- [ ] **7.2** Verify channel groups render in correct order (EMERGENCY → ALL-HANDS → MISSION → SQUAD → DIRECT)
- [ ] **7.3** Select `#flash` channel — flash banner visible and blinking
- [ ] **7.4** Toggle URGENT + GRID, send message — amber styling + grid pill in message list
- [ ] **7.5** Right panel shows operator list from DB
- [ ] **7.6** Alert feed shows recent urgent messages
- [ ] **7.7** Server mode: delete buttons accessible on messages and channels
- [x] **7.8** `pytest tests/` — 89 tests pass, migration 0011 clean

---

## Color Tokens

```python
CHAT_BG0     = (0.016, 0.031, 0.016, 1)   # #040804
CHAT_BG1     = (0.031, 0.055, 0.031, 1)   # #080e08 — panel bg
CHAT_BG2     = (0.047, 0.078, 0.047, 1)   # #0c140c — surface / hover
CHAT_BG3     = (0.067, 0.102, 0.067, 1)   # #111a11 — input / item hover
CHAT_BG4     = (0.086, 0.125, 0.086, 1)   # #162016 — active channel
CHAT_G1      = (0.110, 0.188, 0.110, 1)   # #1c301c — borders
CHAT_G2      = (0.153, 0.271, 0.153, 1)   # #274527 — dim / offline
CHAT_G3      = (0.227, 0.431, 0.227, 1)   # #3a6e3a — secondary text
CHAT_G4      = (0.322, 0.627, 0.322, 1)   # #52a052 — primary text
CHAT_G5      = (0.471, 0.784, 0.471, 1)   # #78c878 — active / online
CHAT_G6      = (0.690, 0.941, 0.690, 1)   # #b0f0b0 — highlights / callsigns
CHAT_RED     = (0.753, 0.188, 0.000, 1)   # #c03000 — badge bg
CHAT_RED2    = (1.000, 0.267, 0.000, 1)   # #ff4400 — emergency
CHAT_AMBER   = (0.722, 0.471, 0.000, 1)   # #b87800 — urgent bg
CHAT_AMBER2  = (1.000, 0.667, 0.000, 1)   # #ffaa00 — urgent text
CHAT_BORDER  = (0.090, 0.133, 0.090, 1)   # #172217 — dividers
```

## Layout Dimensions

```
┌──────┬──────────────┬────────────────────────┬──────────────┐
│ ICON │   CHANNEL    │      CHAT THREAD        │    RIGHT     │
│ RAIL │    LIST      │                         │    PANEL     │
│ 52dp │   220dp      │       flex (1)          │   210dp      │
└──────┴──────────────┴────────────────────────┴──────────────┘
```

## Channel Group Mapping

| DB `group_type` | Header label | Icon | Left border |
|----------------|-------------|------|------------|
| `emergency`    | EMERGENCY   | ⚡   | CHAT_RED2  |
| `allhands`     | ALL-HANDS   | ◉   | transparent |
| `mission`      | MISSION     | ◎   | transparent |
| `squad`        | SQUAD       | ◈   | transparent |
| `direct`       | DIRECT      | ◆   | transparent |

Active channel left border always: CHAT_G5

## Files Modified

| File | Change |
|------|--------|
| `talon/constants.py` | Add `#flash` to DEFAULT_CHANNELS; bump schema version |
| `talon/db/migrations.py` | Migration 0011 |
| `talon/db/models.py` | New fields on Message + Channel |
| `talon/chat.py` | Updated load/send functions + #flash seeding |
| `talon/ui/theme.py` | CHAT_* color constants |
| `talon/ui/kv/chat.kv` | Complete rewrite |
| `talon/ui/screens/chat_screen.py` | Complete rewrite |

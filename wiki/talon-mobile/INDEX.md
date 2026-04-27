# talon-mobile Wiki

`talon-mobile` is the Android-first field client. The target stack is native
Android UI with Chaquopy embedding Python `talon-core`.

## Current Status

Mobile work is planned and spike-gated. No full mobile UI should start until the
Android/Chaquopy spike proves Reticulum and core dependencies can run reliably.

## Roadmap

1. Build minimal Android app with Chaquopy.
2. Import and initialize `talon-core`.
3. Initialize `RNS` with app-private config/data dirs.
4. Create/load mobile Reticulum identity.
5. Complete loopback or TCP Reticulum sync test.
6. Package SQLCipher, PyNaCl/cryptography, Argon2, and document cache
   dependencies.
7. Build the full mobile UI after the spike passes.

## Function Docs

- [android_shell.md](android_shell.md) - native Android lifecycle and UI shell.
- [chaquopy_reticulum.md](chaquopy_reticulum.md) - Python bridge and RNS spike.
- [operators.md](operators.md) - unlock, enrollment, lease, lock state.
- [assets.md](assets.md) - field asset workflows.
- [sitreps.md](sitreps.md) - field SITREP create/feed/alerts.
- [missions.md](missions.md) - mission view and status.
- [map.md](map.md) - map-first field dashboard.
- [chat.md](chat.md) - mobile chat and DMs.
- [documents.md](documents.md) - mobile document fetch/cache.
- [packaging.md](packaging.md) - Android build requirements.
- [testing.md](testing.md) - spike and full acceptance matrix.

## Mobile Scope

- Android first.
- Client-only first.
- iOS out of scope until Android proves Reticulum viability.
- No mobile rewrite of Reticulum.

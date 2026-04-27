# Mobile Packaging

Android packaging is spike-gated.

## Target Stack

- Native Android UI.
- Chaquopy embedded Python.
- `talon-core` packaged as Python runtime code.
- Reticulum and crypto dependencies packaged inside the app.

## Required Build Capabilities

- Reproducible Python dependency set.
- SQLCipher support.
- PyNaCl/cryptography/Argon2 support.
- RNS import and initialization.
- App-private config/data/RNS/document/cache dirs.
- Foreground service permissions.

## Deferred

- iOS.
- Server/admin mode.
- RNode USB/Bluetooth production support until Android integration is designed.

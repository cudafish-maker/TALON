# Android Shell

The mobile shell is native Android UI that calls embedded Python `talon-core`
through Chaquopy.

## Responsibilities

- Android activity and navigation lifecycle.
- App-private storage path selection.
- Permissions for network, notifications, foreground service, and future
  USB/Bluetooth/RNode integrations.
- Foreground service for active field sync.
- Touch-first layouts.
- Event adapter from Python core events to Android UI state.

## Initial Shell

- Unlock/enrollment screen.
- Map-first dashboard.
- Bottom or rail navigation for core functions.
- Sync/lease status indicator.
- Lock/revocation screen.

## Rules

- Android UI does not access SQLCipher or Reticulum internals directly.
- Long-running sync is coordinated through core and Android foreground service.
- Mobile lifecycle pause/resume must not corrupt DB or RNS state.

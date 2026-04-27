# Mobile Testing

Mobile testing starts with the Chaquopy/Reticulum spike.

## Spike Acceptance

- Android debug build starts.
- Chaquopy imports `talon-core`.
- Chaquopy imports `RNS`.
- Mobile opens SQLCipher DB.
- Mobile creates and reloads Reticulum identity.
- Mobile initializes isolated RNS config dir.
- Mobile completes loopback or TCP Reticulum sync.
- No TALON sync path bypasses RNS.

## Full Mobile Acceptance

- Unlock/enroll/lock.
- Sync startup and heartbeat.
- Revocation lock.
- Offline create and reconnect push.
- Map-first dashboard.
- SITREP create/feed/FLASH overlay.
- Mission view.
- Asset view/create/update.
- Chat send/receive.
- Document fetch/cache.

## Manual Device Checks

- App background/foreground transition.
- Foreground service notification.
- Network loss and reconnect.
- Storage cleanup after document delete.
- Battery and lifecycle behavior during active sync.

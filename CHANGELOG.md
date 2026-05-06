# Changelog

All notable user-facing changes to TALON are documented here.

## [Unreleased]

### Added

### Changed

### Fixed

- Clients no longer stay soft-locked if a stale lease-expired network error
  arrives after renewal, or if the local lease expiry is stale while the
  operator version already matches the server.

### Security

## [0.1.1] - 2026-05-05

### Added

- Signed in-app update checks for Linux and Windows desktop client/server builds.
- Optional app version, role, and capability metadata on TALON protocol messages
  to warn about mixed-version deployments without blocking field operation.
- Server i2pd Network Setup now shows the server `.b32.i2p` address for clients.
- Enrollment tokens can now carry constrained I2P and Yggdrasil transport hints
  so an unenrolled client can configure TALON Reticulum interfaces from the
  pasted token before enrollment.
- Server operators can choose how long generated enrollment tokens remain valid,
  within the core minimum and maximum expiration policy.

### Changed

- GitHub release publishing now groups desktop download links in the release
  notes and publishes one `SHA256SUMS` checksum asset instead of per-file
  checksum sidecars.
- Desktop enrollment token expiration now uses local date and time controls
  instead of a raw minute-duration field.

### Fixed

- Client desktop enrollment now prepares Reticulum networking on the main
  thread before the background enrollment exchange, avoiding Python signal
  handler failures during first enrollment.
- Desktop startup now converts Reticulum interface startup panics into a normal
  UI error instead of letting a bad or unavailable server interface terminate
  the app after password entry.
- Desktop release artifacts now report version `0.1.1` after installation so
  the updater does not repeatedly offer the same release.

### Security

## [0.1.0] - 2026-05-04

### Added

- Initial working Windows and Linux desktop release builds.
- Client and server desktop artifacts for tagged version releases.

### Fixed

- Renewed client leases recover from local lockout after the client receives the updated lease state.

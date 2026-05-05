# Changelog

All notable user-facing changes to TALON are documented here.

## [Unreleased]

### Added

### Changed

### Fixed

### Security

## [0.1.1] - 2026-05-05

### Added

- Signed in-app update checks for Linux and Windows desktop client/server builds.
- Optional app version, role, and capability metadata on TALON protocol messages
  to warn about mixed-version deployments without blocking field operation.
- Server i2pd Network Setup now shows the server `.b32.i2p` address for clients.

### Changed

### Fixed

### Security

## [0.1.0] - 2026-05-04

### Added

- Initial working Windows and Linux desktop release builds.
- Client and server desktop artifacts for tagged version releases.

### Fixed

- Renewed client leases recover from local lockout after the client receives the updated lease state.

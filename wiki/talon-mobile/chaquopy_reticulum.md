# Chaquopy And Reticulum Spike

This spike gates full mobile development.

## Required Proofs

- Chaquopy imports `talon-core`.
- Chaquopy imports and initializes `RNS`.
- Android app uses isolated app-private TALON config, data, RNS, document, and
  cache dirs.
- Mobile creates and reloads a Reticulum identity.
- Mobile completes a loopback or TCP Reticulum sync test.
- No TALON sync traffic bypasses RNS.

## Dependency Proofs

- SQLCipher binding packages and opens an encrypted DB.
- PyNaCl/cryptography/Argon2 dependencies package and run.
- Document cache encryption and hash verification work.
- Python package versions are reproducible in Android build config.

## Output

The spike should produce a short report in this wiki with:

- Build environment.
- Dependency versions.
- RNS config path.
- Identity path.
- Sync test command/result.
- Blockers and required follow-up.

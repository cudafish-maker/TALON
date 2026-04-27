# Mobile Operators

Planned mobile operator workflows are client-only until Android core viability is
proven.

## Required Workflows

- Unlock local encrypted state.
- First-run enrollment with `TOKEN:SERVER_HASH`.
- Display current callsign and lease status.
- Lock immediately on lease failure or revocation.
- Show clear offline/online/sync state.

## Constraints

- Server admin operator management stays desktop-only initially.
- Mobile must use core read models for identity and lease state.
- Enrollment and revocation traffic must use Reticulum through core.

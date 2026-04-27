# Mobile Assets

Mobile assets are planned as field-first workflows after the Reticulum spike.

## Required Workflows

- View nearby/current assets.
- Create field asset with category, description, and coordinates.
- Update asset details allowed by core policy.
- Show verification state clearly.
- Link asset context to map and SITREPs.

## Constraints

- Verification policy stays in core.
- Mobile must not trust client-supplied author or verification fields.
- Offline-created assets use core outbox behavior.

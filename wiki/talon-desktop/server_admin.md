# Desktop Server Admin

Server admin screens are desktop/server-mode workflows. Mobile is client-only
until explicitly approved otherwise.

## Current Implementation

- `talon_desktop.operator_page.EnrollmentPage` generates enrollment tokens,
  displays the combined token/server-hash value, supports clipboard copy, and
  lists pending unexpired tokens.
- `talon_desktop.operator_page.OperatorPage` backs the server Clients section
  with profile editing, lease renewal, and revocation.
- `talon_desktop.operator_page.AuditPage` reads `audit.list`, supports exact
  event filtering, and shows payload details.
- `talon_desktop.operator_page.KeysPage` shows server hash, Reticulum identity
  status, operator identity rows, and server revocation controls. Group key
  rotation remains a non-destructive placeholder until the core service exists.
- Enrollment, Clients, Audit, and Keys remain server-only through
  `navigation_items("client")`.

## Screens

- Enrollment token generation and pending token list.
- Clients/operators list.
- Lease renewal.
- Operator revocation.
- Audit log viewer.
- Key/group rotation screen.

## Behavior

- Enrollment displays the combined `TOKEN:SERVER_HASH` string.
- Client rows show lease and revocation state.
- Revocation requires confirmation and emits core revocation events.
- Audit log filtering is exact-match by event name.
- Current key rotation UI is legacy stub state and should be redesigned through
  core services before relying on it.

## Acceptance

- Renew/revoke/profile changes refresh server UI and connected clients.
- Server sentinel does not appear as a normal client.

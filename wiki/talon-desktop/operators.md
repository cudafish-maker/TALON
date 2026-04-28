# Desktop Operators

Desktop presents operator state from `talon-core`.

## Current Implementation

- `talon_desktop.operators` provides Qt-free operator view models, lease status
  labels, profile/skills update payloads, enrollment token rows, audit rows,
  and server-action policy helpers.
- `talon_desktop.operator_page.OperatorPage` renders operator/client lists,
  detail panels, profile/skills edit dialog, server lease renewal, and server
  revocation controls.
- The profile dialog uses checkbox skills plus add/remove custom skill rows.
- Profile updates call `TalonCoreSession.command("operators.update")`.
- Lease renewals call `TalonCoreSession.command("operators.renew_lease")`.
- Revocations call `TalonCoreSession.command("operators.revoke")` after
  confirmation.
- Client mode can edit only the current local operator profile; server mode can
  edit enrolled operators. The server sentinel remains hidden from normal
  operator/client lists.

## Client Mode

- Show current callsign, lease status, and lock/revocation state.
- Allow profile and skills editing when core exposes the command.
- Surface enrollment errors clearly.

## Server Mode

- Show enrolled operators with active/inactive/revoked status.
- Renew leases.
- Revoke operators with confirmation.
- Edit operator profile and skills.
- Hide the server sentinel from normal operator lists.

## Acceptance

- Client locks immediately on explicit revocation event or inactive denial.
- Server admin changes emit core events and update visible views without restart.

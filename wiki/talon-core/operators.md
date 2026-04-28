# Operators

Core owns operator identity, enrollment, profile state, lease state, and
revocation.

## Current Behavior

- Server generates one-time enrollment tokens.
- Client enrolls with `TOKEN:SERVER_HASH` and callsign.
- Operator rows carry RNS identity hash and lease state.
- Clients use `my_operator_id` metadata after enrollment.
- Server sentinel `id=1` exists only to support current server-authored rows.
- Clients protect and locally repair the server sentinel because it is excluded
  from normal server operator sync.

## Service Rules

- Callsigns and RNS hashes are validated at enrollment.
- Lease renew/revoke operations are server-authority commands.
- Revoked or inactive operator denials must trigger local lock behavior.
- Profile and skill updates emit domain events for UI and sync refresh.

## Read Models

Core should expose:

- Current operator and lock state.
- Enrolled clients for server admin.
- Operator profile and skills.
- Lease expiration and revocation status.

# Invite and membership foundation scope

This branch is a **foundation step** for organisation membership and invitation flows. It is intended to be a safe baseline for the next development iterations, not the final end-to-end invite management system.

## Implemented in this foundation

- Active/inactive membership model for transfer-style membership changes.
- Invite creation baseline with pending invite records.
- Invite acceptance with atomic membership transfer and explicit transaction handling.
- Invite expiration support via `expires_at` and lazy expiration enforcement during accept.
- Soft-delete organisation baseline (`deleted_at`).
- Superadmin bootstrap support for platform-level operational access.

## Not fully implemented yet

The following capabilities are intentionally out of scope for this foundation and remain future work:

- Invite revocation flows.
- Invite resend flows.
- Full support/operations workflows around invite recovery.
- Member removal flows.
- Self-leave flows.
- Full owner/admin role mutation flows.
- Comprehensive audit logging for membership and invite lifecycle events.
- Complete organisation deletion/status policy matrix.

## Security and delivery note

Raw invite tokens are generated for out-of-band delivery but are not part of the normal public invite creation API response contract.

## Authorisation semantics and invite token test seam

For organisation-scoped foundation endpoints, this branch now applies a single access rule consistently:

1. Load organisation first.
2. Return `404 Not Found` when organisation does not exist (including soft-deleted records).
3. Only then evaluate actor access and return `403 Forbidden` when the organisation exists but actor permissions are insufficient.

This policy is applied to organisation read/membership-list flows and organisation-scoped invite creation.

## Membership contract scope

- Current domain contract is single-active-membership per user.
- A user can have one active organisation membership, or none.
- Multiple active organisations per user are intentionally out of scope for this stage.
- The active/inactive model keeps the implementation extensible for future policy changes without changing the current contract.

To keep invite API tests realistic without exposing raw tokens in the public API contract, invite creation now calls a token delivery port (`InviteTokenSink`). The production default sink is a no-op placeholder for out-of-band delivery, while tests override the sink with an in-memory capture implementation to retrieve tokens for acceptance tests.

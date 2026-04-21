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

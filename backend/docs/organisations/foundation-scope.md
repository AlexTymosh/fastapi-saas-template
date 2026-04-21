# Organisations and invites foundation scope

This branch is a **foundation step** for organisation membership lifecycle work.
It is safe to merge as a baseline, but it is **not** the final invite and membership system.

## Implemented in this foundation

- Active/inactive membership baseline (`is_active`) with transfer semantics.
- Invite creation baseline (token generation + hashed persistence).
- Invite acceptance with explicit atomic transfer flow.
- Soft-delete organisation baseline (`deleted_at`).
- Superadmin bootstrap path for organisation administration scaffolding.

## Not fully implemented yet

The following are intentionally out of scope in this foundation step:

- Invite revocation.
- Invite resend flows.
- Full support workflows.
- Member removal flows.
- Self-leave flows.
- Full owner/admin mutation flows.
- Audit logging.
- Complete organisation deletion/status policy matrix.

## Notes

- Invite expiration is enforced lazily at read/accept time.
- Raw invite token delivery is treated as out-of-band and not part of the normal public API contract.

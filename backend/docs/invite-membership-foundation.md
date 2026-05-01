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

Raw invite tokens are generated for out-of-band delivery but are not part of the normal public invite creation API response contract. Invite delivery now uses a transactional outbox: invite/audit/outbox rows are committed together, while delivery runs asynchronously and at-least-once from background workers.

Raw token material is stored only in outbox payloads until delivery is processed. Production hardening should encrypt sensitive outbox payloads or replace raw-token payload storage with a secure token material strategy before real provider integration.

Outbox processing strategy: the outbox table is the source of truth. Workers update attempts/status in the same database and persist failure state before propagating worker errors. Pending due events are dispatched by a dedicated outbox dispatcher actor and can be scheduled independently from request handling.

## Authorisation semantics and invite token test seam

For organisation-scoped foundation endpoints, this branch now applies a single access rule consistently:

1. Load organisation first.
2. Return `404 Not Found` when organisation does not exist (including soft-deleted records).
3. Only then evaluate actor access and return `403 Forbidden` when the organisation exists but actor permissions are insufficient.

This policy is applied to organisation read/membership-list flows and organisation-scoped invite creation.

To keep invite API tests realistic without exposing raw tokens in the public API contract, token delivery is executed only by outbox workers through a token sink abstraction (`InviteTokenSink`). The production default sink remains a no-op placeholder for out-of-band delivery, while tests can override the sink with an in-memory capture implementation.

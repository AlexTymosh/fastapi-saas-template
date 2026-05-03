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

- Full support/operations workflows around invite recovery.
- Member removal flows.
- Self-leave flows.
- Full owner/admin role mutation flows.
- Comprehensive audit logging for membership and invite lifecycle events.
- Complete organisation deletion/status policy matrix.

## Local role model

- Platform roles are stored in `platform_staff` and drive `/api/v1/platform/*` authorisation.
- Tenant roles are stored in organisation `memberships` and drive `/api/v1/organisations/*` authorisation.
- These role models are intentionally separated and must not be merged in business logic.

## Security and delivery note

Raw invite tokens are generated for out-of-band delivery but are not part of the normal public invite creation API response contract. Invite delivery now uses a transactional outbox: invite/audit/outbox rows are committed together, while delivery runs asynchronously and at-least-once from background workers.

`invites.token_hash` stores `sha256(raw_token)`. The outbox payload stores only `encrypted_raw_token`; plain `raw_token` is never persisted in payload JSON.
Workers decrypt token material in memory, verify `sha256(raw_token) == invites.token_hash`, and then deliver. Wrong key/material mismatch is handled as a safe failed attempt.
Outbox workers now use DB-backed status/attempt tracking as the source of truth and do not rely on Dramatiq retries for business delivery retries. A dispatcher actor (`enqueue_pending_outbox_events`) enqueues due pending events for processing.

## Authorisation semantics and invite token test seam

For organisation-scoped foundation endpoints, this branch now applies a single access rule consistently:

1. Load organisation first.
2. Return `404 Not Found` when organisation does not exist (including soft-deleted records).
3. Only then evaluate actor access and return `403 Forbidden` when the organisation exists but actor permissions are insufficient.

This policy is applied to organisation read/membership-list flows and organisation-scoped invite creation.

To keep invite API tests realistic without exposing raw tokens in the public API contract, token delivery is executed only by outbox workers through a token sink abstraction (`InviteTokenSink`). The production default sink remains a no-op placeholder for out-of-band delivery, while tests can override the sink with an in-memory capture implementation.


## Outbox runtime operations (P0)

Runtime now uses two dedicated background processes:

- Dramatiq worker: `dramatiq app.outbox.worker_runtime`
- Outbox dispatcher: `python -m app.outbox.dispatcher --interval 5 --batch-size 100`

Lifecycle is explicitly split:

1. Request transaction writes invite + audit + outbox event.
2. Dispatcher claims due events (`pending -> processing`, sets `locked_at`) and commits.
3. Dispatcher enqueues claimed IDs to Dramatiq. If enqueue fails after claim commit, dispatcher immediately releases the event via DB retry policy (`processing -> pending/failed`) and stores compact `enqueue_failed:<ExceptionType>` error.
4. Worker loads claimed event, performs external delivery **outside** DB transaction, then commits result transition.
5. Each dispatcher tick first recovers stale `processing` rows (`locked_at < now - stale_timeout`) and requeues/fails them using the same DB retry policy.

Status transitions:

- Success: `pending -> processing -> processed`
- Failure with retries remaining: `pending -> processing -> pending`
- Failure with max attempts reached: `pending -> processing -> failed`

Delivery semantics remain **at-least-once**: duplicate deliveries are still possible if a worker crashes after external send and before `mark_processed`. Idempotent downstream delivery remains a follow-up P1/P2 hardening task.


## Encryption key requirements

- Invite outbox payload encryption uses Fernet (`SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY`).
- `local` and `test` may use deterministic fallback key when env var is omitted.
- `dev`, `staging`, and `prod` require explicit key when `OUTBOX__INVITE_DELIVERY_ENABLED=true`.
- Worker decryption/key mismatch is handled safely: event is failed/retried without exposing raw token or encrypted payload.
- Key rotation and KMS integration are not part of this task.
- Processed-outbox retention/cleanup remains a separate follow-up task.

## SQLite and PostgreSQL compatibility note

- Production-safe path remains PostgreSQL.
- Invite repository update flows use SQL `RETURNING` through SQLAlchemy.
- SQLite compatibility for these flows requires SQLite **3.35+** (first version with `RETURNING` support).
